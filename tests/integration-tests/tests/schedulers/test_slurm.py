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

import boto3
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from utils import InstanceTypesData, get_compute_nodes_instance_ids, get_head_node_instance_id

from tests.common.assertions import (
    assert_errors_in_logs,
    assert_no_errors_in_logs,
    assert_no_msg_in_logs,
    assert_no_node_in_ec2,
    assert_num_instances_constant,
    assert_num_instances_in_cluster,
    assert_scaling_worked,
    wait_for_num_instances_in_cluster,
)
from tests.common.hit_common import (
    assert_compute_node_states,
    assert_initial_conditions,
    assert_num_nodes_in_scheduler,
    get_partition_nodes,
    submit_initial_job,
    wait_for_compute_nodes_states,
    wait_for_num_nodes_in_scheduler,
)
from tests.common.mpi_common import compile_mpi_ring
from tests.common.schedulers_common import SlurmCommands, TorqueCommands, get_scheduler_commands


@pytest.mark.regions(["us-east-2"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("instance", "scheduler", "os")
def test_slurm(region, pcluster_config_reader, clusters_factory, test_datadir, architecture):
    """
    Test all AWS Slurm related features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    scaledown_idletime = 3
    gpu_instance_type = "g3.4xlarge"
    gpu_instance_type_info = InstanceTypesData.get_instance_info(gpu_instance_type, region)
    # For OSs running _test_mpi_job_termination, spin up 2 compute nodes at cluster creation to run test
    # Else do not spin up compute node and start running regular slurm tests
    supports_impi = architecture == "x86_64"
    cluster_config = pcluster_config_reader(scaledown_idletime=scaledown_idletime, gpu_instance_type=gpu_instance_type)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = SlurmCommands(remote_command_executor)

    if supports_impi:
        _test_mpi_job_termination(remote_command_executor, test_datadir)

    _assert_no_node_in_cluster(region, cluster.cfn_name, slurm_commands)
    _test_job_dependencies(slurm_commands, region, cluster.cfn_name, scaledown_idletime)
    _test_job_arrays_and_parallel_jobs(
        slurm_commands,
        region,
        cluster.cfn_name,
        scaledown_idletime,
        partition="ondemand",
        instance_type="c5.xlarge",
        cpu_per_instance=4,
    )
    _gpu_resource_check(
        slurm_commands, partition="gpu", instance_type=gpu_instance_type, instance_type_info=gpu_instance_type_info
    )
    _test_cluster_limits(
        slurm_commands, partition="ondemand", instance_type="c5.xlarge", max_count=5, cpu_per_instance=4
    )
    _test_cluster_gpu_limits(
        slurm_commands,
        partition="gpu",
        instance_type=gpu_instance_type,
        max_count=5,
        gpu_per_instance=_get_num_gpus_on_instance(gpu_instance_type_info),
        gpu_type="m60",
    )
    # Test torque command wrapper
    _test_torque_job_submit(remote_command_executor, test_datadir)
    assert_no_errors_in_logs(remote_command_executor, "slurm")


@pytest.mark.regions(["eu-west-1"])
@pytest.mark.instances(["c5.xlarge", "m6g.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_slurm_pmix(pcluster_config_reader, clusters_factory):
    """Test interactive job submission using PMIx."""
    num_computes = 2
    cluster_config = pcluster_config_reader(queue_size=num_computes)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # Ensure the expected PMIx version is listed when running `srun --mpi=list`.
    # Since we're installing PMIx v3.1.5, we expect to see pmix and pmix_v3 in the output.
    # Sample output:
    # [ec2-user@ip-172-31-33-187 ~]$ srun 2>&1 --mpi=list
    # srun: MPI types are...
    # srun: none
    # srun: openmpi
    # srun: pmi2
    # srun: pmix
    # srun: pmix_v3
    mpi_list_output = remote_command_executor.run_remote_command("srun 2>&1 --mpi=list").stdout
    assert_that(mpi_list_output).matches(r"\s+pmix($|\s+)")
    assert_that(mpi_list_output).matches(r"\s+pmix_v3($|\s+)")

    # Compile and run an MPI program interactively
    mpi_module = "openmpi"
    binary_path = "/shared/ring"
    compile_mpi_ring(mpi_module, remote_command_executor, binary_path=binary_path)
    interactive_command = f"module load {mpi_module} && srun --mpi=pmix -N {num_computes} {binary_path}"
    remote_command_executor.run_remote_command(interactive_command)


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
@pytest.mark.slurm_scaling
def test_slurm_scaling(scheduler, region, instance, pcluster_config_reader, clusters_factory, test_datadir):
    """Test that slurm-specific scaling logic is behaving as expected for normal actions and failures."""
    cluster_config = pcluster_config_reader(scaledown_idletime=3)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    _assert_cluster_initial_conditions(scheduler_commands, instance, 20, 20, 4, 1)
    _test_online_node_configured_correctly(
        scheduler_commands,
        partition="ondemand1",
        num_static_nodes=2,
        num_dynamic_nodes=2,
        dynamic_instance_type=instance,
    )
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
    assert_no_errors_in_logs(remote_command_executor, scheduler)


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
@pytest.mark.slurm_error_handling
def test_error_handling(scheduler, region, instance, pcluster_config_reader, clusters_factory, test_datadir):
    """Test that slurm-specific scaling logic can handle rare failures."""
    cluster_config = pcluster_config_reader(scaledown_idletime=3)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    _assert_cluster_initial_conditions(scheduler_commands, instance, 10, 20, 1, 1)
    _test_cloud_node_health_check(
        remote_command_executor,
        scheduler_commands,
        cluster.cfn_name,
        region,
        partition="ondemand1",
        num_static_nodes=1,
        # Test only works with num_dynamic = 1
        num_dynamic_nodes=1,
        dynamic_instance_type=instance,
    )
    _test_ec2_status_check_replacement(
        remote_command_executor,
        scheduler_commands,
        cluster.cfn_name,
        region,
        partition="ondemand1",
        num_static_nodes=1,
    )
    _test_cluster_stop_with_powering_up_node(
        scheduler_commands,
        cluster,
        partition="clusterstop",
        num_dynamic_nodes=1,
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
        num_static_nodes=1,
        num_dynamic_nodes=1,
        dynamic_instance_type=instance,
    )
    _test_head_node_down(
        remote_command_executor,
        scheduler_commands,
        cluster.cfn_name,
        region,
        test_datadir,
        partition="ondemand1",
        num_static_nodes=1,
        num_dynamic_nodes=1,
        dynamic_instance_type=instance,
    )


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
@pytest.mark.slurm_scontrol_reboot
def test_scontrol_reboot(
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = SlurmCommands(remote_command_executor)

    # Clear clustermgtd logs before starting the tests
    remote_command_executor.run_remote_command("sudo truncate -s 0 /var/log/parallelcluster/clustermgtd")
    # Run first job to wake up dynamic nodes from power_down state
    slurm_commands.submit_command(
        command="hostname",
        nodes=2,
        slots=2,
        constraint="dynamic",
        stop_max_delay_secs=330,
    )
    wait_for_compute_nodes_states(
        slurm_commands,
        ["queue1-dy-t2micro-1", "queue1-dy-t2micro-2"],
        "idle",
    )

    # Test that idle static and dynamic nodes can be rebooted
    _test_scontrol_reboot_nodes(
        remote_command_executor,
        slurm_commands,
        "idle",
    )

    # Run job to allocate all nodes and test that allocated nodes can be rebooted
    slurm_commands.submit_command(
        command="sleep 150",
        nodes=4,
        slots=4,
    )
    _test_scontrol_reboot_nodes(
        remote_command_executor,
        slurm_commands,
        "alloc",
    )

    # Check that node in REBOOT_REQUESTED state can be powered down
    _test_scontrol_reboot_powerdown_reboot_requested_node(
        remote_command_executor,
        slurm_commands,
        "queue1-st-t2micro-1",
    )

    # Clear clustermgtd logs produced in previous tests
    remote_command_executor.run_remote_command("sudo truncate -s 0 /var/log/parallelcluster/clustermgtd")

    # Check that node in REBOOT_ISSUED state can be powered down
    _test_scontrol_reboot_powerdown_reboot_issued_node(
        remote_command_executor,
        slurm_commands,
        "queue1-st-t2micro-2",
    )


def _assert_cluster_initial_conditions(
    scheduler_commands,
    instance,
    expected_num_dummy,
    expected_num_instance_node,
    expected_num_static,
    expected_num_dynamic,
):
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
    assert_that(len(c5l_nodes)).is_equal_to(expected_num_dummy)
    assert_that(len(instance_nodes)).is_equal_to(expected_num_instance_node)
    assert_that(len(static_nodes)).is_equal_to(expected_num_static)
    assert_that(len(dynamic_nodes)).is_equal_to(expected_num_dynamic)


def _test_online_node_configured_correctly(
    scheduler_commands,
    partition,
    num_static_nodes,
    num_dynamic_nodes,
    dynamic_instance_type,
):
    logging.info("Testing that online nodes' nodeaddr and nodehostname are configured correctly.")
    init_job_id = submit_initial_job(
        scheduler_commands,
        "sleep infinity",
        partition,
        dynamic_instance_type,
        num_dynamic_nodes,
        other_options="--no-requeue",
    )
    static_nodes, dynamic_nodes = assert_initial_conditions(
        scheduler_commands, num_static_nodes, num_dynamic_nodes, partition, cancel_job_id=init_job_id
    )
    node_attr_map = {}
    for node_entry in scheduler_commands.get_node_addr_host():
        nodename, nodeaddr, nodehostname = node_entry.split()
        node_attr_map[nodename] = {"nodeaddr": nodeaddr, "nodehostname": nodehostname}
    logging.info(node_attr_map)
    for nodename in static_nodes + dynamic_nodes:
        # For online nodes:
        # Nodeaddr should be set to private ip of instance
        # Nodehostname should be the same with nodename
        assert_that(nodename in node_attr_map).is_true()
        assert_that(nodename).is_not_equal_to(node_attr_map.get(nodename).get("nodeaddr"))
        assert_that(nodename).is_equal_to(node_attr_map.get(nodename).get("nodehostname"))


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


def _test_cloud_node_health_check(
    remote_command_executor,
    scheduler_commands,
    cluster_name,
    region,
    partition,
    num_static_nodes,
    num_dynamic_nodes,
    dynamic_instance_type,
):
    """
    Test nodes with networking failure are correctly replaced.

    This will test if slurm is performing health check on CLOUD nodes correctly.
    """
    logging.info("Testing that nodes with networking failure fails slurm health check and replaced")
    job_id = submit_initial_job(
        scheduler_commands,
        "sleep 500",
        partition,
        dynamic_instance_type,
        num_dynamic_nodes,
        other_options="--no-requeue",
    )
    static_nodes, dynamic_nodes = assert_initial_conditions(
        scheduler_commands, num_static_nodes, num_dynamic_nodes, partition, job_id
    )
    # Assert that the default SlurmdTimeout=180 is in effect
    _assert_slurmd_timeout(remote_command_executor, timeout=180)
    # Nodes with networking failures should fail slurm health check before failing ec2_status_check
    # Test on freshly launched dynamic nodes
    kill_job_id = _submit_kill_networking_job(
        remote_command_executor, scheduler_commands, partition, node_type="dynamic", num_nodes=num_dynamic_nodes
    )
    # Sleep for a bit so the command to detach network interface can be run
    time.sleep(15)
    # Job will hang, cancel it manually to avoid waiting for job failing
    scheduler_commands.cancel_job(kill_job_id)
    # Assert nodes are put into DOWN for not responding
    # TO-DO: this test only works with num_dynamic = 1 because slurm will record this error in nodelist format
    # i.e. error: Nodes q2-st-t2large-[1-2] not responding, setting DOWN
    # To support multiple nodes, need to convert list of node into nodelist format string
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))(assert_errors_in_logs)(
        remote_command_executor,
        ["/var/log/slurmctld.log"],
        ["Nodes {} not responding, setting DOWN".format(",".join(dynamic_nodes))],
    )
    # Assert dynamic nodes are reset
    _wait_for_node_reset(scheduler_commands, static_nodes=[], dynamic_nodes=dynamic_nodes)
    assert_num_instances_in_cluster(cluster_name, region, len(static_nodes))
    # Assert ec2_status_check code path is not triggered
    assert_no_msg_in_logs(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        ["Setting nodes failing health check type ec2_health_check to DRAIN"],
    )


def _test_ec2_status_check_replacement(
    remote_command_executor,
    scheduler_commands,
    cluster_name,
    region,
    partition,
    num_static_nodes,
):
    """Test nodes with failing ec2 status checks are correctly replaced."""
    logging.info("Testing that nodes with failing ec2 status checks are correctly replaced")
    static_nodes, _ = assert_initial_conditions(scheduler_commands, num_static_nodes, 0, partition)
    # Can take up to 15 mins for ec2_status_check to show
    # Need to increase SlurmdTimeout to avoid slurm health check and trigger ec2_status_check code path
    _set_slurmd_timeout(remote_command_executor, timeout=10000)
    kill_job_id = _submit_kill_networking_job(
        remote_command_executor, scheduler_commands, partition, node_type="static", num_nodes=num_static_nodes
    )
    # Assert ec2_status_check code path is triggered
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(15))(assert_errors_in_logs)(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        ["Setting nodes failing health check type ec2_health_check to DRAIN"],
    )
    scheduler_commands.cancel_job(kill_job_id)
    # Assert static nodes are reset
    _wait_for_node_reset(scheduler_commands, static_nodes=static_nodes, dynamic_nodes=[])
    assert_num_instances_in_cluster(cluster_name, region, len(static_nodes))
    # Reset SlurmdTimeout to 180s
    _set_slurmd_timeout(remote_command_executor, timeout=180)


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
        "echo -n '{}' | sudo tee /opt/slurm/etc/pcluster/.slurm_plugin/clustermgtd_heartbeat".format(overwrite_time_str)
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


def _test_head_node_down(
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
    # Make sure clustermgtd and slurmctld are running
    remote_command_executor.run_remote_script(str(test_datadir / "slurm_start_clustermgtd.sh"), run_as_root=True)
    remote_command_executor.run_remote_script(str(test_datadir / "slurm_start_slurmctld.sh"), run_as_root=True)
    # Sleep for 60 seconds to make sure clustermgtd finishes 1 iteration and write a valid heartbeat
    # Otherwise ResumeProgram will not be able to launch dynamic nodes due to invalid heartbeat
    time.sleep(60)
    submit_initial_job(
        scheduler_commands,
        "sleep infinity",
        partition,
        dynamic_instance_type,
        num_dynamic_nodes,
        other_options="--no-requeue",
    )
    # On slurmctld restart, offline nodes might still show as responding for a short time, breaking assertions
    # Add some retries to avoid failing due to this case
    _, _ = retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))(assert_initial_conditions)(
        scheduler_commands, num_static_nodes, num_dynamic_nodes, partition
    )
    _stop_head_node(cluster_name, region)
    # Default computemgtd clustermgtd_timeout is 10 mins, check that compute instances are terminated around this time
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(15))(assert_num_instances_in_cluster)(cluster_name, region, 0)


def _stop_head_node(cluster_name, region):
    """Stop head node instance."""
    head_node_id = get_head_node_instance_id(cluster_name, region)
    ec2_client = boto3.client("ec2", region_name=region)
    ec2_client.stop_instances(InstanceIds=head_node_id)


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
        node_addr_host = scheduler_commands.get_node_addr_host()
        _assert_node_addr_host_reset(node_addr_host, dynamic_nodes)


def _assert_node_addr_host_reset(addr_host_list, nodes):
    """Assert that NodeAddr and NodeHostname are reset."""
    for nodename in nodes:
        assert_that(addr_host_list).contains("{0} {0} {0}".format(nodename))


def _assert_nodes_not_terminated(scheduler_commands, nodes, timeout=5):
    logging.info("Waiting for cluster daemon action")
    start_time = time.time()
    while time.time() < start_time + 60 * (timeout):
        assert_that(set(nodes) <= set(scheduler_commands.get_compute_nodes())).is_true()
        time.sleep(20)


def _set_nodes_to_suspend_state_manually(scheduler_commands, compute_nodes):
    scheduler_commands.set_nodes_state(compute_nodes, state="drain")
    # draining means that there is job currently running on the node
    # drained would mean we placed node in drain when there is no job running on the node
    assert_compute_node_states(scheduler_commands, compute_nodes, expected_states=["draining", "drained"])


def _set_nodes_to_down_manually(scheduler_commands, compute_nodes):
    scheduler_commands.set_nodes_state(compute_nodes, state="down")
    assert_compute_node_states(scheduler_commands, compute_nodes, expected_states=["down"])


def _set_nodes_to_power_down_manually(scheduler_commands, compute_nodes):
    scheduler_commands.set_nodes_state(compute_nodes, state="power_down")
    time.sleep(5)
    scheduler_commands.set_nodes_state(compute_nodes, state="resume")
    assert_compute_node_states(scheduler_commands, compute_nodes, expected_states=["idle~"])


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))
def _wait_for_compute_nodes_states(scheduler_commands, compute_nodes, expected_states):
    assert_compute_node_states(scheduler_commands, compute_nodes, expected_states)


def _terminate_nodes_manually(instance_ids, region):
    ec2_client = boto3.client("ec2", region_name=region)
    for instance_id in instance_ids:
        instance_states = ec2_client.terminate_instances(InstanceIds=[instance_id]).get("TerminatingInstances")[0]
        assert_that(instance_states.get("InstanceId")).is_equal_to(instance_id)
        assert_that(instance_states.get("CurrentState").get("Name")).is_in("shutting-down", "terminated")
    logging.info("Terminated nodes: {}".format(instance_ids))


def _test_mpi_job_termination(remote_command_executor, test_datadir):
    """
    Test canceling mpirun job will not leave stray processes.

    IntelMPI is known to leave stray processes after job termination if slurm process tracking is not setup correctly,
    i.e. using ProctrackType=proctrack/pgid
    Test IntelMPI script to make sure no stray processes after the job is cancelled
    This bug cannot be reproduced using OpenMPI
    """
    logging.info("Testing no stray process left behind after mpirun job is terminated")
    slurm_commands = SlurmCommands(remote_command_executor)
    # Assert initial condition
    assert_that(slurm_commands.compute_nodes_count()).is_equal_to(2)

    # Submit mpi_job, which runs Intel MPI benchmarks with intelmpi
    # Leaving 1 vcpu on each node idle so that the process check job can run while mpi_job is running
    result = slurm_commands.submit_script(str(test_datadir / "mpi_job.sh"))
    job_id = slurm_commands.assert_job_submitted(result.stdout)

    # Check that mpi processes are started
    _assert_job_state(slurm_commands, job_id, job_state="RUNNING")
    _check_mpi_process(remote_command_executor, slurm_commands, test_datadir, num_nodes=2, after_completion=False)
    slurm_commands.cancel_job(job_id)

    # Make sure mpirun job is cancelled
    _assert_job_state(slurm_commands, job_id, job_state="CANCELLED")

    # Check that mpi processes are terminated
    _check_mpi_process(remote_command_executor, slurm_commands, test_datadir, num_nodes=2, after_completion=True)


@retry(wait_fixed=seconds(10), stop_max_attempt_number=4)
def _check_mpi_process(remote_command_executor, slurm_commands, test_datadir, num_nodes, after_completion):
    """Submit script and check for MPI processes."""
    # Clean up old datafiles
    remote_command_executor.run_remote_command("rm -f /shared/check_proc.out")
    result = slurm_commands.submit_command("ps aux | grep IMB | grep MPI >> /shared/check_proc.out", nodes=num_nodes)
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    proc_track_result = remote_command_executor.run_remote_command("cat /shared/check_proc.out")
    if after_completion:
        assert_that(proc_track_result.stdout).does_not_contain("IMB-MPI1")
    else:
        assert_that(proc_track_result.stdout).contains("IMB-MPI1")


def _test_cluster_gpu_limits(slurm_commands, partition, instance_type, max_count, gpu_per_instance, gpu_type):
    """Test edge cases regarding the number of GPUs."""
    logging.info("Testing scheduler does not accept jobs when requesting for more GPUs than available")
    # Expect commands below to fail with exit 1
    _submit_command_and_assert_job_rejected(
        slurm_commands,
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": "--gpus-per-task {0} -n 1".format(gpu_per_instance + 1),
            "raise_on_error": False,
        },
    )
    _submit_command_and_assert_job_rejected(
        slurm_commands,
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": "--gres=gpu:{0}".format(gpu_per_instance + 1),
            "raise_on_error": False,
        },
    )
    _submit_command_and_assert_job_rejected(
        slurm_commands,
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": "-G {0}".format(gpu_per_instance * max_count + 1),
            "raise_on_error": False,
        },
    )
    logging.info("Testing scheduler does not accept jobs when requesting job containing conflicting options")
    _submit_command_and_assert_job_rejected(
        slurm_commands,
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": "-G 1 --cpus-per-gpu 32 --cpus-per-task 20",
            "raise_on_error": False,
        },
        reason="sbatch: error: --cpus-per-gpu is mutually exclusive with --cpus-per-task",
    )

    # Commands below should be correctly submitted
    slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "slots": gpu_per_instance,
            "other_options": "-G {0}:{1} --gpus-per-task={0}:1".format(gpu_type, gpu_per_instance),
        }
    )
    slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": "--gres=gpu:{0}:{1}".format(gpu_type, gpu_per_instance),
        }
    )
    # Submit job without '-N' option(nodes=-1)
    slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "nodes": -1,
            "other_options": "-G {0} --gpus-per-node={1}".format(gpu_per_instance * max_count, gpu_per_instance),
        }
    )


def _test_cluster_limits(slurm_commands, partition, instance_type, max_count, cpu_per_instance):
    logging.info("Testing scheduler rejects jobs that require a capacity that is higher than the max available")

    # Check node limit job is rejected at submission
    _submit_command_and_assert_job_rejected(
        slurm_commands,
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "nodes": (max_count + 1),
            "constraint": instance_type,
            "raise_on_error": False,
        },
    )

    # Check cpu limit job is rejected at submission
    _submit_command_and_assert_job_rejected(
        slurm_commands,
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": "--cpus-per-task {0}".format(cpu_per_instance + 1),
            "raise_on_error": False,
        },
    )


def _submit_command_and_assert_job_rejected(
    slurm_commands, submit_command_args, reason="sbatch: error: Batch job submission failed:"
):
    """Submit a limit-violating job and assert the job is failed at submission."""
    result = slurm_commands.submit_command(**submit_command_args)
    assert_that(result.stdout).contains(reason)


def _gpu_resource_check(slurm_commands, partition, instance_type, instance_type_info):
    """Test GPU related resources are correctly allocated."""
    logging.info("Testing number of GPU/CPU resources allocated to job")

    cpus_per_gpu = min(5, instance_type_info.get("VCpuInfo").get("DefaultCores"))
    job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": f"-G 1 --cpus-per-gpu {cpus_per_gpu}",
        }
    )
    job_info = slurm_commands.get_job_info(job_id)
    assert_that(job_info).contains("TresPerJob=gres:gpu:1", f"CpusPerTres=gres:gpu:{cpus_per_gpu}")

    gpus_per_instance = _get_num_gpus_on_instance(instance_type_info)
    job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": f"--gres=gpu:{gpus_per_instance} --cpus-per-gpu {cpus_per_gpu}",
        }
    )
    job_info = slurm_commands.get_job_info(job_id)
    assert_that(job_info).contains(f"TresPerNode=gres:gpu:{gpus_per_instance}", f"CpusPerTres=gres:gpu:{cpus_per_gpu}")


def _test_job_dependencies(slurm_commands, region, stack_name, scaledown_idletime):
    logging.info("Testing cluster doesn't scale when job dependencies are not satisfied")
    job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 60", "nodes": 1}
    )
    dependent_job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 1", "nodes": 1, "after_ok": job_id}
    )

    # Wait for reason to be computed
    time.sleep(3)
    # Job should be in CF and waiting for nodes to power_up
    assert_that(slurm_commands.get_job_info(job_id)).contains("JobState=CONFIGURING")
    assert_that(slurm_commands.get_job_info(dependent_job_id)).contains("JobState=PENDING Reason=Dependency")

    assert_scaling_worked(slurm_commands, region, stack_name, scaledown_idletime, expected_max=1, expected_final=0)
    # Assert jobs were completed
    _assert_job_completed(slurm_commands, job_id)
    _assert_job_completed(slurm_commands, dependent_job_id)


def _test_job_arrays_and_parallel_jobs(
    slurm_commands, region, stack_name, scaledown_idletime, partition, instance_type, cpu_per_instance
):
    logging.info("Testing cluster scales correctly with array jobs and parallel jobs")

    # Following 2 jobs requires total of 3 nodes
    array_job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 1",
            "nodes": -1,
            "partition": partition,
            "constraint": instance_type,
            "other_options": "-a 1-{0}".format(cpu_per_instance + 1),
        }
    )

    parallel_job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 1",
            "nodes": -1,
            "slots": 2,
            "partition": partition,
            "constraint": instance_type,
            "other_options": "-c {0}".format(cpu_per_instance - 1),
        }
    )

    # Assert scaling worked as expected
    assert_scaling_worked(slurm_commands, region, stack_name, scaledown_idletime, expected_max=3, expected_final=0)
    # Assert jobs were completed
    _assert_job_completed(slurm_commands, array_job_id)
    _assert_job_completed(slurm_commands, parallel_job_id)


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(7))
def _assert_no_node_in_cluster(region, stack_name, scheduler_commands, partition=None):
    assert_that(scheduler_commands.compute_nodes_count(filter_by_partition=partition)).is_equal_to(0)
    assert_no_node_in_ec2(region, stack_name)


def _assert_job_completed(slurm_commands, job_id):
    _assert_job_state(slurm_commands, job_id, job_state="COMPLETED")


@retry(wait_fixed=seconds(3), stop_max_delay=seconds(15))
def _assert_job_state(slurm_commands, job_id, job_state):
    try:
        result = slurm_commands.get_job_info(job_id)
        assert_that(result).contains("JobState={}".format(job_state))
    except RemoteCommandExecutionError as e:
        # Handle the case when job is deleted from history
        assert_that(e.result.stdout).contains("slurm_load_jobs error: Invalid job id specified")


def _test_torque_job_submit(remote_command_executor, test_datadir):
    """Test torque job submit command in slurm cluster."""
    logging.info("Testing cluster submits job by torque command")
    torque_commands = TorqueCommands(remote_command_executor)
    result = torque_commands.submit_script(str(test_datadir / "torque_job.sh"))
    torque_commands.assert_job_submitted(result.stdout)


def _submit_kill_networking_job(remote_command_executor, scheduler_commands, partition, node_type, num_nodes):
    """Submit job that will detach network interface on compute."""
    # Get network interface name from Head node, assuming Head node and Compute are of the same instance type
    interface_name = remote_command_executor.run_remote_command(
        "nmcli device status | grep ether | awk '{print $1}'"
    ).stdout
    logging.info("Detaching network interface {} on {} Compute nodes".format(interface_name, node_type))
    # Submit job that will detach network interface on all dynamic nodes
    return scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sudo ifconfig {} down && sleep 600".format(interface_name),
            "partition": partition,
            "constraint": "{}".format(node_type),
            "other_options": "-a 1-{} --exclusive --no-requeue".format(num_nodes),
        }
    )


def _set_slurmd_timeout(remote_command_executor, timeout):
    """Set SlurmdTimeout in slurm.conf."""
    remote_command_executor.run_remote_command(
        "sudo sed -i '/SlurmdTimeout/s/=.*/={0}/' /opt/slurm/etc/slurm.conf".format(timeout)
    )
    remote_command_executor.run_remote_command("sudo /opt/slurm/bin/scontrol reconfigure")
    _assert_slurmd_timeout(remote_command_executor, timeout)


def _assert_slurmd_timeout(remote_command_executor, timeout):
    """Assert that SlurmdTimeout is correctly set."""
    configured_timeout = remote_command_executor.run_remote_command(
        'scontrol show config | grep -oP "^SlurmdTimeout\\s*\\=\\s*\\K(.+)"'
    ).stdout
    assert_that(configured_timeout).is_equal_to("{0} sec".format(timeout))


def _get_num_gpus_on_instance(instance_type_info):
    """
    Return the number of GPUs attached to the instance type.

    instance_type_info is expected to be as returned by DescribeInstanceTypes:
    {
        ...,
        "GpuInfo": {
            "Gpus": [
                {
                    "Name": "M60",
                    "Manufacturer": "NVIDIA",
                    "Count": 2,
                    "MemoryInfo": {
                        "SizeInMiB": 8192
                    }
                }
            ],
        }
        ...
    }
    """
    return sum([gpu_type.get("Count") for gpu_type in instance_type_info.get("GpuInfo").get("Gpus")])


def _test_cluster_stop_with_powering_up_node(
    scheduler_commands, cluster, partition, num_dynamic_nodes, dynamic_instance_type
):
    """Test powering up nodes are set to power_down after cluster stop."""
    # Submit a job to a dynamic node
    submit_initial_job(
        scheduler_commands,
        "sleep 30",
        partition,
        dynamic_instance_type,
        num_dynamic_nodes,
        other_options="--no-requeue",
    )
    # Wait for node to be powering up
    dynamic_nodes = [node for node in scheduler_commands.get_compute_nodes(partition) if "-dy-" in node]
    _wait_for_compute_nodes_states(scheduler_commands, dynamic_nodes, expected_states=["alloc#", "idle#", "mix#"])
    # stop cluster
    cluster.stop()
    _wait_for_computefleet_changed(cluster, "STOPPED")
    # start cluster
    cluster.start()
    _wait_for_computefleet_changed(cluster, "RUNNING")
    # wait node power save
    _wait_for_compute_nodes_states(scheduler_commands, dynamic_nodes, expected_states=["idle~"])
    # submit the job to the node again and assert job succeeded
    job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 1", "nodes": num_dynamic_nodes, "partition": partition}
    )
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))
def _wait_for_computefleet_changed(cluster, desired_status):
    assert_that(cluster.status()).contains(f"ComputeFleetStatus: {desired_status}")


def _test_scontrol_reboot_nodes(
    remote_command_executor,
    slurm_commands,
    nodes_state,
):
    """Test scontrol reboot with idle nodes."""
    jiff = 2

    # Get nodes and check that they are in the expected state
    nodes_in_queue = slurm_commands.get_compute_nodes("queue1")
    if nodes_state == "idle":
        assert_compute_node_states(slurm_commands, nodes_in_queue, "idle")
    else:
        assert_compute_node_states(slurm_commands, nodes_in_queue, ["allocated", "mixed"])

    # Reboot nodes according to this logic:
    # - 1 static idle node
    # - 1 static idle node asap
    # - 1 dynamic idle node
    # - 1 dynamic idle node asap
    static_nodes, dynamic_nodes = get_partition_nodes(nodes_in_queue)
    assert_that(len(static_nodes)).is_equal_to(2)
    assert_that(len(dynamic_nodes)).is_equal_to(2)
    slurm_commands.reboot_compute_node(static_nodes[0], asap=False)
    slurm_commands.reboot_compute_node(static_nodes[1], asap=True)
    slurm_commands.reboot_compute_node(dynamic_nodes[0], asap=False)
    slurm_commands.reboot_compute_node(dynamic_nodes[1], asap=True)

    # Check that nodes enter a reboot state
    time.sleep(jiff)
    if nodes_state == "idle":
        assert_compute_node_states(slurm_commands, nodes_in_queue, "reboot^")
    else:
        assert_compute_node_states(slurm_commands, nodes_in_queue, ["mixed@", "allocated@", "draining@"])
        wait_for_compute_nodes_states(slurm_commands, nodes_in_queue, expected_states=["reboot^"])

    # Wait that nodes come back after a while, without having triggered clustermgtd
    wait_for_compute_nodes_states(slurm_commands, nodes_in_queue, expected_states=["idle"])
    assert_no_msg_in_logs(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        ["Found the following unhealthy static nodes"],
    )


def _test_scontrol_reboot_powerdown_reboot_requested_node(
    remote_command_executor,
    slurm_commands,
    node,
):
    """
    Check that a node in REBOOT_REQUESTED state will be set in POWER_DOWN if requested
    (either manually or by a parameter update strategy).
    """
    jiff = 2

    # Submit a job on the node to have it allocated
    job_id = slurm_commands.submit_command(
        command="sleep 120",
        nodes=1,
        slots=1,
        other_options=f"-w {node}",
    )
    slurm_commands.wait_job_running(job_id)
    assert_compute_node_states(slurm_commands, [node], ["allocated", "mixed"])

    # Request node reboot
    slurm_commands.reboot_compute_node(node, asap=False)
    time.sleep(jiff)
    assert_compute_node_states(slurm_commands, [node], ["mixed@", "allocated@"])

    # Request node power down
    slurm_commands.set_nodes_state([node], "POWER_DOWN_ASAP")
    time.sleep(jiff)
    assert_compute_node_states(slurm_commands, [node], ["draining!"])

    # Check that a new reboot does not change the state
    slurm_commands.reboot_compute_node(node, asap=False)
    time.sleep(jiff)
    assert_compute_node_states(slurm_commands, [node], ["draining!"])

    # The node will be handled as a POWER_DOWN node by clustermgtd
    retry(wait_fixed=seconds(60), stop_max_delay=minutes(10))(assert_errors_in_logs)(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        ["Found the following unhealthy static nodes"],
    )


def _test_scontrol_reboot_powerdown_reboot_issued_node(
    remote_command_executor,
    slurm_commands,
    node,
):
    """
    Check that a node in REBOOT_REQUESTED state will be set in POWER_DOWN if requested
    (either manually or by a parameter update strategy).
    """
    jiff = 2

    assert_compute_node_states(slurm_commands, [node], ["idle"])

    # Request node reboot
    slurm_commands.reboot_compute_node(node, asap=False)
    time.sleep(jiff)
    assert_compute_node_states(slurm_commands, [node], ["reboot^"])

    # Request node power down
    slurm_commands.set_nodes_state([node], "POWER_DOWN_FORCE")
    wait_for_compute_nodes_states(slurm_commands, [node], ["idle%"])

    # Check that a new reboot does not change the state
    slurm_commands.reboot_compute_node(node, asap=False)
    time.sleep(jiff)
    assert_compute_node_states(slurm_commands, [node], ["idle%"])

    # The node will be handled as a POWER_DOWN node by clustermgtd
    retry(wait_fixed=seconds(60), stop_max_delay=minutes(10))(assert_errors_in_logs)(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        ["Found the following unhealthy static nodes"],
    )
