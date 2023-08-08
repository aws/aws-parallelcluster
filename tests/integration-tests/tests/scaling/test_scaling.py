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
from assertpy import assert_that, soft_assertions
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from retrying import RetryError, retry
from time_utils import minutes, seconds

from tests.common.assertions import assert_lines_in_logs, assert_no_errors_in_logs
from tests.common.scaling_common import get_compute_nodes_allocation, setup_ec2_launch_override_to_emulate_ice
from tests.schedulers.test_slurm import _assert_job_state


@pytest.mark.usefixtures("os", "instance")
def test_multiple_jobs_submission(
    scheduler,
    region,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
    test_custom_config,
):
    scaledown_idletime = 4
    # Test jobs should take at most 9 minutes to be executed.
    # These guarantees that the jobs are executed in parallel.
    max_jobs_execution_time = 9
    # Test using the max no of queues because the scheduler and node daemon operations take slight longer
    # with multiple queues
    no_of_queues = 50

    cluster_config = pcluster_config_reader(
        scaledown_idletime=scaledown_idletime,
        no_of_queues=no_of_queues,
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    # Check if the multiple partitions were created on Slurm
    partitions = scheduler_commands.get_partitions()
    assert_that(partitions).is_length(no_of_queues)

    scheduler = "slurm" if scheduler == "slurm_plugin" else scheduler

    logging.info("Executing sleep job to start a dynamic node")
    result = scheduler_commands.submit_command("sleep 1")
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    retry(wait_fixed=seconds(30), stop_max_delay=seconds(500))(_assert_job_state)(
        scheduler_commands, job_id, job_state="COMPLETED"
    )

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


def _submit_job_partial_capacity(scheduler_commands, remote_command_executor):
    remote_command_executor.clear_slurm_resume_log()

    result = scheduler_commands.submit_command(
        "srun hostname",
        partition="queue-jls-1-partial",
        host="queue-jls-1-partial-dy-compute-resource-0-1,queue-jls-1-partial-dy-ice-cr-multiple-1",
        other_options="--ntasks-per-node 1 --ntasks 2",
    )
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    try:
        scheduler_commands.wait_job_completed(job_id, timeout=2)
    except RetryError as e:
        # Timeout waiting for job to be completed
        logging.info("Exception while waiting for job to complete: %s", e)

    scheduler_commands.assert_job_state(job_id, expected_state="PENDING")
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(3))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/parallelcluster/slurm_resume.log"],
        [
            "Terminating unassigned launched instances.*queue-jls-1-partial.*compute-resource-0.*",
            "Failed to launch following nodes.*\\(x2\\) \\['queue-jls-1-partial-dy-ice-cr-multiple-1', "
            + "'queue-jls-1-partial-dy-compute-resource-0-1'\\]",
        ],
    )
    scheduler_commands.cancel_job(job_id)


def _submit_job_full_capacity(scheduler_commands, remote_command_executor):
    remote_command_executor.clear_slurm_resume_log()

    result = scheduler_commands.submit_command(
        "srun hostname",
        partition="queue-jls-1-full",
        host="queue-jls-1-full-dy-compute-resource-0-1,queue-jls-1-full-dy-compute-resource-1-1",
        other_options="--ntasks-per-node 1 --ntasks 2",
    )
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(3))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/parallelcluster/slurm_resume.log"],
        [
            "Successful launched all instances for nodes \\(x2\\) \\['queue-jls-1-full-dy-compute-resource-0-1', "
            + "'queue-jls-1-full-dy-compute-resource-1-1'\\]",
        ],
    )


@pytest.mark.usefixtures("os", "instance")
def test_job_level_scaling(
    pcluster_config_reader,
    clusters_factory,
    scheduler_commands_factory,
    test_datadir,
):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    setup_ec2_launch_override_to_emulate_ice(
        cluster,
        multi_instance_types_ice_cr="ice-cr-multiple",
    )

    _submit_job_partial_capacity(scheduler_commands, remote_command_executor)
    _submit_job_full_capacity(scheduler_commands, remote_command_executor)


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
