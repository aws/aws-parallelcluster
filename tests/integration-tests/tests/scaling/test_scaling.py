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
import os
from typing import Union

import boto3
import pytest
from assertpy import assert_that, soft_assertions
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from retrying import RetryError, retry
from time_utils import minutes, seconds
from utils import render_jinja_template, retrieve_resource_group_arn_from_resource

from tests.common.assertions import assert_lines_in_logs, assert_no_errors_in_logs
from tests.common.scaling_common import get_compute_nodes_allocation, setup_ec2_launch_override_to_emulate_ice
from tests.common.schedulers_common import SlurmCommands
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


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_scaling_special_cases(
    region, pcluster_config_reader, clusters_factory, scaling_odcr_stack, scheduler_commands_factory, test_datadir
):
    full_cluster_size = 1600  # no of nodes after scaling the cluster up
    downscaled_cluster_size = 1570  # no of nodes after scaling down the cluster
    max_scaling_time = 7  # Chosen based on running the test multiple times

    odcr_stack = scaling_odcr_stack(full_cluster_size)
    resource_group_arn = retrieve_resource_group_arn_from_resource(
        odcr_stack.cfn_resources["integTestsScalingOdcrGroup"]
    )
    cluster_config = pcluster_config_reader(
        target_capacity_reservation_arn=resource_group_arn, full_cluster_size=full_cluster_size
    )
    cluster = clusters_factory(cluster_config)

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    upscale_cluster_config = pcluster_config_reader(
        config_file="pcluster-upscale.config.yaml",
        target_capacity_reservation_arn=resource_group_arn,
        full_cluster_size=full_cluster_size,
    )

    # Scale up cluster
    _assert_cluster_update_scaling(
        cluster,
        scheduler_commands,
        region,
        cluster_config=str(upscale_cluster_config),
        expected_ec2_capacity=(0, full_cluster_size),
        expected_compute_nodes=(0, full_cluster_size),
        max_monitoring_time=minutes(max_scaling_time),
        is_scale_down=False,
    )
    _assert_compute_nodes_in_cluster_are_from_odcr(cluster, region, resource_group_arn)
    _assert_simple_job_succeeds(scheduler_commands, full_cluster_size, partition="q1")

    # Apply custom partitions
    output_file_path = render_jinja_template(
        template_file_path=os.path.join(str(test_datadir), "include_custom_partition_large.sh.jinja"),
        partition="q1",
        cr="cr1",
    )
    remote_command_executor.run_remote_script(output_file_path, run_as_root=True)
    _assert_simple_job_succeeds(scheduler_commands, full_cluster_size, partition="q1")

    # Scale down cluster
    downscale_cluster_config = pcluster_config_reader(
        config_file="pcluster-downscale.config.yaml",
        target_capacity_reservation_arn=resource_group_arn,
        downscaled_cluster_size=downscaled_cluster_size,
        full_cluster_size=full_cluster_size,
    )
    _assert_cluster_update_scaling(
        cluster,
        scheduler_commands,
        region,
        cluster_config=str(downscale_cluster_config),
        expected_ec2_capacity=(downscaled_cluster_size, full_cluster_size),
        expected_compute_nodes=(downscaled_cluster_size, full_cluster_size),
        max_monitoring_time=minutes(max_scaling_time),
        is_scale_down=True,
    )
    _assert_simple_job_succeeds(scheduler_commands, downscaled_cluster_size, partition="q1")

    # Scale up the cluster
    _assert_cluster_update_scaling(
        cluster,
        scheduler_commands,
        region,
        cluster_config=str(upscale_cluster_config),
        expected_ec2_capacity=(downscaled_cluster_size, full_cluster_size),
        expected_compute_nodes=(downscaled_cluster_size, full_cluster_size),
        max_monitoring_time=minutes(max_scaling_time),
        is_scale_down=False,
    )
    _assert_compute_nodes_in_cluster_are_from_odcr(cluster, region, resource_group_arn)
    _assert_simple_job_succeeds(scheduler_commands, full_cluster_size, partition="q1")


def _assert_simple_job_succeeds(
    scheduler_commands: SlurmCommands, no_of_nodes: int, partition: Union[str, None] = None
):
    job_command_args = {
        "command": "srun sleep 10",
        "partition": partition,
        "nodes": no_of_nodes,
        "slots": no_of_nodes,
    }
    result = scheduler_commands.submit_command(**job_command_args)
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)


