# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import json
import logging
import re
from typing import AnyStr, Dict, Iterator, Tuple

from assertpy import assert_that
from clusters_factory import Cluster
from retrying import retry
from time_utils import minutes, seconds

from tests.cloudwatch_logging.cloudwatch_logging_boto3_utils import (
    get_cluster_log_groups_from_boto3,
    get_log_events,
    get_log_streams,
)

logger = logging.getLogger(__name__)


def get_log_stream_events(cluster: Cluster, stream_name_pattern: AnyStr) -> Iterator[Tuple[str, Dict]]:
    pattern = re.compile(stream_name_pattern)
    log_group_name = get_cluster_log_groups_from_boto3(f"/aws/parallelcluster/{cluster.name}")[0].get("logGroupName")
    for log_stream in get_log_streams(log_group_name):
        log_stream_name = log_stream.get("logStreamName")
        if pattern.fullmatch(log_stream_name):
            yield from ((log_stream_name, event) for event in get_log_events(log_group_name, log_stream_name))


def get_log_stream_events_by_event_type(
    cluster: Cluster, stream_name_pattern: AnyStr, event_type_pattern: AnyStr
) -> Iterator[Tuple[str, Dict[str, Dict]]]:
    pattern = re.compile(event_type_pattern)
    for stream_name, log_event in get_log_stream_events(cluster, stream_name_pattern):
        json_event = json.loads(log_event.get("message", {}))
        logger.info(
            "Got Event Type: %s, looking for event type %s", json_event.get("event-type", ""), event_type_pattern
        )
        if pattern.fullmatch(json_event.get("event-type", "")):
            logger.info("Returning event %s for event type %s", json_event.get("event-type", ""), event_type_pattern)
            yield stream_name, json_event


def get_node_info_from_stream_name(stream_name: str) -> Dict[str, str]:
    match = re.match(r"ip-(\d{1,3}(-\d{1,3}){3})\.(i-[0-9a-f]+)\.(.+)", stream_name)
    return {
        "ip": match.group(1).replace("-", "."),
        "instance-id": match.group(3),
        "logfile": match.group(4),
    }


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))
def assert_that_event_exists(cluster: Cluster, stream_name_pattern: str, event_type_pattern: str):
    stream_name, event = next(get_log_stream_events_by_event_type(cluster, stream_name_pattern, event_type_pattern))
    logger.info("Found event %s for %s", event, event_type_pattern)
    info = get_node_info_from_stream_name(stream_name)
    assert_that(event.get("cluster-name")).is_equal_to(cluster.name)
    assert_that(event.get("scheduler")).is_equal_to("slurm")
    assert_that(event.get("instance-id")).is_equal_to(info.get("instance-id"))
    if "compute" in event:
        assert_that(event.get("compute").get("address")).is_equal_to(info.get("ip"))
        assert_that(event.get("node-role")).is_equal_to("ComputeFleet")
    else:
        assert_that(event.get("node-role")).is_equal_to("HeadNode")
