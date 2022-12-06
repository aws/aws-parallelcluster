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
from tags_utils import convert_tags_dicts_to_tags_list, get_compute_node_tags
from time_utils import minutes, seconds
from utils import check_status, get_compute_nodes_instance_ids, get_instance_info, wait_for_computefleet_changed

from tests.common.assertions import (
    assert_lines_in_logs,
    assert_msg_in_log,
    assert_no_errors_in_logs,
    assert_no_msg_in_logs,
    assert_no_node_in_ec2,
    assert_num_instances_constant,
    assert_num_instances_in_cluster,
    assert_scaling_worked,
    wait_for_num_instances_in_cluster,
)
from tests.common.hit_common import (
    assert_compute_node_reasons,
    assert_compute_node_states,
    assert_initial_conditions,
    assert_num_nodes_in_scheduler,
    get_partition_nodes,
    submit_initial_job,
    wait_for_compute_nodes_states,
    wait_for_num_nodes_in_scheduler,
)
from tests.common.mpi_common import compile_mpi_ring
from tests.common.schedulers_common import TorqueCommands


@pytest.mark.usefixtures("instance", "os")
def test_slurm(
    region, scheduler, pcluster_config_reader, clusters_factory, test_datadir, architecture, scheduler_commands_factory
):
    """
    Test all AWS Slurm related features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    scaledown_idletime = 3
    gpu_instance_type = "g3.4xlarge"
    gpu_instance_type_info = get_instance_info(gpu_instance_type, region)
    # For OSs running _test_mpi_job_termination, spin up 2 compute nodes at cluster creation to run test
    # Else do not spin up compute node and start running regular slurm tests
    supports_impi = architecture == "x86_64"
    compute_node_bootstrap_timeout = 1600
    cluster_config = pcluster_config_reader(
        scaledown_idletime=scaledown_idletime,
        gpu_instance_type=gpu_instance_type,
        compute_node_bootstrap_timeout=compute_node_bootstrap_timeout,
    )
    cluster = clusters_factory(cluster_config, upper_case_cluster_name=True)
    remote_command_executor = RemoteCommandExecutor(cluster)
    clustermgtd_conf_path = _retrieve_clustermgtd_conf_path(remote_command_executor)
    slurm_root_path = _retrieve_slurm_root_path(remote_command_executor)
    slurm_commands = scheduler_commands_factory(remote_command_executor)
    _test_slurm_version(remote_command_executor)

    if supports_impi:
        _test_mpi_job_termination(remote_command_executor, test_datadir, slurm_commands, region, cluster)

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
    # Test compute node bootstrap timeout
    if scheduler == "slurm":  # TODO enable this once bootstrap_timeout feature is implemented in slurm plugin
        _test_compute_node_bootstrap_timeout(
            cluster,
            pcluster_config_reader,
            remote_command_executor,
            compute_node_bootstrap_timeout,
            scaledown_idletime,
            gpu_instance_type,
            clustermgtd_conf_path,
            slurm_root_path,
        )


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
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
def test_slurm_scaling(
    scheduler, region, instance, pcluster_config_reader, clusters_factory, test_datadir, scheduler_commands_factory
):
    """Test that slurm-specific scaling logic is behaving as expected for normal actions and failures."""
    cluster_config = pcluster_config_reader(scaledown_idletime=3)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    _assert_cluster_initial_conditions(scheduler_commands, 20, 20, 4)
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
def test_error_handling(
    scheduler, region, instance, pcluster_config_reader, clusters_factory, test_datadir, scheduler_commands_factory
):
    """Test that slurm-specific scaling logic can handle rare failures."""
    cluster_config = pcluster_config_reader(scaledown_idletime=3)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_root_path = _retrieve_slurm_root_path(remote_command_executor)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    _assert_cluster_initial_conditions(scheduler_commands, 10, 10, 1)
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
        slurm_root_path,
        partition="ondemand1",
        num_static_nodes=1,
    )
    # Next test will introduce error in logs, assert no error now
    assert_no_errors_in_logs(remote_command_executor, scheduler)
    _test_clustermgtd_down_logic(
        remote_command_executor,
        scheduler_commands,
        cluster.cfn_name,
        region,
        test_datadir,
        slurm_root_path,
        partition="ondemand1",
        num_static_nodes=1,
        num_dynamic_nodes=1,
        dynamic_instance_type=instance,
    )


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
@pytest.mark.slurm_protected_mode
def test_slurm_protected_mode(
    region,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    s3_bucket_factory,
    scheduler_commands_factory,
):
    """Test that slurm protected mode logic can handle bootstrap failure nodes."""
    # Create S3 bucket for pre-install scripts
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "preinstall.sh"), "scripts/preinstall.sh")
    cluster_config = pcluster_config_reader(bucket=bucket_name)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    clustermgtd_conf_path = _retrieve_clustermgtd_conf_path(remote_command_executor)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    _test_disable_protected_mode(
        remote_command_executor, cluster, bucket_name, pcluster_config_reader, clustermgtd_conf_path
    )
    pending_job_id = _test_active_job_running(scheduler_commands, remote_command_executor, clustermgtd_conf_path)
    _test_protected_mode(scheduler_commands, remote_command_executor, cluster)
    _test_job_run_in_working_queue(scheduler_commands)
    _test_recover_from_protected_mode(pending_job_id, pcluster_config_reader, bucket_name, cluster, scheduler_commands)


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
@pytest.mark.fast_capacity_failover
def test_fast_capacity_failover(
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    clustermgtd_conf_path = _retrieve_clustermgtd_conf_path(remote_command_executor)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    # after the cluster is launched, apply the override patch to launch ice nodes
    remote_command_executor.run_remote_script(str(test_datadir / "overrides.sh"), run_as_root=True)
    nodes_in_scheduler = scheduler_commands.get_compute_nodes("queue1", all_nodes=True)
    static_nodes, dynamic_nodes = get_partition_nodes(nodes_in_scheduler)
    ice_dynamic_nodes = [node for node in dynamic_nodes if "ice-compute-resource" in node]
    static_nodes_in_ice_compute_resource = [node for node in static_nodes if "ice-compute-resource" in node]
    # test enable fast instance capacity failover
    _test_enable_fast_capacity_failover(
        scheduler_commands,
        remote_command_executor,
        clustermgtd_conf_path,
        static_nodes_in_ice_compute_resource,
        ice_dynamic_nodes,
    )
    # remove logs from slurm_resume log and clustermgtd log in order to check logs after disable fast capacity fail-over
    remote_command_executor.run_remote_command("sudo truncate -s 0 /var/log/parallelcluster/slurm_resume.log")
    remote_command_executor.run_remote_command("sudo truncate -s 0 /var/log/parallelcluster/clustermgtd")
    # test disable ice logic
    _test_disable_fast_capacity_failover(
        scheduler_commands,
        remote_command_executor,
        clustermgtd_conf_path,
        static_nodes_in_ice_compute_resource,
        ice_dynamic_nodes,
    )


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
@pytest.mark.slurm_config_update
def test_slurm_config_update(
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    # test update without queue param change, clustermgtd and slurmctld not restart
    _test_update_without_update_queue_params(pcluster_config_reader, cluster, remote_command_executor)
    # test update with queue param change, clustermgtd and slurmctld restart
    _test_update_with_queue_params(
        pcluster_config_reader,
        cluster,
        remote_command_executor,
        config_file="pcluster.config.update_scheduling.yaml",
    )


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
@pytest.mark.slurm_memory_based_scheduling
def test_slurm_memory_based_scheduling(
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = scheduler_commands_factory(remote_command_executor)

    # test Slurm without memory-based scheduling feature
    _test_memory_based_scheduling_enabled_false(
        remote_command_executor,
        slurm_commands,
        test_datadir,
    )

    # test update cluster with memory-based scheduling, clustermgtd and slurmctld restart
    _test_update_with_queue_params(
        pcluster_config_reader,
        cluster,
        remote_command_executor,
        config_file="pcluster.config.mem-based-scheduling.yaml",
    )

    # test Slurm with memory-based scheduling feature
    _test_memory_based_scheduling_enabled_true(
        remote_command_executor,
        slurm_commands,
        test_datadir,
    )

    # Check that jobs submitted prior to an update of SchedulableMemory via queue parameter update
    # strategy can still access the memory requested at submission time
    job_id_1 = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "nodes": 1,
            "slots": 1,
            "command": "srun ./a.out 3500000000 300",
            "other_options": "-w queue1-st-ondemand1-i1-1",
            "raise_on_error": False,
        }
    )
    slurm_commands.wait_job_running(job_id_1)
    node = slurm_commands.get_job_info(job_id_1, field="NodeList")

    updated_config_file = pcluster_config_reader(config_file="pcluster.config.update-schedulable-memory.yaml")
    cluster.update(
        config_file=updated_config_file,
        wait=True,
    )

    retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/slurmctld.log"],
        [f"node {node} memory is overallocated"],
    )
    assert_that(slurm_commands.get_job_info(job_id_1, field="JobState")).is_equal_to("RUNNING")
    slurm_commands.wait_job_completed(job_id_1)
    assert_that(slurm_commands.get_job_info(job_id_1, field="JobState")).is_equal_to("COMPLETED")


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
@pytest.mark.slurm_scontrol_reboot
def test_scontrol_reboot(
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = scheduler_commands_factory(remote_command_executor)

    # Clear clustermgtd logs before starting the tests
    remote_command_executor.run_remote_command("sudo truncate -s 0 /var/log/parallelcluster/clustermgtd")

    # Run first job to wake up dynamic nodes from power_down state
    slurm_commands.submit_command(
        command="hostname",
        nodes=2,
        slots=2,
        constraint="dynamic",
    )
    wait_for_compute_nodes_states(
        slurm_commands,
        ["queue1-dy-t2micro-1", "queue1-dy-t2micro-2"],
        "idle",
        stop_max_delay_secs=330,
    )

    # Test that idle static and dynamic nodes can be rebooted
    _test_scontrol_reboot_nodes(
        remote_command_executor,
        slurm_commands,
        "idle",
    )

    # Run job to allocate all nodes and test that allocated nodes can be rebooted
    job_id_1 = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 150",
            "nodes": 4,
            "slots": 4,
        }
    )
    slurm_commands.wait_job_running(job_id_1)
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


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
def test_update_slurm_reconfigure_race_condition(
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
):
    """
    Test race condition between restart of slurmctld and scontrol reconfigure.

    In Slurm 21.08 it looks like cloud nodes may not get powered-down after their
    SuspendTime has expired if a cluster update is performed, which restarts the
    slurmctld daemon and immediately performs an scontrol reconfigure.

    See https://bugs.schedmd.com/show_bug.cgi?id=13953
    """

    max_count_cr1 = 10
    scale_down_idle_time_mins = 5

    cluster_config = pcluster_config_reader(
        config_file="pcluster.config.yaml",
        output_file="pcluster.config.initial.yaml",
        max_count_cr1=max_count_cr1,
        scale_down_idle_time_mins=scale_down_idle_time_mins,
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = scheduler_commands_factory(remote_command_executor)

    assert_compute_node_states(slurm_commands, compute_nodes=None, expected_states=["idle~"])

    max_retries = 5
    for iter in range(1, max_retries + 1):

        job_id_1 = slurm_commands.submit_command_and_assert_job_accepted(
            submit_command_args={
                "nodes": 2,
                "slots": 2,
                "command": "srun sleep 300",
                "raise_on_error": False,
            }
        )
        slurm_commands.wait_job_running(job_id_1)
        nodelist = slurm_commands.get_job_info(job_id_1, field="NodeList")
        nodes = remote_command_executor.run_remote_command(
            f"sinfo -N --nodes {nodelist} -h -O NodeHost:100 | sort | uniq"
        ).stdout.splitlines()
        nodes = [node.strip() for node in nodes]
        slurm_commands.cancel_job(job_id_1)

        max_count_cr1 = max_count_cr1 + 3

        updated_config_file = pcluster_config_reader(
            config_file="pcluster.config.yaml",
            output_file=f"pcluster.config.iter_{iter}.yaml",
            max_count_cr1=max_count_cr1,
            scale_down_idle_time_mins=scale_down_idle_time_mins,
        )
        cluster.update(
            config_file=updated_config_file,
            wait=True,
        )

        # Check that nodes get powered down by Slurm.
        retry(wait_fixed=seconds(30), stop_max_delay=minutes(2 * scale_down_idle_time_mins))(
            assert_compute_node_states
        )(
            scheduler_commands=slurm_commands,
            compute_nodes=nodes,
            expected_states=["idle%"],
        )


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
def test_slurm_overrides(
    scheduler,
    region,
    pcluster_config_reader,
    s3_bucket_factory,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
):
    """Test that run-instances and create-fleet overrides is behaving as expected."""

    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "launch_override.sh"), "launch_override.sh")

    cluster_config = pcluster_config_reader(bucket_name=bucket_name)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    # submit two jobs in the two partitions using run-instances and create-fleet overrides.
    scheduler_commands.submit_command("sleep 1", partition="fleet")
    scheduler_commands.submit_command("sleep 1", partition="single")

    # Wait slurm_resume and instances to start
    wait_for_num_instances_in_cluster(cluster.cfn_name, cluster.region, desired=2)

    # Assert override file is loaded correctly
    slurm_resume_log = "/var/log/parallelcluster/slurm_resume.log"
    assert_no_msg_in_logs(
        remote_command_executor,
        [slurm_resume_log],
        [
            "Unable to read file '/opt/slurm/etc/pcluster/run_instances_overrides.json' due to an exception",
            "Unable to read file '/opt/slurm/etc/pcluster/create_fleet_overrides.json' due to an exception",
        ],
    )

    # Assert the Tags configured through override setting are correctly attached to the instances
    for partition, api in [("fleet", "CreateFleet"), ("single", "RunInstances")]:
        node_tags = get_compute_node_tags(cluster, queue_name=partition)
        assert_that(node_tags).contains(
            *convert_tags_dicts_to_tags_list([{f"override{partition}": f"override{partition}"}])
        )
        assert_msg_in_log(remote_command_executor, slurm_resume_log, f"Found {api} parameters override")

    assert_no_errors_in_logs(remote_command_executor, scheduler)


def _assert_cluster_initial_conditions(
    scheduler_commands, expected_num_dummy, expected_num_instance_node, expected_num_static
):
    """Assert that expected nodes are in cluster."""
    cluster_node_states = scheduler_commands.get_nodes_status()
    c5l_nodes, instance_nodes, static_nodes = [], [], []
    logging.info(cluster_node_states)
    for nodename, node_states in cluster_node_states.items():
        if "dummy" in nodename:
            c5l_nodes.append(nodename)
        if "-ondemand" in nodename:
            instance_nodes.append(nodename)
        if node_states == "idle":
            if "-st-" in nodename:
                static_nodes.append(nodename)
    assert_that(len(c5l_nodes)).is_equal_to(expected_num_dummy)
    assert_that(len(instance_nodes)).is_equal_to(expected_num_instance_node)
    assert_that(len(static_nodes)).is_equal_to(expected_num_static)


def _test_online_node_configured_correctly(
    scheduler_commands, partition, num_static_nodes, num_dynamic_nodes, dynamic_instance_type
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
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))(assert_lines_in_logs)(
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
    slurm_root_path,
    partition,
    num_static_nodes,
):
    """Test nodes with failing ec2 status checks are correctly replaced."""
    logging.info("Testing that nodes with failing ec2 status checks are correctly replaced")
    static_nodes, _ = assert_initial_conditions(scheduler_commands, num_static_nodes, 0, partition)
    # Can take up to 15 mins for ec2_status_check to show
    # Need to increase SlurmdTimeout to avoid slurm health check and trigger ec2_status_check code path
    _set_slurmd_timeout(remote_command_executor, slurm_root_path, timeout=10000)
    kill_job_id = _submit_kill_networking_job(
        remote_command_executor, scheduler_commands, partition, node_type="static", num_nodes=num_static_nodes
    )
    # Assert ec2_status_check code path is triggered
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(15))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        ["Setting nodes failing health check type ec2_health_check to DRAIN"],
    )
    scheduler_commands.cancel_job(kill_job_id)
    # Assert static nodes are reset
    _wait_for_node_reset(
        scheduler_commands,
        static_nodes=static_nodes,
        dynamic_nodes=[],
        stop_max_delay_secs=1200,
    )
    assert_num_instances_in_cluster(cluster_name, region, len(static_nodes))
    # Reset SlurmdTimeout to 180s
    _set_slurmd_timeout(remote_command_executor, slurm_root_path, timeout=180)


def _test_clustermgtd_down_logic(
    remote_command_executor,
    scheduler_commands,
    cluster_name,
    region,
    test_datadir,
    slurm_root_path,
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
    logging.info("Retrieving clustermgtd config path before killing it.")
    clustermgtd_conf_path = _retrieve_clustermgtd_conf_path(remote_command_executor)
    clustermgtd_heartbeat_file = _retrieve_clustermgtd_heartbeat_file(remote_command_executor, clustermgtd_conf_path)
    logging.info("Killing clustermgtd and rewriting timestamp file to trigger timeout.")
    remote_command_executor.run_remote_script(str(test_datadir / "slurm_kill_clustermgtd.sh"), run_as_root=True)
    # Overwrite clusterctld heartbeat to trigger timeout path
    timestamp_format = "%Y-%m-%d %H:%M:%S.%f%z"
    overwrite_time_str = datetime(2020, 1, 1, tzinfo=timezone.utc).strftime(timestamp_format)
    remote_command_executor.run_remote_command(
        "echo -n '{0}' | sudo tee {1}".format(overwrite_time_str, clustermgtd_heartbeat_file)
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

    assert_lines_in_logs(
        remote_command_executor,
        ["/var/log/parallelcluster/slurm_resume.log"],
        ["No valid clustermgtd heartbeat detected"],
    )


def _wait_for_node_reset(
    scheduler_commands,
    static_nodes,
    dynamic_nodes,
    wait_fixed_secs=20,
    stop_max_delay_secs=300,
):
    """Wait for static and dynamic nodes to be reset."""
    if static_nodes:
        logging.info("Assert static nodes are placed in DOWN during replacement")
        # DRAIN+DOWN = drained
        wait_for_compute_nodes_states(
            scheduler_commands,
            static_nodes,
            expected_states=["down", "down*", "drained", "drained*"],
            wait_fixed_secs=wait_fixed_secs,
            stop_max_delay_secs=stop_max_delay_secs,
        )
        logging.info("Assert static nodes are replaced")
        wait_for_compute_nodes_states(
            scheduler_commands,
            static_nodes,
            expected_states=["idle"],
            wait_fixed_secs=wait_fixed_secs,
            stop_max_delay_secs=stop_max_delay_secs,
        )
    # dynamic nodes are power saved after SuspendTimeout. static_nodes must be checked first
    if dynamic_nodes:
        logging.info("Assert dynamic nodes are power saved")
        wait_for_compute_nodes_states(
            scheduler_commands,
            dynamic_nodes,
            expected_states=["idle~"],
            wait_fixed_secs=wait_fixed_secs,
            stop_max_delay_secs=stop_max_delay_secs,
        )
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
    if len(compute_nodes) > 0:
        scheduler_commands.set_nodes_state(compute_nodes, state="down")
        assert_compute_node_states(scheduler_commands, compute_nodes, expected_states=["down"])


def _set_nodes_to_power_down_manually(scheduler_commands, compute_nodes):
    if len(compute_nodes) > 0:
        scheduler_commands.set_nodes_state(compute_nodes, state="power_down")
        time.sleep(5)
        scheduler_commands.set_nodes_state(compute_nodes, state="resume")
        assert_compute_node_states(scheduler_commands, compute_nodes, expected_states=["idle~"])


def _terminate_nodes_manually(instance_ids, region):
    ec2_client = boto3.client("ec2", region_name=region)
    for instance_id in instance_ids:
        instance_states = ec2_client.terminate_instances(InstanceIds=[instance_id]).get("TerminatingInstances")[0]
        assert_that(instance_states.get("InstanceId")).is_equal_to(instance_id)
        assert_that(instance_states.get("CurrentState").get("Name")).is_in("shutting-down", "terminated")
    logging.info("Terminated nodes: {}".format(instance_ids))


def _test_mpi_job_termination(remote_command_executor, test_datadir, slurm_commands, region, cluster):
    """
    Test canceling mpirun job will not leave stray processes.

    IntelMPI is known to leave stray processes after job termination if slurm process tracking is not setup correctly,
    i.e. using ProctrackType=proctrack/pgid
    Test IntelMPI script to make sure no stray processes after the job is cancelled
    This bug cannot be reproduced using OpenMPI
    """
    logging.info("Testing no stray process left behind after mpirun job is terminated")

    # Submit mpi_job, which runs Intel MPI benchmarks with intelmpi
    # Leaving 1 vcpu on each node idle so that the process check job can run while mpi_job is running
    result = slurm_commands.submit_script(str(test_datadir / "mpi_job.sh"))
    job_id = slurm_commands.assert_job_submitted(result.stdout)

    # Wait for compute node to start and check that mpi processes are started
    _wait_computefleet_running(region, cluster, remote_command_executor)
    retry(wait_fixed=seconds(30), stop_max_delay=seconds(500))(_assert_job_state)(
        slurm_commands, job_id, job_state="RUNNING"
    )
    _check_mpi_process(remote_command_executor, slurm_commands, num_nodes=2, after_completion=False)
    slurm_commands.cancel_job(job_id)

    # Make sure mpirun job is cancelled
    _assert_job_state(slurm_commands, job_id, job_state="CANCELLED")

    # Check that mpi processes are terminated
    _check_mpi_process(remote_command_executor, slurm_commands, num_nodes=2, after_completion=True)


def _wait_computefleet_running(region, cluster, remote_command_executor):
    """Wait computefleet to finish setup"""
    ec2_client = boto3.client("ec2", region_name=region)
    compute_nodes = cluster.describe_cluster_instances(node_type="Compute")
    for compute in compute_nodes:
        instance_id = compute.get("instanceId")
        _wait_instance_running(ec2_client, [instance_id])
        _wait_compute_cloudinit_done(remote_command_executor, compute)


def _wait_instance_running(ec2_client, instance_ids):
    """Wait EC2 instance to go running"""
    logging.info(f"Waiting for {instance_ids} to be running")
    ec2_client.get_waiter("instance_running").wait(
        InstanceIds=instance_ids, WaiterConfig={"Delay": 60, "MaxAttempts": 5}
    )


@retry(wait_fixed=seconds(10), stop_max_delay=minutes(3))
def _wait_compute_cloudinit_done(remote_command_executor, compute_node):
    """Wait till cloud-init complete on a given compute node"""
    compute_node_private_ip = compute_node.get("privateIpAddress")
    compute_cloudinit_status_output = remote_command_executor.run_remote_command(
        f"ssh -q {compute_node_private_ip} sudo cloud-init status"
    ).stdout
    assert_that(compute_cloudinit_status_output).contains("status: done")


@retry(wait_fixed=seconds(10), stop_max_attempt_number=4)
def _check_mpi_process(remote_command_executor, slurm_commands, num_nodes, after_completion):
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


def _test_slurm_version(remote_command_executor):
    logging.info("Testing Slurm Version")
    version = remote_command_executor.run_remote_command("sinfo -V").stdout
    assert_that(version).is_equal_to("slurm 22.05.6")


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


def _set_slurmd_timeout(remote_command_executor, slurm_root_path, timeout):
    """Set SlurmdTimeout in slurm.conf."""
    remote_command_executor.run_remote_command(
        "sudo sed -i '/SlurmdTimeout/s/=.*/={0}/' {1}/etc/slurm.conf".format(timeout, slurm_root_path)
    )
    remote_command_executor.run_remote_command("sudo -i scontrol reconfigure")
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


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))
def _wait_for_partition_state_changed(scheduler_commands, partition, desired_state):
    assert_that(scheduler_commands.get_partition_state(partition=partition)).is_equal_to(desired_state)


def _update_and_start_cluster(cluster, config_file):
    cluster.stop()
    wait_for_computefleet_changed(cluster, "STOPPED")
    # After cluster stop, add time sleep here to wait longer than SuspendTimeout for nodes turn from
    # powering down(%) to power save(~) to avoid the problem in slurm 21.08.3 before cluster update
    time.sleep(150)
    cluster.update(str(config_file), force_update="true")
    # During cluster update, slurmctld will be restart and clustermgtd restart, nodes will be up during slurmctld
    # restart,and powered down when clustermgtd start. Add time sleep here to wait longer than SuspendTimeout for
    # nodes turn from powering down(% to power save(~) to avoid the problem in slurm 21.08.3
    time.sleep(150)
    cluster.start()
    wait_for_computefleet_changed(cluster, "RUNNING")


def _inject_bootstrap_failures(cluster, bucket_name, pcluster_config_reader):
    """Update cluster to include pre-install script, which introduce bootstrap error."""
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.broken.yaml", bucket=bucket_name)
    _update_and_start_cluster(cluster, updated_config_file)


def _set_protected_failure_count(remote_command_executor, protected_failure_count, clustermgtd_conf_path):
    """Disable protected mode by setting protected_failure_count to -1."""
    remote_command_executor.run_remote_command(
        f"echo 'protected_failure_count = {protected_failure_count}' | sudo tee -a " f"{clustermgtd_conf_path}"
    )


def _enable_protected_mode(remote_command_executor, clustermgtd_conf_path):
    """Enable protected mode by removing lines related to protected mode in the config, so it will be set to default."""
    remote_command_executor.run_remote_command(f"sudo sed -i '/'protected_failure_count'/d' {clustermgtd_conf_path}")


def _test_disable_protected_mode(
    remote_command_executor, cluster, bucket_name, pcluster_config_reader, clustermgtd_conf_path
):
    """Test Bootstrap failures have no affect on cluster when protected mode is disabled."""
    # Disable protected_mode by setting protected_failure_count to -1
    _set_protected_failure_count(remote_command_executor, -1, clustermgtd_conf_path)
    _inject_bootstrap_failures(cluster, bucket_name, pcluster_config_reader)
    # wait till the node failed
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(7))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        [
            "Found the following unhealthy static nodes",
        ],
    )
    # Assert that it does not contain bootstrap failure
    assert_no_msg_in_logs(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        ["Node bootstrap error"],
    )


def _test_active_job_running(scheduler_commands, remote_command_executor, clustermgtd_conf_path):
    """Test cluster is not placed into protected mode when there is an active job running even reach threshold."""
    # Submit a job to the queue contains broken nodes and normal node, submit the job to the normal node to test
    # the queue will not be disabled if there's active job running.
    cancel_job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 3000", "nodes": 1, "partition": "half-broken", "constraint": "c5.xlarge"}
    )
    # Wait for the job to run
    scheduler_commands.wait_job_running(cancel_job_id)

    # Re-enable protected mode
    _enable_protected_mode(remote_command_executor, clustermgtd_conf_path)
    # Decrease protected failure count for quicker enter protected mode.
    _set_protected_failure_count(remote_command_executor, 2, clustermgtd_conf_path)

    # Submit a job to the problematic compute resource, so the protected_failure count will increase
    job_id_pending = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 60", "nodes": 2, "partition": "half-broken", "constraint": "c5.large"}
    )
    # Check the threshold reach but partition will be still UP since there's active job running
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(7))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        [
            "currently have jobs running, not disabling them",
        ],
    )
    assert_that(scheduler_commands.get_partition_state(partition="half-broken")).is_equal_to("UP")
    # Cancel the job
    scheduler_commands.cancel_job(cancel_job_id)
    return job_id_pending


def _test_protected_mode(scheduler_commands, remote_command_executor, cluster):
    """Test cluster will be placed into protected mode when protected count reach threshold and no job running."""
    # See if the cluster can be put into protected mode when there's no job running after reaching threshold
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(7))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        [
            "Setting cluster into protected mode due to failures detected in node provisioning",
            "Placing bootstrap failure partitions to INACTIVE",
            "Updating compute fleet status from RUNNING to PROTECTED",
            "is in power up state without valid backing instance",
        ],
    )
    # Assert bootstrap failure queues are inactive and compute fleet status is PROTECTED
    check_status(cluster, compute_fleet_status="PROTECTED")
    assert_that(scheduler_commands.get_partition_state(partition="normal")).is_equal_to("UP")
    _wait_for_partition_state_changed(scheduler_commands, "broken", "INACTIVE")
    _wait_for_partition_state_changed(scheduler_commands, "half-broken", "INACTIVE")


def _test_job_run_in_working_queue(scheduler_commands):
    """After enter protected state, submit a job to the active queue to make sure it can still run jobs."""
    job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 1", "nodes": 2, "partition": "normal"}
    )
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)


def _test_recover_from_protected_mode(
    incomplete_job_id, pcluster_config_reader, bucket_name, cluster, scheduler_commands
):
    """
    Test cluster after recovering from protected mode.

    Test previous pending job can run successfully.
    Test all queues can run jobs.
    """
    # Update the cluster again, remove the pre-install script to make the cluster work as expected
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.recover.yaml", bucket=bucket_name)
    _update_and_start_cluster(cluster, updated_config_file)
    # Assert all queues are UP
    assert_that(scheduler_commands.get_partition_state(partition="normal")).is_equal_to("UP")
    assert_that(scheduler_commands.get_partition_state(partition="broken")).is_equal_to("UP")
    assert_that(scheduler_commands.get_partition_state(partition="half-broken")).is_equal_to("UP")
    # Pending job that is in the queue when cluster entered protected mode will be run again when cluster is
    # taken out of protected mode.
    scheduler_commands.wait_job_completed(incomplete_job_id)
    scheduler_commands.assert_job_succeeded(incomplete_job_id)
    # Job can be run succesfully in all queues
    for partition in ["normal", "broken", "half-broken"]:
        job_id = scheduler_commands.submit_command_and_assert_job_accepted(
            submit_command_args={"command": "sleep 1", "partition": partition}
        )
        scheduler_commands.wait_job_completed(job_id)
        scheduler_commands.assert_job_succeeded(job_id)
    # Test after pcluster stop and then start, static nodes are not treated as bootstrap failure nodes,
    # not enter protected mode
    check_status(cluster, compute_fleet_status="RUNNING")


def _test_compute_node_bootstrap_timeout(
    cluster,
    pcluster_config_reader,
    remote_command_executor,
    compute_node_bootstrap_timeout,
    scaledown_idletime,
    gpu_instance_type,
    clustermgtd_conf_path,
    slurm_root_path,
):
    """Test compute_node_bootstrap_timeout is passed into slurm.conf and parallelcluster_clustermgtd.conf."""
    slurm_parallelcluster_conf = remote_command_executor.run_remote_command(
        "sudo cat {}/etc/slurm_parallelcluster.conf".format(slurm_root_path)
    ).stdout
    assert_that(slurm_parallelcluster_conf).contains(f"ResumeTimeout={compute_node_bootstrap_timeout}")
    clustermgtd_conf = remote_command_executor.run_remote_command(f"sudo cat {clustermgtd_conf_path}").stdout
    assert_that(clustermgtd_conf).contains(f"node_replacement_timeout = {compute_node_bootstrap_timeout}")
    # Update cluster
    update_compute_node_bootstrap_timeout = 1200
    updated_config_file = pcluster_config_reader(
        scaledown_idletime=scaledown_idletime,
        gpu_instance_type=gpu_instance_type,
        compute_node_bootstrap_timeout=update_compute_node_bootstrap_timeout,
        config_file="pcluster.update.config.yaml",
    )
    _update_and_start_cluster(cluster, updated_config_file)
    slurm_parallelcluster_conf = remote_command_executor.run_remote_command(
        "sudo cat {}/etc/slurm_parallelcluster.conf".format(slurm_root_path)
    ).stdout
    assert_that(slurm_parallelcluster_conf).contains(f"ResumeTimeout={update_compute_node_bootstrap_timeout}")
    clustermgtd_conf = remote_command_executor.run_remote_command(f"sudo cat {clustermgtd_conf_path}").stdout
    assert_that(clustermgtd_conf).contains(f"node_replacement_timeout = {update_compute_node_bootstrap_timeout}")
    assert_that(clustermgtd_conf).does_not_contain(f"node_replacement_timeout = {compute_node_bootstrap_timeout}")


def _retrieve_slurm_root_path(remote_command_executor):
    return remote_command_executor.run_remote_command("dirname $(dirname $(which scontrol))").stdout


def _retrieve_clustermgtd_conf_path(remote_command_executor):
    clustermgtd_conf_path = "/etc/parallelcluster/slurm_plugin/parallelcluster_clustermgtd.conf"
    clustermgtd_conf_path_override = remote_command_executor.run_remote_command(
        "sudo strings /proc/$(pgrep -f bin/clustermgtd$)/environ | grep CONFIG_FILE= | cut -d '=' -f2"
    ).stdout
    if clustermgtd_conf_path_override:
        clustermgtd_conf_path = clustermgtd_conf_path_override
    return clustermgtd_conf_path


def _retrieve_clustermgtd_heartbeat_file(remote_command_executor, clustermgtd_conf_path):
    return remote_command_executor.run_remote_command(
        f"cat {clustermgtd_conf_path} | grep heartbeat_file_path | cut -d '=' -f2 | xargs"
    ).stdout


def _set_insufficient_capacity_timeout(remote_command_executor, insufficient_capacity_timeout, clustermgtd_conf_path):
    """Set insufficient_capacity_timeout in clustermgtd conf."""
    remote_command_executor.run_remote_command(
        f"sudo sed -i '/'insufficient_capacity_timeout'/d' {clustermgtd_conf_path}"
    )
    remote_command_executor.run_remote_command(
        f"echo 'insufficient_capacity_timeout = {insufficient_capacity_timeout}' | sudo tee -a "
        f"{clustermgtd_conf_path}"
    )


def _enable_fast_capacity_failover(remote_command_executor, clustermgtd_conf_path):
    """Enable protected mode by removing lines related to protected mode in the config, so it will be set to default."""
    remote_command_executor.run_remote_command(
        f"sudo sed -i '/'insufficient_capacity_timeout'/d' {clustermgtd_conf_path}"
    )


def _test_disable_fast_capacity_failover(
    scheduler_commands,
    remote_command_executor,
    clustermgtd_conf_path,
    static_nodes_in_ice_compute_resource,
    ice_dynamic_nodes,
):
    """Test fast capacity failover has no effect on cluster when it is disabled."""
    # set insufficient_capacity_timeout to 0 to disable fast instance capacity failover logic
    _set_insufficient_capacity_timeout(remote_command_executor, 0, clustermgtd_conf_path)
    # submit a job to trigger insufficient capacity
    job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 30",
            "nodes": 2,
            "other_options": "--no-requeue",
            "constraint": "c5.large",
        }
    )
    # wait till the node failed to launch
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/parallelcluster/slurm_resume.log"],
        [
            "InsufficientInstanceCapacity",
        ],
    )
    # assert that ice node is detected as unhealthy node
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(2))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        [
            "Found the following unhealthy dynamic nodes",
        ],
    )
    # Assert that clustermgtd log doesn't contains insufficient capacity compute resources
    assert_no_msg_in_logs(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        ["The following compute resources are in down state due to insufficient capacity"],
    )

    # wait until job failed
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_state(job_id, "NODE_FAIL")
    # wait for nodes reset
    wait_for_compute_nodes_states(scheduler_commands, static_nodes_in_ice_compute_resource, expected_states=["idle"])
    wait_for_compute_nodes_states(scheduler_commands, ice_dynamic_nodes, expected_states=["idle~"])


def assert_job_requeue_in_time(scheduler_commands, job_id):
    """Test that job will requeue to a different compute resource after AuthInfo=cred_expire=70 timeout."""
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
    submit_time = datetime.strptime(scheduler_commands.get_job_submit_time(job_id), "%Y-%m-%dT%H:%M:%S")
    eligible_time = datetime.strptime(scheduler_commands.get_job_eligible_time(job_id), "%Y-%m-%dT%H:%M:%S")
    wait_seconds = (eligible_time - submit_time).total_seconds()
    # Test it takes less than 2 minutes a job is re-queued to a different compute resource."""
    assert_that(wait_seconds).is_less_than_or_equal_to(120)


