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
import time
from datetime import datetime, timezone
from os import environ

import boto3
import pytest
from assertpy import assert_that, soft_assertions
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from utils import get_compute_nodes_instance_ids, get_instance_ids_compute_hostnames_conversion_dict

from tests.common.assertions import (
    assert_errors_in_logs,
    assert_instance_replaced_or_terminating,
    assert_no_errors_in_logs,
    assert_num_instances_constant,
    assert_num_instances_in_cluster,
    wait_for_num_instances_in_cluster,
)
from tests.common.hit_common import (
    assert_initial_conditions,
    assert_num_nodes_in_scheduler,
    submit_initial_job,
    wait_for_num_nodes_in_scheduler,
)
from tests.common.scaling_common import get_compute_nodes_allocation, get_desired_asg_capacity
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
        asg_capacity_time_series=ec2_capacity_time_series,
        compute_nodes_time_series=compute_nodes_time_series,
        expected_asg_capacity=(0, 3),
        expected_compute_nodes=(0, 3),
    )

    logging.info("Verifying no error in logs")
    assert_no_errors_in_logs(remote_command_executor, scheduler)


@pytest.mark.regions(["sa-east-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["sge", "torque"])
@pytest.mark.oss(["alinux2", "centos7", "centos8", "ubuntu1804"])
@pytest.mark.usefixtures("region", "instance", "os")
@pytest.mark.nodewatcher
def test_nodewatcher_terminates_failing_node(scheduler, region, pcluster_config_reader, clusters_factory, test_datadir):
    # slurm test use more nodes because of internal request to test in multi-node settings
    initial_queue_size = 1
    environ["AWS_DEFAULT_REGION"] = region
    cluster_config = pcluster_config_reader(initial_queue_size=initial_queue_size)
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


@pytest.mark.regions(["us-west-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.oss(["alinux2", "centos7", "centos8", "ubuntu1804"])
@pytest.mark.usefixtures("region", "os")
@pytest.mark.hit_scaling
def test_hit_scaling(scheduler, region, instance, pcluster_config_reader, clusters_factory, test_datadir):
    """Test that slurm-specific scaling logic is resistent to manual actions and failures."""
    cluster_config = pcluster_config_reader(scaledown_idletime=3)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    _assert_cluster_initial_conditions(scheduler_commands, instance)
    _test_partition_states(
        scheduler_commands,
        cluster.cfn_name,
        region,
        active_partition="ondemand1",
        inactive_partition="ondemand2",
        num_static_nodes=2,
        num_dynamic_nodes=3,
        dynamic_instance_type=instance,
    )
    _test_reset_terminated_nodes(
        scheduler_commands,
        cluster.cfn_name,
        region,
        partition="ondemand1",
        num_static_nodes=2,
        num_dynamic_nodes=3,
        dynamic_instance_type=instance,
    )
    _test_replace_down_nodes(
        remote_command_executor,
        scheduler_commands,
        test_datadir,
        cluster.cfn_name,
        region,
        partition="ondemand1",
        num_static_nodes=2,
        num_dynamic_nodes=3,
        dynamic_instance_type=instance,
    )
    _test_keep_or_replace_suspended_nodes(
        scheduler_commands,
        cluster.cfn_name,
        region,
        partition="ondemand1",
        num_static_nodes=2,
        num_dynamic_nodes=3,
        dynamic_instance_type=instance,
    )
    # Next test will introduce error in logs, assert no error now
    assert_no_errors_in_logs(remote_command_executor, scheduler)
    _test_clustermgtd_down_logic(
        remote_command_executor,
        scheduler_commands,
        cluster.cfn_name,
        region,
        test_datadir,
        partition="ondemand1",
        num_static_nodes=2,
        num_dynamic_nodes=3,
        dynamic_instance_type=instance,
    )


def _assert_cluster_initial_conditions(scheduler_commands, instance):
    """Assert that expected nodes are in cluster."""
    cluster_node_states = scheduler_commands.get_nodes_status()
    c5l_nodes, instance_nodes, static_nodes, dynamic_nodes = [], [], [], []
    logging.info(cluster_node_states)
    for nodename, node_states in cluster_node_states.items():
        if "c5l" in nodename:
            c5l_nodes.append(nodename)
        # "c5.xlarge"[: "c5.xlarge".index(".")+2].replace(".", "") = c5x
        if instance[: instance.index(".") + 2].replace(".", "") in nodename:
            instance_nodes.append(nodename)
        if node_states == "idle":
            if "-st-" in nodename:
                static_nodes.append(nodename)
            if "-dy-" in nodename:
                dynamic_nodes.append(nodename)
    assert_that(len(c5l_nodes)).is_equal_to(20)
    assert_that(len(instance_nodes)).is_equal_to(20)
    assert_that(len(static_nodes)).is_equal_to(4)
    assert_that(len(dynamic_nodes)).is_equal_to(1)


def _test_partition_states(
    scheduler_commands,
    cluster_name,
    region,
    active_partition,
    inactive_partition,
    num_static_nodes,
    num_dynamic_nodes,
    dynamic_instance_type,
):
    """Partition states INACTIVE and UP are processed."""
    logging.info("Testing that INACTIVE partiton are cleaned up")
    # submit job to inactive partition to scale up some dynamic nodes
    init_job_id = submit_initial_job(
        scheduler_commands,
        "sleep 300",
        inactive_partition,
        dynamic_instance_type,
        num_dynamic_nodes,
        other_options="--no-requeue",
    )
    assert_initial_conditions(
        scheduler_commands, num_static_nodes, num_dynamic_nodes, partition=inactive_partition, cancel_job_id=init_job_id
    )
    # set partition to inactive and wait for instances/node to terminate
    scheduler_commands.set_partition_state(inactive_partition, "inactive")
    # wait for all instances from inactive_partition to terminate
    # active_partition should only have 2 static instances
    wait_for_num_instances_in_cluster(cluster_name, region, 2)
    # Assert no nodes in inactive partition
    wait_for_num_nodes_in_scheduler(scheduler_commands, desired=0, filter_by_partition=inactive_partition)
    # Assert active partition is not affected
    assert_num_nodes_in_scheduler(scheduler_commands, desired=num_static_nodes, filter_by_partition=active_partition)
    # set inactive partition back to active and wait for nodes to spin up
    scheduler_commands.set_partition_state(inactive_partition, "up")
    wait_for_num_nodes_in_scheduler(
        scheduler_commands, desired=num_static_nodes, filter_by_partition=inactive_partition
    )
    # set inactive partition to inactive to save resources, this partition will not be used for later tests
    scheduler_commands.set_partition_state(inactive_partition, "inactive")


def _test_reset_terminated_nodes(
    scheduler_commands, cluster_name, region, partition, num_static_nodes, num_dynamic_nodes, dynamic_instance_type
):
    """
    Test that slurm nodes are reset if instances are terminated manually.

    Static capacity should be replaced and dynamic capacity power saved.
    """
    logging.info("Testing that nodes are reset when instances are terminated manually")
    init_job_id = submit_initial_job(
        scheduler_commands,
        "sleep 300",
        partition,
        dynamic_instance_type,
        num_dynamic_nodes,
        other_options="--no-requeue",
    )
    static_nodes, dynamic_nodes = assert_initial_conditions(
        scheduler_commands, num_static_nodes, num_dynamic_nodes, partition, cancel_job_id=init_job_id
    )
    instance_ids = get_compute_nodes_instance_ids(cluster_name, region)
    # terminate all instances manually
    _terminate_nodes_manually(instance_ids, region)
    # Assert that cluster replaced static node and reset dynamic nodes
    _wait_for_node_reset(scheduler_commands, static_nodes, dynamic_nodes)
    assert_num_instances_in_cluster(cluster_name, region, len(static_nodes))


def _test_replace_down_nodes(
    remote_command_executor,
    scheduler_commands,
    test_datadir,
    cluster_name,
    region,
    partition,
    num_static_nodes,
    num_dynamic_nodes,
    dynamic_instance_type,
):
    """Test that slurm nodes are replaced if nodes are marked DOWN."""
    logging.info("Testing that nodes replaced when set to down state")
    init_job_id = submit_initial_job(
        scheduler_commands,
        "sleep 300",
        partition,
        dynamic_instance_type,
        num_dynamic_nodes,
        other_options="--no-requeue",
    )
    static_nodes, dynamic_nodes = assert_initial_conditions(
        scheduler_commands, num_static_nodes, num_dynamic_nodes, partition, cancel_job_id=init_job_id
    )
    # kill slurmd on static nodes, these nodes will be in down*
    for node in static_nodes:
        remote_command_executor.run_remote_script(str(test_datadir / "slurm_kill_slurmd_job.sh"), args=[node])
    # set dynamic to down manually
    _set_nodes_to_down_manually(scheduler_commands, dynamic_nodes)
    _wait_for_node_reset(scheduler_commands, static_nodes, dynamic_nodes)
    assert_num_instances_in_cluster(cluster_name, region, len(static_nodes))


def _test_keep_or_replace_suspended_nodes(
    scheduler_commands, cluster_name, region, partition, num_static_nodes, num_dynamic_nodes, dynamic_instance_type
):
    """Test keep DRAIN nodes if there is job running, or terminate if no job is running."""
    logging.info(
        "Testing that nodes are NOT terminated when set to suspend state and there is job running on the nodes"
    )
    job_id = submit_initial_job(
        scheduler_commands,
        "sleep 500",
        partition,
        dynamic_instance_type,
        num_dynamic_nodes,
        other_options="--no-requeue",
    )
    static_nodes, dynamic_nodes = assert_initial_conditions(
        scheduler_commands, num_static_nodes, num_dynamic_nodes, partition
    )
    # Set all nodes to drain, static should be in DRAINED and dynamic in DRAINING
    _set_nodes_to_suspend_state_manually(scheduler_commands, static_nodes + dynamic_nodes)
    # Static nodes in DRAINED are immediately replaced
    _wait_for_node_reset(scheduler_commands, static_nodes=static_nodes, dynamic_nodes=[])
    # Assert dynamic nodes in DRAINING are not terminated during job run
    _assert_nodes_not_terminated(scheduler_commands, dynamic_nodes)
    # wait until the job is completed and check that the DRAINING dynamic nodes are then terminated
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
    _wait_for_node_reset(scheduler_commands, static_nodes=[], dynamic_nodes=dynamic_nodes)
    assert_num_instances_in_cluster(cluster_name, region, len(static_nodes))


def _test_clustermgtd_down_logic(
    remote_command_executor,
    scheduler_commands,
    cluster_name,
    region,
    test_datadir,
    partition,
    num_static_nodes,
    num_dynamic_nodes,
    dynamic_instance_type,
):
    """Test that computemgtd is able to shut nodes down when clustermgtd and slurmctld are offline."""
    logging.info("Testing cluster protection logic when clustermgtd is down.")
    submit_initial_job(
        scheduler_commands,
        "sleep infinity",
        partition,
        dynamic_instance_type,
        num_dynamic_nodes,
        other_options="--no-requeue",
    )
    static_nodes, dynamic_nodes = assert_initial_conditions(
        scheduler_commands, num_static_nodes, num_dynamic_nodes, partition
    )
    logging.info("Killing clustermgtd and rewriting timestamp file to trigger timeout.")
    remote_command_executor.run_remote_script(str(test_datadir / "slurm_kill_clustermgtd.sh"), run_as_root=True)
    # Overwrite clusterctld heartbeat to trigger timeout path
    timestamp_format = "%Y-%m-%d %H:%M:%S.%f%z"
    overwrite_time_str = datetime(2020, 1, 1, tzinfo=timezone.utc).strftime(timestamp_format)
    remote_command_executor.run_remote_command(
        f"echo -n '{overwrite_time_str}' | sudo tee /opt/slurm/etc/pcluster/.slurm_plugin/clustermgtd_heartbeat"
    )
    # Test that computemgtd will terminate compute nodes that are down or in power_save
    # Put first static node and first dynamic node into DOWN
    # Put rest of dynamic nodes into POWER_DOWN
    logging.info("Asserting that computemgtd will terminate nodes in DOWN or POWER_SAVE")
    _set_nodes_to_down_manually(scheduler_commands, static_nodes[:1] + dynamic_nodes[:1])
    _set_nodes_to_power_down_manually(scheduler_commands, dynamic_nodes[1:])
    wait_for_num_instances_in_cluster(cluster_name, region, num_static_nodes - 1)

    logging.info("Testing that ResumeProgram launches no instance when clustermgtd is down")
    submit_initial_job(
        scheduler_commands,
        "sleep infinity",
        partition,
        dynamic_instance_type,
        num_dynamic_nodes,
    )

    logging.info("Asserting that computemgtd is not self-terminating when slurmctld is up")
    assert_num_instances_constant(cluster_name, region, desired=num_static_nodes - 1, timeout=2)

    logging.info("Killing slurmctld")
    remote_command_executor.run_remote_script(str(test_datadir / "slurm_kill_slurmctld.sh"), run_as_root=True)
    logging.info("Waiting for computemgtd to self-terminate all instances")
    wait_for_num_instances_in_cluster(cluster_name, region, 0)

    assert_errors_in_logs(
        remote_command_executor,
        ["/var/log/parallelcluster/slurm_resume.log"],
        ["No valid clustermgtd heartbeat detected"],
    )


@retry(wait_fixed=seconds(30), stop_max_delay=minutes(15))
def _assert_failing_nodes_terminated(nodes_to_remove, hostname_to_instance_id, region):
    for node in nodes_to_remove:
        assert_instance_replaced_or_terminating(hostname_to_instance_id.get(node), region)


def _wait_for_node_reset(scheduler_commands, static_nodes, dynamic_nodes):
    """Wait for static and dynamic nodes to be reset."""
    if static_nodes:
        logging.info("Assert static nodes are placed in DOWN during replacement")
        # DRAIN+DOWN = drained
        _wait_for_compute_nodes_states(
            scheduler_commands, static_nodes, expected_states=["down", "down*", "drained", "drained*"]
        )
        logging.info("Assert static nodes are replaced")
        _wait_for_compute_nodes_states(scheduler_commands, static_nodes, expected_states=["idle"])
    # dynamic nodes are power saved after SuspendTimeout. static_nodes must be checked first
    if dynamic_nodes:
        logging.info("Assert dynamic nodes are power saved")
        _wait_for_compute_nodes_states(scheduler_commands, dynamic_nodes, expected_states=["idle~"])


def _assert_nodes_not_terminated(scheduler_commands, nodes, timeout=5):
    logging.info("Waiting for cluster daemon action")
    start_time = time.time()
    while time.time() < start_time + 60 * (timeout):
        assert_that(set(nodes) <= set(scheduler_commands.get_compute_nodes())).is_true()
        time.sleep(20)


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


def _set_nodes_to_suspend_state_manually(scheduler_commands, compute_nodes):
    scheduler_commands.set_nodes_state(compute_nodes, state="drain")
    # draining means that there is job currently running on the node
    # drained would mean we placed node in drain when there is no job running on the node
    _assert_compute_node_states(scheduler_commands, compute_nodes, expected_states=["draining", "drained"])


def _set_nodes_to_down_manually(scheduler_commands, compute_nodes):
    scheduler_commands.set_nodes_state(compute_nodes, state="down")
    _assert_compute_node_states(scheduler_commands, compute_nodes, expected_states=["down"])


def _set_nodes_to_power_down_manually(scheduler_commands, compute_nodes):
    scheduler_commands.set_nodes_state(compute_nodes, state="power_down")
    time.sleep(5)
    scheduler_commands.set_nodes_state(compute_nodes, state="resume")
    _assert_compute_node_states(scheduler_commands, compute_nodes, expected_states=["idle~"])


def _assert_compute_node_states(scheduler_commands, compute_nodes, expected_states):
    node_states = scheduler_commands.get_nodes_status(compute_nodes)
    for node in compute_nodes:
        assert_that(expected_states).contains(node_states.get(node))


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))
def _wait_for_compute_nodes_states(scheduler_commands, compute_nodes, expected_states):
    _assert_compute_node_states(scheduler_commands, compute_nodes, expected_states)


def _terminate_nodes_manually(instance_ids, region):
    ec2_client = boto3.client("ec2", region_name=region)
    for instance_id in instance_ids:
        instance_states = ec2_client.terminate_instances(InstanceIds=[instance_id]).get("TerminatingInstances")[0]
        assert_that(instance_states.get("InstanceId")).is_equal_to(instance_id)
        assert_that(instance_states.get("CurrentState").get("Name")).is_in("shutting-down", "terminated")
    logging.info("Terminated nodes: {}".format(instance_ids))


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(10))
def _assert_nodes_removed_from_scheduler(scheduler_commands, nodes):
    assert_that(scheduler_commands.get_compute_nodes()).does_not_contain(*nodes)


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
    with soft_assertions():
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
