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
import hashlib
import logging
import os
import re
import tempfile
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import boto3
from assertpy import assert_that
from retrying import retry
from time_utils import minutes, seconds
from utils import (
    DEFAULT_PARTITION,
    DEFAULT_REPORTING_REGION,
    REPORTING_REGION_MAP,
    describe_cluster_instances,
    get_arn_partition,
)

_INSTALLER_BUCKET = "aws-parallelcluster-dev-build-dependencies"
_INSTALLER_KEY = "install_software.sh"
_COMPUTE_INSTANCE_STATES = ["pending", "running", "shutting-down", "stopping", "stopped"]
_COMPUTE_FLEET_TERMINAL_STATES = {"RUNNING", "STOPPED", "PROTECTED"}
_CAPACITY_WAIT_MINUTES = 15
# Login nodes are drained before they are terminated, and loginmgtd waits out the pool's grace time period (10 minutes
# by default) before it lets the Auto Scaling group reclaim them, so a pool routinely takes over 10 minutes and has
# been measured at more than 15 to disappear. This wait therefore gets a budget of its own.
_TERMINATION_WAIT_MINUTES = 30
_PARTITION_WAIT_MINUTES = 10
_STATE_CHECK_RESERVATION = "slurm-upgrade-state-check"
# The reservation only has to be persisted in StateSaveLocation, so keep it far in the future:
# an active maintenance reservation would take nodes out of the scheduler for the rest of the test.
_STATE_CHECK_RESERVATION_START = "now+7days"
# The name above must stay outside the "pcluster-" namespace: clustermgtd's capacity block manager deletes every
# reservation whose name starts with that prefix and does not belong to a Capacity Block in the cluster
# configuration, which used to make this reservation disappear a couple of minutes after the compute fleet came
# back up, without a trace in slurmctld.log.
_CLUSTERMGTD_LOG = "/var/log/parallelcluster/clustermgtd"
_SLURM_VERSION_COMMANDS = ("sinfo --version", "sudo -n /opt/slurm/sbin/slurmdbd -V", "sacctmgr --version")
_SLURM_CONF = "/opt/slurm/etc/slurm.conf"
_SLURMCTLD_LOG = "/var/log/slurmctld.log"
_INSTALL_BACKUP_GLOB = "/opt/slurm_backup_*.tar.gz"
_STATE_BACKUP_GLOB = "/opt/slurm_state_backup_*.tar.gz"
_SLURM_PREFIX_PARENT = "/opt"
_SLURM_PREFIX_NAME = "slurm"
_SUPERVISORCTL_GLOB = "/opt/parallelcluster/pyenv/versions/*/envs/cookbook_virtualenv/bin/supervisorctl"
# The order daemons are stopped in, and started in reverse: the ParallelCluster daemons go down first because
# clustermgtd treats an unreachable slurmctld as a node failure, and slurmdbd comes up before slurmctld because
# Slurm requires it to be at the same major version or higher.
_PARALLELCLUSTER_DAEMONS = ("clusterstatusmgtd", "clustermgtd")
_SLURM_SERVICES = ("slurmrestd", "slurmctld", "slurmdbd")
_CHEF_CACHE_DIR = "/etc/chef/local-mode-cache/cache"
_ROLLBACK_ASIDE_SUFFIX = "_rollback_aside"
_ACCOUNTING_DATABASE_SCRIPT = Path(__file__).parent / "data" / "slurm_accounting_database.sh"
# Kept in step with the default backup path of the script above.
_ACCOUNTING_BACKUP_GLOB = "/opt/slurm_accounting_backup_*.sql.gz"
# Dumping and restoring the accounting database of a long lived cluster is minutes of work, and it runs
# against a database that may be scaling up while it does, so it gets the same budget as the build itself.
_ACCOUNTING_DATABASE_TIMEOUT = 3600
# Remote commands have no timeout by default, so anything that blocks on the target host stalls the test for as long
# as the run is allowed to last, without a single line of output saying where. Every command this module runs itself
# is minutes of work at most, the installer and the accounting database script being the exceptions that carry their
# own budgets, so they are all capped generously and a stuck one fails instead of hanging.
_REMOTE_COMMAND_TIMEOUT = 600
# The upstream MySQL repository, which holds the command line client of the same release as the client library the
# cookbook installs. The series is read from that library rather than pinned here, so that an AMI moving to another
# MySQL release needs no change.
_MYSQL_CLIENT_RPM_URL = "https://repo.mysql.com/yum/mysql-{series}-community/el/{el_version}/{arch}/{rpm}"


def _artifact_region():
    """Return the Region the artifact bucket lives in for the partition the tests are running against.

    The bucket name is the same in every partition, but the bucket is not: each partition has its own copy, in the
    Region where the development infrastructure of that partition runs, and it is only reachable from inside that
    partition. That is the same Region the test framework reports metrics to, so the mapping is reused from there.
    """
    region = os.environ.get("AWS_DEFAULT_REGION")
    partition = get_arn_partition(region) if region else DEFAULT_PARTITION
    return REPORTING_REGION_MAP.get(partition, DEFAULT_REPORTING_REGION)


