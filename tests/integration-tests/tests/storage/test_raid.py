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
import re

import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor

from tests.common.schedulers_common import get_scheduler_commands
from tests.storage.storage_common import verify_directory_correctly_shared


@pytest.mark.regions(["ap-south-1", "us-gov-east-1"])
@pytest.mark.instances(["c4.xlarge", "c5.xlarge"])
@pytest.mark.schedulers(["sge", "awsbatch"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_raid_performance_mode(scheduler, pcluster_config_reader, clusters_factory):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    mount_dir = "/raid_dir"
    _test_raid_correctly_configured(remote_command_executor, raid_type="0", volume_size=75, raid_devices=5)
    _test_raid_correctly_mounted(remote_command_executor, mount_dir, volume_size=74)
    _test_raid_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


@pytest.mark.regions(["us-gov-west-1", "cn-northwest-1"])
@pytest.mark.instances(["c4.xlarge", "c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.oss(["alinux2"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_raid_fault_tolerance_mode(scheduler, pcluster_config_reader, clusters_factory):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    mount_dir = "/raid_dir"
    _test_raid_correctly_configured(remote_command_executor, raid_type="1", volume_size=20, raid_devices=2)
    _test_raid_correctly_mounted(remote_command_executor, mount_dir, volume_size=20)
    _test_raid_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


def _test_raid_correctly_mounted(remote_command_executor, mount_dir, volume_size):
    logging.info("Testing raid {0} is correctly mounted".format(mount_dir))
    result = remote_command_executor.run_remote_command(
        "df -h -t ext4 | tail -n +2 | awk '{{print $2, $6}}' | grep '{0}'".format(mount_dir)
    )
    assert_that(result.stdout).matches(r"{size}G {mount_dir}".format(size=volume_size, mount_dir=mount_dir))

    result = remote_command_executor.run_remote_command("cat /etc/fstab")
    assert_that(result.stdout).matches(
        r"/dev/md0 {mount_dir} ext4 defaults,nofail,_netdev 0 2".format(mount_dir=mount_dir)
    )


def _test_raid_correctly_shared(remote_command_executor, mount_dir, scheduler_commands):
    logging.info("Testing raid correctly mounted on compute nodes")
    verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


def _test_raid_correctly_configured(remote_command_executor, raid_type, volume_size, raid_devices):
    result = remote_command_executor.run_remote_command("sudo mdadm --detail /dev/md0")
    assert_that(result.stdout).contains("Raid Level : raid{0}".format(raid_type))
    assert_that(result.stdout).contains("Raid Devices : {0}".format(raid_devices))
    assert_that(result.stdout).contains("Active Devices : {0}".format(raid_devices))
    assert_that(result.stdout).contains("Failed Devices : 0")

    # Compare rounded size to match output from different mdadm version
    # Array Size : 41942912 (40.00 GiB 42.95 GB) --> on Centos7 with mdadm-4.1-4.el7
    # Array Size : 41908224 (39.97 GiB 42.91 GB) --> on Centos8 with mdadm-4.1-13.el8
    array_size = re.search(r"Array Size : .*\((.*) GiB", result.stdout).group(1)
    expected_size = volume_size - 0.1
    assert_that(float(array_size)).is_greater_than_or_equal_to(expected_size)

    # ensure that the RAID array is reassembled automatically on boot
    expected_entry = remote_command_executor.run_remote_command("sudo mdadm --detail --scan").stdout
    mdadm_conf = remote_command_executor.run_remote_command(
        "sudo cat /etc/mdadm.conf || sudo cat /etc/mdadm/mdadm.conf"
    ).stdout
    assert_that(mdadm_conf).contains(expected_entry)
