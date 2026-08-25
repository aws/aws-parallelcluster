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
from contextlib import contextmanager
from pathlib import Path

import boto3
from assertpy import assert_that
from retrying import retry
from time_utils import minutes, seconds

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
_COMPUTE_INSTANCE_STATES = ["pending", "running", "shutting-down", "stopping", "stopped"]
_COMPUTE_FLEET_TERMINAL_STATES = {"RUNNING", "STOPPED", "PROTECTED"}
_COMPUTE_FLEET_START_TRANSITIONS = {"START_REQUESTED", "STARTING"}
_COMPUTE_FLEET_STOP_TRANSITIONS = {"STOP_REQUESTED", "STOPPING"}
_CAPACITY_WAIT_MINUTES = 15


class _UnexpectedComputeFleetStatusError(RuntimeError):
    pass


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


def _deduplicate_clusters(clusters):
    unique_clusters = []
    seen = set()
    for cluster in clusters:
        key = (cluster.name, cluster.region)
        if key not in seen:
            seen.add(key)
            unique_clusters.append(cluster)
    return unique_clusters


def _get_compute_instance_ids(snapshot):
    filters = [
        {"Name": "tag:parallelcluster:cluster-name", "Values": [snapshot["cluster"].cfn_name]},
        {"Name": "tag:parallelcluster:node-type", "Values": ["Compute"]},
        {"Name": "instance-state-name", "Values": _COMPUTE_INSTANCE_STATES},
    ]
    instance_ids = set()
    paginator = snapshot["ec2"].get_paginator("describe_instances")
    for page in paginator.paginate(Filters=filters):
        for reservation in page.get("Reservations", []):
            instance_ids.update(instance["InstanceId"] for instance in reservation.get("Instances", []))
    return instance_ids


def _describe_login_asg(snapshot, asg_name, pool_name):
    groups = snapshot["autoscaling"].describe_auto_scaling_groups(
        AutoScalingGroupNames=[asg_name]
    ).get("AutoScalingGroups", [])
    if len(groups) != 1 or groups[0].get("AutoScalingGroupName") != asg_name:
        raise RuntimeError(
            f"Expected exactly one login-node Auto Scaling group named {asg_name}, found {len(groups)}"
        )

    group = groups[0]
    tag_values = [
        tag.get("Value")
        for tag in group.get("Tags", [])
        if tag.get("Key") == "parallelcluster:login-nodes-pool"
    ]
    if tag_values != [pool_name]:
        raise RuntimeError(
            f"Auto Scaling group {asg_name} has unexpected parallelcluster:login-nodes-pool tag values "
            f"{tag_values}; expected [{pool_name}]"
        )
    return group


def _snapshot_cluster(cluster):
    snapshot = {
        "cluster": cluster,
        "ec2": boto3.client("ec2", region_name=cluster.region),
        "autoscaling": boto3.client("autoscaling", region_name=cluster.region),
        "login_asgs": [],
        "instance_ids": set(),
    }
    compute_status = cluster.describe_compute_fleet()["status"]
    if compute_status not in _COMPUTE_FLEET_TERMINAL_STATES:
        raise RuntimeError(
            f"Cluster {cluster.name} compute fleet must be in RUNNING, STOPPED, or PROTECTED state before maintenance; "
            f"found {compute_status}"
        )
    snapshot["compute_status"] = compute_status
    snapshot["instance_ids"].update(_get_compute_instance_ids(snapshot))

    for pool in cluster.config.get("LoginNodes", {}).get("Pools", []):
        pool_name = pool["Name"]
        asg_name = f"{cluster.name}-{pool_name}-AutoScalingGroup"
        group = _describe_login_asg(snapshot, asg_name, pool_name)
        asg_snapshot = {
            "pool_name": pool_name,
            "AutoScalingGroupName": group["AutoScalingGroupName"],
            "MinSize": group["MinSize"],
            "MaxSize": group["MaxSize"],
            "DesiredCapacity": group["DesiredCapacity"],
            "instance_ids": {instance["InstanceId"] for instance in group.get("Instances", [])},
        }
        snapshot["instance_ids"].update(asg_snapshot["instance_ids"])
        snapshot["login_asgs"].append(asg_snapshot)

    logging.info(
        "Snapshotted cluster %s in %s: compute fleet %s, %d compute/login instances, %d login pools",
        cluster.name,
        cluster.region,
        compute_status,
        len(snapshot["instance_ids"]),
        len(snapshot["login_asgs"]),
    )
    return snapshot


def _wait_for_compute_status(snapshot, expected_status):
    cluster = snapshot["cluster"]

    @retry(
        wait_fixed=seconds(15),
        stop_max_delay=minutes(_CAPACITY_WAIT_MINUTES),
        retry_on_result=lambda status: status != expected_status,
    )
    def _poll():
        status = cluster.describe_compute_fleet()["status"]
        logging.info("Cluster %s compute fleet status is %s; waiting for %s", cluster.name, status, expected_status)
        return status

    return _poll()