@lru_cache(maxsize=None)
def _download_artifact(key, suffix, mode, region):
    """Download an artifact bucket object once per session and return the local path it was cached at."""
    file_descriptor, downloaded_path = tempfile.mkstemp(prefix="pcluster-software-installer-", suffix=suffix)
    os.close(file_descriptor)
    try:
        logging.info("Downloading s3://%s/%s in region %s", _INSTALLER_BUCKET, key, region)
        boto3.client("s3", region_name=region).download_file(_INSTALLER_BUCKET, key, downloaded_path)
        os.chmod(downloaded_path, mode)
    except Exception as error:
        raise RuntimeError(f"Failed to download s3://{_INSTALLER_BUCKET}/{key} in region {region}: {error}") from error

    # The digest identifies which revision of a mutable bucket object a run actually used, which the object key
    # alone does not: the installer script is overwritten in place whenever it is fixed.
    digest = hashlib.sha256(Path(downloaded_path).read_bytes()).hexdigest()
    logging.info("Downloaded s3://%s/%s (SHA-256: %s)", _INSTALLER_BUCKET, key, digest)
    return downloaded_path


def _download_software_installer_script():
    return _download_artifact(_INSTALLER_KEY, ".sh", 0o700, _artifact_region())


def _installer_constant(script_text, name, substitutions=None):
    """Return a constant declared by the installer script, so that the tests never restate its values."""
    match = re.search(rf'^(?:readonly\s+)?{name}="([^"]*)"', script_text, re.MULTILINE)
    assert_that(match).described_as(f"declaration of {name} in the software installer script").is_not_none()
    value = match.group(1)
    for variable, replacement in (substitutions or {}).items():
        value = value.replace(f"${{{variable}}}", replacement)
    return value


def _source_archive_location(script_path):
    """Return the S3 key of the Slurm source archive and the path the installer expects it at on the host."""
    script_text = Path(script_path).read_text(encoding="utf-8")
    source_name = _installer_constant(script_text, "TARGET_SOURCE_NAME")
    cache_dir = _installer_constant(script_text, "CACHE_DIR")
    key = _installer_constant(script_text, "DEFAULT_ARCHIVE_KEY", {"TARGET_SOURCE_NAME": source_name})
    path = _installer_constant(
        script_text, "ARCHIVE_PATH", {"CACHE_DIR": cache_dir, "TARGET_SOURCE_NAME": source_name}
    )
    return key, path


def _stage_source_archive(executor, script_path):
    """Upload the Slurm source archive to the target host, which is not expected to read the artifact bucket itself.

    The installer can download the archive on its own, but only from a host whose instance role grants read access to
    the artifact bucket. Neither the head node of a cluster nor an external slurmdbd instance has that access, and
    granting it would mean editing the cluster configuration of every test that installs the software (and would be
    impossible for the slurmdbd instance, whose role comes from a customer-facing CloudFormation template that takes
    no parameter to extend it). So the archive travels over the same SSH connection as the installer, on the test
    runner's credentials, and the installer picks up an archive that is already in place instead of downloading one.
    """
    archive_key, remote_path = _source_archive_location(script_path)
    local_path = _download_artifact(archive_key, ".tar.gz", 0o600, _artifact_region())
    remote_name = os.path.basename(remote_path)
    logging.info("Staging s3://%s/%s at %s on the target host", _INSTALLER_BUCKET, archive_key, remote_path)
    executor.run_remote_command(
        f"sudo install -o root -g root -m 644 {remote_name} {remote_path} && rm -f {remote_name}",
        additional_files={local_path: remote_name},
        hide=True,
    )


def _compute_instance_ids(cluster):
    """Return the IDs of the compute instances of a cluster that are not gone yet.

    Instances that are shutting down still count as consumers: they keep the shared /opt/slurm of the head node
    mounted, and their slurmd is still running the version the installer is about to replace.
    """
    instances = describe_cluster_instances(
        cluster.cfn_name,
        cluster.region,
        filter_by_node_type="Compute",
        filter_by_instance_states=_COMPUTE_INSTANCE_STATES,
    )
    return sorted(instance["InstanceId"] for instance in instances)


def _describe_login_asg(snapshot, asg_snapshot):
    """Return the Auto Scaling group of a login pool, checking it is the group the pool owns.

    The group name is built out of the cluster and pool names rather than read from the cluster, so the
    parallelcluster:login-nodes-pool tag is what confirms the guess landed on the right group before its capacity
    is changed.
    """
    asg_name = asg_snapshot["AutoScalingGroupName"]
    groups = snapshot["autoscaling"].describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])[
        "AutoScalingGroups"
    ]
    if len(groups) != 1 or groups[0]["AutoScalingGroupName"] != asg_name:
        raise RuntimeError(f"Expected exactly one login-node Auto Scaling group named {asg_name}, found {len(groups)}")

    group = groups[0]
    tag_values = [tag["Value"] for tag in group.get("Tags", []) if tag["Key"] == "parallelcluster:login-nodes-pool"]
    if tag_values != [asg_snapshot["pool_name"]]:
        raise RuntimeError(
            f"Auto Scaling group {asg_name} has unexpected parallelcluster:login-nodes-pool tag values "
            f"{tag_values}; expected [{asg_snapshot['pool_name']}]"
        )
    return group


