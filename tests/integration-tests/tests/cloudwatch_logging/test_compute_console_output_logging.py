import json
import logging
import re

import boto3
import pytest
from assertpy import assert_that
from clusters_factory import Cluster
from configparser import ConfigParser
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes

from tests.cloudwatch_logging.cloudwatch_logging_boto3_utils import (
    get_cluster_log_groups_from_boto3,
    get_log_events,
    get_log_streams,
)

logger = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def test_resources_dir(datadir):
    return datadir / "resources"


def _get_infra_stack_outputs(stack_name, region_name):
    cfn = boto3.client("cloudformation", region_name=region_name)
    return {
        entry.get("OutputKey"): entry.get("OutputValue")
        for entry in cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    }


@retry(stop_max_attempt_number=15, wait_fixed=minutes(3))
def _verify_compute_console_output_log_exists_in_log_group(cluster):
    log_groups = get_cluster_log_groups_from_boto3(f"/aws/parallelcluster/{cluster.name}")
    assert_that(log_groups).is_length(1)
    log_group_name = log_groups[0].get("logGroupName")
    log_streams = get_log_streams(log_group_name)
    streams = [
        stream.get("logStreamName")
        for stream in log_streams
        if re.fullmatch(r".*\.compute_console_output", stream.get("logStreamName"))
    ]
    assert_that(streams).is_length(1)
    stream_name = streams[0]
    events = get_log_events(log_group_name, stream_name)
    messages = (event.get("message") for event in events)
    assert_that(
        [
            message
            for message in messages
            if re.fullmatch(
                r"2\d{3}-\d{1,2}-\d{1,2} \d{2}(:\d{2}){2},\d{3} - Console output for node compute-st-.*", message
            )
        ]
    ).is_not_empty()


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_compute_console_logging(
    pcluster_config_reader,
    clusters_factory,
):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config, raise_on_error=False, wait=False)

    _verify_compute_console_output_log_exists_in_log_group(cluster)


def _get_clustermgtd_config(remote_command_executor: RemoteCommandExecutor) -> ConfigParser:
    config = remote_command_executor.run_remote_command(
        "cat /etc/parallelcluster/slurm_plugin/parallelcluster_clustermgtd.conf",
        raise_on_error=False,
    ).stdout
    for line in config.splitlines():
        logger.info("  Config-Line: %s", line)
    config_parser = ConfigParser()
    config_parser.read_string(config)
    return config_parser


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_console_output_with_monitoring_disabled(
    pcluster_config_reader,
    cfn_stacks_factory,
    test_datadir,
    test_resources_dir,
    clusters_factory,
):
    cluster_config = pcluster_config_reader()
    cluster: Cluster = clusters_factory(cluster_config)

    head_node_role = cluster.cfn_resources.get("RoleHeadNode")

    iam = boto3.client("iam")
    policies = iam.get_role_policy(RoleName=head_node_role, PolicyName="parallelcluster")
    policies = {policy.get("Sid"): policy for policy in policies.get("PolicyDocument").get("Statement")}
    assert_that(policies).does_not_contain_key("EC2GetComputeConsoleOutput")
    for statement in (policies.get(sid) for sid in policies):
        action = statement.get("Action")
        assert_that(
            "ec2:GetConsoleOutput" in action if isinstance(action, list) else action == "ec2:GetConsoleOutput"
        ).is_false()

    remote_command_executor = RemoteCommandExecutor(cluster)
    config = _get_clustermgtd_config(remote_command_executor)
    assert_that(
        config.getboolean(
            "clustermgtd",
            "compute_console_logging_enabled",
            fallback=False,
        )
    ).is_false()


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_monitoring_enabled_configures_console_output(
    pcluster_config_reader,
    cfn_stacks_factory,
    test_datadir,
    test_resources_dir,
    clusters_factory,
):
    cluster_config = pcluster_config_reader()
    cluster: Cluster = clusters_factory(cluster_config)

    head_node_role = cluster.cfn_resources.get("RoleHeadNode")

    iam = boto3.client("iam")
    policies = iam.get_role_policy(RoleName=head_node_role, PolicyName="parallelcluster")
    policies = {policy.get("Sid"): policy for policy in policies.get("PolicyDocument").get("Statement")}
    logger.info(json.dumps(policies))
    assert_that(policies).contains_key("EC2GetComputeConsoleOutput")
    statement = policies.get("EC2GetComputeConsoleOutput")
    action = statement.get("Action")
    assert_that(
        "ec2:GetConsoleOutput" in action if isinstance(action, list) else action == "ec2:GetConsoleOutput"
    ).is_true()
    queues = statement.get("Condition").get("StringEquals").get("aws:ResourceTag/parallelcluster:queue-name")
    assert_that(queues).contains_only("compute-a", "compute-b")

    remote_command_executor = RemoteCommandExecutor(cluster)
    config = _get_clustermgtd_config(remote_command_executor)
    assert_that(
        config.getboolean(
            "clustermgtd",
            "compute_console_logging_enabled",
            fallback=False,
        )
    ).is_true()


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_custom_action_error(
    pcluster_config_reader, cfn_stacks_factory, test_datadir, test_resources_dir, region, clusters_factory, s3_bucket
):
    bucket_name = s3_bucket
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    script = "on_node_start.sh"
    script_path = f"test_custom_action_error/{script}"
    bucket.upload_file(str(test_datadir / script), script_path)

    cluster_config = pcluster_config_reader(bucket=bucket_name, script_path=script_path)
    cluster: Cluster = clusters_factory(cluster_config, raise_on_error=False, wait=False)
    _verify_compute_console_output_log_exists_in_log_group(cluster)
