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
"""Upgrade Slurm in place on a running cluster, and roll it back, with the scripts of util/slurm-upgrade.

They are the ones https://github.com/aws/aws-parallelcluster/wiki/Upgrade-Slurm-in-an-AWS-ParallelCluster-cluster links
to. The login nodes stay up (Appendix E is skipped), the riskier path.
"""

import logging
import os
import re
import shlex
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from assertpy import assert_that
from retrying import retry
from time_utils import minutes, seconds
from utils import describe_cluster_instances

_SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "util" / "slurm-upgrade"
_UPGRADE_SCRIPT = _SCRIPTS_DIR / "slurm_upgrade.sh"
_REBUILD_SCRIPT = _SCRIPTS_DIR / "rebuild_slurm.sh"
_ACCOUNTING_DATABASE_SCRIPT = _SCRIPTS_DIR / "slurm_accounting_database.sh"
_PINNED_SLURM_VERSION_NEW = os.environ.get("SLURM_VERSION_NEW")
_SLURM_REPOSITORY = "https://github.com/SchedMD/slurm.git"
# Release tags only, not release candidates such as slurm-25-11-0-0rc1.
_RELEASE_TAG_PATTERN = re.compile(r"slurm-\d+-\d+-\d+-\d+")
_TAG_LISTING_TIMEOUT_SECONDS = 120
# Slurm supports upgrading to a major release from the three major releases before it.
_MAX_MAJOR_RELEASES_PER_UPGRADE = 3
_UPGRADE_TIMEOUT = 2 * 60 * 60
_ACCOUNTING_DATABASE_TIMEOUT = 3600
_REMOTE_COMMAND_TIMEOUT = 600
_COMPUTE_INSTANCE_STATES = ["pending", "running", "shutting-down", "stopping", "stopped"]
_COMPUTE_FLEET_WAIT_MINUTES = 15
_PARTITION_WAIT_MINUTES = 10
_STATE_CHECK_RESERVATION = "slurm-upgrade-state-check"
_STATE_CHECK_RESERVATION_START = "now+7days"
_SLURM_VERSION_COMMANDS = ("sinfo --version", "sudo -n /opt/slurm/sbin/slurmdbd -V", "sacctmgr --version")
_CHEF_CACHE_DIR = "/etc/chef/local-mode-cache/cache"
_MYSQL_CLIENT_RPM_URL = "https://repo.mysql.com/yum/mysql-{series}-community/el/{el_version}/{arch}/{rpm}"


def slurm_release(version):
    """Return the (major, minor, patch) release of a version string or tag: "slurm 25.11.8" or slurm-25-11-8-1."""
    match = re.search(r"(\d+)[.-](\d+)[.-](\d+)", version or "")
    assert_that(match).described_as(f"a Slurm release in {version!r}").is_not_none()
    return tuple(int(part) for part in match.groups())


def _tag_key(tag):
    """Order SchedMD tags by release, then by the SchedMD revision of that release."""
    return slurm_release(tag) + (int(tag.rsplit("-", 1)[1]),)


