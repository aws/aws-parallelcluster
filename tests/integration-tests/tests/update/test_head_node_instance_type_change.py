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

import pytest
from assertpy import assert_that, soft_assertions
from conftest import _run_pcluster_diag
from remote_command_executor import RemoteCommandExecutor
from utils import get_username_for_os, random_alphanumeric

from tests.common.assertions import assert_instance_type
from tests.common.login_nodes_utils import get_login_node_executors_by_pool
from tests.common.utils import change_head_node_instance_type
from tests.storage.storage_common import (
    assert_fsx_lustre_correctly_mounted,
    get_fsx_ids,
    test_directory_correctly_shared_between_ln_and_hn,
    test_ebs_correctly_mounted,
    test_efs_correctly_mounted,
)

QUEUE = "q1"
LOGIN_NODE_POOL = "login-node-pool-0"
EBS_MOUNT_DIR = "/shared_ebs"
EFS_MOUNT_DIR = "/shared_efs"
FSX_MOUNT_DIR = "/shared_fsx"

# Default size, in GiB, of the managed EBS volume.
EBS_VOLUME_SIZE = 40

# The head node is created with the initial instance type and vertically scaled to the new one.
# The test config in develop.yaml reserves both instance types in the test AZ with open capacity reservations,
# so that neither the head node creation nor its restart with the new instance type fail for insufficient capacity.
HEAD_NODE_INITIAL_INSTANCE_TYPE = "c5.xlarge"
HEAD_NODE_NEW_INSTANCE_TYPE = "c5.2xlarge"


@pytest.mark.usefixtures("instance", "scheduler")
def test_head_node_instance_type_change(
    request,
    region,
    os,
    pcluster_config_reader,
    clusters_factory,
    scheduler_commands_factory,
):
    """
    Verify the cluster keeps working after the head node instance type is changed with a stop/start.

    The test changes the head node instance type through EC2, which is what customers do to vertically scale
    the head node, and verifies that the running jobs, the compute nodes, the login nodes and the shared
    storages survive the head node stop/start, that the cluster can still scale out, and that a supported
    cluster update still succeeds without replacing the resized head node.
    """
    config_params = {
        "head_node_instance_type": HEAD_NODE_INITIAL_INSTANCE_TYPE,
        "queue": QUEUE,
        "login_node_pool": LOGIN_NODE_POOL,
        "ebs_mount_dir": EBS_MOUNT_DIR,
        "efs_mount_dir": EFS_MOUNT_DIR,
        "fsx_mount_dir": FSX_MOUNT_DIR,
        "max_count": 1,
    }
    # Both the initial and the updated configs are rendered from the same template: write each to its own file,
    # since by default the config reader overwrites the template with the rendered config.
    cluster = clusters_factory(pcluster_config_reader(output_file="pcluster.config.initial.yaml", **config_params))
    username = get_username_for_os(os)
    home_dir = f"/home/{username}"

    head_node_rce = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(head_node_rce)

    # Submit a long-running job and record the compute nodes before touching the head node.
    job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 3600", "nodes": 1, "partition": QUEUE}
    )
    scheduler_commands.wait_job_running(job_id)
    job_instance_id = scheduler_commands.get_job_instance_id(job_id)
    compute_instance_ids = cluster.get_cluster_instance_ids(node_type="Compute")
    logging.info("Job %s is running on %s; compute nodes: %s", job_id, job_instance_id, compute_instance_ids)

    # Change the head node instance type with a stop/start.
    # computemgtd self-terminates the compute nodes if slurmctld is unreachable for more than clustermgtd_timeout
    # (600 seconds by default), so the head node downtime must stay below it for the compute nodes to survive.
    head_node_instance_id = cluster.get_cluster_instance_ids(node_type="HeadNode")[0]
    change_head_node_instance_type(cluster, instance_type=HEAD_NODE_NEW_INSTANCE_TYPE)

    # The head node public IP changes on stop/start, so all the remote command executors must be re-created.
    head_node_rce = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(head_node_rce)
    _assert_cluster_after_head_node_change(
        request,
        cluster,
        region,
        head_node_rce,
        scheduler_commands,
        scheduler_commands_factory,
        job_id,
        job_instance_id,
        compute_instance_ids,
        username,
        home_dir,
    )

    # A supported cluster update must still work on the resized head node. The cluster config still declares the
    # initial head node instance type (HeadNode/InstanceType cannot be updated): the update must not revert or
    # replace the head node.
    # The update adds a dynamic node: increasing MaxCount does not require stopping the compute fleet.
    cluster.update(
        str(pcluster_config_reader(output_file="pcluster.config.update.yaml", **{**config_params, "max_count": 2}))
    )
    _assert_cluster_after_update(
        cluster, region, scheduler_commands, head_node_instance_id, job_id, compute_instance_ids
    )


