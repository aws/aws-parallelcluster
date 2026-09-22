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
"""Upgrade Slurm in place on a running cluster, and roll it back, the way the wiki page documents it.

The page is https://github.com/aws/aws-parallelcluster/wiki/Upgrade-Slurm-in-an-AWS-ParallelCluster-cluster and the
scripts it links to live in util/slurm-upgrade. This module runs those scripts unchanged and adds only what the page
leaves to the operator's own machine (Steps 1 and 6 on the compute fleet) and what a test needs to prove the result
(state snapshots, smoke jobs). Where the page and this module differ, the page wins.

Appendix E, scaling the login nodes down for the duration, is optional on the page and deliberately not done here: the
login nodes stay up and keep /opt/slurm mounted while it is replaced, which is the riskier path and the one to test.
"""
import logging
import os
import re
import shlex
from contextlib import contextmanager
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

# The scripts the wiki page links to. They are uploaded to the target host and run from there as they are.
_SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "util" / "slurm-upgrade"
_UPGRADE_SCRIPT = _SCRIPTS_DIR / "slurm_upgrade.sh"
_REBUILD_SCRIPT = _SCRIPTS_DIR / "rebuild_slurm.sh"
_ACCOUNTING_DATABASE_SCRIPT = _SCRIPTS_DIR / "slurm_accounting_database.sh"
# The Slurm release the tests upgrade to, as the tag of the SchedMD repository the page asks for.
SLURM_VERSION_NEW = os.environ.get("SLURM_VERSION_NEW", "slurm-25-11-8-1")
# The page tells customers to download the sources from GitHub or from the ParallelCluster bucket of their Region. The
# tests take them from the development bucket, which the head node cannot read, so it gets a presigned URL instead.
_SOURCE_BUCKET = "aws-parallelcluster-dev-build-dependencies"
_SOURCE_KEY = f"archives/dependencies/slurm/{SLURM_VERSION_NEW}.tar.gz"
_SOURCE_URL_EXPIRATION_SECONDS = 2 * 60 * 60
# A whole upgrade is a Slurm build plus a possible accounting database conversion.
_UPGRADE_TIMEOUT = 3600
_COMPUTE_INSTANCE_STATES = ["pending", "running", "shutting-down", "stopping", "stopped"]
_COMPUTE_FLEET_TERMINAL_STATES = {"RUNNING", "STOPPED", "PROTECTED"}
_CAPACITY_WAIT_MINUTES = 15
_TERMINATION_WAIT_MINUTES = 15
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
_SLURMCTLD_LOG = "/var/log/slurmctld.log"
_CHEF_CACHE_DIR = "/etc/chef/local-mode-cache/cache"
# Kept in step with the default backup path of slurm_accounting_database.sh.
_ACCOUNTING_BACKUP_GLOB = "/opt/slurm_accounting_backup_*.sql.gz"
# Dumping and restoring the accounting database of a long lived cluster is minutes of work, and it runs
# against a database that may be scaling up while it does, so it gets the same budget as the build itself.
_ACCOUNTING_DATABASE_TIMEOUT = 3600
# Remote commands have no timeout by default, so anything that blocks on the target host stalls the test for as long
# as the run is allowed to last, without a single line of output saying where. Every command this module runs itself
# is minutes of work at most, the scripts being the exceptions that carry their own budgets, so they are all capped
# generously and a stuck one fails instead of hanging.
_REMOTE_COMMAND_TIMEOUT = 600
# The upstream MySQL repository, which holds the command line client of the same release as the client library the
# cookbook installs. The series is read from that library rather than pinned here, so that an AMI moving to another
# MySQL release needs no change.
_MYSQL_CLIENT_RPM_URL = "https://repo.mysql.com/yum/mysql-{series}-community/el/{el_version}/{arch}/{rpm}"


def slurm_version_of_tag(tag):
    """Return the Slurm release a SchedMD tag names: slurm-25-11-8-1 is Slurm 25.11.8."""
    match = re.fullmatch(r"slurm-(\d+)-(\d+)-(\d+)-\d+", tag)
    assert_that(match).described_as(f"a Slurm tag such as slurm-25-11-8-1 in {tag!r}").is_not_none()
    return ".".join(match.groups())


