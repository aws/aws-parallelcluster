# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import logging
import time

import boto3
from retrying import RetryError, retry

from time_utils import seconds


def get_compute_nodes_allocation(scheduler_commands, region, stack_name, max_monitoring_time):
    """
    Watch periodically the number of compute nodes in the cluster.

    :return: (asg_capacity_time_series, compute_nodes_time_series, timestamps): three lists describing
        the variation over time in the number of compute nodes and the timestamp when these fluctuations occurred.
        asg_capacity_time_series describes the variation in the desired asg capacity. compute_nodes_time_series
        describes the variation in the number of compute nodes seen by the scheduler. timestamps describes the
        time since epoch when the variations occurred.
    """
    asg_capacity_time_series = []
    compute_nodes_time_series = []
    timestamps = []

    @retry(
        # Retry until ASG and Scheduler capacities scale down to 0
        # Also make sure cluster scaled up before scaling down
        retry_on_result=lambda _: asg_capacity_time_series[-1] != 0
        or compute_nodes_time_series[-1] != 0
        or max(asg_capacity_time_series) == 0
        or max(compute_nodes_time_series) == 0,
        wait_fixed=seconds(20),
        stop_max_delay=max_monitoring_time,
    )
    def _watch_compute_nodes_allocation():
        compute_nodes = scheduler_commands.compute_nodes_count()
        asg_capacity = _get_desired_asg_capacity(region, stack_name)
        timestamp = time.time()

        # add values only if there is a transition.
        if (
            len(asg_capacity_time_series) == 0
            or asg_capacity_time_series[-1] != asg_capacity
            or compute_nodes_time_series[-1] != compute_nodes
        ):
            asg_capacity_time_series.append(asg_capacity)
            compute_nodes_time_series.append(compute_nodes)
            timestamps.append(timestamp)

    try:
        _watch_compute_nodes_allocation()
    except RetryError:
        # ignoring this error in order to perform assertions on the collected data.
        pass

    logging.info(
        "Monitoring completed: %s, %s, %s",
        "asg_capacity_time_series [" + " ".join(map(str, asg_capacity_time_series)) + "]",
        "compute_nodes_time_series [" + " ".join(map(str, compute_nodes_time_series)) + "]",
        "timestamps [" + " ".join(map(str, timestamps)) + "]",
    )
    return asg_capacity_time_series, compute_nodes_time_series, timestamps


def _get_desired_asg_capacity(region, stack_name):
    """Retrieve the desired capacity of the autoscaling group for a specific cluster."""
    asg_conn = boto3.client("autoscaling", region_name=region)
    tags = asg_conn.describe_tags(Filters=[{"Name": "value", "Values": [stack_name]}])
    asg_name = tags.get("Tags")[0].get("ResourceId")
    response = asg_conn.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    return response["AutoScalingGroups"][0]["DesiredCapacity"]
