# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import atexit
import hashlib
import logging
import os
import tempfile
import threading
from pathlib import Path

import boto3
from assertpy import assert_that
from retrying import retry
from time_utils import seconds

from utils import get_arn_partition

_SOFTWARE_INSTALLER_SCRIPT_OVERRIDE = "PCLUSTER_SOFTWARE_INSTALLER_SCRIPT"
_DEFAULT_ARTIFACT_BUCKET = "aws-parallelcluster-dev-build-dependencies"
_DEFAULT_ARTIFACT_KEY = "install_software.sh"
_ADC_ARTIFACT_KEY = f"{_DEFAULT_ARTIFACT_BUCKET}/{_DEFAULT_ARTIFACT_KEY}"
_ARTIFACTS_BY_PARTITION = {
    "aws": (_DEFAULT_ARTIFACT_BUCKET, _DEFAULT_ARTIFACT_KEY),
    "aws-us-gov": (_DEFAULT_ARTIFACT_BUCKET, _DEFAULT_ARTIFACT_KEY),
    "aws-cn": (_DEFAULT_ARTIFACT_BUCKET, _DEFAULT_ARTIFACT_KEY),
    "aws-iso": ("draco-parallelcluster-dca-artifacts", _ADC_ARTIFACT_KEY),
    "aws-iso-b": ("draco-parallelcluster-lck-artifacts", _ADC_ARTIFACT_KEY),
}
_DOWNLOAD_CACHE = {}
_DOWNLOAD_CACHE_LOCK = threading.Lock()


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as script:
        for chunk in iter(lambda: script.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _get_local_override():
    if _SOFTWARE_INSTALLER_SCRIPT_OVERRIDE not in os.environ:
        return None

    override = os.environ[_SOFTWARE_INSTALLER_SCRIPT_OVERRIDE]
    if not override.strip():
        raise ValueError(f"{_SOFTWARE_INSTALLER_SCRIPT_OVERRIDE} is set but empty")

    path = Path(override).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Software installer script override does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Software installer script override is not a file: {path}")
    if not os.access(path, os.R_OK):
        raise PermissionError(f"Software installer script override is not readable: {path}")

    try:
        digest = _sha256(path)
    except OSError as error:
        raise PermissionError(f"Software installer script override is not readable: {path}: {error}") from error

    logging.info("Using software installer script override %s (SHA-256: %s)", path, digest)
    return str(path)


def _artifact_location(region):
    if not region:
        raise ValueError("A region is required to download the software installer script")

    partition = get_arn_partition(region)
    try:
        return _ARTIFACTS_BY_PARTITION[partition]
    except KeyError as error:
        raise ValueError(f"Unsupported AWS partition for region {region}: {partition}") from error


def _remove_file(path):
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        logging.warning("Unable to remove cached software installer script %s: %s", path, error)


def _cleanup_cached_downloads():
    with _DOWNLOAD_CACHE_LOCK:
        cached_paths = list(_DOWNLOAD_CACHE.values())
        _DOWNLOAD_CACHE.clear()

    for path in cached_paths:
        _remove_file(path)


atexit.register(_cleanup_cached_downloads)


def _download_software_installer_script(region):
    region = "us-east-1"
    override = _get_local_override()
    if override:
        return override

    bucket, key = _artifact_location(region)
    with _DOWNLOAD_CACHE_LOCK:
        cached_path = _DOWNLOAD_CACHE.get(region)
        if cached_path:
            path = Path(cached_path)
            if path.is_file() and os.access(path, os.R_OK):
                try:
                    digest = _sha256(path)
                except OSError:
                    pass
                else:
                    logging.info("Using cached s3://%s/%s (SHA-256: %s)", bucket, key, digest)
                    return cached_path
            _DOWNLOAD_CACHE.pop(region, None)
            _remove_file(cached_path)

        file_descriptor, downloaded_path = tempfile.mkstemp(prefix="pcluster-software-installer-", suffix=".sh")
        os.close(file_descriptor)
        try:
            logging.info("Downloading software installer script from s3://%s/%s in region %s", bucket, key, region)
            boto3.client("s3", region_name=region).download_file(bucket, key, downloaded_path)
            os.chmod(downloaded_path, 0o700)
            digest = _sha256(Path(downloaded_path))
            logging.info("Downloaded s3://%s/%s (SHA-256: %s)", bucket, key, digest)
        except Exception as error:
            _remove_file(downloaded_path)
            raise RuntimeError(
                f"Failed to download software installer script from s3://{bucket}/{key} in region {region}: {error}"
            ) from error

        _DOWNLOAD_CACHE[region] = downloaded_path
        return downloaded_path


def install_test_software(executor, region):
    """Download and run the test software installer on the target host."""
    script_path = _download_software_installer_script(region)
    return executor.run_remote_script(script_path, run_as_root=True, timeout=3600, pty=False)


def assert_slurm_controller_healthy(executor):
    """Retry until scontrol reports a successful response from a healthy Slurm controller."""

    @retry(wait_fixed=seconds(10), stop_max_attempt_number=6)
    def _assert_controller_healthy():
        result = executor.run_remote_command("scontrol ping", raise_on_error=False)
        assert_that(result.return_code).described_as(
            f"scontrol ping failed with stderr: {result.stderr}"
        ).is_equal_to(0)
        assert_that(result.stdout).described_as("scontrol ping did not report a healthy controller").contains("is UP")
        return result

    return _assert_controller_healthy()


def run_scheduler_smoke_test(
    scheduler_commands,
    partition=None,
    nodes=1,
    slots=1,
    other_options=None,
    command="hostname",
    timeout=None,
):
    """Submit a short scheduler job, wait for completion, assert success, and return its job ID."""
    submit_command_args = {
        "command": command,
        "nodes": nodes,
        "slots": slots,
    }
    if partition is not None:
        submit_command_args["partition"] = partition
    if other_options is not None:
        submit_command_args["other_options"] = other_options

    job_id = scheduler_commands.submit_command_and_assert_job_accepted(submit_command_args)
    scheduler_commands.wait_job_completed(job_id, timeout=timeout)
    scheduler_commands.assert_job_succeeded(job_id)
    return job_id
