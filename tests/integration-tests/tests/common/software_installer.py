# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import atexit
import hashlib
import logging
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

import boto3
from assertpy import assert_that
from retrying import retry
from time_utils import minutes, seconds

_INSTALLER_REGION = "us-east-1"
_INSTALLER_BUCKET = "aws-parallelcluster-dev-build-dependencies"
_INSTALLER_KEY = "install_software.sh"
_DOWNLOAD_CACHE = {}
_DOWNLOAD_CACHE_LOCK = threading.Lock()
_COMPUTE_INSTANCE_STATES = ["pending", "running", "shutting-down", "stopping", "stopped"]
_COMPUTE_FLEET_TERMINAL_STATES = {"RUNNING", "STOPPED", "PROTECTED"}
_COMPUTE_FLEET_START_TRANSITIONS = {"START_REQUESTED", "STARTING"}
_COMPUTE_FLEET_STOP_TRANSITIONS = {"STOP_REQUESTED", "STOPPING"}
_CAPACITY_WAIT_MINUTES = 15
_PARTITION_WAIT_MINUTES = 10
_STATE_CHECK_RESERVATION = "pcluster-upgrade-state-check"
# The reservation only has to be persisted in StateSaveLocation, so keep it far in the future:
# an active maintenance reservation would take nodes out of the scheduler for the rest of the test.
_STATE_CHECK_RESERVATION_START = "now+7days"
_SLURM_VERSION_COMMANDS = ("sinfo --version", "/opt/slurm/sbin/slurmdbd -V", "sacctmgr --version")


class _UnexpectedComputeFleetStatusError(RuntimeError):
    pass


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as script:
        for chunk in iter(lambda: script.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _download_software_installer_script():
    with _DOWNLOAD_CACHE_LOCK:
        cached_path = _DOWNLOAD_CACHE.get(_INSTALLER_REGION)
        if cached_path:
            path = Path(cached_path)
            if path.is_file() and os.access(path, os.R_OK):
                try:
                    digest = _sha256(path)
                except OSError:
                    pass
                else:
                    logging.info(
                        "Using cached s3://%s/%s (SHA-256: %s)", _INSTALLER_BUCKET, _INSTALLER_KEY, digest
                    )
                    return cached_path
            _DOWNLOAD_CACHE.pop(_INSTALLER_REGION, None)
            _remove_file(cached_path)

        file_descriptor, downloaded_path = tempfile.mkstemp(prefix="pcluster-software-installer-", suffix=".sh")
        os.close(file_descriptor)
        try:
            logging.info(
                "Downloading software installer script from s3://%s/%s in region %s",
                _INSTALLER_BUCKET,
                _INSTALLER_KEY,
                _INSTALLER_REGION,
            )
            boto3.client("s3", region_name=_INSTALLER_REGION).download_file(
                _INSTALLER_BUCKET, _INSTALLER_KEY, downloaded_path
            )
            os.chmod(downloaded_path, 0o700)
            digest = _sha256(Path(downloaded_path))
            logging.info("Downloaded s3://%s/%s (SHA-256: %s)", _INSTALLER_BUCKET, _INSTALLER_KEY, digest)
        except Exception as error:
            _remove_file(downloaded_path)
            raise RuntimeError(
                "Failed to download software installer script from "
                f"s3://{_INSTALLER_BUCKET}/{_INSTALLER_KEY} in region {_INSTALLER_REGION}: {error}"
            ) from error

        _DOWNLOAD_CACHE[_INSTALLER_REGION] = downloaded_path
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


def get_slurm_version(executor):
    """Return the Slurm version reported by the target host, or None when no Slurm binary answers.

    The installer is opaque, so without this the test logs never record which Slurm versions a run
    actually exercised, and a cross-major upgrade is indistinguishable from a no-op reinstall.
    """
    for command in _SLURM_VERSION_COMMANDS:
        result = executor.run_remote_command(command, raise_on_error=False, hide=True)
        if result.return_code == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
    return None


def install_test_software(executor, region):
    """Download the installer from us-east-1 and run it on the target host."""
    script_path = _download_software_installer_script()
    version_before = get_slurm_version(executor)
    result = executor.run_remote_script(script_path, run_as_root=True, timeout=3600, pty=False)
    version_after = get_slurm_version(executor)
    logging.info("Slurm version after the install: %s (was %s before)", version_after, version_before)
    return result


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


def wait_for_partitions_up(scheduler_commands, partitions=None):
    """Wait until the requested partitions (all of them by default) leave the INACTIVE state.

    The compute fleet API reports RUNNING as soon as the status is persisted, but clustermgtd needs
    another iteration to bring the Slurm partitions back UP. Submitting before that happens fails
    with "Requested partition configuration not available now".
    """

    @retry(
        wait_fixed=seconds(15),
        stop_max_delay=minutes(_PARTITION_WAIT_MINUTES),
        retry_on_result=lambda unavailable_partitions: bool(unavailable_partitions),
    )
    def _poll():
        target_partitions = partitions if partitions is not None else scheduler_commands.get_partitions()
        partition_states = {
            partition: scheduler_commands.get_partition_state(partition).strip() for partition in target_partitions
        }
        unavailable_partitions = {
            partition: state for partition, state in partition_states.items() if state.upper() != "UP"
        }
        if unavailable_partitions:
            logging.info("Waiting for Slurm partitions to be UP: %s", unavailable_partitions)
        return unavailable_partitions

    _poll()


def _scontrol_field(text, field):
    """Return the value of a `Key=Value` field of a scontrol one-line output, or None when absent."""
    match = re.search(rf"\b{field}=(\S+)", text)
    return match.group(1) if match else None


def _read_batch_script(remote_command_executor, job_id):
    """Return the batch script slurmctld stored for a job, read back from StateSaveLocation."""
    script_path = f"/tmp/{_STATE_CHECK_RESERVATION}-{job_id}.sh"
    remote_command_executor.run_remote_command(
        f"rm -f {script_path} && scontrol write batch_script {job_id} {script_path}"
    )
    return remote_command_executor.run_remote_command(f"cat {script_path}", hide=True).stdout


def snapshot_slurm_state(remote_command_executor, scheduler_commands):
    """Create Slurm state that a subsequent upgrade must preserve, and return a snapshot describing it.

    The accounting database is not the only thing a Slurm upgrade converts: slurmctld rewrites the contents
    of StateSaveLocation, which holds the queued jobs, their batch scripts and the reservations. Submitting a
    job after the upgrade only proves the controller is up; the state captured here is what proves the upgrade
    converted the state it inherited instead of discarding it.

    Note this deliberately covers pending state only. Running jobs cannot be covered by this harness because
    the installer scales the compute fleet to zero, so verifying that running jobs survive an upgrade needs a
    dedicated test that keeps the fleet up and follows the documented daemon upgrade order.
    """
    held_job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        {"command": "hostname", "nodes": 1, "slots": 1, "other_options": "--hold"}
    )
    job_details = remote_command_executor.run_remote_command(f"scontrol --oneliner show job {held_job_id}").stdout
    snapshot = {
        "held_job_id": held_job_id,
        "held_job_submit_time": _scontrol_field(job_details, "SubmitTime"),
        "held_job_batch_script": _read_batch_script(remote_command_executor, held_job_id),
        "reservation": None,
    }

    nodes = scheduler_commands.get_compute_nodes(all_nodes=True)
    if nodes:
        # Best effort: the reservation widens the coverage to another StateSaveLocation record type, but it is
        # not worth failing a test over, for example if the chosen node cannot be reserved right now.
        remote_command_executor.run_remote_command(
            f"sudo -i scontrol delete ReservationName={_STATE_CHECK_RESERVATION}", raise_on_error=False
        )
        created = remote_command_executor.run_remote_command(
            f"sudo -i scontrol create reservation ReservationName={_STATE_CHECK_RESERVATION} "
            f"user=$(id -un) starttime={_STATE_CHECK_RESERVATION_START} duration=1:00:00 "
            f"flags=maint,ignore_jobs nodes={nodes[0]}",
            raise_on_error=False,
        )
        if created.return_code == 0:
            reservation_details = remote_command_executor.run_remote_command(
                f"scontrol --oneliner show ReservationName={_STATE_CHECK_RESERVATION}"
            ).stdout
            snapshot["reservation"] = {
                "nodes": _scontrol_field(reservation_details, "Nodes"),
                "start_time": _scontrol_field(reservation_details, "StartTime"),
            }
        else:
            logging.warning("Unable to reserve node %s, skipping the reservation check: %s", nodes[0], created.stderr)
    else:
        logging.info("No compute node is configured, skipping the reservation part of the Slurm state snapshot")

    logging.info("Captured Slurm state to verify across the upgrade: %s", snapshot)
    return snapshot


