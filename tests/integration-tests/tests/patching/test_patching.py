# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

import boto3
from assertpy import assert_that, soft_assertions
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds

from tests.common.login_nodes_utils import wait_for_login_fleet_stop
from tests.common.osu_common import PRIVATE_OSES
from tests.common.utils import (
    COMPUTE_NODE,
    GPU_JOB_SCRIPT,
    HEAD_NODE,
    LOGIN_NODE,
    NODE_TYPES,
    reboot_head_node,
    retrieve_cluster_head_node_ami,
    wait_node_reachable,
)

# Time budget (seconds) for the OS security patching to complete on the head node.
PATCHING_TIMEOUT = 1800

# Snhared storage mount dir
FSX_LUSTRE_MOUNT_DIR = "/shared-fsxlustre"


def test_patching_cluster(
    region,
    os,
    instance,
    scheduler,
    vpc_stack,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
    patched_ami_factory,
    request,
):
    """
    Validate that users can self-patch their clusters.

    Flow:
      1.  Create a cluster.
      2.  Read the AMI it uses from its CloudFormation stack template.
      3.  Bake a patched AMI from that AMI.
      4.  Wait for the cluster creation to complete.
      5.  Run a baseline GPU workload from head node and login node
      6.  Snapshot the loaded kernel modules.
      7.  Stop the login nodes.
      8.  Update the cluster to the patched AMI and wait for nodes to be replaced.
      9.  Patch and reboot the head node, then wait for it to be reachable over SSH.
      10. Re-run the GPU workload from head node and login node.
      11. Assert that every kernel module loaded before patching is still loaded, on each node type.
    """
    ec2 = boto3.client("ec2", region_name=region)

    # Start the cluster creation but do not block on it: the AMI patching below
    # runs concurrently while the cluster comes up.
    create_config = pcluster_config_reader(
        output_file="pcluster.config.create.yaml", login_nodes_count=1, fsx_lustre_mount_dir=FSX_LUSTRE_MOUNT_DIR
    )
    cluster = clusters_factory(create_config, wait=False)

    # Use the exact AMI the cluster uses as the source for patching, read from the
    # cluster stack template instead of resolving it with a separate AMI lookup.
    base_ami = retrieve_cluster_head_node_ami(cluster, region)
    logging.info("Cluster is created with AMI %s", base_ami)

    # Pin the AMI on updates only for private OSes (rocky8/rocky9), where the framework
    # re-injects the latest private AMI on every render and an update would otherwise
    # drift to a newer, possibly not-yet-available, AMI. None means no pin.
    base_ami_pin = base_ami if os in PRIVATE_OSES else None

    # Bake the patched AMI while the cluster is still being created. The builder
    # instance uses the same GPU instance type as the cluster nodes.
    patched_ami = patched_ami_factory(base_ami, instance)
    logging.info("Patched AMI is %s", patched_ami)

    # Wait for the cluster creation to complete before using it.
    logging.info("Waiting for cluster %s to reach CREATE_COMPLETE", cluster.name)
    cluster.wait_cluster_status("CREATE_COMPLETE")

    # Snapshot the loaded kernel modules on the head, compute and login nodes before
    # patching so we can later assert the same modules remain loaded.
    kernel_modules_before = _collect_loaded_kernel_modules(cluster, scheduler_commands_factory)
    logging.info("Kernel modules loaded before patching: %s", kernel_modules_before)

    # GPU workload BEFORE patching, from the head node and login node (baseline).
    _run_gpu_workload(cluster, scheduler_commands_factory, use_login_node=False)
    _run_gpu_workload(cluster, scheduler_commands_factory, use_login_node=True)

    # Stop the login nodes (required before changing the login pool image). For private
    # OSes the cluster is pinned (via base_ami_pin) to the AMI it was created with so
    # this update does not drift to a newer AMI.
    stop_login_config = pcluster_config_reader(
        output_file="pcluster.config.stop-login.yaml",
        login_nodes_count=0,
        base_ami=base_ami_pin,
        fsx_lustre_mount_dir=FSX_LUSTRE_MOUNT_DIR,
    )
    cluster.update(str(stop_login_config))
    wait_for_login_fleet_stop(cluster)
    logging.info("Login nodes stopped")

    # Update the cluster so login and compute nodes use the patched AMI. For private
    # OSes the head node stays pinned (via base_ami_pin) to the AMI the cluster was
    # created with, so only compute and login move to the patched AMI.
    update_config = pcluster_config_reader(
        output_file="pcluster.config.update-ami.yaml",
        login_nodes_count=1,
        base_ami=base_ami_pin,
        patched_ami=patched_ami,
        fsx_lustre_mount_dir=FSX_LUSTRE_MOUNT_DIR,
    )
    cluster.update(str(update_config))

    # With QueueUpdateStrategy DRAIN the static compute node is drained and replaced
    # asynchronously after the update completes, and the login pool is recreated, so
    # wait for both to come back running the patched AMI.
    logging.info("Waiting for compute and login nodes to be replaced with the patched AMI")
    _wait_instances_using_ami(ec2, cluster, "Compute", patched_ami)
    _wait_instances_using_ami(ec2, cluster, "LoginNode", patched_ami)

    # Patch the head node in place and reboot it.
    remote_command_executor = RemoteCommandExecutor(cluster)
    logging.info("Patching the head node")
    patch_result = remote_command_executor.run_remote_script(
        str(test_datadir / "patch_node.sh"), run_as_root=True, timeout=PATCHING_TIMEOUT
    )
    logging.info("Head node patching script output:\n%s", patch_result.stdout)
    reboot_head_node(cluster)

    # Verify the head node is reachable over SSH again after the reboot (and that
    # the patch left it healthy) before exercising the cluster further.
    wait_node_reachable(cluster, cluster.head_node_ip)

    # GPU workload AFTER patching, from the head node and login node.
    _run_gpu_workload(cluster, scheduler_commands_factory, use_login_node=False)
    _run_gpu_workload(cluster, scheduler_commands_factory, use_login_node=True)

    # Snapshot and log the kernel modules loaded after patching, then assert (softly,
    # so every node type is reported even if one fails) that every module loaded
    # before patching is still loaded on the head, compute and login nodes.
    kernel_modules_after = _collect_loaded_kernel_modules(
        cluster, scheduler_commands_factory, trigger_head_node_mount=True
    )
    logging.info("Kernel modules loaded after patching: %s", kernel_modules_after)
    with soft_assertions():
        for node_type in NODE_TYPES:
            missing = kernel_modules_before[node_type] - kernel_modules_after[node_type]
            assert_that(missing).described_as(f"kernel modules no longer loaded on the {node_type}").is_empty()


