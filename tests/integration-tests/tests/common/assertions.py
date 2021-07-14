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
from assertpy import assert_that, soft_assertions
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from utils import get_compute_nodes_count, get_compute_nodes_instance_ids

from tests.common.scaling_common import get_compute_nodes_allocation


def assert_instance_replaced_or_terminating(instance_id, region):
    """Assert that a given instance got replaced or is marked as Unhealthy."""
    ec2_response = boto3.client("ec2", region_name=region).describe_instances(InstanceIds=[instance_id])
    assert_that(ec2_response["Reservations"][0]["Instances"][0]["State"]["Name"]).is_in("shutting-down", "terminated")


def assert_no_errors_in_logs(remote_command_executor, scheduler):
    __tracebackhide__ = True
    if scheduler == "slurm":
        log_files = [
            "/var/log/parallelcluster/clustermgtd",
            "/var/log/parallelcluster/slurm_resume.log",
            "/var/log/parallelcluster/slurm_suspend.log",
        ]
    else:
        log_files = []

    for log_file in log_files:
        log = remote_command_executor.run_remote_command("sudo cat {0}".format(log_file), hide=True).stdout
        for error_level in ["CRITICAL", "ERROR"]:
            assert_that(log).does_not_contain(error_level)


def assert_no_msg_in_logs(remote_command_executor, log_files, log_msg):
    """Assert log msgs are not in logs."""
    __tracebackhide__ = True
    log = ""
    for log_file in log_files:
        log += remote_command_executor.run_remote_command("sudo cat {0}".format(log_file), hide=True).stdout
    for message in log_msg:
        assert_that(log).does_not_contain(message)


def assert_errors_in_logs(remote_command_executor, log_files, expected_errors):
    # assert every expected error exists in at least one of the log files
    __tracebackhide__ = True

    log = ""
    for log_file in log_files:
        log += remote_command_executor.run_remote_command("sudo cat {0}".format(log_file), hide=True).stdout
    for message in expected_errors:
        assert_that(log).matches(message)


def assert_no_node_in_ec2(region, stack_name, instance_types=None):
    assert_that(get_compute_nodes_count(stack_name, region, instance_types)).is_equal_to(0)


def assert_scaling_worked(
    scheduler_commands,
    region,
    stack_name,
    scaledown_idletime,
    expected_max,
    expected_final,
    assert_ec2=True,
    assert_scheduler=True,
):
    jobs_execution_time = 1
    estimated_scaleup_time = 5
    max_scaledown_time = 10
    ec2_capacity_time_series, compute_nodes_time_series, _ = get_compute_nodes_allocation(
        scheduler_commands=scheduler_commands,
        region=region,
        stack_name=stack_name,
        max_monitoring_time=minutes(jobs_execution_time)
        + minutes(scaledown_idletime)
        + minutes(estimated_scaleup_time)
        + minutes(max_scaledown_time),
    )

    with soft_assertions():
        if assert_ec2:
            ec2_capacity_time_series_str = f"ec2_capacity_time_series={ec2_capacity_time_series}"
            assert_that(max(ec2_capacity_time_series)).described_as(ec2_capacity_time_series_str).is_equal_to(
                expected_max
            )
            assert_that(ec2_capacity_time_series[-1]).described_as(ec2_capacity_time_series_str).is_equal_to(
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


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))
def wait_for_num_instances_in_cluster(cluster_name, region, desired):
    assert_num_instances_in_cluster(cluster_name, region, desired)


def assert_num_instances_in_cluster(cluster_name, region, desired):
    assert_that(len(get_compute_nodes_instance_ids(cluster_name, region))).is_equal_to(desired)


def assert_num_instances_constant(cluster_name, region, desired, timeout=5):
    """Assert number of cluster instances if constant during a time period."""
    logging.info("Waiting for cluster daemon action")
    start_time = time.time()
    while time.time() < start_time + 60 * (timeout):
        assert_num_instances_in_cluster(cluster_name, region, desired)


def assert_head_node_is_running(region, cluster):
    logging.info("Asserting the head node is running")
    head_node_state = (
        boto3.client("ec2", region_name=region)
        .describe_instances(Filters=[{"Name": "ip-address", "Values": [cluster.head_node_ip]}])
        .get("Reservations")[0]
        .get("Instances")[0]
        .get("State")
        .get("Name")
    )
    assert_that(head_node_state).is_equal_to("running")


def assert_aws_identity_access_is_correct(cluster, users_allow_list, remote_command_executor=None):
    logging.info("Asserting access to AWS caller identity is correct")

    if not remote_command_executor:
        remote_command_executor = RemoteCommandExecutor(cluster)

    for user, allowed in users_allow_list.items():
        logging.info(f"Asserting access to AWS caller identity is {'allowed' if allowed else 'denied'} for user {user}")
        command = f"sudo -u {user} aws sts get-caller-identity"
        result = remote_command_executor.run_remote_command(command, raise_on_error=False)
        logging.info(f"user={user} and result.failed={result.failed}")
        logging.info(f"user={user} and result.stdout={result.stdout}")
        assert_that(result.failed).is_equal_to(not allowed)
