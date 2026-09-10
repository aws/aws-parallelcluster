import logging
import os
import re
from urllib.parse import urlparse

import boto3
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import seconds
from utils import get_arn_partition, to_snake_case

from tests.cloudwatch_logging import cloudwatch_logging_boto3_utils as cw_utils
from tests.common.assertions import assert_no_defunct_slurm_config_params, known_defunct_slurm_config_params
from tests.common.software_installer import (
    assert_slurm_state_preserved,
    back_up_accounting_database,
    get_slurm_version,
    install_test_software,
    install_test_software_with_stopped_consumers,
    roll_back_test_software,
    roll_back_test_software_with_stopped_consumers,
    snapshot_slurm_state,
    stopped_shared_slurm_consumers,
    wait_for_partitions_up,
)
from tests.common.utils import get_aws_domain, installed_parallelcluster_version_is_at_least

STARTED_PATTERN = re.compile(r".*slurmdbd version \S+ started")
SLURMDBD_LOG_FILE = "/var/log/slurmdbd.log"
UPGRADE_FAILURE_PATTERN = re.compile(r"(?i)(fatal:|rolling back|conversion failed|error: *mysql)")
# When slurmdbd converts the schema it checks whether it is talking to a Galera cluster, and neither MySQL nor Aurora
# MySQL knows the `wsrep_on` variable, so the probe fails with an `error: mysql...` line on every successful cross
# major version conversion. It says nothing about the conversion itself, so it is excluded from the check below.
BENIGN_FAILURE_PATTERN = re.compile(r"(?i)wsrep")
RDS_TRUSTSTORE_ENDPOINTS = {
    "aws": "https://truststore.pki.rds.amazonaws.com",
    "aws-us-gov": "https://truststore.pki.us-gov-west-1.rds.amazonaws.com",
    "aws-cn": "https://rds-truststore.s3.cn-north-1.amazonaws.com.cn",
}


def _get_slurm_database_config_parameters(database_stack_outputs):
    return _get_config_parameters_from_cfn_outputs(
        database_stack_outputs,
        ["DatabaseHost", "DatabaseAdminUser", "DatabaseSecretArn", "DatabaseClientSecurityGroup"],
    )


def _get_slurm_dbd_config_parameters(database_stack_outputs):
    return _get_config_parameters_from_cfn_outputs(
        database_stack_outputs,
        ["AccountingClientSecurityGroup", "SshClientSecurityGroup", "SlurmdbdPrivateIp", "SlurmdbdPort"],
    )


def _get_config_parameters_from_cfn_outputs(database_stack_outputs, keys):
    return {to_snake_case(key): database_stack_outputs.get(key) for key in keys}


def _get_expected_users(remote_command_executor, test_resources_dir):
    users = remote_command_executor.run_remote_script(
        os.path.join(str(test_resources_dir), "get_accounting_users.sh")
    ).stdout
    for user in users.splitlines():
        logging.info("  Expected User: %s", user)
    return users.splitlines()


def _is_accounting_enabled(remote_command_executor):
    return remote_command_executor.run_remote_command("sacct", raise_on_error=False).ok


def _rds_ca_bundle_url(region):
    if "us-iso" in region:
        return f"https://s3.{region}.{get_aws_domain(region)}/rds-downloads/rds-combined-ca-bundle.pem"
    else:
        return f"{RDS_TRUSTSTORE_ENDPOINTS.get(get_arn_partition(region))}/{region}/{region}-bundle.pem"


def _require_server_identity(remote_command_executor, test_resources_dir, region):
    ca_url = _rds_ca_bundle_url(region)
    remote_command_executor.run_remote_script(
        os.path.join(str(test_resources_dir), "require_server_identity.sh"),
        args=[
            ca_url,
            os.path.basename(urlparse(ca_url).path),
        ],
        run_as_root=True,
    )


def _test_require_server_identity(remote_command_executor, test_resources_dir, region):
    # TODO We must address the extra challenges of configuring SSL in isolated regions.
    # For the time being we skip this check to unblock the validation of the feature without SSL.
    # This is reasonable in the short term because the SSL configuration is actually out of scope for ParallelCluster.
    if "us-iso" not in region:
        _require_server_identity(remote_command_executor, test_resources_dir, region)
    retry(stop_max_attempt_number=3, wait_fixed=seconds(10))(_is_accounting_enabled)(
        remote_command_executor,
    )


