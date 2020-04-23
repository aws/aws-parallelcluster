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
from retrying import retry

from assertpy import assert_that, soft_assertions
from tests.common.scaling_common import get_compute_nodes_allocation
from time_utils import minutes, seconds


def assert_instance_replaced_or_terminating(instance_id, region):
    """Assert that a given instance got replaced or is marked as Unhealthy."""
    response = boto3.client("autoscaling", region_name=region).describe_auto_scaling_instances(
        InstanceIds=[instance_id]
    )
    assert_that(
        not response["AutoScalingInstances"]
        or response["AutoScalingInstances"][0]["LifecycleState"] == "Terminating"
        or response["AutoScalingInstances"][0]["HealthStatus"] == "UNHEALTHY"
    ).is_true()


def assert_asg_desired_capacity(region, asg_name, expected):
    asg_client = boto3.client("autoscaling", region_name=region)
    asg = asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name]).get("AutoScalingGroups")[0]
    assert_that(asg.get("DesiredCapacity")).is_equal_to(expected)


def assert_no_errors_in_logs(remote_command_executor, log_files):
    __tracebackhide__ = True
    for log_file in log_files:
        log = remote_command_executor.run_remote_command("cat {0}".format(log_file), hide=True).stdout
        for error_level in ["CRITICAL", "ERROR"]:
            assert_that(log).does_not_contain(error_level)


def assert_scaling_worked(
    scheduler_commands,
    region,
    stack_name,
    scaledown_idletime,
    expected_max,
    expected_final,
    assert_asg=True,
    assert_scheduler=True,
):
    jobs_execution_time = 1
    estimated_scaleup_time = 5
    max_scaledown_time = 10
    asg_capacity_time_series, compute_nodes_time_series, _ = get_compute_nodes_allocation(
        scheduler_commands=scheduler_commands,
        region=region,
        stack_name=stack_name,
        max_monitoring_time=minutes(jobs_execution_time)
        + minutes(scaledown_idletime)
        + minutes(estimated_scaleup_time)
        + minutes(max_scaledown_time),
    )

    with soft_assertions():
        if assert_asg:
            asg_capacity_time_series_str = f"asg_capacity_time_series={asg_capacity_time_series}"
            assert_that(max(asg_capacity_time_series)).described_as(asg_capacity_time_series_str).is_equal_to(
                expected_max
            )
            assert_that(asg_capacity_time_series[-1]).described_as(asg_capacity_time_series_str).is_equal_to(
                expected_final
            )
        if assert_scheduler:
            compute_nodes_time_series_str = f"compute_nodes_time_series={compute_nodes_time_series}"
            assert_that(max(compute_nodes_time_series)).described_as(compute_nodes_time_series_str).is_equal_to(
                expected_max
            )
            assert_that(compute_nodes_time_series[-1]).described_as(compute_nodes_time_series_str).is_equal_to(
                expected_final
            )


def assert_nodes_removed_and_replaced_in_scheduler(
    scheduler_commands, nodes_to_remove, nodes_to_retain, desired_capacity
):
    """
    Assert that nodes are removed from scheduler and replaced so that number of nodes in scheduler equals to desired.
    Returns list of new nodenames in scheduler.
    """
    assert_nodes_removed_from_scheduler(scheduler_commands, nodes_to_remove)
    wait_num_nodes_in_scheduler(scheduler_commands, desired_capacity)
    new_compute_nodes = scheduler_commands.get_compute_nodes()
    if nodes_to_retain:
        assert_that(set(nodes_to_retain) <= set(new_compute_nodes)).is_true()
    logging.info(
        "\nNodes removed from scheduler: {}"
        "\nNodes retained in scheduler {}"
        "\nNodes currently in scheduler after replacements: {}".format(
            nodes_to_remove, nodes_to_retain, new_compute_nodes
        )
    )


@retry(wait_fixed=seconds(30), stop_max_delay=minutes(10))
def assert_nodes_removed_from_scheduler(scheduler_commands, nodes):
    assert_that(scheduler_commands.get_compute_nodes()).does_not_contain(*nodes)


@retry(wait_fixed=seconds(30), stop_max_delay=minutes(10))
def wait_num_nodes_in_scheduler(scheduler_commands, desired):
    assert_num_nodes_in_scheduler(scheduler_commands, desired)


def assert_num_nodes_in_scheduler(scheduler_commands, desired):
    assert_that(len(scheduler_commands.get_compute_nodes())).is_equal_to(desired)


def assert_nodes_not_terminated_by_nodewatcher(scheduler_commands, nodes, nodewatcher_timeout=7):
    logging.info("Waiting for nodewatcher action")
    start_time = time.time()
    while time.time() < start_time + 60 * (nodewatcher_timeout):
        assert_that(set(nodes) <= set(scheduler_commands.get_compute_nodes())).is_true()
        time.sleep(30)


def assert_initial_conditions(scheduler_commands, num_compute_nodes, assert_state=True):
    """Assert cluster is in expected state before test starts; return list of compute nodes."""
    compute_nodes = scheduler_commands.get_compute_nodes()
    logging.info(
        "Assert initial condition, expect cluster to have {num_nodes} idle nodes".format(num_nodes=num_compute_nodes)
    )
    assert_num_nodes_in_scheduler(scheduler_commands, num_compute_nodes)
    if assert_state:
        assert_compute_node_states(scheduler_commands, compute_nodes, expected_states=["idle"])

    return compute_nodes


def assert_compute_node_states(scheduler_commands, compute_nodes, expected_states):
    # Assert state currently only work for slurm
    # To-do: add support for sge and torque
    node_states = scheduler_commands.get_nodes_status(compute_nodes)
    for node in compute_nodes:
        assert_that(expected_states).contains(node_states.get(node))
