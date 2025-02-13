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
from itertools import chain
from typing import Union

import boto3
import pytest
from assertpy import assert_that, soft_assertions
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from utils import render_jinja_template, retrieve_resource_group_arn_from_resource

from tests.common.assertions import assert_no_errors_in_logs, submit_job_and_assert_logs
from tests.common.scaling_common import get_compute_nodes_allocation, setup_ec2_launch_override_to_emulate_ice
from tests.common.schedulers_common import SlurmCommands
from tests.schedulers.test_slurm import _assert_job_state


@pytest.mark.usefixtures("os")
@pytest.mark.parametrize(
    "scaling_strategy, scaling_behaviour_by_capacity",
    [
        (
            "all-or-nothing",
            {
                "partial_capacity": {
                    "job": {
                        "command": "srun hostname",
                        "partition": "queue-jls-1-partial",
                        "host": "queue-jls-1-partial-dy-compute-resource-0-1,queue-jls-1-partial-dy-ice-cr-multiple-1",
                        "other_options": "--ntasks-per-node 1 --ntasks 2",
                    },
                    "log_assertions": {
                        "launch": [
                            ".*Launching all-or-nothing .*\\['queue-.+-partial-.+-resource-0-1'\\]",
                            ".*Launching all-or-nothing .*\\['queue-.+-partial-dy-ice-cr-multiple-1'\\]",
                        ],
                        "node_assignment": [
                            ".*Assigning nodes with all-or-nothing strategy.*",
                        ],
                        "post_scaling": [
                            "Terminating unassigned launched instances.*queue-jls-1-partial.*compute-resource-0.*",
                            "Failed to launch following nodes.*\\(x2\\) \\["
                            + "('queue-.+-partial-dy-ice-cr-multiple-1', 'queue-.+-partial-dy-.+-resource-0-1'|"
                            + "'queue-.+-partial-dy-.+-resource-0-1', 'queue-.+-partial-dy-ice-cr-multiple-1')\\]",
                        ],
                    },
                },
                "full_capacity": {
                    "job": {
                        "command": "srun hostname",
                        "partition": "queue-jls-1-full",
                        "host": "queue-jls-1-full-dy-compute-resource-0-1,queue-jls-1-full-dy-compute-resource-1-1",
                        "other_options": "--ntasks-per-node 1 --ntasks 2",
                    },
                    "log_assertions": {
                        "launch": [
                            ".*Launching all-or-nothing .*\\['queue-.+-full-dy-compute-resource-0-1'\\]",
                            ".*Launching all-or-nothing .*\\['queue-.+-full-dy-compute-resource-1-1'\\]",
                        ],
                        "node_assignment": [
                            ".*Assigning nodes with all-or-nothing strategy.*",
                        ],
                        "post_scaling": [
                            "Successful launched all instances for nodes \\(x2\\) \\["
                            + "('queue-.+-full-.+-resource-0-1', 'queue-.+-full-.+-resource-1-1'|"
                            + "'queue-.+-full-.+-resource-1-1', 'queue-.+-full-.+-resource-0-1')\\]"
                        ],
                    },
                },
            },
        ),
        (
            "best-effort",
            {
                "partial_capacity": {
                    "job": {
                        "command": "srun hostname",
                        "partition": "queue-jls-1-partial",
                        "host": "queue-jls-1-partial-dy-compute-resource-0-1,queue-jls-1-partial-dy-ice-cr-multiple-1",
                        "other_options": "--ntasks-per-node 1 --ntasks 2",
                    },
                    "log_assertions": {
                        "launch": [
                            ".*Launching best-effort .*\\['queue-.+-partial-.+-resource-0-1'\\]",
                            ".*Launching best-effort .*\\['queue-.+-partial-dy-ice-cr-multiple-1'\\]",
                        ],
                        "node_assignment": [
                            ".*Assigning nodes with best-effort strategy.*",
                        ],
                        "post_scaling": [
                            "Nodes are now configured with instances \\(x1\\).*queue-.*-partial.*compute-resource-0-1",
                            "Successful launched partial instances for nodes.*queue-.*-partial.*compute-resource-0-1",
                            "Failed to launch following nodes.*\\(x1\\) \\['queue-.+-partial-dy-ice-cr-multiple-1'\\]",
                        ],
                    },
                },
                "full_capacity": {
                    "job": {
                        "command": "srun hostname",
                        "partition": "queue-jls-1-full",
                        "host": "queue-jls-1-full-dy-compute-resource-0-1,queue-jls-1-full-dy-compute-resource-1-1",
                        "other_options": "--ntasks-per-node 1 --ntasks 2",
                    },
                    "log_assertions": {
                        "launch": [
                            ".*Launching best-effort .*\\['queue-.+-full-dy-compute-resource-0-1'\\]",
                            ".*Launching best-effort .*\\['queue-.+-full-dy-compute-resource-1-1'\\]",
                        ],
                        "node_assignment": [
                            ".*Assigning nodes with best-effort strategy.*",
                        ],
                        "post_scaling": [
                            "Successful launched all instances for nodes \\(x2\\) \\["
                            + "('queue-.+-full-.+-resource-0-1', 'queue-.+-full-.+-resource-1-1'|"
                            + "'queue-.+-full-.+-resource-1-1', 'queue-.+-full-.+-resource-0-1')\\]"
                        ],
                    },
                },
            },
        ),
        (
            "greedy-all-or-nothing",
            {
                "partial_capacity": {
                    "job": {
                        "command": "srun hostname",
                        "partition": "queue-jls-1-partial",
                        "host": "queue-jls-1-partial-dy-compute-resource-0-1,queue-jls-1-partial-dy-ice-cr-multiple-1",
                        "other_options": "--ntasks-per-node 1 --ntasks 2",
                    },
                    "log_assertions": {
                        "launch": [
                            ".*Launching best-effort .*\\['queue-.+-partial-.+-resource-0-1'\\]",
                            ".*Launching best-effort .*\\['queue-.+-partial-dy-ice-cr-multiple-1'\\]",
                        ],
                        "node_assignment": [
                            ".*Assigning nodes with all-or-nothing strategy.*",
                        ],
                        "post_scaling": [
                            "Terminating unassigned launched instances.*queue-jls-1-partial.*compute-resource-0.*",
                            "Failed to launch following nodes.*\\(x2\\) \\["
                            + "('queue-.+-partial-dy-ice-cr-multiple-1', 'queue-.+-partial-dy-.+-resource-0-1'|"
                            + "'queue-.+-partial-dy-.+-resource-0-1', 'queue-.+-partial-dy-ice-cr-multiple-1')\\]",
                        ],
                    },
                },
                "full_capacity": {
                    "job": {
                        "command": "srun hostname",
                        "partition": "queue-jls-1-full",
                        "host": "queue-jls-1-full-dy-compute-resource-0-1,queue-jls-1-full-dy-compute-resource-1-1",
                        "other_options": "--ntasks-per-node 1 --ntasks 2",
                    },
                    "log_assertions": {
                        "launch": [
                            ".*Launching best-effort .*\\['queue-.+-full-dy-compute-resource-0-1'\\]",
                            ".*Launching best-effort .*\\['queue-.+-full-dy-compute-resource-1-1'\\]",
                        ],
                        "node_assignment": [
                            ".*Assigning nodes with all-or-nothing strategy.*",
                        ],
                        "post_scaling": [
                            "Successful launched all instances for nodes \\(x2\\) \\["
                            + "('queue-.+-full-.+-resource-0-1', 'queue-.+-full-.+-resource-1-1'|"
                            + "'queue-.+-full-.+-resource-1-1', 'queue-.+-full-.+-resource-0-1')\\]"
                        ],
                    },
                },
            },
        ),
    ],
)
def test_job_level_scaling(
    region,
    instance,
    pcluster_config_reader,
    clusters_factory,
    scheduler_commands_factory,
    test_datadir,
    scaling_strategy,
    scaling_behaviour_by_capacity,
):
    scaledown_idletime = 4
    # Test using the max no of compute resources because the scheduler and node daemon operations take slight longer
    # with multiple compute resources. (2 queues with 2 compute resources + 46 queues with 1 compute resource)
    no_of_queues = 46

    cluster_config = pcluster_config_reader(
        scaledown_idletime=scaledown_idletime,
        scaling_strategy=scaling_strategy,
        no_of_queues=no_of_queues,
        head_node_instance_type=instance.replace(".xlarge", ".2xlarge"),
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    _test_multiple_jobs(cluster, remote_command_executor, test_datadir, region, scheduler_commands, scaledown_idletime)

    setup_ec2_launch_override_to_emulate_ice(
        cluster,
        multi_instance_types_ice_cr="ice-cr-multiple",
    )

    # Assert scaling behaviour when partial capacity for a job is available
    submit_job_and_assert_logs(
        scheduler_commands=scheduler_commands,
        remote_command_executor=remote_command_executor,
        job_kwargs=scaling_behaviour_by_capacity["partial_capacity"]["job"],
        log_files=["/var/log/parallelcluster/slurm_resume.log"],
        log_assertions=chain.from_iterable(
            scaling_behaviour_by_capacity["partial_capacity"]["log_assertions"].values()
        ),
        wait_for_job_completion=False,
        clear_logs_before_job_submission=True,
    )
    # Assert scaling behaviour when all capacity is available
    submit_job_and_assert_logs(
        scheduler_commands=scheduler_commands,
        remote_command_executor=remote_command_executor,
        job_kwargs=scaling_behaviour_by_capacity["full_capacity"]["job"],
        log_files=["/var/log/parallelcluster/slurm_resume.log"],
        log_assertions=chain.from_iterable(scaling_behaviour_by_capacity["full_capacity"]["log_assertions"].values()),
        wait_for_job_completion=True,
        clear_logs_before_job_submission=True,
    )


def _test_multiple_jobs(cluster, remote_command_executor, test_datadir, region, scheduler_commands, scaledown_idletime):
    # Test jobs should take at most 9 minutes to be executed.
    # These guarantees that the jobs are executed in parallel.
    max_jobs_execution_time = 9

    # Check if the multiple partitions were created on Slurm
    partitions = scheduler_commands.get_partitions()
    assert_that(partitions).is_length(48)

    logging.info("Executing sleep job to start a dynamic node")
    result = scheduler_commands.submit_command("sleep 1")
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    retry(wait_fixed=seconds(30), stop_max_delay=seconds(500))(_assert_job_state)(
        scheduler_commands, job_id, job_state="COMPLETED"
    )

    logging.info("Executing multiple test jobs on cluster")
    remote_command_executor.run_remote_script(test_datadir / "cluster-check.sh", args=["submit", "slurm"])

    logging.info("Monitoring ec2 capacity and compute nodes")
    monitoring_buffer_minutes = 10 if "us-iso" in region else 5
    ec2_capacity_time_series, compute_nodes_time_series, timestamps = get_compute_nodes_allocation(
        scheduler_commands=scheduler_commands,
        region=region,
        stack_name=cluster.cfn_name,
        max_monitoring_time=minutes(max_jobs_execution_time)
        + minutes(scaledown_idletime)
        + minutes(monitoring_buffer_minutes),
    )

    logging.info("Verifying test jobs completed successfully and in the expected time")
    _assert_test_jobs_completed(remote_command_executor, max_jobs_execution_time * 60)

    logging.info("Verifying auto-scaling worked correctly")
    _assert_scaling_results_match_expected_range(
        ec2_capacity_time_series=ec2_capacity_time_series,
        compute_nodes_time_series=compute_nodes_time_series,
        expected_ec2_capacity=(0, 3),
        expected_compute_nodes=(0, 3),
    )

    logging.info("Verifying no error in logs")
    assert_no_errors_in_logs(remote_command_executor, "slurm")


@pytest.mark.usefixtures("os", "instance", "scheduler")
@pytest.mark.parametrize("shared_headnode_storage_type", ["Efs", "Ebs"])
def test_scaling_special_cases(
    region,
    scheduler,
    pcluster_config_reader,
    clusters_factory,
    scaling_odcr_stack,
    scheduler_commands_factory,
    test_datadir,
    shared_headnode_storage_type,
):
    """
    This test aims to verify the following:
    1. When scaling up to 1000+ static nodes launched from an ODCR there should be with almost no bootstrap errors and
    scale up should complete within a specific amount of time (`max_scaling_time`) with no over-scaling
        - We however apply a threshold/allowance such that we permit at most 2% of nodes to still be pending
        successful bootstrap (this is based on currently known limitations where some instances may fail bootstrap and
        need to be relaunched by the scheduler)
    2. For a cluster with custom partitions, scaling operations should NOT be impacted due to the mapping of some
    nodes to both a PCluster managed partition and a custom partition. We will confirm that there is no over-scaling.

    To test the above scenarios, the following special cases have been applied to the cluster:
    - Compute nodes targeting an ODCR Reservation Group. `1600` nodes have been selected based on manual tests where
     some nodes were seen to have bootstrap errors
    - A custom partitions configuration has been applied with the partitions pointing to nodes ranging from 1 to 1565
    in various combinations
    """
    full_cluster_size = 1600  # no of nodes after scaling the cluster up
    downscaled_cluster_size = 1570  # no of nodes after scaling down the cluster,
    # chosen because the custom partitions point up to node 1565
    # We want to avoid scaling down to a point where some custom partitions end up pointing to nodes
    # that no longer exist - This would result in slurmctld restart failing after scale down as expected but this
    # is not in scope for this test
    max_scaling_time = 7  # Chosen based on running the test multiple times

    odcr_stack = scaling_odcr_stack(full_cluster_size)
    resource_group_arn = retrieve_resource_group_arn_from_resource(
        odcr_stack.cfn_resources["integTestsScalingOdcrGroup"]
    )

    # Using different launch APIs here to reuse the same ODCR stack
    for launch_api in ["run_instances", "create_fleet"]:
        cluster_config = pcluster_config_reader(
            target_capacity_reservation_arn=resource_group_arn,
            full_cluster_size=full_cluster_size,
            launch_api=launch_api,
            shared_headnode_storage_type=shared_headnode_storage_type,
        )
        cluster = clusters_factory(cluster_config)

        remote_command_executor = RemoteCommandExecutor(cluster)
        scheduler_commands = scheduler_commands_factory(remote_command_executor)

        upscale_cluster_config = pcluster_config_reader(
            config_file="pcluster-upscale.config.yaml",
            target_capacity_reservation_arn=resource_group_arn,
            full_cluster_size=full_cluster_size,
            launch_api=launch_api,
            shared_headnode_storage_type=shared_headnode_storage_type,
        )

        # Scale up cluster
        _assert_cluster_update_scaling(
            cluster,
            remote_command_executor,
            scheduler_commands,
            region,
            scheduler,
            updated_cluster_config=str(upscale_cluster_config),
            expected_ec2_capacity=(0, full_cluster_size),
            expected_compute_nodes=(0, full_cluster_size),
            max_monitoring_time=minutes(max_scaling_time),
            is_scale_down=False,
            threshold=0.998,
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
            launch_api=launch_api,
            shared_headnode_storage_type=shared_headnode_storage_type,
        )
        _assert_cluster_update_scaling(
            cluster,
            remote_command_executor,
            scheduler_commands,
            region,
            scheduler,
            updated_cluster_config=str(downscale_cluster_config),
            expected_ec2_capacity=(downscaled_cluster_size, full_cluster_size),
            expected_compute_nodes=(downscaled_cluster_size, full_cluster_size),
            max_monitoring_time=minutes(max_scaling_time),
            is_scale_down=True,
        )
        _assert_simple_job_succeeds(scheduler_commands, downscaled_cluster_size, partition="q1")

        # Scale up the cluster
        _assert_cluster_update_scaling(
            cluster,
            remote_command_executor,
            scheduler_commands,
            region,
            scheduler,
            updated_cluster_config=str(upscale_cluster_config),
            expected_ec2_capacity=(downscaled_cluster_size, full_cluster_size),
            expected_compute_nodes=(downscaled_cluster_size, full_cluster_size),
            max_monitoring_time=minutes(max_scaling_time),
            is_scale_down=False,
        )
        _assert_compute_nodes_in_cluster_are_from_odcr(cluster, region, resource_group_arn)
        _assert_simple_job_succeeds(scheduler_commands, full_cluster_size, partition="q1")

        cluster.delete()


def _assert_simple_job_succeeds(slurm_commands: SlurmCommands, no_of_nodes: int, partition: Union[str, None] = None):
    job_command_args = {
        "command": "srun sleep 10",
        "partition": partition,
        "nodes": no_of_nodes,
        "slots": no_of_nodes,
    }
    slurm_commands.submit_command_and_assert_job_succeeded(job_command_args)


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


def _monitor_cluster_update(cluster, updated_cluster_config, scheduler_commands, region, max_monitoring_time):
    cluster.update(str(updated_cluster_config), force_update="true", wait=False, raise_on_error=False)

    logging.info("Monitoring ec2 capacity and compute nodes")
    ec2_capacity_time_series, compute_nodes_time_series, timestamps = get_compute_nodes_allocation(
        scheduler_commands=scheduler_commands,
        region=region,
        stack_name=cluster.cfn_name,
        max_monitoring_time=max_monitoring_time,
    )

    # Wait for cluster update to complete (in case ot wasn't able to scale up within the monitoring time
    cloud_formation = boto3.client("cloudformation")
    waiter = cloud_formation.get_waiter("stack_update_complete")
    waiter.wait(StackName=cluster.name)

    return ec2_capacity_time_series, compute_nodes_time_series, timestamps


def _check_scaling_results(
    ec2_capacity_time_series,
    compute_nodes_time_series,
    expected_ec2_capacity,
    expected_compute_nodes,
    max_monitoring_time,
    threshold,
    is_scale_down,
):
    logging.info(
        f"Verifying scaling worked with EC2 Instances: {ec2_capacity_time_series} and "
        f"Compute nodes: {compute_nodes_time_series}."
    )
    if is_scale_down:
        # Last value in scaling time series should be the min capacity expected
        assert_that(ec2_capacity_time_series[-1]).is_equal_to(expected_ec2_capacity[0])
        assert_that(compute_nodes_time_series[-1]).is_equal_to(expected_compute_nodes[0])
    else:
        # Last value in scaling time series should be the max capacity expected
        assert_that(ec2_capacity_time_series[-1]).is_greater_than_or_equal_to(int(expected_ec2_capacity[1] * threshold))
        assert_that(compute_nodes_time_series[-1]).is_greater_than_or_equal_to(
            int(expected_compute_nodes[1] * threshold)
        )
        if ec2_capacity_time_series[-1] < expected_ec2_capacity[1]:
            logging.warning(
                f"Cluster was unable to scale up to {expected_ec2_capacity[1]} within {max_monitoring_time} seconds"
                + "Review the clustermgtd logs for details."
            )
    _assert_scaling_results_match_expected_range(
        ec2_capacity_time_series=ec2_capacity_time_series,
        compute_nodes_time_series=compute_nodes_time_series,
        expected_ec2_capacity=expected_ec2_capacity,
        expected_compute_nodes=expected_compute_nodes,
        min_for_scaledown=is_scale_down,
        threshold=threshold,
    )


def _assert_cluster_update_scaling(
    cluster,
    remote_command_executor,
    scheduler_commands,
    region,
    scheduler,
    updated_cluster_config,
    expected_ec2_capacity,
    expected_compute_nodes,
    max_monitoring_time,
    is_scale_down=True,
    threshold: float = 1,
):
    ec2_capacity_time_series, compute_nodes_time_series, timestamps = _monitor_cluster_update(
        cluster, updated_cluster_config, scheduler_commands, region, max_monitoring_time
    )

    _check_scaling_results(
        ec2_capacity_time_series,
        compute_nodes_time_series,
        expected_ec2_capacity,
        expected_compute_nodes,
        max_monitoring_time,
        threshold,
        is_scale_down,
    )

    # Thresholds less than one imply that bootstrap errors occurred,
    # we are therefore checking for errors only when we did not expect any error
    if threshold == 1:
        logging.info("Checking for errors in logs")
        assert_no_errors_in_logs(
            remote_command_executor,
            scheduler,
            ignore_patterns=[
                "RequestLimitExceeded",
                "Failed RunInstances request",
                "Failed CreateFleet request",
            ],  # Occurs when getting throttled at 1000+ instances
        )


def _assert_scaling_results_match_expected_range(
    ec2_capacity_time_series,
    compute_nodes_time_series,
    expected_ec2_capacity,
    expected_compute_nodes,
    min_for_scaledown=True,
    threshold: float = 1,
):
    """
    Verify that cluster scaling-up and scaling-down features work correctly.

    :param ec2_capacity_time_series: list describing the fluctuations over time in the ec2 capacity
    :param compute_nodes_time_series: list describing the fluctuations over time in the compute nodes
    :param expected_ec2_capacity: pair containing the expected ec2 capacity (min_ec2_capacity, max_ec2_capacity)
    :param expected_compute_nodes: pair containing the expected compute nodes (min_compute_nodes, max_compute_nodes)
    :param min_for_scaledown: consider values captured only after reaching maximum capacity when evaluating the minimum
        (useful when asserting scaling involving both increasing and decreasing the capacity
        e.g. dynamic nodes + scaledown event)
    """
    assert_that(ec2_capacity_time_series).described_as("ec2_capacity_time_series cannot be empty").is_not_empty()
    assert_that(compute_nodes_time_series).described_as("compute_nodes_time_series cannot be empty").is_not_empty()

    expected_ec2_capacity_min, expected_ec2_capacity_max = expected_ec2_capacity
    expected_compute_nodes_min, expected_compute_nodes_max = expected_compute_nodes

    # Apply threshold/allowance
    expected_compute_nodes_max = int(expected_compute_nodes_max * threshold)
    expected_ec2_capacity_max = int(expected_ec2_capacity_max * threshold)

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
        ).is_greater_than_or_equal_to(expected_ec2_capacity_max)
        assert_that(actual_compute_nodes_min).described_as(
            "actual number of min compute nodes does not match the expected one"
        ).is_equal_to(expected_compute_nodes_min)
        assert_that(actual_compute_nodes_max).described_as(
            "actual number of max compute nodes does not match the expected one"
        ).is_greater_than_or_equal_to(expected_compute_nodes_max)


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