def _test_enable_fast_capacity_failover(
    scheduler_commands,
    remote_command_executor,
    clustermgtd_conf_path,
    static_nodes_in_ice_compute_resource,
    ice_dynamic_nodes,
):
    # set insufficient_capacity_timeout to 180 seconds to quicker reset compute resources
    _set_insufficient_capacity_timeout(remote_command_executor, 180, clustermgtd_conf_path)
    # trigger insufficient capacity
    job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 30", "nodes": 2}
    )
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(3))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        [
            "The following compute resources are in down state due to insufficient capacity",
        ],
    )
    # test static nodes in ice compute resource are up
    assert_compute_node_states(
        scheduler_commands, static_nodes_in_ice_compute_resource, expected_states=["idle", "mixed", "allocated"]
    )
    # test dynamic nodes in ice compute resource are down
    assert_compute_node_states(scheduler_commands, ice_dynamic_nodes, expected_states=["down#", "down~"])
    assert_compute_node_reasons(scheduler_commands, ice_dynamic_nodes, "(Code:InsufficientInstanceCapacity)")
    # test job takes less than 2 minutes to requeue
    scheduler_commands.wait_job_completed(job_id)
    assert_job_requeue_in_time(scheduler_commands, job_id)

    # check insufficient timeout expired
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(4))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        [
            "Reset the following compute resources because insufficient capacity timeout expired",
        ],
    )
    # check dynamic nodes in ice compute resource are reset after insufficient_capacity_timeout expired
    _wait_for_node_reset(scheduler_commands, static_nodes=[], dynamic_nodes=ice_dynamic_nodes)
    # test insufficient capacity does not trigger protected mode
    assert_no_msg_in_logs(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        ["Node bootstrap error"],
    )