def _test_slurmdb_users(remote_command_executor, scheduler_commands, test_resources_dir):
    logging.info("Testing Slurm Accounting Users")
    expected_users = _get_expected_users(remote_command_executor, test_resources_dir)
    users = list(scheduler_commands.get_accounting_users())
    assert_that(users).is_length(len(expected_users))
    for user in users:
        logging.info("  User: %s", user)
        assert_that(user.get("user")).is_in(*expected_users)
        assert_that(user.get("adminlevel")).is_equal_to("Administrator")


def _read_slurmdbd_log(remote_command_executor, since_line=0):
    """Return the slurmdbd log, optionally only the lines appended after the given line number."""
    return remote_command_executor.run_remote_command(
        "sudo tail -n +{0} {1}".format(since_line + 1, SLURMDBD_LOG_FILE), hide=True
    ).stdout


def _get_slurmdbd_log_line_count(remote_command_executor):
    """Return the current length of the slurmdbd log, to scope later assertions to newly appended lines."""
    result = remote_command_executor.run_remote_command(f"sudo wc -l {SLURMDBD_LOG_FILE}", hide=True)
    line_count = int(result.stdout.split()[0])
    logging.info("%s currently has %s lines", SLURMDBD_LOG_FILE, line_count)
    return line_count


@retry(stop_max_attempt_number=36, wait_fixed=10 * 1000)
def _test_successful_startup_in_log(remote_command_executor, since_line=0):
    # Scoping to the lines appended after since_line matters after an upgrade: the whole log always contains
    # the startup line of the version installed at cluster creation, so an unscoped check would pass even if
    # the upgraded slurmdbd never started.
    log = _read_slurmdbd_log(remote_command_executor, since_line)
    assert_that(
        [line for line in log.splitlines() if STARTED_PATTERN.fullmatch(line) is not None], "Successful Startup"
    ).is_not_empty()


def _assert_no_upgrade_failures_in_slurmdbd_log(remote_command_executor, since_line):
    """Assert slurmdbd did not report a failed database migration after the upgrade.

    Deliberately narrow: slurmdbd logs benign advice such as "error: Database settings not recommended for
    use" on every startup, so this matches only the patterns that indicate a failed or rolled back schema
    conversion.
    """
    log = _read_slurmdbd_log(remote_command_executor, since_line)
    failures = [
        line
        for line in log.splitlines()
        if UPGRADE_FAILURE_PATTERN.search(line) is not None and BENIGN_FAILURE_PATTERN.search(line) is None
    ]
    assert_that(failures).described_as("database migration failures reported by slurmdbd").is_empty()


@retry(stop_max_attempt_number=36, wait_fixed=10 * 1000)
def _test_slurmdbd_log_exists_in_log_group(cluster):
    log_groups = cw_utils.get_cluster_log_groups_from_boto3(f"/aws/parallelcluster/{cluster.name}")
    assert_that(log_groups).is_length(1)
    log_group_name = log_groups[0].get("logGroupName")
    log_streams = cw_utils.get_log_streams(log_group_name)
    streams = [
        stream.get("logStreamName")
        for stream in log_streams
        if re.fullmatch(r".*\.slurmdbd", stream.get("logStreamName")) is not None
    ]
    assert_that(streams).is_length(1)
    stream_name = streams[0]
    events = cw_utils.get_log_events(log_group_name, stream_name)
    messages = (event.get("message") for event in events)
    assert_that([message for message in messages if STARTED_PATTERN.fullmatch(message) is not None]).is_not_empty()


def _test_jobs_get_recorded(scheduler_commands):
    job_submission_output = scheduler_commands.submit_command(
        'echo "$(hostname) ${SLURM_JOB_ACCOUNT} ${SLURM_JOB_ID} ${SLURM_JOB_NAME}"',
    ).stdout
    job_id = scheduler_commands.assert_job_submitted(job_submission_output)
    logging.info(" Submitted Job ID: %s", job_id)
    scheduler_commands.wait_job_completed(job_id)
    retry(stop_max_attempt_number=5, wait_fixed=seconds(5))(_assert_job_completion_recorded_in_accounting)(
        job_id, scheduler_commands
    )
    return job_id


def _assert_job_completion_recorded_in_accounting(job_id, scheduler_commands, clusters=None):
    results = list(scheduler_commands.get_accounting_job_records(job_id, clusters=clusters))
    assert_that(results).is_not_empty()
    for row in results:
        logging.info(" Result: %s", row)
        assert_that(row.get("state")).is_equal_to("COMPLETED")