def _wait_for_consumers_terminated(snapshots):
    @retry(
        wait_fixed=seconds(15),
        stop_max_delay=minutes(_CAPACITY_WAIT_MINUTES),
        retry_on_result=lambda consumers_remain: consumers_remain,
    )
    def _poll():
        consumers_remain = False
        for snapshot in snapshots:
            cluster = snapshot["cluster"]
            compute_instance_ids = _get_compute_instance_ids(snapshot)
            snapshot["instance_ids"].update(compute_instance_ids)
            if compute_instance_ids:
                consumers_remain = True
                logging.info(
                    "Waiting for cluster %s compute instances to terminate: %s",
                    cluster.name,
                    sorted(compute_instance_ids),
                )

            for asg_snapshot in snapshot["login_asgs"]:
                group = _describe_login_asg(
                    snapshot, asg_snapshot["AutoScalingGroupName"], asg_snapshot["pool_name"]
                )
                login_instance_ids = {instance["InstanceId"] for instance in group.get("Instances", [])}
                asg_snapshot["instance_ids"].update(login_instance_ids)
                snapshot["instance_ids"].update(login_instance_ids)
                if login_instance_ids:
                    consumers_remain = True
                    logging.info(
                        "Waiting for login Auto Scaling group %s instances to terminate: %s",
                        asg_snapshot["AutoScalingGroupName"],
                        sorted(login_instance_ids),
                    )
        return consumers_remain

    _poll()

    for snapshot in snapshots:
        instance_ids = sorted(snapshot["instance_ids"])
        if not instance_ids:
            continue
        logging.info("Verifying captured compute/login instances terminated for cluster %s", snapshot["cluster"].name)
        for offset in range(0, len(instance_ids), 1000):
            snapshot["ec2"].get_waiter("instance_terminated").wait(
                InstanceIds=instance_ids[offset : offset + 1000],
                WaiterConfig={"Delay": 15, "MaxAttempts": 40},
            )


def _pause_consumers(snapshots):
    for snapshot in snapshots:
        cluster = snapshot["cluster"]
        if snapshot["compute_status"] == "RUNNING":
            logging.info("Requesting compute fleet stop for cluster %s", cluster.name)
            cluster.stop(wait_stopped=False)

    for snapshot in snapshots:
        for asg_snapshot in snapshot["login_asgs"]:
            logging.info("Scaling login Auto Scaling group %s to zero", asg_snapshot["AutoScalingGroupName"])
            snapshot["autoscaling"].update_auto_scaling_group(
                AutoScalingGroupName=asg_snapshot["AutoScalingGroupName"],
                MinSize=0,
                DesiredCapacity=0,
            )

    for snapshot in snapshots:
        if snapshot["compute_status"] == "RUNNING":
            _wait_for_compute_status(snapshot, "STOPPED")
    _wait_for_consumers_terminated(snapshots)
    logging.info("All non-head-node consumers are stopped")


def _login_asg_capacity_matches(group, asg_snapshot):
    return (
        group["MinSize"] == asg_snapshot["MinSize"]
        and group["MaxSize"] == asg_snapshot["MaxSize"]
        and group["DesiredCapacity"] == asg_snapshot["DesiredCapacity"]
    )


def _restore_login_asg_capacity(snapshot, asg_snapshot):
    @retry(
        wait_fixed=seconds(15),
        stop_max_delay=minutes(_CAPACITY_WAIT_MINUTES),
        retry_on_exception=lambda error: True,
        retry_on_result=lambda restored: not restored,
    )
    def _request():
        group = _describe_login_asg(snapshot, asg_snapshot["AutoScalingGroupName"], asg_snapshot["pool_name"])
        if _login_asg_capacity_matches(group, asg_snapshot):
            return True

        logging.info(
            "Restoring login Auto Scaling group %s capacity to min=%d max=%d desired=%d",
            asg_snapshot["AutoScalingGroupName"],
            asg_snapshot["MinSize"],
            asg_snapshot["MaxSize"],
            asg_snapshot["DesiredCapacity"],
        )
        snapshot["autoscaling"].update_auto_scaling_group(
            AutoScalingGroupName=asg_snapshot["AutoScalingGroupName"],
            MinSize=asg_snapshot["MinSize"],
            MaxSize=asg_snapshot["MaxSize"],
            DesiredCapacity=asg_snapshot["DesiredCapacity"],
        )
        group = _describe_login_asg(snapshot, asg_snapshot["AutoScalingGroupName"], asg_snapshot["pool_name"])
        return _login_asg_capacity_matches(group, asg_snapshot)

    return _request()