def _test_update_without_update_queue_params(pcluster_config_reader, cluster, remote_command_executor):
    """Test update without queue param change, clustermgtd and slurmctld not restart."""
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.update.yaml")
    _update_and_start_cluster(cluster, updated_config_file)
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(2))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/chef-client.log"],
        [
            "Recipe: aws-parallelcluster-slurm::update_head_node",
            "Processing execute\\[stop clustermgtd\\]",
            "Processing service\\[slurmctld\\] action restart",
        ],
    )
    assert_no_msg_in_logs(
        remote_command_executor,
        ["/var/log/chef-client.log"],
        ["INFO: execute\\[stop clustermgtd\\] ran successfully", "INFO: service\\[slurmctld\\] restarted"],
    )


def _test_update_with_queue_params(
    pcluster_config_reader,
    cluster,
    remote_command_executor,
    config_file,
):
    """Test update queue param change, clustermgtd and slurmctld restart."""
    updated_config_file = pcluster_config_reader(config_file=config_file)
    _update_and_start_cluster(cluster, updated_config_file)
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(2))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/chef-client.log"],
        [
            "INFO: execute\\[stop clustermgtd\\] ran successfully",
            "INFO: service\\[slurmctld\\] restarted",
        ],
    )


def _test_memory_based_scheduling_enabled_false(
    remote_command_executor,
    slurm_commands,
    test_datadir,
):
    """Test Slurm without memory-based scheduling feature enabled"""

    jiff = 2

    # check that memory-based scheduling is disabled by default
    assert_that(slurm_commands.get_conf_param("SelectTypeParameters")).is_equal_to("CR_CPU")
    assert_that(slurm_commands.get_conf_param("ConstrainRAMSpace")).is_equal_to("no")

    # check default value of node_reg_mem_percent
    assert_that(slurm_commands.get_conf_param("SlurmctldParameters")).contains("node_reg_mem_percent=75")

    # check values of RealMemory at default settings
    assert_that(slurm_commands.get_node_attribute("queue1-st-ondemand1-i1-1", "Memory")).is_equal_to("3891")
    assert_that(slurm_commands.get_node_attribute("queue1-dy-ondemand1-i3-1", "Memory")).is_equal_to("31129")

    # Upload files for memory allocation tests
    remote_command_executor._copy_additional_files(
        [
            str(test_datadir / "memory_allocation_chars.c"),
        ],
    )

    # Compile C program to test memory allocations
    remote_command_executor.run_remote_command("gcc memory_allocation_chars.c")
    remote_command_executor.run_remote_command("ls ./a.out")

    # Check that I can use the `--mem` flag to filter compute nodes
    # Try to allocate on nodes with not enough memory
    result = slurm_commands.submit_command(
        nodes=1,
        command="sleep 1",
        constraint="ondemand1-i1",
        other_options="--mem=4000 --test-only",
        raise_on_error=False,
    )
    assert_that(result.stdout).is_equal_to("allocation failure: Requested node configuration is not available")

    # Check that compatible nodes would be selected
    result = slurm_commands.submit_command(
        nodes=1,
        command="sleep 1",
        other_options="--mem=4000 --test-only",
        raise_on_error=False,
    )
    assert_that(result.stdout).matches(r"^.*Job \d* to start.*$")
    assert_that(result.stdout).does_not_contain("ondemand1-i1")

    # Check that the `--mem` option only filters compute nodes instead of managing memory required by jobs
    job_id_1 = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "nodes": 1,
            "slots": 1,
            "command": "sleep 30",
            "other_options": "--mem=2000 -w queue1-st-ondemand1-i1-1",
            "raise_on_error": False,
        }
    )
    job_id_2 = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "nodes": 1,
            "slots": 1,
            "command": "sleep 30",
            "other_options": "--mem=2000 -w queue1-st-ondemand1-i1-1",
            "raise_on_error": False,
        }
    )
    time.sleep(jiff)
    assert_that(slurm_commands.get_job_info(job_id_1, field="JobState")).is_equal_to("RUNNING")
    assert_that(slurm_commands.get_job_info(job_id_2, field="JobState")).is_equal_to("RUNNING")
    # Here two jobs submitted with `--mem=2000` can fit on a node with less than 4000 MiB memory
    # because without memory as consumable resource, Slurm doesn't track the memory usage of
    # each job.
    assert_that(slurm_commands.get_job_info(job_id_1, field="NodeList")).is_equal_to(
        slurm_commands.get_job_info(job_id_2, field="NodeList")
    )
    slurm_commands.wait_job_completed(job_id_1)
    slurm_commands.wait_job_completed(job_id_2)

    # Check that without memory constraining, jobs might contend memory on the compute node
    # (memory constraining makes sense only if memory is set as consumable resource)
    job_id_1 = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "nodes": 1,
            "slots": 1,
            "command": "srun ./a.out 2000000000",
            "other_options": "--mem=2500 -w queue1-st-ondemand1-i1-1",
            "raise_on_error": False,
        }
    )
    time.sleep(jiff)
    job_id_2 = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "nodes": 1,
            "slots": 1,
            "command": "srun ./a.out 2000000000",
            "other_options": "--mem=2500 -w queue1-st-ondemand1-i1-1",
            "raise_on_error": False,
        }
    )
    slurm_commands.wait_job_completed(job_id_1)
    slurm_commands.wait_job_completed(job_id_2)
    # In this scenario the second job will have stolen memory from the first job, causing
    # it to fail
    assert_that(slurm_commands.get_job_info(job_id_1, field="JobState")).is_equal_to("FAILED")
    assert_that(slurm_commands.get_job_info(job_id_2, field="JobState")).is_equal_to("COMPLETED")