def _source_bucket_region():
    """Return the Region the source bucket lives in for the partition the tests are running against.

    The bucket name is the same in every partition, but the bucket is not: each partition has its own copy, in the
    Region where the development infrastructure of that partition runs, and it is only reachable from inside that
    partition. That is the same Region the test framework reports metrics to, so the mapping is reused from there.
    """
    region = os.environ.get("AWS_DEFAULT_REGION")
    partition = get_arn_partition(region) if region else DEFAULT_PARTITION
    return REPORTING_REGION_MAP.get(partition, DEFAULT_REPORTING_REGION)


def _source_archive_url():
    """Return a presigned URL of the Slurm source archive, for SLURM_SOURCE_URL of the wiki script.

    The ETag is logged because the bucket object can be replaced in place: it is what tells two runs apart.
    """
    s3 = boto3.client("s3", region_name=_source_bucket_region())
    etag = s3.head_object(Bucket=_SOURCE_BUCKET, Key=_SOURCE_KEY)["ETag"]
    logging.info("Slurm sources: s3://%s/%s (ETag %s)", _SOURCE_BUCKET, _SOURCE_KEY, etag)
    return s3.generate_presigned_url(
        "get_object", Params={"Bucket": _SOURCE_BUCKET, "Key": _SOURCE_KEY}, ExpiresIn=_SOURCE_URL_EXPIRATION_SECONDS
    )


def _curl_ca_bundle(executor):
    """Return the CA bundle curl needs to reach S3 on this host, or None where the system store is enough.

    In the isolated partitions the S3 endpoint is signed by a CA the AMI installs under /etc/pki/<region>, which is not
    in the store curl uses by default. The wiki script downloads with curl, so the bundle is handed to it through the
    environment variable curl honours rather than by changing the script.
    """
    bundle = executor.run_remote_command(
        "ls -1 /etc/pki/us-iso*/certs/ca-bundle.pem 2>/dev/null | head -n 1", raise_on_error=False, hide=True
    ).stdout.strip()
    return bundle or None


def _run_upgrade_script(executor, *args, env=None, timeout=_UPGRADE_TIMEOUT):
    """Upload the scripts of util/slurm-upgrade to the target host and run slurm_upgrade.sh there, as root.

    The three scripts go together: slurm_upgrade.sh runs rebuild_slurm.sh for Step 4 and slurm_accounting_database.sh
    for Appendix D.4 from its own directory, exactly as a customer who downloaded the directory would.
    """
    assignments = " ".join(f"{name}={shlex.quote(value)}" for name, value in (env or {}).items())
    command = f"sudo {assignments} /bin/bash {_UPGRADE_SCRIPT.name} {' '.join(shlex.quote(arg) for arg in args)}"
    return executor.run_remote_command(
        command,
        additional_files=[str(script) for script in (_UPGRADE_SCRIPT, _REBUILD_SCRIPT, _ACCOUNTING_DATABASE_SCRIPT)],
        timeout=timeout,
        pty=False,
    )


def _compute_instance_ids(cluster):
    """Return the IDs of the compute instances of a cluster that are not gone yet.

    Instances that are shutting down still count as consumers: they keep the shared /opt/slurm of the head node
    mounted, and their slurmd is still running the version the upgrade is about to replace.
    """
    instances = describe_cluster_instances(
        cluster.cfn_name,
        cluster.region,
        filter_by_node_type="Compute",
        filter_by_instance_states=_COMPUTE_INSTANCE_STATES,
    )
    return sorted(instance["InstanceId"] for instance in instances)


def _snapshot_cluster(cluster):
    compute_status = cluster.describe_compute_fleet()["status"]
    if compute_status not in _COMPUTE_FLEET_TERMINAL_STATES:
        raise RuntimeError(
            f"Cluster {cluster.name} compute fleet must be in RUNNING, STOPPED, or PROTECTED state before maintenance; "
            f"found {compute_status}"
        )
    logging.info("Snapshotted cluster %s in %s: compute fleet %s", cluster.name, cluster.region, compute_status)
    return {"cluster": cluster, "compute_status": compute_status}


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
        stop_max_delay=minutes(_TERMINATION_WAIT_MINUTES),
        retry_on_result=lambda consumers_remain: consumers_remain,
    )
    def _poll():
        consumers_remain = False
        for snapshot in snapshots:
            cluster = snapshot["cluster"]
            instance_ids = _compute_instance_ids(cluster)
            if instance_ids:
                consumers_remain = True
                logging.info("Waiting for cluster %s compute instances to terminate: %s", cluster.name, instance_ids)
        return consumers_remain

    _poll()


