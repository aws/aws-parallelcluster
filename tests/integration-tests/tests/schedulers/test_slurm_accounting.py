import logging
import os
import re

import boto3
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import seconds

from tests.cloudwatch_logging import cloudwatch_logging_boto3_utils as cw_utils
from tests.common.utils import get_aws_domain

STARTED_PATTERN = re.compile(r".*slurmdbd version [\d.]+ started")


def _get_slurm_database_config_parameters(database_stack_outputs):
    return {
        "database_host": database_stack_outputs.get("DatabaseHost"),
        "database_admin_user": database_stack_outputs.get("DatabaseAdminUser"),
        "database_secret_arn": database_stack_outputs.get("DatabaseSecretArn"),
        "database_client_security_group": database_stack_outputs.get("DatabaseClientSecurityGroup"),
    }


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
        return f"https://truststore.pki.rds.amazonaws.com/{region}/{region}-bundle.pem"


def _require_server_identity(remote_command_executor, test_resources_dir, region):
    ca_url = _rds_ca_bundle_url(region)
    remote_command_executor.run_remote_script(
        os.path.join(str(test_resources_dir), "require_server_identity.sh"),
        args=[
            ca_url,
            f"{region}-bundle.pem",
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


@retry(stop_max_attempt_number=36, wait_fixed=10 * 1000)
def _test_successful_startup_in_log(remote_command_executor):
    log_file = "/var/log/slurmdbd.log"

    log = remote_command_executor.run_remote_command("sudo cat {0}".format(log_file), hide=True).stdout
    assert_that(
        [line for line in log.splitlines() if STARTED_PATTERN.fullmatch(line) is not None], "Successful Startup"
    ).is_not_empty()


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
    results = scheduler_commands.get_accounting_job_records(job_id)
    for row in results:
        logging.info(" Result: %s", row)
        assert_that(row.get("state")).is_equal_to("COMPLETED")


def _test_that_slurmdbd_is_not_running(remote_command_executor):
    assert_that(_is_accounting_enabled(remote_command_executor)).is_false()


def _test_that_slurmdbd_is_running(remote_command_executor):
    assert_that(_is_accounting_enabled(remote_command_executor)).is_true()


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
    cluster_config = pcluster_config_reader(
        public_subnet_id=public_subnet_id, private_subnet_id=private_subnet_id, **config_params
    )
    cluster = clusters_factory(cluster_config)

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    _test_that_slurmdbd_is_running(remote_command_executor)
    _test_successful_startup_in_log(remote_command_executor)
    _test_slurmdbd_log_exists_in_log_group(cluster)
    _test_slurmdb_users(remote_command_executor, scheduler_commands, test_resources_dir)
    _test_require_server_identity(remote_command_executor, test_resources_dir, region)
    _test_jobs_get_recorded(scheduler_commands)

    # Update the queues to check that bug with the Slurm Accounting database server password
    # is fixed (see https://github.com/aws/aws-parallelcluster/issues/5151 )
    # Re-use the same update to test the modification of DatabaseName.
    custom_database_name = "test_custom_dbname"
    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update.yaml",
        public_subnet_id=public_subnet_id,
        private_subnet_id=private_subnet_id,
        custom_database_name=custom_database_name,
        **config_params,
    )
    cluster.update(str(updated_config_file), force_update="true")
    _test_slurm_accounting_password(remote_command_executor)
    _test_slurm_accounting_database_name(remote_command_executor, custom_database_name)
    _test_that_slurmdbd_is_running(remote_command_executor)


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_slurm_accounting_disabled_to_enabled_update(
    region,
    pcluster_config_reader,
    database,
    vpc_stack_for_database,
    request,
    test_datadir,
    test_resources_dir,
    clusters_factory,
    scheduler_commands_factory,
):

    public_subnet_id = vpc_stack_for_database.get_public_subnet()
    private_subnet_id = vpc_stack_for_database.get_private_subnet()

    # First create a cluster without Slurm Accounting enabled
    cluster_config = pcluster_config_reader(public_subnet_id=public_subnet_id, private_subnet_id=private_subnet_id)
    cluster = clusters_factory(cluster_config)

    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_that_slurmdbd_is_not_running(remote_command_executor)

    config_params = _get_slurm_database_config_parameters(database.cfn_outputs)

    # Then update the cluster to enable Slurm Accounting
    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update.yaml",
        public_subnet_id=public_subnet_id,
        private_subnet_id=private_subnet_id,
        **config_params,
    )
    cluster.update(str(updated_config_file), force_update="true")

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    # Test for successful Slurm Accounting start up
    _test_that_slurmdbd_is_running(remote_command_executor)
    _test_successful_startup_in_log(remote_command_executor)
    _test_slurmdbd_log_exists_in_log_group(cluster)
    _test_slurmdb_users(remote_command_executor, scheduler_commands, test_resources_dir)
    _test_jobs_get_recorded(scheduler_commands)
