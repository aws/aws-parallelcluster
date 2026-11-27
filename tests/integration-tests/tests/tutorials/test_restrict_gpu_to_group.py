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
import pytest
from assertpy import assert_that, soft_assertions
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from utils import get_username_for_os

from tests.dcv.test_dcv import _test_show_url

# The custom actions of the tutorial are added to the gated queue only: the GPUs of the other queue stay open.
GATED_QUEUE = "q1"
UNGATED_QUEUE = "q2"
COMPUTE_RESOURCE_NAME = "cr1"

GPU_GROUP_GID = 1500
GPU_GROUP_NAME = "my-pcluster-gpuusers"
GATE_SCRIPT = "gpu-group-gate.sh"
DCV_PORT = 8443

# Ownership and mode of the GPU device files before and after the gating.
UNGATED_DEVICE_PERMISSIONS = "root:root 666"
GATED_DEVICE_PERMISSIONS = f"root:{GPU_GROUP_NAME} 660"

# Command run in the jobs: prints the groups of the job, the permissions of the GPU device file and the GPUs
# visible to the job. nvidia-smi fails for users outside the group: "|| true" keeps the job successful so that its
# output can be checked.
GPU_CHECK_COMMAND = 'id -Gn; stat -c "%U:%G %a" /dev/nvidia0; nvidia-smi -L || true'
GPU_VISIBLE = "GPU 0:"
GPU_DENIED_MESSAGES = ["No devices were found", "Insufficient Permissions"]


@pytest.mark.usefixtures("instance", "scheduler")
def test_restrict_gpu_to_group(
    region,
    os,
    pcluster_config_reader,
    clusters_factory,
    scheduler_commands_factory,
    s3_bucket_factory,
    test_datadir,
):
    """
    Validate the tutorial procedure to restrict GPU usage to the members of a group on a running cluster.

    The head node and the compute nodes are GPU instances, and DCV is enabled on the head node, so the test
    covers the gating of the head node GPU used by DCV. The cluster has two GPU queues: the gating is enabled
    on the first one only, the second one checks that queues without the custom action are not affected.

    Steps:
    1. Upload the tutorial custom action script to S3.
    2. Create a cluster without GPU gating and assert that the GPUs are open to every user and that
       dcv-connect works.
    3. Update the cluster to add the tutorial custom actions: OnNodeUpdated on the head node (adding the users
       needed by DCV to the group) and OnNodeConfigured on the gated queue.
    4. Assert the gating on the head node: group members, device permissions, display stack and DCV running,
       Xorg running with the group.
    5. Assert that dcv-connect works and that the DCV session uses the GPU.
    6. Assert the gating on the gated queue, through jobs: a member and root can use the GPU, a user outside the
       group cannot, and the GPU Health Check succeeds.
    7. Assert that the GPUs of the ungated queue are still open to a user outside the group.
    """
    default_user = get_username_for_os(os)
    config_params = {
        "gated_queue": GATED_QUEUE,
        "ungated_queue": UNGATED_QUEUE,
        "compute_resource_name": COMPUTE_RESOURCE_NAME,
    }

    # Step 1: upload the tutorial custom action script to S3.
    bucket_name = s3_bucket_factory()
    boto3.resource("s3", region_name=region).Bucket(bucket_name).upload_file(
        str(test_datadir / GATE_SCRIPT), GATE_SCRIPT
    )

    # Step 2: create a cluster without GPU gating.
    cluster_config = pcluster_config_reader(bucket_name=bucket_name, **config_params)
    cluster = clusters_factory(cluster_config)
    head_node_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(head_node_executor)

    with soft_assertions():
        assert_that(_device_permissions(head_node_executor)).described_as(
            "head node GPU before the gating"
        ).is_equal_to(UNGATED_DEVICE_PERMISSIONS)
        for queue in [GATED_QUEUE, UNGATED_QUEUE]:
            assert_that(_run_gpu_check_job(scheduler_commands, queue)).described_as(
                f"{queue} GPU before the gating"
            ).contains(UNGATED_DEVICE_PERMISSIONS)
    _test_show_url(cluster, region, DCV_PORT, access_from=None)

    # Step 3: enable the GPU gating with a cluster update.
    updated_config = pcluster_config_reader(
        config_file="pcluster.config.update.yaml",
        bucket_name=bucket_name,
        gpu_group_gid=GPU_GROUP_GID,
        gpu_group_name=GPU_GROUP_NAME,
        head_node_gpu_users=f"gdm,{default_user}",
        **config_params,
    )
    cluster.update(str(updated_config))

    # Step 4: gating on the head node.
    _assert_head_node_gated(head_node_executor, default_user)

    # Step 5: dcv-connect works and the DCV session uses the GPU.
    _test_show_url(cluster, region, DCV_PORT, access_from=None)
    _assert_dcv_session_uses_gpu(head_node_executor)

    # Step 6: gating on the gated queue. DRAIN replaces its static node after the update: wait until a job runs
    # on a node gated by the OnNodeConfigured custom action. The default user is a member of the group.
    member_output, member_job_id = _wait_for_gated_compute_node(scheduler_commands, head_node_executor)
    assert_that(member_output).described_as("GPUs visible to a member job").contains(GPU_VISIBLE)

    compute_node_ip = cluster.get_compute_nodes_private_ip(GATED_QUEUE, COMPUTE_RESOURCE_NAME)[0]
    compute_node_executor = RemoteCommandExecutor(cluster, compute_node_ip=compute_node_ip)
    _assert_gpu_health_check_succeeded(compute_node_executor, member_job_id)
    assert_that(compute_node_executor.run_remote_command("sudo nvidia-smi -L").stdout).described_as(
        "GPUs visible to root on the gated compute node"
    ).contains(GPU_VISIBLE)

    # A user outside the group: remove the default user from the group on the head node, where Slurm resolves
    # the groups of the jobs, run the jobs, then add it back.
    head_node_executor.run_remote_command(f"sudo gpasswd -d {default_user} {GPU_GROUP_NAME}")
    try:
        gated_output = _run_gpu_check_job(scheduler_commands, GATED_QUEUE)
        # Step 7: the ungated queue is not affected by the gating.
        ungated_output = _run_gpu_check_job(scheduler_commands, UNGATED_QUEUE)
    finally:
        head_node_executor.run_remote_command(f"sudo gpasswd -a {default_user} {GPU_GROUP_NAME}")

    with soft_assertions():
        assert_that(gated_output).described_as("groups of a non-member job").does_not_contain(GPU_GROUP_NAME)
        assert_that(gated_output).described_as("GPUs visible to a non-member job on the gated queue").does_not_contain(
            GPU_VISIBLE
        )
        assert_that(any(message in gated_output for message in GPU_DENIED_MESSAGES)).described_as(
            f"non-member job denied the GPU on the gated queue, output: {gated_output}"
        ).is_true()
        assert_that(ungated_output).described_as("ungated queue GPU after the gating").contains(
            UNGATED_DEVICE_PERMISSIONS
        )
        assert_that(ungated_output).described_as("GPUs visible to a non-member job on the ungated queue").contains(
            GPU_VISIBLE
        )


