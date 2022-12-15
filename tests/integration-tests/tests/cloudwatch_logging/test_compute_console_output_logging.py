import logging
import re

import boto3
import pytest
from assertpy import assert_that
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
                r"2\d{3}-\d{1,2}-\d{1,2} \d{2}(:\d{2}){2},\d{3} - Console output for node compute-st-.*", message
            )
        ]
    ).is_not_empty()


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_compute_console_logging(
    pcluster_config_reader,
    cfn_stacks_factory,
    test_datadir,
    test_resources_dir,
    clusters_factory,
):
    logger.info("Test Data Dir: %s", test_datadir)

    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config, raise_on_error=False, wait=False)

    _verify_compute_console_output_log_exists_in_log_group(cluster)