def _assert_compute_nodes_in_cluster_are_from_odcr(cluster, region, odcr_resource_group_arn):
    ec2_client = boto3.client("ec2", region_name=region)
    describe_instances_paginator = ec2_client.get_paginator("describe_instances")
    describe_instances_iterator = describe_instances_paginator.paginate(
        Filters=[
            {"Name": "tag:parallelcluster:cluster-name", "Values": [cluster.name]},
            {"Name": "tag:parallelcluster:node-type", "Values": ["Compute"]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )
    instances_outside_odcr_iter = describe_instances_iterator.search(
        "Reservations[*].Instances[?CapacityReservationId==null && "
        + "CapacityReservationSpecification.CapacityReservationTarget.CapacityReservationResourceGroupArn=="
        + f"`{odcr_resource_group_arn}`"
        + "].InstanceId[]"
    )
    instances_outside_odcr = [instance for instance in instances_outside_odcr_iter]
    logging.info(f"Instances launched outside ODCR {odcr_resource_group_arn}: {instances_outside_odcr}")
    assert_that(instances_outside_odcr).is_length(0)


def _assert_cluster_update_scaling(
    cluster,
    scheduler_commands,
    region,
    cluster_config,
    expected_ec2_capacity,
    expected_compute_nodes,
    max_monitoring_time,
    is_scale_down=True,
):
    cluster.update(str(cluster_config), force_update="true", wait=False, raise_on_error=False)

    logging.info("Monitoring ec2 capacity and compute nodes")
    ec2_capacity_time_series, compute_nodes_time_series, timestamps = get_compute_nodes_allocation(
        scheduler_commands=scheduler_commands,
        region=region,
        stack_name=cluster.cfn_name,
        max_monitoring_time=max_monitoring_time,
    )

    logging.info(
        f"Verifying scale up worked with EC2 Instances: {ec2_capacity_time_series} and "
        f"Compute nodes: {ec2_capacity_time_series}."
    )
    if is_scale_down:
        # Last value in scaling time series should be the min capacity expected
        assert_that(ec2_capacity_time_series[-1]).is_equal_to(expected_ec2_capacity[0])
        assert_that(compute_nodes_time_series[-1]).is_equal_to(expected_compute_nodes[0])
    else:
        # Last value in scaling time series should be the max capacity expected
        assert_that(ec2_capacity_time_series[-1]).is_equal_to(expected_ec2_capacity[1])
        assert_that(compute_nodes_time_series[-1]).is_equal_to(expected_compute_nodes[1])
    _assert_scaling_works(
        ec2_capacity_time_series=ec2_capacity_time_series,
        compute_nodes_time_series=compute_nodes_time_series,
        expected_ec2_capacity=expected_ec2_capacity,
        expected_compute_nodes=expected_compute_nodes,
        min_for_scaledown=is_scale_down,
    )


def _assert_scaling_works(
    ec2_capacity_time_series,
    compute_nodes_time_series,
    expected_ec2_capacity,
    expected_compute_nodes,
    min_for_scaledown=True,  #
):
    """
    Verify that cluster scaling-up and scaling-down features work correctly.

    :param ec2_capacity_time_series: list describing the fluctuations over time in the ec2 capacity
    :param compute_nodes_time_series: list describing the fluctuations over time in the compute nodes
    :param expected_ec2_capacity: pair containing the expected ec2 capacity (min_ec2_capacity, max_ec2_capacity)
    :param expected_compute_nodes: pair containing the expected compute nodes (min_compute_nodes, max_compute_nodes)
    :param consider values captured only after reaching maximum capacity when evaluating the minimum
    """
    assert_that(ec2_capacity_time_series).described_as("ec2_capacity_time_series cannot be empty").is_not_empty()
    assert_that(compute_nodes_time_series).described_as("compute_nodes_time_series cannot be empty").is_not_empty()

    expected_ec2_capacity_min, expected_ec2_capacity_max = expected_ec2_capacity
    expected_compute_nodes_min, expected_compute_nodes_max = expected_compute_nodes
    actual_ec2_capacity_max = max(ec2_capacity_time_series)
    actual_ec2_capacity_min = (
        min(ec2_capacity_time_series[ec2_capacity_time_series.index(actual_ec2_capacity_max) :])  # noqa E203
        if min_for_scaledown
        else min(ec2_capacity_time_series)
    )
    actual_compute_nodes_max = max(compute_nodes_time_series)
    actual_compute_nodes_min = (
        min(compute_nodes_time_series[compute_nodes_time_series.index(actual_compute_nodes_max) :])  # noqa E203
        if min_for_scaledown
        else min(ec2_capacity_time_series)
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
