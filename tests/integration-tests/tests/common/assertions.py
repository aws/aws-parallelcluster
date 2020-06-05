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
import boto3

from assertpy import assert_that, soft_assertions
from tests.common.scaling_common import get_compute_nodes_allocation
from time_utils import minutes


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