def _pause_consumers(snapshots):
    # Step 1: stop the compute fleet. A PROTECTED fleet is stopped as well: protected mode disables the queues but
    # leaves the compute instances of the healthy compute resources running, and those keep the old Slurm mounted.
    for snapshot in snapshots:
        if snapshot["compute_status"] != "STOPPED":
            logging.info("Requesting compute fleet stop for cluster %s", snapshot["cluster"].name)
            snapshot["cluster"].stop()

    for snapshot in snapshots:
        if snapshot["compute_status"] != "STOPPED":
            _wait_for_compute_status(snapshot, "STOPPED")
    _wait_for_consumers_terminated(snapshots)
    logging.info("All compute nodes are stopped")


def _attempt(errors, operation, action):
    """Run one restoration step, recording rather than raising its failure so that the other steps still run."""
    try:
        action()
    except Exception as error:
        errors.append((operation, error))


def _request_consumers_back(snapshot, errors):
    cluster = snapshot["cluster"]
    if snapshot["compute_status"] == "RUNNING":
        _attempt(errors, f"start compute fleet for cluster {cluster.name}", cluster.start)
    elif snapshot["compute_status"] != "STOPPED":
        # PROTECTED is not a status the compute fleet API accepts, so it cannot be requested back. Leaving the
        # fleet STOPPED is reported here rather than silently, because it changes what the caller sees next.
        logging.warning(
            "Cluster %s compute fleet was %s before the maintenance and is left STOPPED",
            cluster.name,
            snapshot["compute_status"],
        )


def _wait_for_consumers_back(snapshot, errors):
    cluster = snapshot["cluster"]
    if snapshot["compute_status"] == "RUNNING":
        _attempt(
            errors,
            f"wait for cluster {cluster.name} compute fleet RUNNING",
            lambda: _wait_for_compute_status(snapshot, "RUNNING"),
        )


def _restore_consumers(snapshots):
    """Step 6: start the compute fleet."""
    errors = []
    for snapshot in snapshots:
        _request_consumers_back(snapshot, errors)
    for snapshot in snapshots:
        _wait_for_consumers_back(snapshot, errors)
    return errors


@contextmanager
def stopped_shared_slurm_consumers(*clusters):
    """Steps 1 and 6 of the page: no compute node uses /opt/slurm while the block runs. Login nodes stay up."""
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
    """Return the Slurm version reported by the target host, or None when no Slurm binary answers."""
    for command in _SLURM_VERSION_COMMANDS:
        result = executor.run_remote_command(command, raise_on_error=False, hide=True)
        if result.return_code == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
    return None


def slurm_major_version(version):
    """Return the major.minor Slurm release of a version string such as "slurm 24.11.6", or None."""
    match = re.search(r"\d+\.\d+", version or "")
    return match.group(0) if match else None


def upgrade_slurm(executor, assert_controller=True):
    """Run the upgrade on the target host and verify what it left: Steps 2 to 5 and 7 of the page, or Appendix A.

    Clear assert_controller for a host that runs no slurmctld, such as an external slurmdbd instance.
    """
    version_before = get_slurm_version(executor)
    env = {"SLURM_VERSION_NEW": SLURM_VERSION_NEW, "SLURM_SOURCE_URL": _source_archive_url()}
    ca_bundle = _curl_ca_bundle(executor)
    if ca_bundle:
        env["CURL_CA_BUNDLE"] = ca_bundle
    result = _run_upgrade_script(executor, "upgrade", env=env)

    version_after = get_slurm_version(executor)
    logging.info(
        "Slurm version after the upgrade: %s (was %s before), a %s",
        version_after,
        version_before,
        (
            "same-major upgrade"
            if slurm_major_version(version_before) == slurm_major_version(version_after)
            else "cross-major upgrade"
        ),
    )
    assert_that(version_after).described_as("Slurm version reported by the host after the upgrade").contains(
        slurm_version_of_tag(SLURM_VERSION_NEW)
    )
    if assert_controller:
        assert_slurm_controller_healthy(executor)
    return result