def _snapshot_cluster(cluster):
    snapshot = {
        "cluster": cluster,
        "autoscaling": boto3.client("autoscaling", region_name=cluster.region),
        "login_asgs": [],
    }
    compute_status = cluster.describe_compute_fleet()["status"]
    if compute_status not in _COMPUTE_FLEET_TERMINAL_STATES:
        raise RuntimeError(
            f"Cluster {cluster.name} compute fleet must be in RUNNING, STOPPED, or PROTECTED state before maintenance; "
            f"found {compute_status}"
        )
    snapshot["compute_status"] = compute_status

    for pool in cluster.config.get("LoginNodes", {}).get("Pools", []):
        asg_snapshot = {
            "pool_name": pool["Name"],
            "AutoScalingGroupName": f"{cluster.name}-{pool['Name']}-AutoScalingGroup",
        }
        group = _describe_login_asg(snapshot, asg_snapshot)
        asg_snapshot.update({key: group[key] for key in ("MinSize", "MaxSize", "DesiredCapacity")})
        snapshot["login_asgs"].append(asg_snapshot)

    logging.info(
        "Snapshotted cluster %s in %s: compute fleet %s, %d login pools",
        cluster.name,
        cluster.region,
        compute_status,
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


def _login_asg_instance_ids(snapshot, asg_snapshot, lifecycle_state=None):
    """Return the instances of a login pool's Auto Scaling group, optionally only those in a given state."""
    instances = _describe_login_asg(snapshot, asg_snapshot).get("Instances", [])
    return sorted(
        instance["InstanceId"]
        for instance in instances
        if lifecycle_state is None
        or (instance["LifecycleState"] == lifecycle_state and instance["HealthStatus"] == "Healthy")
    )


def _wait_for_consumers_terminated(snapshots):
    @retry(
        wait_fixed=seconds(15),
        stop_max_delay=minutes(_TERMINATION_WAIT_MINUTES),
        retry_on_result=lambda consumers_remain: consumers_remain,
    )
    def _poll():
        consumers_remain = False
        for snapshot in snapshots:
            compute_instance_ids = _compute_instance_ids(snapshot["cluster"])
            if compute_instance_ids:
                consumers_remain = True
                logging.info(
                    "Waiting for cluster %s compute instances to terminate: %s",
                    snapshot["cluster"].name,
                    compute_instance_ids,
                )

            for asg_snapshot in snapshot["login_asgs"]:
                login_instance_ids = _login_asg_instance_ids(snapshot, asg_snapshot)
                if login_instance_ids:
                    consumers_remain = True
                    logging.info(
                        "Waiting for login Auto Scaling group %s instances to terminate: %s",
                        asg_snapshot["AutoScalingGroupName"],
                        login_instance_ids,
                    )
        return consumers_remain

    _poll()


def _pause_consumers(snapshots):
    for snapshot in snapshots:
        if snapshot["compute_status"] != "STOPPED":
            # A PROTECTED fleet is stopped as well: protected mode disables the queues but leaves the compute
            # instances of the healthy compute resources running, and those keep the old Slurm mounted.
            logging.info("Requesting compute fleet stop for cluster %s", snapshot["cluster"].name)
            snapshot["cluster"].stop()

    for snapshot in snapshots:
        for asg_snapshot in snapshot["login_asgs"]:
            logging.info("Scaling login Auto Scaling group %s to zero", asg_snapshot["AutoScalingGroupName"])
            snapshot["autoscaling"].update_auto_scaling_group(
                AutoScalingGroupName=asg_snapshot["AutoScalingGroupName"],
                MinSize=0,
                DesiredCapacity=0,
            )

    for snapshot in snapshots:
        if snapshot["compute_status"] != "STOPPED":
            _wait_for_compute_status(snapshot, "STOPPED")
    _wait_for_consumers_terminated(snapshots)
    logging.info("All non-head-node consumers are stopped")


def _wait_for_login_asg_restored(snapshot, asg_snapshot):
    desired_capacity = asg_snapshot["DesiredCapacity"]

    @retry(
        wait_fixed=seconds(15),
        stop_max_delay=minutes(_CAPACITY_WAIT_MINUTES),
        retry_on_result=lambda instance_ids: len(instance_ids) < desired_capacity,
    )
    def _poll():
        instance_ids = _login_asg_instance_ids(snapshot, asg_snapshot, lifecycle_state="InService")
        logging.info(
            "Login Auto Scaling group %s has %d/%d instances in service",
            asg_snapshot["AutoScalingGroupName"],
            len(instance_ids),
            desired_capacity,
        )
        return instance_ids

    _poll()


def _restore_consumers(snapshots):
    errors = []

    for snapshot in snapshots:
        for asg_snapshot in snapshot["login_asgs"]:
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

        if snapshot["compute_status"] == "RUNNING":
            try:
                snapshot["cluster"].start()
            except Exception as error:
                errors.append((f"start compute fleet for cluster {snapshot['cluster'].name}", error))
        elif snapshot["compute_status"] != "STOPPED":
            # PROTECTED is not a status the compute fleet API accepts, so it cannot be requested back. Leaving the
            # fleet STOPPED is reported here rather than silently, because it changes what the caller sees next.
            logging.warning(
                "Cluster %s compute fleet was %s before the maintenance and is left STOPPED",
                snapshot["cluster"].name,
                snapshot["compute_status"],
            )

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


@contextmanager
def stopped_shared_slurm_consumers(*clusters):
    """Temporarily stop all compute fleets and login pools shared by a maintenance operation."""
    snapshots = []
    mutation_started = False
    primary_error = None
    try:
        # A cluster passed twice, for example because two head nodes share an external slurmdbd, must only be
        # snapshotted and restored once.
        unique_clusters = {(cluster.name, cluster.region): cluster for cluster in clusters}.values()
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
                details = "\n".join(f"- {operation}: {error}" for operation, error in restoration_errors)
                message = f"Failed to fully restore cluster consumers:\n{details}"
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


def slurm_major_version(version):
    """Return the major.minor Slurm release of a version string such as "slurm 24.11.6", or None."""
    match = re.search(r"\d+\.\d+", version or "")
    return match.group(0) if match else None


def _newest_backup_archive(executor, pattern):
    """Return the path of the newest archive matching a glob on the target host."""
    newest = executor.run_remote_command(f"ls -1t {pattern} | head -n 1", raise_on_error=False, hide=True)
    assert_that(newest.return_code).described_as(
        f"no backup archive matches {pattern}: {newest.stderr}"
    ).is_equal_to(0)
    archive = newest.stdout.strip()
    assert_that(archive).described_as(f"newest backup archive matching {pattern}").is_not_empty()
    return archive


def _assert_backup_archive_readable(executor, pattern):
    """Assert the newest archive matching a glob exists and can be listed by tar."""
    archive = _newest_backup_archive(executor, pattern)

    # Listing the archive proves it is a valid gzip stream with contents, which "the file exists" does not: a
    # backup truncated by a full disk looks identical until someone actually needs to restore it.
    listing = executor.run_remote_command(f"sudo tar -tzf {archive} | head -n 5", raise_on_error=False, hide=True)
    assert_that(listing.stdout.strip()).described_as(
        f"contents of backup archive {archive}: {listing.stderr}"
    ).is_not_empty()
    logging.info("Verified upgrade backup archive %s is readable", archive)


def assert_upgrade_backups_readable(executor):
    """Assert the installer left a readable backup of everything it converts in place.

    These archives are the only way back from an upgrade: one holds the previous /opt/slurm build, the other the
    pre-conversion StateSaveLocation. Cross-major the accounting database conversion cannot be undone at all, so
    an unusable backup turns a recoverable upgrade into an unrecoverable one.
    """
    patterns = [_INSTALL_BACKUP_GLOB]
    # The installer only backs up StateSaveLocation when slurm.conf declares one, which excludes an external
    # slurmdbd node.
    state_save_location = executor.run_remote_command(
        f"grep -iE '^[[:space:]]*StateSaveLocation[[:space:]]*=' {_SLURM_CONF}", raise_on_error=False, hide=True
    )
    if state_save_location.return_code == 0:
        patterns.append(_STATE_BACKUP_GLOB)

    for pattern in patterns:
        _assert_backup_archive_readable(executor, pattern)


def _log_file_size(executor, path):
    """Return the current size of a root-owned log file, so a later check can be scoped to what is appended after."""
    result = executor.run_remote_command(f"sudo wc -c {path}", raise_on_error=False, hide=True)
    return int(result.stdout.split()[0]) if result.return_code == 0 else 0


def _report_slurmctld_log_of_replacement(executor, offset, operation):
    """Report what slurmctld logged while Slurm was replaced under it, by the installer or by a rollback.

    Error-level lines are expected here rather than exceptional: every daemon of the new Slurm re-validates the
    slurm.conf written by the ParallelCluster release under test, which is what known_harmless_slurm_daemon_errors
    exists for. They are logged instead of asserted on because a "defunct" or "obsolete" parameter reported here
    is a finding about the release, not a failure of the upgrade. A fatal line is different: it means the daemon
    gave up, which no ParallelCluster release may cause.
    """
    log = executor.run_remote_command(
        f"sudo tail -c +{offset + 1} {_SLURMCTLD_LOG}", raise_on_error=False, hide=True
    ).stdout
    error_lines = [line for line in log.splitlines() if re.search(r"error|fatal|defunct|obsolete", line, re.I)]
    if error_lines:
        logging.warning(
            "slurmctld reported %d error-level lines during the %s:\n%s",
            len(error_lines),
            operation,
            "\n".join(error_lines),
        )
    assert_that([line for line in error_lines if "fatal" in line.lower()]).described_as(
        f"fatal slurmctld messages logged during the {operation}"
    ).is_empty()


def install_test_software(executor, assert_controller=True):
    """Download the installer and the Slurm sources, run the installer on the target host and verify what it left.

    Clear assert_controller for a host that runs no slurmctld, such as an external slurmdbd instance.
    """
    script_path = _download_software_installer_script()
    _stage_source_archive(executor, script_path)
    target_version = _installer_constant(Path(script_path).read_text(encoding="utf-8"), "TARGET_RUNTIME_VERSION")
    version_before = get_slurm_version(executor)
    slurmctld_log_size = _log_file_size(executor, _SLURMCTLD_LOG)
    result = executor.run_remote_script(script_path, run_as_root=True, timeout=3600, pty=False)

    version_after = get_slurm_version(executor)
    logging.info(
        "Slurm version after the install: %s (was %s before), a %s",
        version_after,
        version_before,
        (
            "same-major reinstall"
            if slurm_major_version(version_before) == slurm_major_version(version_after)
            else "cross-major upgrade"
        ),
    )
    # The installer checks the version it installed itself, but only against its own constant. Checking it here as
    # well is what fails a run whose installer targets a different version than the run is meant to exercise, for
    # example because the mutable bucket object was replaced between two runs of the same suite.
    assert_that(version_after).described_as("Slurm version reported by the host after the install").contains(
        target_version
    )
    if version_after != version_before:
        # Only when the installer actually replaced something: it skips the backups, and everything else, when
        # the target version is already installed.
        assert_upgrade_backups_readable(executor)
    if assert_controller:
        assert_slurm_controller_healthy(executor)
        _report_slurmctld_log_of_replacement(executor, slurmctld_log_size, "install")
    return result


def install_test_software_with_stopped_consumers(executor, *clusters):
    """Run the test software installer while the clusters have no compute or login consumers."""
    with stopped_shared_slurm_consumers(*clusters):
        return install_test_software(executor)


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
        remote_command_executor.run_remote_command(
            f"sudo -i scontrol delete ReservationName={_STATE_CHECK_RESERVATION}", raise_on_error=False
        )
        # Not best effort: a reservation covers a StateSaveLocation record type the held job does not, and a
        # controller that cannot create one is already a finding, whether the upgrade is to blame or not.
        created = remote_command_executor.run_remote_command(
            f"sudo -i scontrol create reservation ReservationName={_STATE_CHECK_RESERVATION} "
            f"user=$(id -un) starttime={_STATE_CHECK_RESERVATION_START} duration=1:00:00 "
            f"flags=maint,ignore_jobs nodes={nodes[0]}",
            raise_on_error=False,
        )
        assert_that(created.return_code).described_as(
            f"creation of reservation {_STATE_CHECK_RESERVATION} on node {nodes[0]}: {_failed_command_output(created)}"
        ).is_equal_to(0)
        reservation_details = remote_command_executor.run_remote_command(
            f"scontrol --oneliner show ReservationName={_STATE_CHECK_RESERVATION}"
        ).stdout
        snapshot["reservation"] = {
            "nodes": _scontrol_field(reservation_details, "Nodes"),
            "start_time": _scontrol_field(reservation_details, "StartTime"),
        }
    else:
        logging.info("No compute node is configured, skipping the reservation part of the Slurm state snapshot")

    logging.info("Captured Slurm state to verify across the upgrade: %s", snapshot)
    return snapshot


def _failed_command_output(result):
    """Return the output that explains a failed remote command.

    Remote commands run over a pty by default, which merges stderr into stdout, so an assertion message built out
    of stderr alone is empty for most of the commands here.
    """
    return result.stderr.strip() or result.stdout.strip()


def _reservation_diagnostics(remote_command_executor):
    """Describe what the controller knows about reservations, for when the state check finds one missing.

    A reservation can disappear for two very different reasons: the upgrade failed to convert the record, or
    something in the cluster deleted the reservation deliberately. Which reservations survived and what slurmctld
    logged about them is what separates the two, and neither is recoverable from the test's own commands.

    clustermgtd is included because a deletion it performs leaves no trace in slurmctld.log: a successful delete
    is only logged by slurmctld under DebugFlags=Reservation.
    """
    reservations = remote_command_executor.run_remote_command(
        "scontrol show reservation", raise_on_error=False, hide=True
    )
    controller_log = remote_command_executor.run_remote_command(
        f"sudo grep -i -e reservation -e 'recovered state' {_SLURMCTLD_LOG} | tail -n 40",
        raise_on_error=False,
        hide=True,
    )
    node_daemon_log = remote_command_executor.run_remote_command(
        f"sudo grep -i reservation {_CLUSTERMGTD_LOG} | tail -n 20",
        raise_on_error=False,
        hide=True,
    )
    return (
        f"reservations known to the controller: {reservations.stdout.strip() or '<none>'}. "
        f"slurmctld log: {controller_log.stdout.strip() or '<nothing about reservations>'}. "
        f"clustermgtd log: {node_daemon_log.stdout.strip() or '<nothing about reservations>'}"
    )


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
        f"job {held_job_id} is unknown to slurmctld after the upgrade: {_failed_command_output(job_details)}"
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
        diagnostics = (
            "" if reservation_details.return_code == 0 else f" {_reservation_diagnostics(remote_command_executor)}"
        )
        assert_that(reservation_details.return_code).described_as(
            f"reservation {_STATE_CHECK_RESERVATION} is gone after the upgrade: "
            f"{_failed_command_output(reservation_details)}.{diagnostics}"
        ).is_equal_to(0)
        for field, expected_value in (("Nodes", "nodes"), ("StartTime", "start_time")):
            assert_that(_scontrol_field(reservation_details.stdout, field)).described_as(
                f"{field} of reservation {_STATE_CHECK_RESERVATION}"
            ).is_equal_to(expected_reservation[expected_value])
        remote_command_executor.run_remote_command(
            f"sudo -i scontrol delete ReservationName={_STATE_CHECK_RESERVATION}", raise_on_error=False
        )

    remote_command_executor.run_remote_command(f"scancel {held_job_id}", raise_on_error=False)


def _run_probe(executor, command, sudo=False):
    """Run a remote command whose exit code or output the caller inspects itself, under the same time cap."""
    return executor.run_remote_command(
        f"sudo {command}" if sudo else command, raise_on_error=False, hide=True, timeout=_REMOTE_COMMAND_TIMEOUT
    )


def _run_checked(executor, command, description, sudo=True):
    """Run a remote command that must succeed and return its stripped stdout."""
    result = executor.run_remote_command(
        f"sudo {command}" if sudo else command, raise_on_error=False, hide=True, timeout=_REMOTE_COMMAND_TIMEOUT
    )
    assert_that(result.return_code).described_as(f"{description}: {_failed_command_output(result)}").is_equal_to(0)
    return result.stdout.strip()


def _supervisorctl_path(executor):
    """Return the supervisorctl of the cookbook virtual environment, which controls the ParallelCluster daemons."""
    paths = _run_checked(
        executor, f"ls -1 {_SUPERVISORCTL_GLOB}", "the cookbook supervisorctl of the target host", sudo=False
    ).split()
    assert_that(paths).described_as(f"supervisorctl binaries matching {_SUPERVISORCTL_GLOB}").is_length(1)
    return paths[0]


def _service_exists(executor, service):
    """Return whether a systemd service is installed on the target host.

    slurmrestd is only present when the cluster enables the REST API, and slurmdbd only runs on a head node whose
    cluster keeps its accounting database locally, so neither can be stopped unconditionally.

    The load state is asked for instead of the unit file being printed with `systemctl cat`, which hung the whole
    test on every host that really has slurmdbd installed: printing commands are piped through a pager when
    systemctl believes it writes to a terminal, which the pty of a remote command makes it believe. `show` prints
    a single line and pages nothing. --property is spelled out and the value matched inside the output because
    --value needs a newer systemd than the oldest supported distribution has.
    """
    load_state = executor.run_remote_command(
        f"systemctl show --no-pager --property=LoadState {service}.service",
        raise_on_error=False,
        hide=True,
        pty=False,
        timeout=_REMOTE_COMMAND_TIMEOUT,
    ).stdout
    return "LoadState=loaded" in load_state


def _parallelcluster_daemons(executor, supervisorctl):
    """Return the ParallelCluster daemons of _PARALLELCLUSTER_DAEMONS supervisord runs on this host.

    The names are read back from supervisord rather than used as they are, so that a supervisord that cannot be
    reached fails here instead of turning every stop and start below into a silent no-op.
    """
    # supervisorctl exits non-zero as soon as one program is not RUNNING, so the exit code says nothing here.
    status = _run_probe(executor, f"{supervisorctl} status", sudo=True).stdout
    known = {line.split()[0] for line in status.splitlines() if line.strip()}
    daemons = [daemon for daemon in _PARALLELCLUSTER_DAEMONS if daemon in known]
    assert_that(daemons).described_as(
        f"ParallelCluster daemons known to supervisord, which reported: {status}"
    ).is_length(len(_PARALLELCLUSTER_DAEMONS))
    return daemons


def _stop_slurm_stack(executor, supervisorctl, daemons):
    for daemon in daemons:
        # supervisorctl reports a program that is already down as an error, so the state is asserted rather than
        # the exit code: what matters is that the daemon is not running while the binaries are replaced.
        _run_probe(executor, f"{supervisorctl} stop {daemon}", sudo=True)
        status = _run_probe(executor, f"{supervisorctl} status {daemon}", sudo=True).stdout
        assert_that(status).described_as(f"status of {daemon} after stopping it").does_not_contain("RUNNING")

    for service in _SLURM_SERVICES:
        if _service_exists(executor, service):
            _run_checked(executor, f"systemctl stop {service}", f"stop of {service}")


def _start_slurm_stack(executor, supervisorctl, daemons):
    for service in reversed(_SLURM_SERVICES):
        if _service_exists(executor, service):
            _run_checked(executor, f"systemctl start {service}", f"start of {service}")
    for daemon in daemons:
        _run_checked(executor, f"{supervisorctl} start {daemon}", f"start of the ParallelCluster daemon {daemon}")


def _state_save_location(executor):
    """Return the StateSaveLocation the cluster configuration declares."""
    declaration = _run_checked(
        executor,
        f"grep -ihE '^[[:space:]]*StateSaveLocation[[:space:]]*=' {_SLURM_CONF} | tail -n 1",
        f"StateSaveLocation declared in {_SLURM_CONF}",
        sudo=False,
    )
    return declaration.split("=", 1)[1].strip()


def _restore_directory_from_archive(executor, archive, parent, name, aside):
    """Replace parent/name with the copy the archive holds, keeping what is there now under aside.

    The current directory is moved aside rather than extracted over, because tar merges into an existing tree: an
    extraction on top of it would leave behind every file that exists only in the version being rolled back.
    """
    members = _run_checked(executor, f"tar -tzf {archive} | head -n 20", f"listing of {archive}")
    top_level = {member.split("/")[0] for member in members.splitlines() if member.strip()}
    assert_that(top_level).described_as(f"top-level entries of {archive}").is_equal_to({name})

    _run_checked(executor, f"rm -rf {aside}", f"removal of a leftover {aside}")
    _run_checked(executor, f"mv {parent}/{name} {aside}", f"move of {parent}/{name} to {aside}")
    _run_checked(executor, f"tar -xzf {archive} -C {parent}", f"extraction of {archive} into {parent}")
    _run_checked(executor, f"test -d {parent}/{name}", f"presence of {parent}/{name} after extracting {archive}")


def _ensure_mysql_client(executor):
    """Install the MySQL command line tools on the target host if they are missing.

    No ParallelCluster AMI ships them. The cookbook installs the client library slurmdbd links against, together
    with its common, plugin and development components on the RPM based distributions and libmysqlclient alone on
    the Debian family, and none of those carries mysqldump. So this runs on every operating system, before the
    accounting database is dumped or restored.
    """
    if _run_probe(executor, "command -v mysqldump").return_code == 0:
        return
    logging.info("mysqldump is not installed on the target host, installing the MySQL command line client")
    if _run_probe(executor, "command -v apt-get").return_code == 0:
        _run_checked(
            executor,
            "sh -c 'apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y mysql-client'",
            "installation of the MySQL command line client",
        )
    else:
        _install_mysql_client_rpm(executor)
    _run_checked(executor, "sh -c 'command -v mysqldump && command -v mysql'", "MySQL command line tools")


def _install_mysql_client_rpm(executor):
    """Install the mysql-community-client release that matches the client library already on the host.

    The RPM is fetched from the MySQL repository rather than installed with `yum install mysql`, because the
    repositories an AMI is pinned to are not dependable: those of Rocky Linux 9.5 have been retired, so every dnf
    call ignores them and no package name resolves at all. The ParallelCluster mirror is not an alternative, as it
    only carries the four components the cookbook installs, none of which is the one holding mysqldump. The
    distribution package is still tried afterwards, so a host whose repositories do work is never worse off.
    """
    release = _run_checked(
        executor,
        "rpm -q --queryformat '%{VERSION}-%{RELEASE}.%{ARCH}' mysql-community-libs",
        "release of the MySQL client library installed on the target host",
    )
    # The release reads like 8.4.10-1.el9.x86_64, which is everything the repository layout and the file name need.
    match = re.fullmatch(r"(\d+\.\d+)\.\d+-\S+\.el(\d+)\.(\w+)", release)
    if match:
        series, el_version, arch = match.groups()
        rpm = f"mysql-community-client-{release}.rpm"
        url = _MYSQL_CLIENT_RPM_URL.format(series=series, el_version=el_version, arch=arch, rpm=rpm)
        logging.info("Installing the MySQL command line client from %s", url)
        # The repositories are disabled because the client only needs the components the cookbook already
        # installed, and reading their metadata is exactly what fails on an AMI whose mirrors are gone.
        installation = _run_probe(
            executor,
            f'sh -c \'curl -fsSL -o /tmp/{rpm} {url} && yum install -y --disablerepo="*" /tmp/{rpm}\'',
            sudo=True,
        )
        if installation.return_code == 0:
            return
        logging.warning(
            "Could not install %s, falling back to the distribution package: %s",
            url,
            _failed_command_output(installation),
        )
    else:
        logging.warning(
            "Cannot tell which mysql-community-client release matches the installed library %s, falling back to "
            "the distribution package",
            release,
        )
    _run_checked(executor, "yum install -y mysql", "installation of the MySQL command line client")


def _run_accounting_database_script(executor, *args):
    """Run the accounting database backup and restore script on the host that runs slurmdbd."""
    _ensure_mysql_client(executor)
    return executor.run_remote_script(
        str(_ACCOUNTING_DATABASE_SCRIPT),
        args=list(args),
        run_as_root=True,
        timeout=_ACCOUNTING_DATABASE_TIMEOUT,
        pty=False,
    )


def back_up_accounting_database(executor):
    """Dump the Slurm accounting database of the host the executor targets, and return the archive path.

    Call this before the upgrade, from the host that runs slurmdbd: the head node of a cluster that keeps its
    accounting database locally, or the external slurmdbd instance. The first slurmdbd of a new Slurm major
    release converts the database schema one way, so this dump is the only thing that can undo that conversion,
    and therefore the only thing that makes a cross major version rollback possible at all.
    """
    _run_accounting_database_script(executor, "backup")
    archive = _newest_backup_archive(executor, _ACCOUNTING_BACKUP_GLOB)
    _run_checked(executor, f"gzip --test {archive}", f"integrity of the accounting database backup {archive}")
    # A dump of zero tables is a valid gzip stream, and restoring it would silently replace the accounting
    # database with an empty one, so the archive is checked for the schema it is supposed to carry.
    tables = _run_checked(
        executor,
        f"sh -c 'gzip -dc {archive} | grep -c \"^CREATE TABLE\"'",
        f"tables in the accounting database backup {archive}",
    )
    logging.info("Backed the accounting database up to %s, holding %s tables", archive, tables)
    return archive


def _restore_accounting_database(executor, archive):
    """Restore an accounting database dump, undoing the schema conversion of a cross-major upgrade.

    slurmdbd must already be stopped: the script refuses to run otherwise, because the dump drops and recreates
    the database it restores.
    """
    logging.info("Restoring the accounting database from %s", archive)
    _run_accounting_database_script(executor, "restore", archive)


def _assert_rollback_is_supported(executor, version_before, expected_version, accounting_backup):
    """Refuse to roll back a cross-major upgrade that would leave a converted accounting database behind.

    The conversion the first slurmdbd of a new major version performs is one way: the older binaries cannot read
    the converted database. Restoring only the binaries would leave slurmdbd unable to start, so a cross-major
    rollback of the host that runs slurmdbd also needs the dump taken before the upgrade.

    A head node whose cluster uses an external slurmdbd is not subject to this: an older slurmctld talking to a
    newer slurmdbd is the combination Slurm supports, and it is the external slurmdbd host that has to restore
    the database when it is rolled back in turn.
    """
    if slurm_major_version(version_before) == slurm_major_version(expected_version):
        return
    if accounting_backup is not None or not _service_exists(executor, "slurmdbd"):
        return
    raise RuntimeError(
        f"Refusing to roll Slurm {version_before} back to {expected_version}: the major version differs and this "
        f"host runs slurmdbd, so the accounting database was converted one way. Pass the accounting_backup that "
        f"back_up_accounting_database took before the upgrade."
    )


def assert_slurm_source_tree_present(executor, version):
    """Assert the Chef cache still holds the source tree a given Slurm version was built from.

    That tree is what `make uninstall` of the installed version needs, so an upgrade cannot be attempted again
    without it. Nothing can recreate it on a cluster with no internet access, which makes deleting it during an
    upgrade the difference between a recoverable and an unrecoverable cluster.
    """
    release = re.search(r"\d+\.\d+\.\d+", version or "")
    assert_that(release).described_as(f"a Slurm release in {version!r}").is_not_none()
    # find rather than a glob, because the Chef cache directory is only readable by root, so a pattern expanded by
    # the shell of the login user matches nothing instead of failing.
    name = f"slurm-slurm-{release.group(0).replace('.', '-')}-*"
    trees = _run_checked(
        executor,
        f'find {_CHEF_CACHE_DIR} -mindepth 1 -maxdepth 1 -type d -name "{name}"',
        f"search for the source tree of Slurm {version} under {_CHEF_CACHE_DIR}",
    ).split()
    assert_that(trees).described_as(f"source trees of Slurm {version} named {name}").is_length(1)
    _run_checked(executor, f"test -f {trees[0]}/Makefile", f"Makefile of the source tree {trees[0]}")
    logging.info("The source tree of Slurm %s is still available at %s", version, trees[0])


def roll_back_test_software(executor, expected_version, accounting_backup=None, assert_controller=True):
    """Roll the target host back to the Slurm version it ran before the test software was installed.

    This is the procedure the upgrade documentation prescribes, exercised end to end: restoring the archives the
    installer left is the only way back from an upgrade, and a backup that cannot be restored is indistinguishable
    from a readable one until a cluster actually needs it. Pass the version the host reported before the install.

    Pass the accounting_backup that back_up_accounting_database took before the upgrade to roll a host that runs
    slurmdbd back across a major version: the schema conversion is not reversible any other way. Clear
    assert_controller for a host that runs no slurmctld, such as an external slurmdbd instance; such a host has no
    StateSaveLocation to restore either.

    The compute and login nodes must already be stopped, exactly as for the install, and the call leaves the host
    on the previous Slurm version, so it belongs after everything that must run on the new one.
    """
    version_before = get_slurm_version(executor)
    assert_that(version_before).described_as("Slurm version reported by the host before the rollback").is_not_none()
    if version_before == expected_version:
        raise RuntimeError(f"The host already runs Slurm {expected_version}, so there is nothing to roll back")
    _assert_rollback_is_supported(executor, version_before, expected_version, accounting_backup)

    install_archive = _newest_backup_archive(executor, _INSTALL_BACKUP_GLOB)
    slurmctld_log_size = _log_file_size(executor, _SLURMCTLD_LOG)
    slurm_aside = f"{_SLURM_PREFIX_PARENT}/{_SLURM_PREFIX_NAME}{_ROLLBACK_ASIDE_SUFFIX}"
    supervisorctl = None
    daemons = []
    state_archive = state_save_location = state_aside = None
    if assert_controller:
        # A host that runs no controller runs no clustermgtd and has no StateSaveLocation of its own either, so
        # both are looked up only where they exist.
        supervisorctl = _supervisorctl_path(executor)
        daemons = _parallelcluster_daemons(executor, supervisorctl)
        state_archive = _newest_backup_archive(executor, _STATE_BACKUP_GLOB)
        state_save_location = _state_save_location(executor)
        state_aside = f"{state_save_location}{_ROLLBACK_ASIDE_SUFFIX}"

    logging.info("Rolling Slurm %s back to %s from %s", version_before, expected_version, install_archive)
    _stop_slurm_stack(executor, supervisorctl, daemons)
    _restore_directory_from_archive(
        executor, install_archive, _SLURM_PREFIX_PARENT, _SLURM_PREFIX_NAME, slurm_aside
    )
    _run_checked(executor, "ldconfig", f"ldconfig after restoring {_SLURM_PREFIX_PARENT}/{_SLURM_PREFIX_NAME}")
    if state_archive:
        # The controller state has to go back with the binaries: Slurm state files are not backward compatible, so
        # the state the new slurmctld rewrote can be state the restored one refuses to read.
        _restore_directory_from_archive(
            executor,
            state_archive,
            os.path.dirname(state_save_location),
            os.path.basename(state_save_location),
            state_aside,
        )
    if accounting_backup:
        # After the binaries and before the daemons come back: the restored slurmdbd is the one that has to find a
        # schema it can read, and the dump drops and recreates the database, which no slurmdbd may be using.
        _restore_accounting_database(executor, accounting_backup)
    _start_slurm_stack(executor, supervisorctl, daemons)

    version_after = get_slurm_version(executor)
    assert_that(version_after).described_as("Slurm version reported by the host after the rollback").is_equal_to(
        expected_version
    )
    if assert_controller:
        assert_slurm_controller_healthy(executor)
        _report_slurmctld_log_of_replacement(executor, slurmctld_log_size, "rollback")
    assert_slurm_source_tree_present(executor, expected_version)
    aside_directories = " ".join(path for path in (slurm_aside, state_aside) if path)
    _run_checked(executor, f"rm -rf {aside_directories}", "cleanup of the directories moved aside")
    logging.info("Rolled Slurm back to %s", version_after)
    return version_after


def roll_back_test_software_with_stopped_consumers(executor, *clusters, expected_version, accounting_backup=None):
    """Roll the target host back while the clusters have no compute or login consumers."""
    with stopped_shared_slurm_consumers(*clusters):
        return roll_back_test_software(executor, expected_version, accounting_backup=accounting_backup)


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
