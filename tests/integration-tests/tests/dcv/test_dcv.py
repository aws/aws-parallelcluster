# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import contextlib
import fcntl
import json
import logging
import os as operating_system
import re
import stat
import subprocess
from pathlib import Path

import pytest
import requests
from assertpy import assert_that
from framework.credential_providers import run_pcluster_command
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from utils import (
    add_keys_to_known_hosts,
    check_node_security_group,
    get_cidr_from_ip,
    get_local_ip,
    get_username_for_os,
    remove_keys_from_known_hosts,
)

from tests.cloudwatch_logging.test_cloudwatch_logging import FeatureSpecificCloudWatchLoggingTestRunner

SERVER_URL = "https://localhost"
DCV_CONNECT_SCRIPT = "/opt/parallelcluster/scripts/pcluster_dcv_connect.sh"

# Crashes matching any of these patterns are never tolerated, regardless of TOLERATED_CRASH_PATTERNS.
UNTOLERATED_CRASH_PATTERNS = [
    re.compile(r"dcv|nvidia", re.IGNORECASE),
]

# Tolerated crash patterns: list of regex patterns.
# A crash is tolerated if it is unrelated to DCV and the software stack owned by ParallelCluster.
TOLERATED_CRASH_PATTERNS = [
    # gnome-software segfaults in libadwaita related to animated scrolling of UI widget, observed on RHEL9/Rocky9
    re.compile(r"gnome-software.*scroll_to \(libadwaita", re.DOTALL),
    # tracker-miner-fs-3 and tracker-extract crash on Ubuntu/RHEL — GNOME file indexer, unrelated to DCV
    re.compile(r"tracker-(miner|extract)", re.DOTALL),
]

DIAGNOSIS_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "common" / "diagnosis"


def test_dcv_configuration(region, instance, os, scheduler, pcluster_config_reader, clusters_factory, test_datadir):
    host_ip = get_local_ip()
    dcv_allowed_ips = get_cidr_from_ip(host_ip) if host_ip else "0.0.0.0/0"
    _test_dcv_configuration(
        8443, dcv_allowed_ips, region, instance, os, scheduler, pcluster_config_reader, clusters_factory, test_datadir
    )


@pytest.mark.parametrize("dcv_port, access_from", [(8443, "PLACEHOLDER_TEST_HOST_CIDR"), (5678, "192.168.1.1/32")])
def test_dcv_with_remote_access(
    dcv_port, access_from, region, instance, os, scheduler, pcluster_config_reader, clusters_factory, test_datadir
):
    if access_from == "PLACEHOLDER_TEST_HOST_CIDR":
        host_ip = get_local_ip()
        dcv_allowed_ips = get_cidr_from_ip(host_ip) if host_ip else "0.0.0.0/0"
    else:
        dcv_allowed_ips = access_from
    _test_dcv_configuration(
        dcv_port,
        dcv_allowed_ips,
        region,
        instance,
        os,
        scheduler,
        pcluster_config_reader,
        clusters_factory,
        test_datadir,
    )