def _device_permissions(remote_command_executor):
    """Return the owner, group and mode of /dev/nvidia0 on the node."""
    return remote_command_executor.run_remote_command('stat -c "%U:%G %a" /dev/nvidia0').stdout.strip()


def _run_gpu_check_job(scheduler_commands, queue):
    """Run the GPU check command in a job with one GPU on the queue, as the default user, and return its output."""
    return scheduler_commands.submit_command_and_get_output(
        {"command": GPU_CHECK_COMMAND, "partition": queue, "other_options": "--gres=gpu:1"}
    )


def _assert_head_node_gated(head_node_executor, default_user):
    """Assert the group members, the GPU device permissions and the display stack on the head node."""

    def _run(command):
        return head_node_executor.run_remote_command(command).stdout.strip()

    with soft_assertions():
        assert_that(_run(f"getent group {GPU_GROUP_NAME}")).described_as("head node group").is_equal_to(
            f"{GPU_GROUP_NAME}:x:{GPU_GROUP_GID}:gdm,{default_user}"
        )
        assert_that(_device_permissions(head_node_executor)).described_as("head node GPU").is_equal_to(
            GATED_DEVICE_PERMISSIONS
        )
        assert_that(_run("systemctl is-active gdm dcvserver parallelcluster_nvidia").split()).described_as(
            "display stack, DCV and NVIDIA services"
        ).is_equal_to(["active", "active", "active"])
        # Xorg runs as gdm: the group must be among its groups to open the GPU.
        assert_that(_run("grep ^Groups: /proc/$(pgrep -x Xorg)/status").split()[1:]).described_as(
            "groups of Xorg"
        ).contains(str(GPU_GROUP_GID))


@retry(stop_max_delay=minutes(3), wait_fixed=seconds(15))
def _assert_dcv_session_uses_gpu(head_node_executor):
    """Assert that the DCV agent of the session created by dcv-connect runs on the GPU."""
    processes = head_node_executor.run_remote_command(
        "sudo nvidia-smi --query-compute-apps=process_name --format=csv,noheader"
    ).stdout
    assert_that(processes).described_as("processes running on the head node GPU").contains("dcvagent")


@retry(stop_max_delay=minutes(30), wait_fixed=seconds(60))
def _wait_for_gated_compute_node(scheduler_commands, head_node_executor):
    """Run the GPU check job on the gated queue until it runs on a gated node; return its output and job id."""
    result = scheduler_commands.submit_command(GPU_CHECK_COMMAND, partition=GATED_QUEUE, other_options="--gres=gpu:1")
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
    output = head_node_executor.run_remote_command(f"cat slurm-{job_id}.out").stdout
    logging.info("GPU check job %s output: %s", job_id, output)
    assert_that(output).described_as("gated queue GPU after the gating").contains(GATED_DEVICE_PERMISSIONS)
    return output, job_id


def _assert_gpu_health_check_succeeded(compute_node_executor, job_id):
    """Assert that the GPU Health Check of the job succeeded on the compute node."""
    health_check_log = compute_node_executor.run_remote_command(
        f'sudo grep "JobID {job_id} " /var/log/parallelcluster/slurm_health_check.log || true'
    ).stdout
    assert_that(health_check_log).described_as(f"GPU Health Check of job {job_id}").contains(
        "The GPU Health Check succeeded"
    )