def upgrade_slurm_with_stopped_consumers(executor, *clusters):
    """Upgrade Slurm on the target host while the clusters have no compute node."""
    with stopped_shared_slurm_consumers(*clusters):
        return upgrade_slurm(executor)


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
    the compute fleet is stopped for the upgrade, so verifying that running jobs survive an upgrade needs a
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

    Every command here runs through the given executor, which must target the head node.
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


def _service_exists(executor, service):
    """Return whether a systemd service is installed on the target host.

    slurmdbd only runs on a head node whose cluster keeps its accounting database locally, and on the external slurmdbd
    instance, so whether the unit is there is what says whether this host owns a converted accounting database.

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


def _newest_backup_archive(executor, pattern):
    """Return the path of the newest archive matching a glob on the target host."""
    newest = executor.run_remote_command(f"ls -1t {pattern} | head -n 1", raise_on_error=False, hide=True)
    assert_that(newest.return_code).described_as(
        f"no backup archive matches {pattern}: {newest.stderr}"
    ).is_equal_to(0)
    archive = newest.stdout.strip()
    assert_that(archive).described_as(f"newest backup archive matching {pattern}").is_not_empty()
    return archive


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


def back_up_accounting_database(executor):
    """Step 3.2: dump the Slurm accounting database of the host the executor targets, and return the archive path.

    Call this before the upgrade, from the host that runs slurmdbd: the head node of a cluster that keeps its
    accounting database locally, or the external slurmdbd instance. The first slurmdbd of a new Slurm major
    release converts the database schema one way, so this dump is the only thing that can undo that conversion,
    and therefore the only thing that makes a cross major version rollback possible at all.
    """
    _ensure_mysql_client(executor)
    executor.run_remote_script(
        str(_ACCOUNTING_DATABASE_SCRIPT),
        args=["backup"],
        run_as_root=True,
        timeout=_ACCOUNTING_DATABASE_TIMEOUT,
        pty=False,
    )
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


def roll_back_slurm(executor, expected_version, accounting_backup=None, assert_controller=True):
    """Appendix D: roll the target host back to the Slurm version it ran before the upgrade, and verify it.

    Pass the version the host reported before the upgrade. Pass the accounting_backup that
    back_up_accounting_database took before the upgrade to roll a host that runs slurmdbd back across a major
    version: the schema conversion is not reversible any other way. Clear assert_controller for a host that runs no
    slurmctld, such as an external slurmdbd instance.

    The compute nodes must already be stopped, exactly as for the upgrade, and the call leaves the host on the
    previous Slurm version, so it belongs after everything that must run on the new one.
    """
    version_before = get_slurm_version(executor)
    assert_that(version_before).described_as("Slurm version reported by the host before the rollback").is_not_none()
    if version_before == expected_version:
        raise RuntimeError(f"The host already runs Slurm {expected_version}, so there is nothing to roll back")
    _assert_rollback_is_supported(executor, version_before, expected_version, accounting_backup)

    logging.info("Rolling Slurm %s back to %s", version_before, expected_version)
    args = ["rollback"]
    if accounting_backup:
        args += ["--accounting-backup", accounting_backup]
    _run_upgrade_script(executor, *args)

    version_after = get_slurm_version(executor)
    assert_that(version_after).described_as("Slurm version reported by the host after the rollback").is_equal_to(
        expected_version
    )
    if assert_controller:
        assert_slurm_controller_healthy(executor)
    assert_slurm_source_tree_present(executor, expected_version)
    logging.info("Rolled Slurm back to %s", version_after)
    return version_after


def roll_back_slurm_with_stopped_consumers(executor, *clusters, expected_version, accounting_backup=None):
    """Roll the target host back while the clusters have no compute node."""
    with stopped_shared_slurm_consumers(*clusters):
        return roll_back_slurm(executor, expected_version, accounting_backup=accounting_backup)


def run_scheduler_smoke_test(
    scheduler_commands,
    partition=None,
    nodes=1,
    slots=1,
    other_options=None,
    command="hostname",
    timeout=None,
):
    """Step 7.4: submit a short job, wait for completion, assert success, and return its job ID."""
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