@retry(stop_max_attempt_number=10, wait_fixed=seconds(10))
def _assert_preexisting_job_records_readable(scheduler_commands, job_ids, clusters=None):
    """Verify the job records created before a Slurm upgrade are still readable afterwards.

    Submitting a new job only proves that the accounting database is writable: it would pass even if the
    upgrade dropped the existing job table or failed to migrate it. Reading back records created before the
    upgrade is what proves the database migration preserved the historical job information.
    """
    logging.info("Verifying %s job records created before the upgrade are still readable", len(job_ids))
    for job_id in job_ids:
        _assert_job_completion_recorded_in_accounting(job_id, scheduler_commands, clusters=clusters)


def _test_that_slurmdbd_is_not_running(remote_command_executor):
    assert_that(_is_accounting_enabled(remote_command_executor)).is_false()


@retry(stop_max_attempt_number=3, wait_fixed=seconds(10))
def _test_that_slurmdbd_is_running(remote_command_executor):
    assert_that(_is_accounting_enabled(remote_command_executor)).is_true()


def _test_cluster_registered_with_custom_name(remote_command_executor, custom_cluster_name):
    """Verify the cluster is registered in Slurm accounting under the expected custom name (lowercased by Slurm)."""
    expected_name = custom_cluster_name.lower()
    result = remote_command_executor.run_remote_command("sacctmgr show clusters -nP format=cluster").stdout
    registered_clusters = [line.strip() for line in result.splitlines() if line.strip()]
    logging.info("Registered accounting clusters: %s (expecting: %s)", registered_clusters, expected_name)
    assert_that(registered_clusters).contains(expected_name)


def _test_slurm_accounting_password(remote_command_executor):
    storage_pass = remote_command_executor.run_remote_command(
        "sudo grep StoragePass /opt/slurm/etc/slurm_parallelcluster_slurmdbd.conf |" "sed -e 's/StoragePass=//g'",
        hide=True,
    ).stdout.strip()
    assert_that(storage_pass).is_not_equal_to("dummy")