def _available_slurm_tags():
    """Return the release tags of the SchedMD repository, or none when GitHub cannot be reached.

    git ls-remote rather than the GitHub API, which pages tags and rate limits anonymous clients.
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", _SLURM_REPOSITORY, "slurm-*"],
            capture_output=True,
            text=True,
            timeout=_TAG_LISTING_TIMEOUT_SECONDS,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        logging.warning("Cannot list the Slurm tags of %s: %s", _SLURM_REPOSITORY, error)
        return []
    tags = [line.split("refs/tags/", 1)[-1] for line in result.stdout.splitlines()]
    return [tag for tag in tags if _RELEASE_TAG_PATTERN.fullmatch(tag)]


def _major_releases_between(tags, installed, target):
    """Return how many major releases an upgrade from an installed release to a target release moves forward."""
    majors = {slurm_release(tag)[:2] for tag in tags} | {target[:2]}
    return len([major for major in majors if installed[:2] < major <= target[:2]])


def select_slurm_upgrade_target(*executors):
    """Return the SchedMD tag to upgrade the target hosts to, or None when no newer Slurm is available."""
    installed_versions = [get_slurm_version(executor) for executor in executors]
    assert_that(installed_versions).described_as("Slurm versions reported by the target hosts").does_not_contain(None)
    installed = [slurm_release(version) for version in installed_versions]
    tags = [_PINNED_SLURM_VERSION_NEW] if _PINNED_SLURM_VERSION_NEW else _available_slurm_tags()
    candidates = [
        tag
        for tag in tags
        if slurm_release(tag) > max(installed)
        and _major_releases_between(tags, min(installed), slurm_release(tag)) <= _MAX_MAJOR_RELEASES_PER_UPGRADE
    ]
    if not candidates:
        logging.warning(
            "Skipping the Slurm upgrade: no release newer than %s within %s major releases among %s tags, the newest "
            "being %s",
            ", ".join(installed_versions),
            _MAX_MAJOR_RELEASES_PER_UPGRADE,
            len(tags),
            max(tags, key=_tag_key) if tags else None,
        )
        return None
    target = max(candidates, key=_tag_key)
    logging.info("Slurm upgrade target: %s (the target hosts run %s)", target, ", ".join(installed_versions))
    return target


def _run_upgrade_script(executor, *args, env=None):
    """Upload the scripts of util/slurm-upgrade to the target host and run slurm_upgrade.sh there, as root."""
    assignments = " ".join(f"{name}={shlex.quote(value)}" for name, value in (env or {}).items())
    command = f"sudo {assignments} /bin/bash {_UPGRADE_SCRIPT.name} {' '.join(shlex.quote(arg) for arg in args)}"
    executor.run_remote_command(
        command,
        additional_files=[str(script) for script in (_UPGRADE_SCRIPT, _REBUILD_SCRIPT, _ACCOUNTING_DATABASE_SCRIPT)],
        timeout=_UPGRADE_TIMEOUT,
        pty=False,
    )


def _wait_for_compute_fleet_status(cluster, expected_status):
    @retry(
        wait_fixed=seconds(15),
        stop_max_delay=minutes(_COMPUTE_FLEET_WAIT_MINUTES),
        retry_on_result=lambda status: status != expected_status,
    )
    def _poll():
        status = cluster.describe_compute_fleet()["status"]
        logging.info("Cluster %s compute fleet status is %s; waiting for %s", cluster.name, status, expected_status)
        return status

    _poll()


def _wait_for_compute_instances_terminated(clusters):
    """Wait until no compute instance is left, shutting down ones included: they still have /opt/slurm mounted."""

    @retry(
        wait_fixed=seconds(15),
        stop_max_delay=minutes(_COMPUTE_FLEET_WAIT_MINUTES),
        retry_on_result=bool,
    )
    def _poll():
        remaining = {}
        for cluster in clusters:
            instances = describe_cluster_instances(
                cluster.cfn_name,
                cluster.region,
                filter_by_node_type="Compute",
                filter_by_instance_states=_COMPUTE_INSTANCE_STATES,
            )
            if instances:
                remaining[cluster.name] = sorted(instance["InstanceId"] for instance in instances)
        if remaining:
            logging.info("Waiting for compute instances to terminate: %s", remaining)
        return remaining

    _poll()


@contextmanager
def stopped_compute_nodes(*clusters):
    """Steps 1 and 6 of the page: no compute node uses /opt/slurm while the block runs. Login nodes stay up."""
    statuses = {cluster.name: cluster.describe_compute_fleet()["status"] for cluster in clusters}
    assert_that(set(statuses.values())).described_as(f"compute fleet statuses {statuses}").is_subset_of(
        {"RUNNING", "STOPPED"}
    )
    running = [cluster for cluster in clusters if statuses[cluster.name] == "RUNNING"]
    try:
        for cluster in running:
            cluster.stop()
        for cluster in running:
            _wait_for_compute_fleet_status(cluster, "STOPPED")
        _wait_for_compute_instances_terminated(clusters)
        logging.info("All compute nodes are stopped")
        yield
    finally:
        for cluster in running:
            cluster.start()
        for cluster in running:
            _wait_for_compute_fleet_status(cluster, "RUNNING")


def get_slurm_version(executor):
    """Return the Slurm version reported by the target host, or None when no Slurm binary answers."""
    for command in _SLURM_VERSION_COMMANDS:
        result = executor.run_remote_command(command, raise_on_error=False, hide=True)
        if result.return_code == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
    return None


def upgrade_slurm(executor, target):
    """Steps 2 to 5 and 7 of the page, or Appendix A. The script fails unless the target and the daemons are up."""
    logging.info("Upgrading Slurm to %s", target)
    _run_upgrade_script(executor, "upgrade", env={"SLURM_VERSION_NEW": target})


def upgrade_slurm_with_stopped_compute_nodes(executor, *clusters, target=None):
    """Upgrade Slurm on the target host while the clusters have no compute node, and return the tag installed."""
    target = target or select_slurm_upgrade_target(executor)
    if target is None:
        return None
    with stopped_compute_nodes(*clusters):
        upgrade_slurm(executor, target)
    return target


def wait_for_partitions_up(scheduler_commands, partitions=None):
    """Wait until the requested partitions (all of them by default) are UP."""

    @retry(
        wait_fixed=seconds(15),
        stop_max_delay=minutes(_PARTITION_WAIT_MINUTES),
        retry_on_result=bool,
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
    """Return the batch script slurmctld stored for a job in StateSaveLocation."""
    script_path = f"/tmp/{_STATE_CHECK_RESERVATION}-{job_id}.sh"
    remote_command_executor.run_remote_command(
        f"rm -f {script_path} && scontrol write batch_script {job_id} {script_path}"
    )
    return remote_command_executor.run_remote_command(f"cat {script_path}", hide=True).stdout


def snapshot_slurm_state(remote_command_executor, scheduler_commands):
    """Create a held job and a reservation, which the StateSaveLocation conversion must keep, and describe them."""
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
    """Return the output that explains a failed remote command: a pty merges stderr into stdout."""
    return result.stderr.strip() or result.stdout.strip()


def assert_slurm_state_preserved(remote_command_executor, snapshot):
    """Verify the state captured by snapshot_slurm_state survived, then clean it up, through the head node."""
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
    # A converted record keeps its original submission time; a recreated one does not.
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
            f"reservation {_STATE_CHECK_RESERVATION} is gone after the upgrade: "
            f"{_failed_command_output(reservation_details)}"
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
    """Run a remote command whose exit code or output the caller inspects itself."""
    return executor.run_remote_command(
        f"sudo {command}" if sudo else command, raise_on_error=False, hide=True, timeout=_REMOTE_COMMAND_TIMEOUT
    )


def _run_checked(executor, command, description, sudo=True):
    """Run a remote command that must succeed and return its stripped stdout."""
    result = _run_probe(executor, command, sudo=sudo)
    assert_that(result.return_code).described_as(f"{description}: {_failed_command_output(result)}").is_equal_to(0)
    return result.stdout.strip()


def _ensure_mysql_client(executor):
    """Install the MySQL command line tools, which no ParallelCluster AMI ships, if they are missing."""
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
    """Install the mysql-community-client matching the installed client library, from the MySQL repository.

    The repositories of the AMI are disabled because they can be retired (Rocky Linux 9.5).
    """
    release = _run_checked(
        executor,
        "rpm -q --queryformat '%{VERSION}-%{RELEASE}.%{ARCH}' mysql-community-libs",
        "release of the MySQL client library installed on the target host",
    )
    # For example 8.4.10-1.el9.x86_64.
    match = re.fullmatch(r"(\d+\.\d+)\.\d+-\S+\.el(\d+)\.(\w+)", release)
    if match:
        series, el_version, arch = match.groups()
        rpm = f"mysql-community-client-{release}.rpm"
        url = _MYSQL_CLIENT_RPM_URL.format(series=series, el_version=el_version, arch=arch, rpm=rpm)
        logging.info("Installing the MySQL command line client from %s", url)
        installation = _run_probe(
            executor,
            f"sh -c 'curl -fsSL -o /tmp/{rpm} {url} && yum install -y --disablerepo=\"*\" /tmp/{rpm}'",
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
        logging.warning("Unexpected MySQL client library release %s, falling back to the distribution package", release)
    _run_checked(executor, "yum install -y mysql", "installation of the MySQL command line client")


def back_up_accounting_database(executor):
    """Step 3.2: dump the accounting database of the host that runs slurmdbd, and return the archive path."""
    _ensure_mysql_client(executor)
    archive = f"/opt/slurm_accounting_backup_{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}.sql.gz"
    executor.run_remote_script(
        str(_ACCOUNTING_DATABASE_SCRIPT),
        args=["backup", archive],
        run_as_root=True,
        timeout=_ACCOUNTING_DATABASE_TIMEOUT,
        pty=False,
    )
    # A dump of no table is a valid archive too.
    tables = _run_checked(
        executor,
        f"sh -c 'gzip -dc {archive} | grep -c \"^CREATE TABLE\"'",
        f"tables in the accounting database backup {archive}",
    )
    logging.info("Backed the accounting database up to %s, holding %s tables", archive, tables)
    return archive


def assert_slurm_source_tree_present(executor, version):
    """Assert the Chef cache still holds the source tree of a Slurm version, which `make uninstall` of it needs."""
    # The pattern rebuild_slurm.sh looks for before it uninstalls.
    name = "slurm-slurm-{}-{}-{}-*".format(*slurm_release(version))
    # find rather than a glob: the Chef cache is only readable by root.
    trees = _run_checked(
        executor,
        f'find {_CHEF_CACHE_DIR} -mindepth 1 -maxdepth 1 -type d -name "{name}"',
        f"search for the source tree of Slurm {version} under {_CHEF_CACHE_DIR}",
    ).split()
    assert_that(trees).described_as(f"source trees of Slurm {version} named {name}").is_length(1)
    _run_checked(executor, f"test -f {trees[0]}/Makefile", f"Makefile of the source tree {trees[0]}")
    logging.info("The source tree of Slurm %s is still available at %s", version, trees[0])


def roll_back_slurm(executor, expected_version, accounting_backup=None):
    """Appendix D: roll the target host back to the Slurm version it ran before the upgrade, and verify it."""
    logging.info("Rolling Slurm back to %s", expected_version)
    args = ["rollback"]
    if accounting_backup:
        args += ["--accounting-backup", accounting_backup]
    _run_upgrade_script(executor, *args)

    version_after = get_slurm_version(executor)
    assert_that(version_after).described_as("Slurm version reported by the host after the rollback").is_equal_to(
        expected_version
    )
    assert_slurm_source_tree_present(executor, expected_version)
    logging.info("Rolled Slurm back to %s", version_after)


def roll_back_slurm_with_stopped_compute_nodes(executor, *clusters, expected_version, accounting_backup=None):
    """Roll the target host back while the clusters have no compute node."""
    with stopped_compute_nodes(*clusters):
        roll_back_slurm(executor, expected_version, accounting_backup=accounting_backup)


def assert_shared_slurm_version(remote_command_executor, scheduler_commands, expected_version, partition):
    """Assert the nodes that mount /opt/slurm from the head node run the Slurm version it runs."""
    job_id = run_scheduler_smoke_test(scheduler_commands, partition=partition, command="/opt/slurm/sbin/slurmd -V")
    output = remote_command_executor.run_remote_command(f"cat slurm-{job_id}.out", hide=True).stdout.strip()
    assert_that(output).described_as(f"Slurm version a compute node of partition {partition} ran").is_equal_to(
        expected_version
    )


def run_scheduler_smoke_test(scheduler_commands, partition, other_options=None, command="hostname"):
    """Step 7.4: submit a short job to a partition, wait for completion, assert success, and return its job ID."""
    wait_for_partitions_up(scheduler_commands, [partition])
    submit_command_args = {"command": command, "nodes": 1, "slots": 1, "partition": partition}
    if other_options is not None:
        submit_command_args["other_options"] = other_options
    job_id = scheduler_commands.submit_command_and_assert_job_accepted(submit_command_args)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
    return job_id
