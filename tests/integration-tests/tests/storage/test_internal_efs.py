# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from remote_command_executor import RemoteCommandExecutor

from tests.storage.storage_common import (
    test_directory_correctly_shared_between_ln_and_hn,
    test_efs_correctly_encrypted,
    test_efs_correctly_mounted,
    verify_directory_correctly_shared,
)


@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_internal_efs(
    region,
    scheduler,
    pcluster_config_reader,
    architecture,
    clusters_factory,
    vpc_stack,
    scheduler_commands_factory,
):
    """Verify that the internal shared efs is correctly encrypted"""
    # With 2 AZs: head node and compute nodes uses the same AZ, while login nodes use a different one.
    # With 3+ AZs: head node, compute nodes and login nodes use different AZs.
    public_subnet_ids, private_subnet_ids = vpc_stack.get_all_public_subnets(), vpc_stack.get_all_private_subnets()
    num_azs = len(public_subnet_ids)
    compute_index, login_nodes_index = (0, 1) if num_azs <= 2 else (1, 2)
    head_node_subnet_id = public_subnet_ids[0]
    compute_subnet_id = private_subnet_ids[compute_index]
    login_nodes_subnet_id = public_subnet_ids[login_nodes_index]

    cluster_config = pcluster_config_reader(
        head_node_subnet_id=head_node_subnet_id,
        compute_subnet_id=compute_subnet_id,
        login_nodes_subnet_id=login_nodes_subnet_id,
    )
    cluster = clusters_factory(cluster_config)
    managed_efs_filesystem_ids = [efs_id for efs_id in cluster.cfn_outputs["EFSIds"].split(",")]
    test_efs_correctly_encrypted(region, managed_efs_filesystem_ids[0], encrypted=True)

    """Verify the internal shared storage fs is available when set to Efs"""
    compute_shared_dirs = ["/opt/parallelcluster/shared", "/opt/slurm", "/home"]
    login_shared_dirs = ["/opt/parallelcluster/shared_login_nodes", "/opt/slurm", "/home"]
    if architecture == "x86_64":
        compute_shared_dirs.append("/opt/intel")
        login_shared_dirs.append("/opt/intel")
    remote_command_executor = RemoteCommandExecutor(cluster)
    remote_command_executor_login_node = RemoteCommandExecutor(cluster, use_login_node=True)

    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    for directory in compute_shared_dirs:
        test_efs_correctly_mounted(remote_command_executor, directory)
        _test_efs_correctly_shared_compute(remote_command_executor, directory, scheduler_commands)

    for directory in login_shared_dirs:
        test_efs_correctly_mounted(remote_command_executor, directory)
        test_efs_correctly_mounted(remote_command_executor_login_node, directory)
        test_directory_correctly_shared_between_ln_and_hn(
            remote_command_executor, remote_command_executor_login_node, directory, run_sudo=True
        )


def _test_efs_correctly_shared_compute(remote_command_executor, mount_dir, scheduler_commands):
    logging.info("Testing efs correctly mounted on compute nodes")
    verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands, run_sudo=True)