def _assert_cluster_after_head_node_change(
    request,
    cluster,
    region,
    head_node_rce,
    scheduler_commands,
    scheduler_commands_factory,
    job_id,
    job_instance_id,
    compute_instance_ids,
    username,
    home_dir,
):
    """Verify head node, jobs, compute nodes, login nodes and shared storages after the instance type change."""
    login_node_rce = get_login_node_executors_by_pool(cluster, [LOGIN_NODE_POOL])[0]
    login_node_scheduler_commands = scheduler_commands_factory(login_node_rce)

    # Wait for slurmctld to answer again after the restart. It must stay out of the soft assertions block,
    # because wait_job_running retries on assertion failures, which soft assertions do not raise.
    scheduler_commands.wait_job_running(job_id)

    with soft_assertions():
        assert_instance_type(cluster.head_node_instance_id, region, HEAD_NODE_NEW_INSTANCE_TYPE)
        # FSx for Lustre is an automount: after the restart it is mounted only on first access. The shared storage
        # check accesses it, so it must run before pcluster-diag, which reports an unmounted Lustre as a failure.
        _assert_head_node_shared_storages_mounted(cluster, region, head_node_rce)
        _run_pcluster_diag(request, cluster)
        scheduler_commands.assert_job_state(job_id, "RUNNING")
        assert_that(scheduler_commands.get_job_instance_id(job_id)).is_equal_to(job_instance_id)
        _assert_compute_nodes_not_replaced(cluster, compute_instance_ids)
        # /home is served by the internal EFS, while the SharedStorage EBS volume is attached to the head node and
        # exported over NFS: its read/write verifies the head node NFS server is back after the restart.
        _assert_dirs_shared_with_head_node(cluster, head_node_rce, [home_dir, EBS_MOUNT_DIR])
        _assert_job_from_login_node_writes_to_home(
            head_node_rce, login_node_rce, login_node_scheduler_commands, username, home_dir
        )


def _assert_cluster_after_update(
    cluster, region, scheduler_commands, head_node_instance_id, job_id, compute_instance_ids
):
    """Verify the update kept the resized head node, added the dynamic node and the cluster scales out on it."""
    with soft_assertions():
        assert_that(cluster.get_cluster_instance_ids(node_type="HeadNode")).is_equal_to([head_node_instance_id])
        assert_instance_type(head_node_instance_id, region, HEAD_NODE_NEW_INSTANCE_TYPE)
        assert_that(scheduler_commands.get_compute_nodes(filter_by_partition=QUEUE, all_nodes=True)).is_length(2)
        scheduler_commands.assert_job_state(job_id, "RUNNING")
        # The static node is busy with the long-running job: an exclusive job requires launching the new dynamic node.
        logging.info("Verifying the cluster scales out on the dynamic node added by the update")
        scheduler_commands.submit_command_and_assert_job_succeeded(
            {"command": "hostname", "nodes": 1, "partition": QUEUE, "other_options": "--exclusive"}
        )
        assert_that(cluster.get_cluster_instance_ids(node_type="Compute")).is_length(len(compute_instance_ids) + 1)


def _assert_compute_nodes_not_replaced(cluster, compute_instance_ids):
    logging.info("Verifying no compute nodes have been replaced")
    assert_that(sorted(cluster.get_cluster_instance_ids(node_type="Compute"))).is_equal_to(sorted(compute_instance_ids))


def _assert_job_from_login_node_writes_to_home(
    head_node_rce, login_node_rce, login_node_scheduler_commands, username, home_dir
):
    """Submit a hello world job from the login node as the default user, with its output in the user home.

    The output is then read from both the login node and the head node.
    """
    logging.info("Submitting from the login node, as %s, a hello world job with output in %s", username, home_dir)
    output_file = f"{home_dir}/hello-world-{random_alphanumeric()}.out"
    job_id = login_node_scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "echo Hello World",
            "nodes": 1,
            "partition": QUEUE,
            "other_options": f"--output={output_file}",
        }
    )
    login_node_scheduler_commands.wait_job_completed(job_id)
    login_node_scheduler_commands.assert_job_succeeded(job_id)
    assert_that(login_node_scheduler_commands.get_job_info(job_id, field="UserId")).starts_with(f"{username}(")
    for executor in (login_node_rce, head_node_rce):
        assert_that(executor.run_remote_command(f"cat {output_file}").stdout.strip()).is_equal_to("Hello World")


def _assert_dirs_shared_with_head_node(cluster, head_node_rce, shared_dirs):
    """Verify every compute and login node can read and write the shared dirs, sharing them with the head node."""
    compute_node_executors = [
        RemoteCommandExecutor(cluster, compute_node_ip=compute_node["privateIpAddress"])
        for compute_node in cluster.describe_cluster_instances(node_type="Compute")
    ]
    login_node_executors = get_login_node_executors_by_pool(cluster, [LOGIN_NODE_POOL])
    for executor in [*compute_node_executors, *login_node_executors]:
        for shared_dir in shared_dirs:
            logging.info(
                "Verifying %s is shared between the head node and %s", shared_dir, executor.get_target_host_type()
            )
            test_directory_correctly_shared_between_ln_and_hn(head_node_rce, executor, shared_dir)


def _assert_head_node_shared_storages_mounted(cluster, region, head_node_rce):
    """Verify the SharedStorage file systems are correctly mounted on the head node."""
    logging.info("Verifying the shared storages are mounted on the head node")
    test_ebs_correctly_mounted(head_node_rce, EBS_MOUNT_DIR, EBS_VOLUME_SIZE)
    test_efs_correctly_mounted(head_node_rce, EFS_MOUNT_DIR)
    # FSx for Lustre is mounted with x-systemd.automount: access it to trigger the mount before checking it.
    head_node_rce.run_remote_command(f"ls {FSX_MOUNT_DIR}")
    assert_fsx_lustre_correctly_mounted(head_node_rce, FSX_MOUNT_DIR, region, get_fsx_ids(cluster, region)[0])
