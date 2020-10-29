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
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor

from tests.common.schedulers_common import get_scheduler_commands
from tests.storage.snapshots_factory import EBSSnapshotsFactory
from tests.storage.storage_common import verify_directory_correctly_shared


@pytest.mark.regions(["eu-west-3", "cn-north-1", "us-gov-west-1"])
@pytest.mark.instances(["c4.xlarge", "c5.xlarge"])
@pytest.mark.schedulers(["sge"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_ebs_single(scheduler, pcluster_config_reader, clusters_factory):
    mount_dir = "ebs_mount_dir"
    cluster_config = pcluster_config_reader(mount_dir=mount_dir)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    mount_dir = "/" + mount_dir
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size=20)
    _test_ebs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


@pytest.mark.dimensions("ap-northeast-2", "c5.xlarge", "alinux2", "sge")
@pytest.mark.dimensions("cn-northwest-1", "c4.xlarge", "ubuntu1804", "slurm")
@pytest.mark.dimensions("eu-west-1", "c5.xlarge", "centos8", "slurm")
@pytest.mark.usefixtures("os", "instance")
def test_ebs_snapshot(
    request, vpc_stacks, region, scheduler, pcluster_config_reader, clusters_factory, snapshots_factory
):
    logging.info("Testing ebs snapshot")
    mount_dir = "ebs_mount_dir"
    volume_size = 10

    logging.info("Creating snapshot")

    snapshot_id = snapshots_factory.create_snapshot(request, vpc_stacks[region].cfn_outputs["PublicSubnetId"], region)

    logging.info("Snapshot id: %s" % snapshot_id)
    cluster_config = pcluster_config_reader(mount_dir=mount_dir, volume_size=volume_size, snapshot_id=snapshot_id)

    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    mount_dir = "/" + mount_dir
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size="9.8")
    _test_ebs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)

    # Checks for test data
    result = remote_command_executor.run_remote_command("cat {}/test.txt".format(mount_dir))
    assert_that(result.stdout.strip()).is_equal_to("hello world")


# cn-north-1 does not support KMS
@pytest.mark.dimensions("ca-central-1", "c5.xlarge", "alinux2", "awsbatch")
@pytest.mark.dimensions("ca-central-1", "c5.xlarge", "ubuntu1804", "slurm")
@pytest.mark.dimensions("eu-west-2", "c5.xlarge", "centos8", "slurm")
@pytest.mark.usefixtures("region", "os", "instance")
def test_ebs_multiple(scheduler, pcluster_config_reader, clusters_factory):
    mount_dirs = ["/ebs_mount_dir_{0}".format(i) for i in range(0, 5)]
    volume_sizes = [15 + 5 * i for i in range(0, 5)]
    cluster_config = pcluster_config_reader(mount_dirs=mount_dirs, volume_sizes=volume_sizes)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    for mount_dir, volume_size in zip(mount_dirs, volume_sizes):
        _test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size)
        _test_ebs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


@pytest.mark.dimensions("cn-northwest-1", "c4.xlarge", "alinux", "slurm")
@pytest.mark.usefixtures("region", "os", "instance")
def test_default_ebs(scheduler, pcluster_config_reader, clusters_factory):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    mount_dir = "/shared"
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size=20)
    _test_ebs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


@pytest.mark.dimensions("us-gov-east-1", "c5.xlarge", "ubuntu1604", "torque")
@pytest.mark.usefixtures("region", "os", "instance")
def test_ebs_single_empty(scheduler, pcluster_config_reader, clusters_factory):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    mount_dir = "/shared"
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size=20)
    _test_ebs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


def _test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size):
    logging.info("Testing ebs {0} is correctly mounted".format(mount_dir))
    result = remote_command_executor.run_remote_command(
        "df -h -t ext4 | tail -n +2 | awk '{{print $2, $6}}' | grep '{0}'".format(mount_dir)
    )
    assert_that(result.stdout).matches(r"{size}G {mount_dir}".format(size=volume_size, mount_dir=mount_dir))

    result = remote_command_executor.run_remote_command("cat /etc/fstab")
    assert_that(result.stdout).matches(r"UUID=.* {mount_dir} ext4 _netdev 0 0".format(mount_dir=mount_dir))


def _test_ebs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands):
    logging.info("Testing ebs correctly mounted on compute nodes")
    verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


def _test_home_correctly_shared(remote_command_executor, scheduler_commands):
    logging.info("Testing home dir correctly mounted on compute nodes")
    verify_directory_correctly_shared(remote_command_executor, "/home", scheduler_commands)


@pytest.fixture()
def snapshots_factory():
    factory = EBSSnapshotsFactory()
    yield factory
    factory.release_all()
