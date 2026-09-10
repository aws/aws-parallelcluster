# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import json
import logging
import re

import boto3
import pytest
from assertpy import assert_that, soft_assertions
from remote_command_executor import RemoteCommandExecutor
from utils import to_snake_case

from tests.common.assertions import (
    assert_no_errors_in_service_log,
    assert_systemd_service_running,
    known_harmless_slurm_daemon_errors,
)
from tests.common.software_installer import install_test_software_with_stopped_consumers

# slurmrestd listens on this unix socket when configured via the upstream postinstall script
# (aws-samples/aws-parallelcluster-post-install-scripts/rest-api).
SLURMRESTD_SOCKET = "/var/spool/socket/slurmrestd.sock"

CONFIGURE_SCRIPT_NAME = "configure_slurmrestd.sh"
SLURM_REST_API_RB_NAME = "slurm_rest_api.rb"


def _get_slurm_database_config_parameters(database_stack_outputs):
    keys = ["DatabaseHost", "DatabaseAdminUser", "DatabaseSecretArn", "DatabaseClientSecurityGroup"]
    return {to_snake_case(key): database_stack_outputs.get(key) for key in keys}


@pytest.mark.usefixtures("instance", "os", "scheduler")
def test_slurm_rest_api(
    region,
    pcluster_config_reader,
    s3_bucket_factory,
    vpc_stack_for_database,
    database,
    clusters_factory,
    test_datadir,
):
    """Verify that the Slurm REST API (slurmrestd) is functional on a cluster where it is enabled."""
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / CONFIGURE_SCRIPT_NAME), f"scripts/{CONFIGURE_SCRIPT_NAME}")
    bucket.upload_file(str(test_datadir / SLURM_REST_API_RB_NAME), f"scripts/{SLURM_REST_API_RB_NAME}")

    configure_slurmrestd_script_uri = f"s3://{bucket_name}/scripts/{CONFIGURE_SCRIPT_NAME}"
    slurm_rest_api_rb_uri = f"s3://{bucket_name}/scripts/{SLURM_REST_API_RB_NAME}"

    database_params = _get_slurm_database_config_parameters(database.cfn_outputs)
    public_subnet_id = vpc_stack_for_database.get_public_subnet()
    private_subnet_id = vpc_stack_for_database.get_private_subnet()

    cluster_config = pcluster_config_reader(
        public_subnet_id=public_subnet_id,
        private_subnet_id=private_subnet_id,
        bucket_name=bucket_name,
        configure_slurmrestd_script_uri=configure_slurmrestd_script_uri,
        slurm_rest_api_rb_uri=slurm_rest_api_rb_uri,
        **database_params,
    )
    cluster = clusters_factory(cluster_config)

    rce = RemoteCommandExecutor(cluster)

    with soft_assertions():
        assert_systemd_service_running(rce, "slurmrestd")
        _assert_slurmrestd_endpoint_responsive(rce, "ping")
        assert_no_errors_in_service_log(rce, "slurmrestd", ignore_patterns=known_harmless_slurm_daemon_errors())

    # The installer recompiles Slurm with --enable-slurmrestd against /opt/libjwt and restarts the daemon, so the
    # REST API has to be exercised again: a unit that comes back up is no proof that token authentication and the
    # OpenAPI plugins survived the upgrade. The API version is rediscovered from /openapi/v3, which also covers
    # the plugin set changing across the upgrade.
    install_start_time = rce.run_remote_command("date '+%Y-%m-%d %H:%M:%S'", hide=True).stdout.strip()
    install_test_software_with_stopped_consumers(rce, cluster)
    rce = RemoteCommandExecutor(cluster)
    with soft_assertions():
        assert_systemd_service_running(rce, "slurmrestd")
        _assert_slurmrestd_endpoint_responsive(rce, "ping")
        # The journal is cumulative, so the check is scoped to what the upgraded daemon logged: otherwise it would
        # keep passing on the pre-upgrade lines alone.
        assert_no_errors_in_service_log(
            rce, "slurmrestd", ignore_patterns=known_harmless_slurm_daemon_errors(), since=install_start_time
        )


def _slurmrestd_request(rce, url_path, raise_on_error=True):
    """Send an authenticated request to slurmrestd and return the parsed JSON response."""
    cmd = (
        "set -e; "
        "TOKEN=$(sudo -u slurm /opt/slurm/bin/scontrol token lifespan=600 | awk -F= '{print $2}'); "
        "USER=$(id -un); "
        f"sudo curl -sS --unix-socket {SLURMRESTD_SOCKET} "
        f'-H "X-SLURM-USER-TOKEN: ${{TOKEN}}" '
        f'-H "X-SLURM-USER-NAME: ${{USER}}" '
        f"http://localhost{url_path}"
    )
    result = rce.run_remote_command(cmd, raise_on_error=raise_on_error)
    assert_that(result.return_code).described_as(
        f"slurmrestd request to {url_path} failed. stderr={result.stderr}"
    ).is_equal_to(0)
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise AssertionError(f"slurmrestd {url_path} did not return valid JSON: {result.stdout!r}") from exc


def _get_slurm_api_version(rce):
    """Query the slurmrestd OpenAPI spec to discover the latest available slurm API version."""
    logging.info("Discovering slurmrestd API version from /openapi/v3")
    spec = _slurmrestd_request(rce, "/openapi/v3")
    paths = spec.get("paths", {}).keys()
    # Extract version strings from paths like /slurm/v0.0.44/ping
    versions = {m.group(1) for p in paths for m in [re.search(r"/slurm/(v\d+\.\d+\.\d+)/", p)] if m}
    assert_that(versions).described_as("No slurm API versions found in /openapi/v3").is_not_empty()
    latest = sorted(versions, key=lambda v: list(map(int, v.lstrip("v").split("."))))[-1]
    logging.info("Detected slurmrestd API version: %s", latest)
    return latest


def _assert_slurmrestd_endpoint_responsive(rce, endpoint):
    """
    Hit a slurmrestd endpoint (e.g. ping, diag) from the head node using a JWT token
    generated via `scontrol token`, and assert the response is a valid JSON document
    reporting no errors.
    """
    slurm_api_version = _get_slurm_api_version(rce)
    logging.info("Calling slurmrestd endpoint /slurm/%s/%s", slurm_api_version, endpoint)
    payload = _slurmrestd_request(rce, f"/slurm/{slurm_api_version}/{endpoint}")

    errors = payload.get("errors", [])
    assert_that(errors).described_as(f"slurmrestd /{endpoint} returned errors: {errors}").is_empty()

    warnings = payload.get("warnings", [])
    assert_that(warnings).described_as(f"slurmrestd /{endpoint} returned warnings: {warnings}").is_empty()

    pings = payload.get("pings", [])
    assert_that(pings).described_as(f"slurmrestd /{endpoint} returned no pings").is_not_empty()
    assert_that(pings[0].get("pinged")).described_as(
        f"slurmrestd /{endpoint} ping status is not UP: {pings[0]}"
    ).is_equal_to("UP")
