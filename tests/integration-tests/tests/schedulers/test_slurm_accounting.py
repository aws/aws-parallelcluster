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

STARTED_PATTERN = re.compile(r".*slurmdbd version [\d.]+ started")


def get_infra_stack_outputs(stack_name):
    cfn = boto3.client("cloudformation")
    return {
        entry.get("OutputKey"): entry.get("OutputValue")
        for entry in cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    }


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


def _require_server_identity(remote_command_executor, test_resources_dir, region):
    ca_url = f"https://truststore.pki.rds.amazonaws.com/{region}/{region}-bundle.pem"
    remote_command_executor.run_remote_script(
        os.path.join(str(test_resources_dir), "require_server_identity.sh"),
        args=[
            ca_url,
            f"{region}-bundle.pem",
        ],
        run_as_root=True,
    )


def _test_require_server_identity(remote_command_executor, test_resources_dir, region):
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


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_slurm_accounting(
    region,
    pcluster_config_reader,
    database_factory,
    request,
    test_datadir,
    test_resources_dir,
    clusters_factory,
    scheduler_commands_factory,
):
    database_stack_name = database_factory(
        request.config.getoption("slurm_database_stack_name"),
        str(test_datadir),
        region,
    )

    database_stack_outputs = get_infra_stack_outputs(database_stack_name)

    config_params = _get_slurm_database_config_parameters(database_stack_outputs)
    cluster_config = pcluster_config_reader(**config_params)
    cluster = clusters_factory(cluster_config)

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    _test_that_slurmdbd_is_running(remote_command_executor)
    _test_successful_startup_in_log(remote_command_executor)
    _test_slurmdbd_log_exists_in_log_group(cluster)
    _test_slurmdb_users(remote_command_executor, scheduler_commands, test_resources_dir)
    _test_require_server_identity(remote_command_executor, test_resources_dir, region)
    _test_jobs_get_recorded(scheduler_commands)


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_slurm_accounting_disabled_to_enabled_update(
    region,
    pcluster_config_reader,
    database_factory,
    request,
    test_datadir,
    test_resources_dir,
    clusters_factory,
    scheduler_commands_factory,
):
    database_stack_name = database_factory(
        request.config.getoption("slurm_database_stack_name"),
        str(test_datadir),
        region,
    )

    database_stack_outputs = get_infra_stack_outputs(database_stack_name)

    # First create a cluster without Slurm Accounting enabled
    cluster_config = pcluster_config_reader(config_file="pcluster.config.yaml")
    cluster = clusters_factory(cluster_config)

    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_that_slurmdbd_is_not_running(remote_command_executor)

    config_params = _get_slurm_database_config_parameters(database_stack_outputs)

    # Then update the cluster to enable Slurm Accounting
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.update.yaml", **config_params)
    cluster.update(str(updated_config_file), force_update="true")

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    # Test for successful Slurm Accounting start up
    _test_that_slurmdbd_is_running(remote_command_executor)
    _test_successful_startup_in_log(remote_command_executor)
    _test_slurmdbd_log_exists_in_log_group(cluster)
    _test_slurmdb_users(remote_command_executor, scheduler_commands, test_resources_dir)
    _test_jobs_get_recorded(scheduler_commands)