def assert_slurm_state_preserved(remote_command_executor, snapshot):
    """Verify the state captured by snapshot_slurm_state survived the upgrade, then clean it up.

    Every command here runs through the given executor, which must target the head node: the installer scales
    the login pools to zero and back, so any executor bound to a login node before the upgrade now points at a
    terminated instance.
    """
    held_job_id = snapshot["held_job_id"]
    logging.info("Verifying the Slurm state captured before the upgrade is intact")

    job_details = remote_command_executor.run_remote_command(
        f"scontrol --oneliner show job {held_job_id}", raise_on_error=False
    )
    assert_that(job_details.return_code).described_as(
        f"job {held_job_id} is unknown to slurmctld after the upgrade: {job_details.stderr}"
    ).is_equal_to(0)
    assert_that(_scontrol_field(job_details.stdout, "JobState")).described_as(
        f"state of job {held_job_id}"
    ).is_equal_to("PENDING")
    # A converted record keeps its original submission time; a recreated or defaulted one does not.
    assert_that(_scontrol_field(job_details.stdout, "SubmitTime")).described_as(
        f"submit time of job {held_job_id}"
    ).is_equal_to(snapshot["held_job_submit_time"])
    assert_that(_read_batch_script(remote_command_executor, held_job_id)).described_as(
        f"batch script of job {held_job_id}"
    ).is_equal_to(snapshot["held_job_batch_script"])

    expected_reservation = snapshot["reservation"]
    if expected_reservation:
        reservation_details = remote_command_executor.run_remote_command(
            f"scontrol --oneliner show ReservationName={_STATE_CHECK_RESERVATION}", raise_on_error=False
        )
        assert_that(reservation_details.return_code).described_as(
            f"reservation {_STATE_CHECK_RESERVATION} is gone after the upgrade: {reservation_details.stderr}"
        ).is_equal_to(0)
        for field, expected_value in (("Nodes", "nodes"), ("StartTime", "start_time")):
            assert_that(_scontrol_field(reservation_details.stdout, field)).described_as(
                f"{field} of reservation {_STATE_CHECK_RESERVATION}"
            ).is_equal_to(expected_reservation[expected_value])
        remote_command_executor.run_remote_command(
            f"sudo -i scontrol delete ReservationName={_STATE_CHECK_RESERVATION}", raise_on_error=False
        )

    remote_command_executor.run_remote_command(f"scancel {held_job_id}", raise_on_error=False)


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
    wait_for_partitions_up(scheduler_commands, [partition] if partition is not None else None)
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
