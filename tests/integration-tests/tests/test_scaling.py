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

import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from tests.common.compute_logs_common import wait_compute_log
from tests.common.scaling_common import (
    assert_instance_replaced_or_terminating,
    get_compute_nodes_allocation,
    get_desired_asg_capacity,
)
from tests.common.schedulers_common import get_scheduler_commands
from time_utils import minutes


@pytest.mark.skip_schedulers(["awsbatch"])
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

    logging.info("Monitoring asg capacity and compute nodes")
    asg_capacity_time_series, compute_nodes_time_series, timestamps = get_compute_nodes_allocation(
        scheduler_commands=scheduler_commands,
        region=region,
        stack_name=cluster.cfn_name,
        max_monitoring_time=minutes(max_jobs_execution_time) + minutes(scaledown_idletime) + minutes(5),
    )

    logging.info("Verifying test jobs completed successfully and in the expected time")
    _assert_test_jobs_completed(remote_command_executor, max_jobs_execution_time * 60)

    logging.info("Verifying auto-scaling worked correctly")
    _assert_scaling_works(
        asg_capacity_time_series=asg_capacity_time_series,
        compute_nodes_time_series=compute_nodes_time_series,
        expected_asg_capacity=(0, 3),
        expected_compute_nodes=(0, 3),
    )

    logging.info("Verifying no error in logs")
    _assert_no_errors_in_logs(remote_command_executor, ["/var/log/sqswatcher", "/var/log/jobwatcher"])


@pytest.mark.regions(["sa-east-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm", "sge"])
@pytest.mark.usefixtures("region", "os", "instance")
@pytest.mark.nodewatcher
def test_nodewatcher_terminates_failing_node(scheduler, region, pcluster_config_reader, clusters_factory, test_datadir):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    # submit a job that kills the slurm daemon so that the node enters a failing state
    scheduler_commands.submit_script(str(test_datadir / "{0}_kill_scheduler_job.sh".format(scheduler)))
    instance_id = wait_compute_log(remote_command_executor)

    _assert_compute_logs(remote_command_executor, instance_id)
    assert_instance_replaced_or_terminating(instance_id, region)
    # verify that desired capacity is still 1
    assert_that(get_desired_asg_capacity(region, cluster.cfn_name)).is_equal_to(1)


def _assert_compute_logs(remote_command_executor, instance_id):
    remote_command_executor.run_remote_command(
        "tar -xf /home/logs/compute/{0}.tar.gz --directory /tmp".format(instance_id)
    )
    remote_command_executor.run_remote_command("test -f /tmp/var/log/nodewatcher")
    messages_log = remote_command_executor.run_remote_command("cat /tmp/var/log/nodewatcher", hide=True).stdout
    assert_that(messages_log).contains("Node is marked as down by scheduler or not attached correctly. Terminating...")
    assert_that(messages_log).contains("Dumping logs to /home/logs/compute/{0}.tar.gz".format(instance_id))


def _assert_scaling_works(
    asg_capacity_time_series, compute_nodes_time_series, expected_asg_capacity, expected_compute_nodes
):
    """
    Verify that cluster scaling-up and scaling-down features work correctly.

    :param asg_capacity_time_series: list describing the fluctuations over time in the asg capacity
    :param compute_nodes_time_series: list describing the fluctuations over time in the compute nodes
    :param expected_asg_capacity: pair containing the expected asg capacity (min_asg_capacity, max_asg_capacity)
    :param expected_compute_nodes: pair containing the expected compute nodes (min_compute_nodes, max_compute_nodes)
    """
    assert_that(asg_capacity_time_series).described_as("asg_capacity_time_series cannot be empty").is_not_empty()
    assert_that(compute_nodes_time_series).described_as("compute_nodes_time_series cannot be empty").is_not_empty()

    expected_asg_capacity_min, expected_asg_capacity_max = expected_asg_capacity
    expected_compute_nodes_min, expected_compute_nodes_max = expected_compute_nodes
    actual_asg_capacity_max = max(asg_capacity_time_series)
    actual_asg_capacity_min = min(
        asg_capacity_time_series[asg_capacity_time_series.index(actual_asg_capacity_max) :]  # noqa E203
    )
    actual_compute_nodes_max = max(compute_nodes_time_series)
    actual_compute_nodes_min = min(
        compute_nodes_time_series[compute_nodes_time_series.index(actual_compute_nodes_max) :]  # noqa E203
    )
    assert_that(actual_asg_capacity_min).described_as(
        "actual asg min capacity does not match the expected one"
    ).is_equal_to(expected_asg_capacity_min)
    assert_that(actual_asg_capacity_max).described_as(
        "actual asg max capacity does not match the expected one"
    ).is_equal_to(expected_asg_capacity_max)
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


def _assert_no_errors_in_logs(remote_command_executor, log_files):
    __tracebackhide__ = True
    for log_file in log_files:
        log = remote_command_executor.run_remote_command("cat {0}".format(log_file), hide=True).stdout
        for error_level in ["CRITICAL", "ERROR"]:
            assert_that(log).does_not_contain(error_level)
