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
from utils import get_compute_nodes_count


def get_compute_nodes_allocation(scheduler_commands, region, stack_name, max_monitoring_time):
    """
    Watch periodically the number of compute nodes in the cluster.

    :return: (ec2_capacity_time_series, compute_nodes_time_series, timestamps): three lists describing
        the variation over time in the number of compute nodes and the timestamp when these fluctuations occurred.
        ec2_capacity_time_series describes the variation in the desired ec2 capacity. compute_nodes_time_series
        describes the variation in the number of compute nodes seen by the scheduler. timestamps describes the
        time since epoch when the variations occurred.
    """
    ec2_capacity_time_series = []
    compute_nodes_time_series = []
    timestamps = []

    @retry(
        # Retry until EC2 and Scheduler capacities scale down to 0
        # Also make sure cluster scaled up before scaling down
        retry_on_result=lambda _: ec2_capacity_time_series[-1] != 0
        or compute_nodes_time_series[-1] != 0
        or max(ec2_capacity_time_series) == 0
        or max(compute_nodes_time_series) == 0,
        wait_fixed=seconds(20),
        stop_max_delay=max_monitoring_time,
    )
    def _watch_compute_nodes_allocation():
        compute_nodes = scheduler_commands.compute_nodes_count()
        ec2_capacity = get_compute_nodes_count(stack_name, region)
        timestamp = time.time()

        # add values only if there is a transition.
        if (
            len(ec2_capacity_time_series) == 0
            or ec2_capacity_time_series[-1] != ec2_capacity
            or compute_nodes_time_series[-1] != compute_nodes
        ):
            ec2_capacity_time_series.append(ec2_capacity)
            compute_nodes_time_series.append(compute_nodes)
            timestamps.append(timestamp)

    try:
        _watch_compute_nodes_allocation()
    except RetryError:
        # ignoring this error in order to perform assertions on the collected data.
        pass

    logging.info(
        "Monitoring completed: %s, %s, %s",
        "ec2_capacity_time_series [" + " ".join(map(str, ec2_capacity_time_series)) + "]",
        "compute_nodes_time_series [" + " ".join(map(str, compute_nodes_time_series)) + "]",
        "timestamps [" + " ".join(map(str, timestamps)) + "]",
    )
    return ec2_capacity_time_series, compute_nodes_time_series, timestamps


def watch_compute_nodes(scheduler_commands, max_monitoring_time, number_of_nodes):
    """Watch periodically the number of nodes seen by the scheduler."""
    compute_nodes_time_series = []
    timestamps = []

    @retry(
        # Retry until the given number_of_nodes is equal to the number of compute nodes
        retry_on_result=lambda _: compute_nodes_time_series[-1] != number_of_nodes,
        wait_fixed=seconds(20),
        stop_max_delay=max_monitoring_time,
    )
    def _watch_compute_nodes_allocation():
        compute_nodes = scheduler_commands.compute_nodes_count()
        timestamp = time.time()

        # add values only if there is a transition.
        if len(compute_nodes_time_series) == 0 or compute_nodes_time_series[-1] != compute_nodes:
            compute_nodes_time_series.append(compute_nodes)
            timestamps.append(timestamp)

    try:
        _watch_compute_nodes_allocation()
    except RetryError:
        # ignoring this error in order to perform assertions on the collected data.
        pass

    logging.info(
        "Monitoring completed: %s, %s",
        "compute_nodes_time_series [" + " ".join(map(str, compute_nodes_time_series)) + "]",
        "timestamps [" + " ".join(map(str, timestamps)) + "]",
    )


def _get_asg(region, stack_name):
    """Retrieve the autoscaling group for a specific cluster."""
    asg_conn = boto3.client("autoscaling", region_name=region)
    tags = asg_conn.describe_tags(Filters=[{"Name": "value", "Values": [stack_name]}])
    asg_name = tags.get("Tags")[0].get("ResourceId")
    response = asg_conn.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    return response["AutoScalingGroups"][0]


def get_desired_asg_capacity(region, stack_name):
    """Retrieve the desired capacity of the autoscaling group for a specific cluster."""
    return _get_asg(region, stack_name)["DesiredCapacity"]


def get_max_asg_capacity(region, stack_name):
    """Retrieve the max capacity of the autoscaling group for a specific cluster."""
    return _get_asg(region, stack_name)["MaxSize"]


def get_min_asg_capacity(region, stack_name):
    """Retrieve the min capacity of the autoscaling group for a specific cluster."""
    return _get_asg(region, stack_name)["MinSize"]


def get_stack(stack_name, region, cfn_client=None):
    """
    Get the output for a DescribeStacks action for the given Stack.

    :return: the Stack data type
    """
    if not cfn_client:
        cfn_client = boto3.client("cloudformation", region_name=region)
    return cfn_client.describe_stacks(StackName=stack_name).get("Stacks")[0]


def get_stack_output_value(stack_outputs, output_key):
    """
    Get output value from Cloudformation Stack Output.

    :return: OutputValue if that output exists, otherwise None
    """
    return next((o.get("OutputValue") for o in stack_outputs if o.get("OutputKey") == output_key), None)


def get_batch_ce(stack_name, region):
    """
    Get name of the AWS Batch Compute Environment.

    :return: ce_name or exit if not found
    """
    outputs = get_stack(stack_name, region).get("Outputs")
    return get_stack_output_value(outputs, "BatchComputeEnvironmentArn")


def get_batch_ce_max_size(stack_name, region):
    """Get max vcpus for Batch Compute Environment."""
    client = boto3.client("batch", region_name=region)

    return (
        client.describe_compute_environments(computeEnvironments=[get_batch_ce(stack_name, region)])
        .get("computeEnvironments")[0]
        .get("computeResources")
        .get("maxvCpus")
    )


def get_batch_ce_min_size(stack_name, region):
    """Get min vcpus for Batch Compute Environment."""
    client = boto3.client("batch", region_name=region)

    return (
        client.describe_compute_environments(computeEnvironments=[get_batch_ce(stack_name, region)])
        .get("computeEnvironments")[0]
        .get("computeResources")
        .get("minvCpus")
    )