@retry(stop_max_delay=minutes(15), wait_fixed=seconds(30), retry_on_result=lambda replaced: not replaced)
def _wait_instances_using_ami(ec2, cluster, node_type, expected_ami):
    """Wait until all instances of the given node type are running the expected AMI.

    Used after a DRAIN-strategy update, where the static compute node is replaced
    asynchronously and the login pool is recreated, so the new instances may not be
    up (or may briefly coexist with the old ones) right after the update completes.
    """
    instance_ids = cluster.get_cluster_instance_ids(node_type=node_type)
    if not instance_ids:
        return False
    amis = {
        ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]["ImageId"]
        for instance_id in instance_ids
    }
    logging.info("%s instances %s on AMIs %s (expected %s)", node_type, instance_ids, amis, expected_ami)
    using_patched_ami = amis == {expected_ami}
    if using_patched_ami:
        logging.info(
            "Detected new %s node(s) %s now running the patched AMI %s",
            node_type,
            instance_ids,
            expected_ami,
        )
    return using_patched_ami


def _run_gpu_workload(cluster, scheduler_commands_factory, use_login_node):
    """Submit a CUDA sample onto the GPU partition and assert success.

    The job is submitted from the login node when use_login_node is True, otherwise
    from the head node.
    """
    source = "login node" if use_login_node else "head node"
    logging.info("Submitting GPU validation job from the %s", source)
    remote_command_executor = RemoteCommandExecutor(cluster, use_login_node=use_login_node)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    result = scheduler_commands.submit_script(
        str(GPU_JOB_SCRIPT),
        script_args=["1_Utilities/deviceQuery"],
        partition="q1",
        nodes=1,
        slots=1,
    )
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id, timeout=20)
    scheduler_commands.assert_job_succeeded(job_id)
    logging.info("GPU validation job %s submitted from the %s succeeded", job_id, source)


def _collect_loaded_kernel_modules(cluster, scheduler_commands_factory, trigger_head_node_mount=False):
    """Snapshot the loaded kernel modules per node type.

    After patching, the head node is rebooted in place, so we need to perform a read
    operation on the FSx storage to trigger the loading of the Lustre kernel modules
    before sampling. This is gated by trigger_head_node_mount, since it is only needed
    for the post-reboot snapshot: before patching the mount has already been triggered,
    and compute and login nodes perform the mount as part of their bootstrap and so
    trigger it implicitly.
    """
    modules = {}
    for node_type in NODE_TYPES:
        executor = _node_executor(cluster, scheduler_commands_factory, node_type)
        if node_type == HEAD_NODE and trigger_head_node_mount:
            # Access the FSx for Lustre mountpoint to trigger its on-demand automount,
            # so its client kernel modules get loaded before sampling.
            executor.run_remote_command(f"ls {FSX_LUSTRE_MOUNT_DIR}")
        modules[node_type] = _loaded_kernel_modules(executor)
    return modules


def _node_executor(cluster, scheduler_commands_factory, node_type):
    """Return a RemoteCommandExecutor connected to the given node type.

    Compute nodes are reached through the head node, which acts as the bastion.
    """
    if node_type == COMPUTE_NODE:
        scheduler_commands = scheduler_commands_factory(RemoteCommandExecutor(cluster))
        compute_node = scheduler_commands.get_compute_nodes()[0]
        return RemoteCommandExecutor(cluster, compute_node_ip=scheduler_commands.get_node_addr(compute_node))
    if node_type == LOGIN_NODE:
        return RemoteCommandExecutor(cluster, use_login_node=True)
    return RemoteCommandExecutor(cluster)


def _loaded_kernel_modules(remote_command_executor):
    """Return the set of kernel module names currently loaded on the node."""
    output = remote_command_executor.run_remote_command("lsmod | tail -n +2 | awk '{print $1}'").stdout
    return set(output.split())
