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
    test_efs_correctly_mounted,
    verify_directory_correctly_shared,
)


@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_shared_home(
    region, scheduler, pcluster_config_reader, clusters_factory, vpc_stack, scheduler_commands_factory
):
    """Verify the internal shared storage fs is available when set to Efs"""
    mount_dir = "/home"
    cluster_config = pcluster_config_reader(mount_dir=mount_dir)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    remote_command_executor_login_node = RemoteCommandExecutor(cluster, use_login_node=True)

    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    test_efs_correctly_mounted(remote_command_executor, mount_dir)
    _test_efs_correctly_shared_compute(remote_command_executor, mount_dir, scheduler_commands)
    test_efs_correctly_mounted(remote_command_executor_login_node, mount_dir)
    test_directory_correctly_shared_between_ln_and_hn(
        remote_command_executor, remote_command_executor_login_node, mount_dir, run_sudo=True
    )


def _test_efs_correctly_shared_compute(remote_command_executor, mount_dir, scheduler_commands):
    logging.info("Testing efs correctly mounted on compute nodes")
    verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands, run_sudo=True)