def _test_slurm_accounting_database_name(remote_command_executor: RemoteCommandExecutor, custom_database_name: str):
    storage_loc = remote_command_executor.run_remote_command(
        "sudo grep StorageLoc /opt/slurm/etc/slurm_parallelcluster_slurmdbd.conf | sed -e 's/StorageLoc=//g'",
    ).stdout.strip()
    assert_that(storage_loc).is_equal_to(custom_database_name)


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_slurm_accounting(
    region,
    pcluster_config_reader,
    vpc_stack_for_database,
    database,
    test_datadir,
    test_resources_dir,
    clusters_factory,
    scheduler_commands_factory,
):

    config_params = _get_slurm_database_config_parameters(database.cfn_outputs)
    public_subnet_id = vpc_stack_for_database.get_public_subnet()
    private_subnet_id = vpc_stack_for_database.get_private_subnet()

    # Use a mixed-case ClusterName to exercise the case-insensitive matching
    # in the accounting bootstrap. Slurm normalizes ClusterName to lowercase,
    # so the bootstrap must handle the mismatch between the user-specified
    # name and the name returned by sacctmgr.
    custom_cluster_name = "My-Custom-ClusterName"

    # First create a cluster without Slurm Accounting
    cluster_config = pcluster_config_reader(public_subnet_id=public_subnet_id, private_subnet_id=private_subnet_id)
    cluster = clusters_factory(cluster_config)

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    _test_that_slurmdbd_is_not_running(remote_command_executor)

    job_1_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "srun sleep 3000",
            "nodes": 10,
            "other_options": "--exclusive",
        }
    )

    job_2_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "srun sleep 3000",
            "nodes": 10,
            "other_options": "--exclusive",
        }
    )

    scheduler_commands.wait_job_running(job_1_id)
    scheduler_commands.assert_job_state(job_1_id, "RUNNING")
    scheduler_commands.assert_job_state(job_2_id, "PENDING")

    # Then update the cluster to enable Slurm Accounting
    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update.yaml",
        public_subnet_id=public_subnet_id,
        private_subnet_id=private_subnet_id,
        **config_params,
    )
    # Force update because update is not support unless the compute fleet is stopped
    cluster.update(str(updated_config_file), force_update="true")

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    scheduler_commands.assert_job_state(job_1_id, "RUNNING")
    scheduler_commands.assert_job_state(job_2_id, "PENDING")
    scheduler_commands.cancel_job(job_1_id)
    scheduler_commands.cancel_job(job_2_id)

    _test_that_slurmdbd_is_running(remote_command_executor)
    _test_successful_startup_in_log(remote_command_executor)
    _test_slurmdbd_log_exists_in_log_group(cluster)
    _test_slurmdb_users(remote_command_executor, scheduler_commands, test_resources_dir)
    _test_require_server_identity(remote_command_executor, test_resources_dir, region)
    _test_jobs_get_recorded(scheduler_commands)

    # Accounting bootstrap with an overridden or mixed-case ClusterName only works from ParallelCluster 3.16.0
    custom_names_supported = installed_parallelcluster_version_is_at_least("3.16.0")
    custom_database_name = None
    if custom_names_supported:
        # Update the queues to check that bug with the Slurm Accounting database server password
        # is fixed (see https://github.com/aws/aws-parallelcluster/issues/5151 )
        # Re-use the same update to test the modification of DatabaseName.
        custom_database_name = "test_custom_dbname"
        updated_config_file = pcluster_config_reader(
            config_file="pcluster.config.update2.yaml",
            public_subnet_id=public_subnet_id,
            private_subnet_id=private_subnet_id,
            custom_database_name=custom_database_name,
            custom_cluster_name=custom_cluster_name,
            **config_params,
        )

        # Removing the cluster name guardrail is the expected way to signal Slurm that the use of a custom
        # ClusterName is intentional. Slurm stores the current cluster name in /var/spool/slurm.state/clustername
        # and refuses to start if the configured ClusterName doesn't match.
        # Removing this file allows the transition to a custom name.
        logging.info("Removing clustername guardrail to set custom ClusterName: %s", custom_cluster_name)
        remote_command_executor.run_remote_command("sudo rm -rf /var/spool/slurm.state/clustername")

        # Force update because update is not support unless the compute fleet is stopped
        cluster.update(str(updated_config_file), force_update="true")
        _test_slurm_accounting_password(remote_command_executor)
        _test_slurm_accounting_database_name(remote_command_executor, custom_database_name)
        _test_that_slurmdbd_is_running(remote_command_executor)
        assert_no_defunct_slurm_config_params(
            remote_command_executor, ignore_patterns=known_defunct_slurm_config_params()
        )
        _test_cluster_registered_with_custom_name(remote_command_executor, custom_cluster_name)
    else:
        logging.warning(
            "Skipping the custom DatabaseName/ClusterName update: the accounting bootstrap only supports it from "
            "ParallelCluster 3.16.0."
        )

    # Record a job against the final database and cluster name, so that the check after the upgrade below
    # verifies the database migration rather than the DatabaseName/ClusterName changes done above.
    pre_upgrade_job_id = _test_jobs_get_recorded(scheduler_commands)
    slurm_state_snapshot = snapshot_slurm_state(remote_command_executor, scheduler_commands)
    slurmdbd_log_line_count = _get_slurmdbd_log_line_count(remote_command_executor)
    # Taken before the install, because the first slurmdbd of a new major release converts the schema one way:
    # from that point on this dump is the only thing that can put the accounting database back. Recorded together
    # with the version the dump belongs to, which is what the rollback at the end of the test restores.
    version_before_install = get_slurm_version(remote_command_executor)
    accounting_backup = back_up_accounting_database(remote_command_executor)

    install_test_software_with_stopped_consumers(remote_command_executor, cluster)

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    _test_that_slurmdbd_is_running(remote_command_executor)
    _test_successful_startup_in_log(remote_command_executor, since_line=slurmdbd_log_line_count)
    _assert_no_upgrade_failures_in_slurmdbd_log(remote_command_executor, slurmdbd_log_line_count)
    assert_slurm_state_preserved(remote_command_executor, slurm_state_snapshot)
    _assert_preexisting_job_records_readable(scheduler_commands, [pre_upgrade_job_id])
    # The user and association rows live in the same database slurmdbd just converted, so they are read back
    # with the same check used before the upgrade.
    _test_slurmdb_users(remote_command_executor, scheduler_commands, test_resources_dir)
    _test_jobs_get_recorded(scheduler_commands)
    _test_slurm_accounting_password(remote_command_executor)
    if custom_names_supported:
        _test_slurm_accounting_database_name(remote_command_executor, custom_database_name)
        _test_cluster_registered_with_custom_name(remote_command_executor, custom_cluster_name)
    assert_no_defunct_slurm_config_params(remote_command_executor, ignore_patterns=known_defunct_slurm_config_params())
    # Last of the post-upgrade checks, because it reconfigures SSL and restarts slurmdbd: the install recompiles
    # slurmdbd against the system MySQL client libraries, so the TLS connection to the database has to be
    # re-verified.
    _test_require_server_identity(remote_command_executor, test_resources_dir, region)
    _test_that_slurmdbd_is_running(remote_command_executor)

    _test_rollback(
        cluster,
        remote_command_executor,
        scheduler_commands,
        test_resources_dir,
        version_before_install,
        accounting_backup,
        slurm_state_snapshot,
        pre_upgrade_job_id,
        custom_cluster_name if custom_names_supported else None,
    )