def _request_compute_running(snapshot):
    cluster = snapshot["cluster"]

    @retry(
        wait_fixed=seconds(15),
        stop_max_delay=minutes(_CAPACITY_WAIT_MINUTES),
        retry_on_exception=lambda error: not isinstance(error, _UnexpectedComputeFleetStatusError),
        retry_on_result=lambda requested: not requested,
    )
    def _request():
        status = cluster.describe_compute_fleet()["status"]
        logging.info("Cluster %s compute fleet status is %s while requesting RUNNING", cluster.name, status)
        if status == "RUNNING" or status in _COMPUTE_FLEET_START_TRANSITIONS:
            return True
        if status == "STOPPED":
            logging.info("Requesting compute fleet start for cluster %s", cluster.name)
            cluster.start(wait_running=False)
            return True
        if status in _COMPUTE_FLEET_STOP_TRANSITIONS:
            return False
        raise _UnexpectedComputeFleetStatusError(
            f"Cannot restore cluster {cluster.name} compute fleet to RUNNING from {status}"
        )

    return _request()


def _wait_for_login_asg_restored(snapshot, asg_snapshot):
    desired_capacity = asg_snapshot["DesiredCapacity"]

    @retry(
        wait_fixed=seconds(15),
        stop_max_delay=minutes(_CAPACITY_WAIT_MINUTES),
        retry_on_result=lambda instance_ids: instance_ids is None,
    )
    def _poll():
        group = _describe_login_asg(snapshot, asg_snapshot["AutoScalingGroupName"], asg_snapshot["pool_name"])
        instances = group.get("Instances", [])
        ready = (
            _login_asg_capacity_matches(group, asg_snapshot)
            and len(instances) == desired_capacity
            and all(
                instance.get("LifecycleState") == "InService" and instance.get("HealthStatus") == "Healthy"
                for instance in instances
            )
        )
        logging.info(
            "Login Auto Scaling group %s has %d/%d ready instances",
            asg_snapshot["AutoScalingGroupName"],
            len(instances) if ready else 0,
            desired_capacity,
        )
        return [instance["InstanceId"] for instance in instances] if ready else None

    instance_ids = _poll()
    if not instance_ids:
        logging.info("Login Auto Scaling group %s capacity is restored", asg_snapshot["AutoScalingGroupName"])
        return

    logging.info("Waiting for restored login instances to pass EC2 status checks: %s", instance_ids)
    snapshot["ec2"].get_waiter("instance_status_ok").wait(
        InstanceIds=instance_ids,
        WaiterConfig={"Delay": 30, "MaxAttempts": 30},
    )


def _restore_consumers(snapshots):
    errors = []

    for snapshot in snapshots:
        for asg_snapshot in snapshot["login_asgs"]:
            try:
                _restore_login_asg_capacity(snapshot, asg_snapshot)
            except Exception as error:
                errors.append((f"restore login Auto Scaling group {asg_snapshot['AutoScalingGroupName']}", error))

        if snapshot["compute_status"] == "RUNNING":
            try:
                _request_compute_running(snapshot)
            except Exception as error:
                errors.append((f"start compute fleet for cluster {snapshot['cluster'].name}", error))

    for snapshot in snapshots:
        if snapshot["compute_status"] == "RUNNING":
            try:
                _wait_for_compute_status(snapshot, "RUNNING")
            except Exception as error:
                errors.append((f"wait for cluster {snapshot['cluster'].name} compute fleet RUNNING", error))

        for asg_snapshot in snapshot["login_asgs"]:
            try:
                _wait_for_login_asg_restored(snapshot, asg_snapshot)
            except Exception as error:
                errors.append((f"wait for login Auto Scaling group {asg_snapshot['AutoScalingGroupName']}", error))

    return errors


def _restore_error_message(errors):
    details = "\n".join(f"- {operation}: {error}" for operation, error in errors)
    return f"Failed to fully restore cluster consumers:\n{details}"


@contextmanager
def stopped_shared_slurm_consumers(*clusters):
    """Temporarily stop all compute fleets and login pools shared by a maintenance operation."""
    snapshots = []
    mutation_started = False
    primary_error = None
    try:
        unique_clusters = _deduplicate_clusters(clusters)
        snapshots = [_snapshot_cluster(cluster) for cluster in unique_clusters]
        mutation_started = True
        _pause_consumers(snapshots)
        yield
    except BaseException as error:
        primary_error = error
        raise
    finally:
        if mutation_started:
            restoration_errors = _restore_consumers(snapshots)
            if restoration_errors:
                message = _restore_error_message(restoration_errors)
                if primary_error is not None:
                    logging.error("%s; preserving the original failure: %s", message, primary_error)
                else:
                    raise RuntimeError(message)


def install_test_software(executor, region):
    """Download and run the test software installer on the target host."""
    script_path = _download_software_installer_script(region)
    return executor.run_remote_script(script_path, run_as_root=True, timeout=3600, pty=False)


def install_test_software_with_stopped_consumers(executor, region, *clusters):
    """Run the test software installer while the clusters have no compute or login consumers."""
    with stopped_shared_slurm_consumers(*clusters):
        return install_test_software(executor, region)


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