def _test_memory_based_scheduling_enabled_true(
    remote_command_executor,
    slurm_commands,
    test_datadir,
):
    """Test Slurm with memory-based scheduling feature enabled"""

    jiff = 2

    # check that memory-based scheduling is now enabled
    assert_that(slurm_commands.get_conf_param("SelectTypeParameters")).is_equal_to("CR_CPU_MEMORY")
    assert_that(slurm_commands.get_conf_param("ConstrainRAMSpace")).is_equal_to("yes")

    # check RealMemory overridden via config file parameter
    assert_that(slurm_commands.get_node_attribute("queue1-dy-ondemand1-i3-1", "Memory")).is_equal_to("31400")

    assert_that(remote_command_executor.run_remote_command("ls ./a.out").stdout).contains("a.out")

    # Check that the `--mem-per-cpu` option works as expected with memory-based scheduling enabled
    result = slurm_commands.submit_command(
        nodes=1,
        slots=2,
        command="sleep 1",
        constraint="ondemand1-i1",
        other_options="-c 1 --mem-per-cpu=2000 --test-only",
        raise_on_error=False,
    )
    assert_that(result.stdout).is_equal_to("allocation failure: Requested node configuration is not available")

    wait_for_compute_nodes_states(slurm_commands, ["queue1-st-ondemand1-i1-1"], ["idle"])

    # Check that now `--mem` also defines the amount of memory used by the job
    job_id_1 = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "nodes": 1,
            "slots": 1,
            "command": "sleep 30",
            "other_options": "--mem=2000 -w queue1-st-ondemand1-i1-1",
            "raise_on_error": False,
        }
    )
    time.sleep(jiff)
    job_id_2 = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "nodes": 1,
            "slots": 2,
            "command": "sleep 10",
            "other_options": "-c 1 --mem-per-cpu=1000 -w queue1-st-ondemand1-i1-1",
            "raise_on_error": False,
        }
    )
    time.sleep(jiff)
    # Here two jobs submitted with `--mem=2000` cannot fit on a node with less than 4000 MiB memory
    # The second job will run only after the first one has finished
    assert_that(slurm_commands.get_job_info(job_id_1, field="JobState")).is_equal_to("RUNNING")
    assert_that(slurm_commands.get_job_info(job_id_2, field="JobState")).is_equal_to("PENDING")
    # Check that memory appears in the TRES allocated for the job
    assert_that(slurm_commands.get_job_info(job_id_1, field="TRES")).contains("mem=2000M")
    assert_that(slurm_commands.get_job_info(job_id_2, field="TRES")).contains("mem=2000M")
    slurm_commands.wait_job_completed(job_id_1)
    slurm_commands.wait_job_completed(job_id_2)

    # Check that a job cannot access more than the memory requested to the scheduler
    job_id_1 = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "nodes": 1,
            "slots": 1,
            "command": "srun ./a.out 2000000000",
            "other_options": "--mem=1000 -w queue1-st-ondemand1-i1-1",
            "raise_on_error": False,
        }
    )
    job_id_2 = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "nodes": 1,
            "slots": 1,
            "command": "srun ./a.out 2000000000",
            "other_options": "--mem=2500 -w queue1-st-ondemand1-i1-1",
            "raise_on_error": False,
        }
    )
    slurm_commands.wait_job_completed(job_id_1)
    assert_that(slurm_commands.get_job_info(job_id_1, field="JobState")).is_equal_to("FAILED")
    slurm_commands.wait_job_completed(job_id_2)
    assert_that(slurm_commands.get_job_info(job_id_2, field="JobState")).is_equal_to("COMPLETED")


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
        assert_compute_node_states(slurm_commands, nodes_in_queue, ["idle"])
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
    job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 120",
            "nodes": 1,
            "slots": 1,
            "other_options": f"-w {node}",
        },
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
    retry(wait_fixed=seconds(60), stop_max_delay=minutes(10))(assert_lines_in_logs)(
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
    retry(wait_fixed=seconds(60), stop_max_delay=minutes(10))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        ["Found the following unhealthy static nodes"],
    )