def _test_rollback(
    cluster,
    remote_command_executor,
    scheduler_commands,
    test_resources_dir,
    expected_version,
    accounting_backup,
    slurm_state_snapshot,
    pre_upgrade_job_id,
    custom_cluster_name,
):
    """Verify the upgrade of a cluster with Slurm accounting can be undone, database included.

    This is the only rollback that has to undo a database conversion. The conversion the first slurmdbd of a new
    major release performs is one way, so without the dump taken before the upgrade a cross major version upgrade
    of a cluster with accounting is a one-way door: the restored slurmdbd would refuse to start against the
    converted schema. Restoring the dump is what makes the documented rollback procedure work across majors, and
    the checks below are what prove the restored database is the pre-upgrade one and is still usable.
    """
    logging.info("Rolling the upgrade back to Slurm %s", expected_version)
    slurmdbd_log_line_count = _get_slurmdbd_log_line_count(remote_command_executor)

    roll_back_test_software_with_stopped_consumers(
        remote_command_executor, cluster, expected_version=expected_version, accounting_backup=accounting_backup
    )

    # Scoped to the lines the restored slurmdbd appended: the whole log holds the startup lines of both versions
    # installed so far, so an unscoped check would pass even if the restored slurmdbd never came up.
    _test_successful_startup_in_log(remote_command_executor, since_line=slurmdbd_log_line_count)
    _assert_no_upgrade_failures_in_slurmdbd_log(remote_command_executor, slurmdbd_log_line_count)
    _test_that_slurmdbd_is_running(remote_command_executor)

    # The same snapshot is verified a second time on purpose: the rollback restores the StateSaveLocation archive
    # the snapshot was captured from, so the held job and the reservation the post-upgrade check consumed have to
    # be back. Nothing else distinguishes a restored controller state from an empty one that simply starts.
    assert_slurm_state_preserved(remote_command_executor, slurm_state_snapshot)

    # The job records, users and associations all live in the database that was just dropped and recreated from
    # the dump, so they are read back with the same checks used before the upgrade.
    _assert_preexisting_job_records_readable(scheduler_commands, [pre_upgrade_job_id])
    _test_slurmdb_users(remote_command_executor, scheduler_commands, test_resources_dir)
    if custom_cluster_name:
        _test_cluster_registered_with_custom_name(remote_command_executor, custom_cluster_name)

    # Restarting the compute fleet reports RUNNING before clustermgtd has brought the partitions back UP, so a job
    # submitted right away fails with "Requested partition configuration not available now".
    wait_for_partitions_up(scheduler_commands)
    # A job that has to launch a compute node is what shows the rolled-back cluster still provisions and still
    # records: the node boots the slurmd of its AMI, which has to talk to the restored controller and slurmdbd.
    _test_jobs_get_recorded(scheduler_commands)


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_slurm_accounting_external_dbd(
    region,
    pcluster_config_reader,
    munge_key,
    vpc_stack_for_database,
    slurm_dbd,
    test_datadir,
    test_resources_dir,
    clusters_factory,
    scheduler_commands_factory,
):

    config_params = _get_slurm_dbd_config_parameters(slurm_dbd.cfn_outputs)
    public_subnet_id = vpc_stack_for_database.get_public_subnet()
    private_subnet_id = vpc_stack_for_database.get_private_subnet()
    _, munge_key_secret_arn = munge_key
    cluster_config = pcluster_config_reader(
        public_subnet_id=public_subnet_id,
        private_subnet_id=private_subnet_id,
        munge_key_secret_arn=munge_key_secret_arn,
        **config_params,
    )
    cluster = clusters_factory(cluster_config)
    # Don't wait on the second cluster creation so that we can test the first cluster in the meantime.
    cluster_2 = clusters_factory(cluster_config, wait=False)

    logging.info("Testing the first cluster")
    pre_upgrade_job_id_1 = _check_cluster_external_dbd(
        cluster, config_params, region, scheduler_commands_factory, test_resources_dir
    )

    logging.info("Testing the second cluster")
    cluster_2.wait_cluster_status("CREATE_COMPLETE")
    pre_upgrade_job_id_2 = _check_cluster_external_dbd(
        cluster_2, config_params, region, scheduler_commands_factory, test_resources_dir
    )

    logging.info("Testing the inter-clusters slurm accounting information")
    inter_cluster_job_ids = _check_inter_clusters_external_dbd(cluster, cluster_2, scheduler_commands_factory, slurm_dbd.name)

    slurmdbd_node_remote_command_executor = retry(
        stop_max_attempt_number=30, wait_fixed=seconds(20)
    )(RemoteCommandExecutor)(cluster, compute_node_ip=config_params["slurmdbd_private_ip"])
    headnode_remote_command_executor_1 = RemoteCommandExecutor(cluster)
    headnode_remote_command_executor_2 = RemoteCommandExecutor(cluster_2)

    slurmdbd_log_line_count = _get_slurmdbd_log_line_count(slurmdbd_node_remote_command_executor)
    slurm_state_snapshot_1 = snapshot_slurm_state(
        headnode_remote_command_executor_1, scheduler_commands_factory(headnode_remote_command_executor_1)
    )
    slurm_state_snapshot_2 = snapshot_slurm_state(
        headnode_remote_command_executor_2, scheduler_commands_factory(headnode_remote_command_executor_2)
    )
    # Recorded before the install, because they are what the rollback at the end of the test has to restore. The
    # database dump is taken from the slurmdbd host, the only one of the three that can reach the database, and
    # before the upgrade, because the schema conversion the new slurmdbd performs cannot be undone any other way.
    versions_before_install = {
        executor: get_slurm_version(executor)
        for executor in (
            slurmdbd_node_remote_command_executor,
            headnode_remote_command_executor_1,
            headnode_remote_command_executor_2,
        )
    }
    accounting_backup = back_up_accounting_database(slurmdbd_node_remote_command_executor)

    # slurmdbd first, then the controllers: Slurm requires slurmdbd to be at the same or a higher major
    # release than every slurmctld talking to it.
    with stopped_shared_slurm_consumers(cluster, cluster_2):
        # There is no slurmctld on the slurmdbd host to check.
        install_test_software(slurmdbd_node_remote_command_executor, assert_controller=False)
        # This is the only moment a new slurmdbd serves an old slurmctld, which is the combination Slurm
        # supports and customers go through, so it is verified before the controllers are upgraded.
        _test_that_slurmdbd_is_running(headnode_remote_command_executor_1)
        install_test_software(headnode_remote_command_executor_1)
        install_test_software(headnode_remote_command_executor_2)

    _test_successful_startup_in_log(slurmdbd_node_remote_command_executor, since_line=slurmdbd_log_line_count)
    _assert_no_upgrade_failures_in_slurmdbd_log(slurmdbd_node_remote_command_executor, slurmdbd_log_line_count)
    assert_slurm_state_preserved(headnode_remote_command_executor_1, slurm_state_snapshot_1)
    assert_slurm_state_preserved(headnode_remote_command_executor_2, slurm_state_snapshot_2)

    # The per-cluster check is re-run as it is rather than a hand-picked subset of it: it verifies slurmdbd is
    # reachable from the head node, that the TLS server identity check still passes against the recompiled
    # slurmdbd, that new jobs are recorded and that slurm.conf has no defunct parameters.
    logging.info("Re-testing both clusters after the upgrade")
    post_upgrade_job_id_1 = _check_cluster_external_dbd(
        cluster, config_params, region, scheduler_commands_factory, test_resources_dir
    )
    post_upgrade_job_id_2 = _check_cluster_external_dbd(
        cluster_2, config_params, region, scheduler_commands_factory, test_resources_dir
    )

    # The upgraded slurmdbd must still serve the job records written before the upgrade, both to the cluster
    # that submitted them and to the other cluster sharing the same external slurmdbd.
    scheduler_commands_1 = scheduler_commands_factory(headnode_remote_command_executor_1)
    scheduler_commands_2 = scheduler_commands_factory(headnode_remote_command_executor_2)
    for scheduler_commands in (scheduler_commands_1, scheduler_commands_2):
        _assert_preexisting_job_records_readable(
            scheduler_commands, [pre_upgrade_job_id_1] + inter_cluster_job_ids, clusters=cluster.name
        )
        _assert_preexisting_job_records_readable(scheduler_commands, [pre_upgrade_job_id_2], clusters=cluster_2.name)
    retry(stop_max_attempt_number=30, wait_fixed=seconds(20))(_assert_job_completion_recorded_in_accounting)(
        post_upgrade_job_id_1, scheduler_commands_2, clusters=cluster.name
    )
    retry(stop_max_attempt_number=30, wait_fixed=seconds(20))(_assert_job_completion_recorded_in_accounting)(
        post_upgrade_job_id_2, scheduler_commands_1, clusters=cluster_2.name
    )

    _test_rollback_external_dbd(
        cluster,
        cluster_2,
        slurmdbd_node_remote_command_executor,
        headnode_remote_command_executor_1,
        headnode_remote_command_executor_2,
        versions_before_install,
        accounting_backup,
        slurm_state_snapshot_1,
        slurm_state_snapshot_2,
        [pre_upgrade_job_id_1] + inter_cluster_job_ids,
        pre_upgrade_job_id_2,
        cluster.name,
        cluster_2.name,
        scheduler_commands_1,
        scheduler_commands_2,
    )


