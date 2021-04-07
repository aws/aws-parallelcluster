# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import logging
from os import environ

import pytest
from assertpy import assert_that, soft_assertions
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from utils import get_compute_nodes_instance_ids, get_instance_ids_compute_hostnames_conversion_dict

from tests.common.assertions import assert_instance_replaced_or_terminating, assert_no_errors_in_logs
from tests.common.hit_common import wait_for_num_nodes_in_scheduler
from tests.common.scaling_common import (
    assert_maintain_initial_size_behavior,
    get_compute_nodes_allocation,
    get_desired_asg_capacity,
)
from tests.common.schedulers_common import get_scheduler_commands


@pytest.mark.skip_schedulers(["awsbatch"])
@pytest.mark.instances(["c4.xlarge", "c5.xlarge"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_multiple_jobs_submission(scheduler, region, pcluster_config_reader, clusters_factory, test_datadir):
    scaledown_idletime = 4
    # Test jobs should take at most 9 minutes to be executed.
    # These guarantees that the jobs are executed in parallel.
    max_jobs_execution_time = 9

    cluster_config = pcluster_config_reader(scaledown_idletime=scaledown_idletime)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    logging.info("Executing test jobs on cluster")
    remote_command_executor.run_remote_script(test_datadir / "cluster-check.sh", args=["submit", scheduler])

    logging.info("Monitoring ec2 capacity and compute nodes")
    ec2_capacity_time_series, compute_nodes_time_series, timestamps = get_compute_nodes_allocation(
        scheduler_commands=scheduler_commands,
        region=region,
        stack_name=cluster.cfn_name,
        max_monitoring_time=minutes(max_jobs_execution_time) + minutes(scaledown_idletime) + minutes(5),
    )

    logging.info("Verifying test jobs completed successfully and in the expected time")
    _assert_test_jobs_completed(remote_command_executor, max_jobs_execution_time * 60)

    logging.info("Verifying auto-scaling worked correctly")
    _assert_scaling_works(
        ec2_capacity_time_series=ec2_capacity_time_series,
        compute_nodes_time_series=compute_nodes_time_series,
        expected_ec2_capacity=(0, 3),
        expected_compute_nodes=(0, 3),
    )

    logging.info("Verifying no error in logs")
    assert_no_errors_in_logs(remote_command_executor, scheduler)


@pytest.mark.regions(["sa-east-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["sge", "torque"])
@pytest.mark.oss(["alinux2", "centos7", "ubuntu1804"])
@pytest.mark.usefixtures("region", "instance", "os")
@pytest.mark.nodewatcher
def test_nodewatcher_terminates_failing_node(scheduler, region, pcluster_config_reader, clusters_factory, test_datadir):
    # slurm test use more nodes because of internal request to test in multi-node settings
    initial_queue_size = 1
    maintain_initial_size = "true"
    environ["AWS_DEFAULT_REGION"] = region
    cluster_config = pcluster_config_reader(
        initial_queue_size=initial_queue_size, maintain_initial_size=maintain_initial_size
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    compute_nodes = scheduler_commands.get_compute_nodes()
    instance_ids = get_compute_nodes_instance_ids(cluster.cfn_name, region)
    hostname_to_instance_id = get_instance_ids_compute_hostnames_conversion_dict(instance_ids, id_to_hostname=False)

    logging.info("Testing that nodewatcher will terminate a node in failing state")
    # submit a job to run on all nodes
    scheduler_commands.submit_command("sleep infinity", nodes=initial_queue_size)
    expected_num_nodes_killed = 1
    # simulate unexpected hardware failure by killing first x nodes
    nodes_to_remove = compute_nodes[:expected_num_nodes_killed]
    for node in nodes_to_remove:
        remote_command_executor.run_remote_script(
            str(test_datadir / "{0}_kill_scheduler_job.sh".format(scheduler)), args=[node]
        )

    # assert failing nodes are terminated according to ASG
    _assert_failing_nodes_terminated(nodes_to_remove, hostname_to_instance_id, region)
    nodes_to_retain = [compute for compute in compute_nodes if compute not in nodes_to_remove]
    # verify that desired capacity is still the initial_queue_size
    assert_that(get_desired_asg_capacity(region, cluster.cfn_name)).is_equal_to(initial_queue_size)
    # assert failing nodes are removed from scheduler config
    _assert_nodes_removed_and_replaced_in_scheduler(
        scheduler_commands, nodes_to_remove, nodes_to_retain, desired_capacity=initial_queue_size
    )

    assert_no_errors_in_logs(remote_command_executor, scheduler)
    assert_maintain_initial_size_behavior(cluster.cfn_name, region, maintain_initial_size, initial_queue_size)


@retry(wait_fixed=seconds(30), stop_max_delay=minutes(15))
def _assert_failing_nodes_terminated(nodes_to_remove, hostname_to_instance_id, region):
    for node in nodes_to_remove:
        assert_instance_replaced_or_terminating(hostname_to_instance_id.get(node), region)


def _assert_nodes_removed_and_replaced_in_scheduler(
    scheduler_commands, nodes_to_remove, nodes_to_retain, desired_capacity
):
    """
    Assert that nodes are removed from scheduler and replaced so that number of nodes in scheduler equals to desired.
    Returns list of new nodenames in scheduler.
    """
    _assert_nodes_removed_from_scheduler(scheduler_commands, nodes_to_remove)
    wait_for_num_nodes_in_scheduler(scheduler_commands, desired_capacity)
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


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(10))
def _assert_nodes_removed_from_scheduler(scheduler_commands, nodes):
    assert_that(scheduler_commands.get_compute_nodes()).does_not_contain(*nodes)


def _assert_scaling_works(
    ec2_capacity_time_series, compute_nodes_time_series, expected_ec2_capacity, expected_compute_nodes
):
    """
    Verify that cluster scaling-up and scaling-down features work correctly.

    :param ec2_capacity_time_series: list describing the fluctuations over time in the ec2 capacity
    :param compute_nodes_time_series: list describing the fluctuations over time in the compute nodes
    :param expected_ec2_capacity: pair containing the expected ec2 capacity (min_ec2_capacity, max_ec2_capacity)
    :param expected_compute_nodes: pair containing the expected compute nodes (min_compute_nodes, max_compute_nodes)
    """
    assert_that(ec2_capacity_time_series).described_as("ec2_capacity_time_series cannot be empty").is_not_empty()
    assert_that(compute_nodes_time_series).described_as("compute_nodes_time_series cannot be empty").is_not_empty()

    expected_ec2_capacity_min, expected_ec2_capacity_max = expected_ec2_capacity
    expected_compute_nodes_min, expected_compute_nodes_max = expected_compute_nodes
    actual_ec2_capacity_max = max(ec2_capacity_time_series)
    actual_ec2_capacity_min = min(
        ec2_capacity_time_series[ec2_capacity_time_series.index(actual_ec2_capacity_max) :]  # noqa E203
    )
    actual_compute_nodes_max = max(compute_nodes_time_series)
    actual_compute_nodes_min = min(
        compute_nodes_time_series[compute_nodes_time_series.index(actual_compute_nodes_max) :]  # noqa E203
    )
    with soft_assertions():
        assert_that(actual_ec2_capacity_min).described_as(
            "actual ec2 min capacity does not match the expected one"
        ).is_equal_to(expected_ec2_capacity_min)
        assert_that(actual_ec2_capacity_max).described_as(
            "actual ec2 max capacity does not match the expected one"
        ).is_equal_to(expected_ec2_capacity_max)
        assert_that(actual_compute_nodes_min).described_as(
            "actual number of min compute nodes does not match the expected one"
        ).is_equal_to(expected_compute_nodes_min)
        assert_that(actual_compute_nodes_max).described_as(
            "actual number of max compute nodes does not match the expected one"
        ).is_equal_to(expected_compute_nodes_max)


def _assert_test_jobs_completed(remote_command_executor, max_jobs_exec_time):
    """
    Verify that test jobs started by cluster-check.sh script were successfully executed and in a timely manner.

    In order to do this the function checks that some files (jobN.done), which denote the fact
    that a job has been correctly executed, are present in the shared cluster file-system.
    Additionally, the function uses the timestamp contained in those files, that indicates
    the end time of each job, to verify that all jobs were executed within the max expected time.
    """
    try:
        remote_command_executor.run_remote_command("test -f job1.done -a -f job2.done -a -f job3.done")
    except RemoteCommandExecutionError:
        raise AssertionError("Not all test jobs completed in the max allowed time")

    jobs_start_time = int(remote_command_executor.run_remote_command("cat jobs_start_time").stdout.split()[-1])
    jobs_completion_time = int(
        remote_command_executor.run_remote_command(
            "cat job1.done job2.done job3.done | sort -n | tail -1"
        ).stdout.split()[-1]
    )
    jobs_execution_time = jobs_completion_time - jobs_start_time
    logging.info("Test jobs completed in %d seconds", jobs_execution_time)
    assert_that(jobs_execution_time).is_less_than(max_jobs_exec_time)
