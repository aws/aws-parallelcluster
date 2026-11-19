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
    storages survive the head node stop/start.
    """
    cluster_config = pcluster_config_reader(
        head_node_instance_type=HEAD_NODE_INITIAL_INSTANCE_TYPE,
        queue=QUEUE,
        login_node_pool=LOGIN_NODE_POOL,
        ebs_mount_dir=EBS_MOUNT_DIR,
        efs_mount_dir=EFS_MOUNT_DIR,
        fsx_mount_dir=FSX_MOUNT_DIR,
    )
    cluster = clusters_factory(cluster_config)
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
    change_head_node_instance_type(cluster, instance_type=HEAD_NODE_NEW_INSTANCE_TYPE)
    _assert_cluster_after_head_node_change(
        request,
        cluster,
        region,
        scheduler_commands_factory,
        job_id,
        job_instance_id,
        compute_instance_ids,
        username,
        home_dir,
    )


def _assert_cluster_after_head_node_change(
    request,
    cluster,
    region,
    scheduler_commands_factory,
    job_id,
    job_instance_id,
    compute_instance_ids,
    username,
    home_dir,
):
    """Verify head node, jobs, compute nodes, login nodes and shared storages after the instance type change."""
    # The head node public IP changes on stop/start, so all the remote command executors must be re-created.
    head_node_rce = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(head_node_rce)
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
        _assert_home_read_write(cluster, head_node_rce, home_dir)
        _assert_job_from_login_node_writes_to_home(
            head_node_rce, login_node_rce, login_node_scheduler_commands, username, home_dir
        )

    scheduler_commands.cancel_job(job_id)


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


def _assert_home_read_write(cluster, head_node_rce, home_dir):
    """Verify every compute and login node can read and write the user home, sharing it with the head node."""
    compute_node_executors = [
        RemoteCommandExecutor(cluster, compute_node_ip=compute_node["privateIpAddress"])
        for compute_node in cluster.describe_cluster_instances(node_type="Compute")
    ]
    login_node_executors = get_login_node_executors_by_pool(cluster, [LOGIN_NODE_POOL])
    for executor in [*compute_node_executors, *login_node_executors]:
        logging.info("Verifying %s is shared between the head node and %s", home_dir, executor.get_target_host_type())
        test_directory_correctly_shared_between_ln_and_hn(head_node_rce, executor, home_dir)


def _assert_head_node_shared_storages_mounted(cluster, region, head_node_rce):
    """Verify the SharedStorage file systems are correctly mounted on the head node."""
    logging.info("Verifying the shared storages are mounted on the head node")
    test_ebs_correctly_mounted(head_node_rce, EBS_MOUNT_DIR, EBS_VOLUME_SIZE)
    test_efs_correctly_mounted(head_node_rce, EFS_MOUNT_DIR)
    # FSx for Lustre is mounted with x-systemd.automount: access it to trigger the mount before checking it.
    head_node_rce.run_remote_command(f"ls {FSX_MOUNT_DIR}")
    assert_fsx_lustre_correctly_mounted(head_node_rce, FSX_MOUNT_DIR, region, get_fsx_ids(cluster, region)[0])