def _test_rollback_external_dbd(
    cluster,
    cluster_2,
    slurmdbd_executor,
    headnode_executor_1,
    headnode_executor_2,
    versions_before_install,
    accounting_backup,
    slurm_state_snapshot_1,
    slurm_state_snapshot_2,
    pre_upgrade_job_ids_1,
    pre_upgrade_job_id_2,
    cluster_name_1,
    cluster_name_2,
    scheduler_commands_1,
    scheduler_commands_2,
):
    """Verify the upgrade of two clusters sharing an external slurmdbd can be undone, database included.

    Unlike the upgrade, the rollback goes controllers first and slurmdbd last, for the same reason: slurmdbd must
    never be at a lower major release than a slurmctld talking to it, so the controllers have to come down to the
    old release while slurmdbd is still on the new one. The accounting database is restored with the slurmdbd host,
    the only one of the three that can reach it, and only there: an older slurmctld against a newer slurmdbd is a
    combination Slurm supports, so a head node needs no database restore of its own.
    """
    logging.info("Rolling the upgrade of both clusters and of the external slurmdbd back")
    slurmdbd_log_line_count = _get_slurmdbd_log_line_count(slurmdbd_executor)

    with stopped_shared_slurm_consumers(cluster, cluster_2):
        for executor in (headnode_executor_1, headnode_executor_2):
            roll_back_test_software(executor, versions_before_install[executor])
        # This is the mirror image of the upgrade: a new slurmdbd serving old slurmctlds, verified before the
        # database goes back, because after it there is nothing left of the new release to be compatible with.
        _test_that_slurmdbd_is_running(headnode_executor_1)
        # There is no slurmctld and no StateSaveLocation on the slurmdbd host to restore.
        roll_back_test_software(
            slurmdbd_executor,
            versions_before_install[slurmdbd_executor],
            accounting_backup=accounting_backup,
            assert_controller=False,
        )

    # Scoped to the lines the restored slurmdbd appended: the whole log holds the startup lines of both versions
    # installed so far, so an unscoped check would pass even if the restored slurmdbd never came up.
    _test_successful_startup_in_log(slurmdbd_executor, since_line=slurmdbd_log_line_count)
    _assert_no_upgrade_failures_in_slurmdbd_log(slurmdbd_executor, slurmdbd_log_line_count)
    # The same snapshots are verified a second time on purpose: the rollback restores the StateSaveLocation
    # archives they were captured from, so the held jobs and reservations the post-upgrade check consumed have to
    # be back. Nothing else distinguishes a restored controller state from an empty one that simply starts.
    assert_slurm_state_preserved(headnode_executor_1, slurm_state_snapshot_1)
    assert_slurm_state_preserved(headnode_executor_2, slurm_state_snapshot_2)

    # The restored database was dropped and recreated from the dump, so both clusters have to find their own
    # pre-upgrade records and each other's in it, and both have to be able to record a new job in it.
    for scheduler_commands in (scheduler_commands_1, scheduler_commands_2):
        _assert_preexisting_job_records_readable(scheduler_commands, pre_upgrade_job_ids_1, clusters=cluster_name_1)
        _assert_preexisting_job_records_readable(
            scheduler_commands, [pre_upgrade_job_id_2], clusters=cluster_name_2
        )
    for executor, scheduler_commands in (
        (headnode_executor_1, scheduler_commands_1),
        (headnode_executor_2, scheduler_commands_2),
    ):
        _test_that_slurmdbd_is_running(executor)
        # Restarting the compute fleet reports RUNNING before clustermgtd has brought the partitions back UP, so a
        # job submitted right away fails with "Requested partition configuration not available now".
        wait_for_partitions_up(scheduler_commands)
        _test_jobs_get_recorded(scheduler_commands)