def _test_dcv_configuration(
    dcv_port, access_from, region, instance, os, scheduler, pcluster_config_reader, clusters_factory, test_datadir
):

    dcv_authenticator_port = dcv_port + 1
    cluster_config = pcluster_config_reader(dcv_port=str(dcv_port), access_from=access_from)
    cluster = clusters_factory(cluster_config)

    # command executors for the head and login nodes
    head_node_remote_command_executor = RemoteCommandExecutor(cluster)
    login_node_remote_command_executor = RemoteCommandExecutor(cluster, use_login_node=True)

    shared_dir = f"/home/{get_username_for_os(os)}"

    checks = [
        (
            "check_node_security_group (head node)",
            lambda: check_node_security_group(region, cluster, dcv_port, expected_cidr=access_from),
        ),
        (
            "check_node_security_group (login node)",
            lambda: check_node_security_group(
                region, cluster, dcv_port, expected_cidr=access_from, login_pool_name="pool"
            ),
        ),
        ("dcv connect show url (head node)", lambda: _test_show_url(cluster, region, dcv_port, access_from)),
        (
            "dcv connect show url (login node)",
            lambda: _test_show_url(cluster, region, dcv_port, access_from, use_login_node=True),
        ),
        (
            "authenticator (head node)",
            lambda: _test_authenticator(head_node_remote_command_executor, dcv_authenticator_port, shared_dir, os),
        ),
        (
            "authenticator (login node)",
            lambda: _test_authenticator(login_node_remote_command_executor, dcv_authenticator_port, shared_dir, os),
        ),
        (
            "error cases (head node)",
            lambda: _check_error_cases(head_node_remote_command_executor, dcv_authenticator_port),
        ),
        (
            "error cases (login node)",
            lambda: _check_error_cases(login_node_remote_command_executor, dcv_authenticator_port),
        ),
        ("shared dir (head node)", lambda: _check_shared_dir(head_node_remote_command_executor, shared_dir)),
        ("shared dir (login node)", lambda: _check_shared_dir(login_node_remote_command_executor, shared_dir)),
        ("no crashes (head node)", lambda: _assert_no_crashes(head_node_remote_command_executor)),
        ("no crashes (login node)", lambda: _assert_no_crashes(login_node_remote_command_executor)),
        (
            "cloudwatch logs",
            lambda: FeatureSpecificCloudWatchLoggingTestRunner.run_tests_for_feature(
                cluster, scheduler, os, "dcv_enabled", region, shared_dir
            ),
        ),
    ]

    failures = []
    for check_name, check_fn in checks:
        try:
            check_fn()
        except Exception as e:
            logging.error("Soft assertion failed for '%s': %s", check_name, e)
            failures.append(f"{check_name}: {e}")

    if failures:
        formatted = []
        for i, f in enumerate(failures):
            # Unescape literal \n and \t sequences so the output is human-readable
            readable = f.replace("\\n", "\n").replace("\\t", "\t")
            formatted.append(f"  [{i+1}] {readable}")
        pytest.fail(f"{len(failures)} DCV configuration check(s) failed:\n" + "\n".join(formatted))


def _check_auth_ko(remote_command_executor, dcv_authenticator_port, params, expected_message):
    try:
        assert_that(
            remote_command_executor.run_remote_command(
                f"curl -s -k -X GET -G {SERVER_URL}:{dcv_authenticator_port} {params}"
            ).stdout
        ).contains(expected_message)
    except RemoteCommandExecutionError as e:
        logging.info(f"Exception: {e}")
        assert_that(e.result.stdout).contains(expected_message)


def _check_shared_dir(remote_command_executor, shared_dir):
    assert_that(
        int(remote_command_executor.run_remote_command(f"cat /var/log/dcv/server.log | grep -c {shared_dir}").stdout)
    ).is_greater_than(0)


def _check_auth_ok(remote_command_executor, external_authenticator_port, session_id, session_token, os):
    username = get_username_for_os(os)
    assert_that(
        remote_command_executor.run_remote_command(
            f"curl -s -k {SERVER_URL}:{external_authenticator_port} "
            f"-d sessionId={session_id} -d authenticationToken={session_token} -d clientAddr=someIp"
        ).stdout
    ).is_equal_to('<auth result="yes"><username>{0}</username></auth>'.format(username))


