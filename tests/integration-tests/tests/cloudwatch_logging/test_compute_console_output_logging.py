import logging
import re

import boto3
import pytest
from assertpy import assert_that
from botocore.exceptions import WaiterError
from cfn_stacks_factory import CfnStack
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes
from utils import generate_stack_name

from tests.cloudwatch_logging.cloudwatch_logging_boto3_utils import (
    get_cluster_log_groups_from_boto3,
    get_log_events,
    get_log_streams,
)

logger = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def test_resources_dir(datadir):
    return datadir / "resources"


@pytest.fixture(scope="module")
def broken_vpc_factory(cfn_stacks_factory, request):
    region_map = {}

    def _create_vpc_stack(region_name, test_resources_dir):
        broken_vpc_stack_name = generate_stack_name(
            "integ-tests-broken-vpc", request.config.getoption("stackname_suffix")
        )

        broken_vpc_stack_template_path = test_resources_dir / "broken-vpc.yaml"

        availability_zone = f"{region_name}a"

        logger.info("Creating stack %s", broken_vpc_stack_name)

        with open(broken_vpc_stack_template_path) as broken_vpc_template:
            stack_parameters = [
                {"ParameterKey": "AvailabilityZone", "ParameterValue": availability_zone},
                {"ParameterKey": "PublicSubnetCidrBlock", "ParameterValue": "10.0.16.0/24"},
                {"ParameterKey": "PrivateSubnetCidrBlock", "ParameterValue": "10.0.128.0/20"},
            ]
            broken_vpc_stack = CfnStack(
                name=broken_vpc_stack_name,
                region=region_name,
                template=broken_vpc_template.read(),
                parameters=stack_parameters,
                capabilities=["CAPABILITY_AUTO_EXPAND"],
            )
        cfn_stacks_factory.create_stack(broken_vpc_stack)
        logger.info("Creation of stack %s complete", broken_vpc_stack_name)

        return broken_vpc_stack_name

    def _return_broken_vpc(region_name, test_resources_dir):
        broken_vpc_stack_name = region_map.get(region_name) or _create_vpc_stack(region_name, test_resources_dir)
        region_map.update({region_name: broken_vpc_stack_name})

        return broken_vpc_stack_name

    yield _return_broken_vpc

    for region, stack_name in region_map.items():
        if request.config.getoption("no_delete"):
            logging.info(
                "Not deleting VPC stack %s in region %s because --no-delete option was specified",
                stack_name,
                region,
            )
        else:
            logging.info(
                "Deleting VPC stack %s in region %s",
                stack_name,
                region,
            )
            cfn_stacks_factory.delete_stack(stack_name, region)


def _get_infra_stack_outputs(stack_name, region_name):
    cfn = boto3.client("cloudformation", region_name=region_name)
    return {
        entry.get("OutputKey"): entry.get("OutputValue")
        for entry in cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    }


def _get_broken_vpc_cluster_params(broken_vpc_stack_name, region_name):
    stack_outputs = _get_infra_stack_outputs(broken_vpc_stack_name, region_name)
    return {
        "vpc_id": stack_outputs.get("parallelclustervpc"),
        "public_subnet_id": stack_outputs.get("parallelclusterdpublicsubnet"),
        "private_subnet_id": stack_outputs.get("parallelclusterdprivatesubnet"),
    }


@retry(stop_max_attempt_number=10, wait_fixed=minutes(3))
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
                r"2\d{3}-\d{1,2}-\d{1,2} \d{2}:\d{2}:\d{2},\d{3} - Console output for node compute-st-.*", message
            )
        ]
    ).is_not_empty()


def _wait_for_cluster_failure(cluster, region, wait_time_seconds=1800):
    client = boto3.client("cloudformation", region_name=region)
    waiter = client.get_waiter("stack_create_complete")
    count = (wait_time_seconds + 29) // 30

    logger.info("Waiting for cluster creation to fail for %d attempts...", count)

    try:
        waiter.wait(
            StackName=cluster.name,
            WaiterConfig={
                "Delay": 30,
                "MaxAttempts": count,
            },
        )
    except WaiterError as e:
        logger.info("Result: %s", e)
        return

    raise Exception("Cluster creation failed to fail")


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_compute_console_logging(
    region,
    request,
    pcluster_config_reader,
    cfn_stacks_factory,
    test_datadir,
    test_resources_dir,
    clusters_factory,
    broken_vpc_factory,
):
    # broken_vpc_name = broken_vpc_factory(region, test_resources_dir)
    # logger.info("Using VPC Stack: %s", broken_vpc_name)
    #
    # config_params = _get_broken_vpc_cluster_params(broken_vpc_name, region)
    # logger.info("Cluster Config: %s", config_params)

    logger.info("Test Data Dir: %s", test_datadir)

    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config, raise_on_error=False, wait=False)

    # _wait_for_cluster_failure(cluster, region)

    _verify_compute_console_output_log_exists_in_log_group(cluster)

    remote_command_executor = RemoteCommandExecutor(cluster)
