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

import pytest
from remote_command_executor import RemoteCommandExecutor

from tests.storage.storage_common import (
    test_raid_correctly_configured,
    test_raid_correctly_mounted,
    verify_directory_correctly_shared,
)


@pytest.mark.usefixtures("region", "os", "instance")
def test_raid_performance_mode(pcluster_config_reader, clusters_factory, scheduler_commands_factory):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    mount_dir = "/raid_dir"
    test_raid_correctly_configured(remote_command_executor, raid_type="0", volume_size=75, raid_devices=5)
    test_raid_correctly_mounted(remote_command_executor, mount_dir, volume_size=74)
    _test_raid_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


@pytest.mark.usefixtures("region", "os", "instance")
def test_raid_fault_tolerance_mode(pcluster_config_reader, clusters_factory, scheduler_commands_factory):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    mount_dir = "/raid_dir"
    test_raid_correctly_configured(remote_command_executor, raid_type="1", volume_size=35, raid_devices=2)
    test_raid_correctly_mounted(remote_command_executor, mount_dir, volume_size=35)
    _test_raid_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


def _test_raid_correctly_shared(remote_command_executor, mount_dir, scheduler_commands):
    logging.info("Testing raid correctly mounted on compute nodes")
    verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)