def _get_crash_report(remote_command_executor):
    """Check for crash files on the node and return a crash report dictionary.

    Runs a script that scans crash locations across all pcluster-supported OSes
    (Ubuntu, AL2, AL2023, RHEL8/9, Rocky8/9) and returns a JSON dictionary
    mapping crash file paths to their human-readable content.

    Returns an empty dict if no crashes found.
    Raises ValueError if the script output could not be parsed.
    """
    result = remote_command_executor.run_remote_script(str(DIAGNOSIS_SCRIPT_DIR / "get_crash_report.sh"), pty=False)
    try:
        return json.loads(result.stdout)
    except Exception as e:
        raise ValueError(
            f"Failed to parse crash report JSON: {e}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        ) from e


def _is_tolerated_crash(content):
    """A crash is tolerated only if it matches a TOLERATED pattern and no UNTOLERATED pattern.

    Unknown/unclassified crashes are untolerated by default.
    """
    for pattern in UNTOLERATED_CRASH_PATTERNS:
        if pattern.search(content):
            return False
    for pattern in TOLERATED_CRASH_PATTERNS:
        if pattern.search(content):
            return True
    return False


def _assert_no_crashes(remote_command_executor):
    """Get crash report, log all crashes, and fail only on non-tolerated ones."""
    try:
        crash_report = _get_crash_report(remote_command_executor)
    except Exception as e:
        raise AssertionError(f"Crash report could not be determined: {e}") from e
    if crash_report:
        logging.warning("Crash report for %s:\n%s", remote_command_executor.target, json.dumps(crash_report, indent=2))
    tolerated = {path: content for path, content in crash_report.items() if _is_tolerated_crash(content)}
    untolerated = {path: content for path, content in crash_report.items() if not _is_tolerated_crash(content)}
    if tolerated:
        logging.warning("Tolerated crashes on %s:\n%s", remote_command_executor.target, json.dumps(tolerated, indent=2))
    assert_that(untolerated).is_empty()


def _get_known_hosts_content(host_keys_file):
    """Get content of known_hosts file, returning empty bytes if file doesn't exist or can't be read."""
    try:
        return subprocess.check_output(f"cat {host_keys_file}", shell=True)
    except subprocess.CalledProcessError:
        return b""


def _check_error_cases(remote_command_executor, dcv_authenticator_port):
    """Check DCV errors for both head and login nodes."""
    logging.info("Checking expected authentication failure on %s", remote_command_executor.target)
    _check_auth_ko(
        remote_command_executor,
        dcv_authenticator_port,
        "-d action=requestToken -d authUser=centos -d sessionID=invalidSessionId",
        "The given session does not exists",
    )
    _check_auth_ko(
        remote_command_executor, dcv_authenticator_port, "-d action=test", "The action specified 'test' is not valid"
    )
    _check_auth_ko(
        remote_command_executor, dcv_authenticator_port, "-d action=requestToken -d authUser=centos", "Wrong parameters"
    )
    logging.info("Completed checks for authentication failure on %s", remote_command_executor.target)


@contextlib.contextmanager
def _temporary_known_host(hostname, host_keys_file, env):
    """Add SSH host keys for hostname, yield, then remove them. Serialized via file lock across processes."""
    lock_file = host_keys_file + ".lock"
    with open(lock_file, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            add_keys_to_known_hosts(hostname, host_keys_file)
            yield
        finally:
            remove_keys_from_known_hosts(hostname, host_keys_file, env=env)


def _test_show_url(cluster, region, dcv_port, access_from, use_login_node=False):  # noqa: C901
    """Test dcv-connect with --show-url."""
    env = operating_system.environ.copy()
    env["AWS_DEFAULT_REGION"] = region

    node_ip = cluster.get_login_node_public_ip() if use_login_node else cluster.head_node_ip

    # Ensure known_hosts path exists to avoid `cat` command returning non-zero exit when testing in ADC region.
    host_keys_file = operating_system.path.expanduser("~/.ssh/known_hosts")
    host_keys_path = Path(host_keys_file)
    try:
        host_keys_path.parent.mkdir(parents=True, exist_ok=True)
        if not host_keys_path.exists():
            host_keys_path.touch()
            host_keys_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except Exception as e:
        logging.warning("Failed to prepare known_hosts file %s: %s", host_keys_file, e)

    dcv_connect_args = ["pcluster", "dcv-connect", "--cluster-name", cluster.name, "--show-url"]

    if use_login_node:
        dcv_connect_args.extend(["--login-node-ip", node_ip])

    with _temporary_known_host(node_ip, host_keys_file, env):
        try:
            result = run_pcluster_command(dcv_connect_args, env=env)
        except subprocess.CalledProcessError as e:
            raise AssertionError(
                f"Command {e.cmd} failed (exit {e.returncode}).\nstderr: {e.stderr}\nstdout: {e.stdout}"
            ) from e

    assert_that(result.stdout).matches(
        r"Please use the following one-time URL in your browser within 30 seconds:\n"
        r"https:\/\/(\b(?:\d{1,3}\.){3}\d{1,3}\b):" + str(dcv_port) + r"\?authToken=(.*)"
    )
    if access_from == "0.0.0.0/0":
        url = re.search(r"https:\/\/.*", result.stdout).group(0)
        response = requests.get(url, verify=False)
        assert_that(response.status_code).is_equal_to(200)


def _test_authenticator(remote_command_executor, dcv_authenticator_port, shared_dir, os):
    """Launch a DCV session and verify authenticator."""
    command_execution = remote_command_executor.run_remote_command(f"{DCV_CONNECT_SCRIPT} {shared_dir}")
    dcv_parameters = re.search(
        r"PclusterDcvServerPort=([\d]+) PclusterDcvSessionId=([\w]+) PclusterDcvSessionToken=([\w-]+)",
        command_execution.stdout,
    )
    if dcv_parameters:
        dcv_session_id = dcv_parameters.group(2)
        dcv_session_token = dcv_parameters.group(3)
        _check_auth_ok(remote_command_executor, dcv_authenticator_port, dcv_session_id, dcv_session_token, os)
    else:
        assert_that(dcv_parameters).described_as(
            "Command '{0} {1}' fails, output: {2}, error: {3}".format(
                DCV_CONNECT_SCRIPT, shared_dir, command_execution.stdout, command_execution.stderr
            )
        ).is_not_none()