def _check_cluster_external_dbd(cluster, config_params, region, scheduler_commands_factory, test_resources_dir):
    headnode_remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(headnode_remote_command_executor)
    slurmdbd_node_remote_command_executor = RemoteCommandExecutor(
        cluster, compute_node_ip=config_params["slurmdbd_private_ip"]
    )

    _test_that_slurmdbd_is_running(headnode_remote_command_executor)
    _test_successful_startup_in_log(slurmdbd_node_remote_command_executor)

    # TODO: _test_slurmdb_users(headnode_remote_command_executor, scheduler_commands, test_resources_dir)
    _test_require_server_identity(slurmdbd_node_remote_command_executor, test_resources_dir, region)
    _test_that_slurmdbd_is_running(headnode_remote_command_executor)
    job_id = _test_jobs_get_recorded(scheduler_commands)
    assert_no_defunct_slurm_config_params(
        headnode_remote_command_executor, ignore_patterns=known_defunct_slurm_config_params()
    )
    return job_id


def _check_inter_clusters_external_dbd(cluster_1, cluster_2, scheduler_commands_factory, slurm_dbd_stack_name):
    """
    Verify accounting information can be retrieved from another cluster
    and information is not lost after AutoScaling group replaces Slurm DBD instance.
    """
    headnode_remote_command_executor_1 = RemoteCommandExecutor(cluster_1)
    scheduler_commands_1 = scheduler_commands_factory(headnode_remote_command_executor_1)
    headnode_remote_command_executor_2 = RemoteCommandExecutor(cluster_2)
    scheduler_commands_2 = scheduler_commands_factory(headnode_remote_command_executor_2)

    job_ids = []
    for index in range(20):  # 20 is an arbitrary number and can be changed.
        job_submission_output = scheduler_commands_1.submit_command(
            'echo "$(hostname) ${SLURM_JOB_ACCOUNT} ${SLURM_JOB_ID} ${SLURM_JOB_NAME}"',
        ).stdout
        job_id = scheduler_commands_1.assert_job_submitted(job_submission_output)
        job_ids.append(job_id)
        logging.info(" Submitted Job ID: %s", job_id)
        if index == 10:
            logging.info(
                "Terminating the Slurm DBD instance to test robustness of the setup: "
                "Job information should be synced after AutoScaling group launches another Slurm DBD instance."
            )
            ec2_client = boto3.client("ec2")
            slurm_dbd_instance_id = ec2_client.describe_instances(
                Filters=[
                    {"Name": "instance-state-name", "Values": ["running"]},
                    {"Name": "tag:aws:cloudformation:logical-id", "Values": ["ExternalSlurmdbdASG"]},
                    {"Name": "tag:aws:cloudformation:stack-name", "Values": [slurm_dbd_stack_name]},
                ]
            )["Reservations"][0]["Instances"][0]["InstanceId"]
            ec2_client.terminate_instances(InstanceIds=[slurm_dbd_instance_id])

    logging.info("Checking jobs information from another cluster.")
    for job_id in job_ids:
        retry(stop_max_attempt_number=30, wait_fixed=seconds(20))(_assert_job_completion_recorded_in_accounting)(
            job_id, scheduler_commands_2, clusters=cluster_1.name
        )
    return job_ids
