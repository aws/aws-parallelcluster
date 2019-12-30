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
from tests.storage.storage_common import verify_directory_correctly_shared


# For EFS tests, only use regions defined in AVAILABILITY_ZONE_OVERRIDES in conftest
# Otherwise we cannot control the AZs of the subnets to properly test EFS.
@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm", "awsbatch"])
@pytest.mark.os(["alinux"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_efs_compute_az(scheduler, pcluster_config_reader, clusters_factory):
    """
    Test when compute subnet is in a different AZ from master subnet.

    A compute mount target should be created and the efs correctly mounted on compute.
    """
    mount_dir = "efs_mount_dir"
    cluster_config = pcluster_config_reader(mount_dir=mount_dir)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    mount_dir = "/" + mount_dir
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_efs_correctly_mounted(remote_command_executor, mount_dir)
    _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm", "awsbatch"])
@pytest.mark.os(["alinux"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_efs_same_az(scheduler, pcluster_config_reader, clusters_factory):
    """
    Test when compute subnet is in the same AZ as master subnet.

    No compute mount point needed and the efs correctly mounted on compute.
    """
    mount_dir = "efs_mount_dir"
    cluster_config = pcluster_config_reader(mount_dir=mount_dir)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    mount_dir = "/" + mount_dir
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_efs_correctly_mounted(remote_command_executor, mount_dir)
    _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


def _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands):
    logging.info("Testing efs correctly mounted on compute nodes")
    verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


def _test_efs_correctly_mounted(remote_command_executor, mount_dir):
    logging.info("Testing ebs {0} is correctly mounted".format(mount_dir))
    result = remote_command_executor.run_remote_command("df | grep '{0}'".format(mount_dir))
    assert_that(result.stdout).contains(mount_dir)

    result = remote_command_executor.run_remote_command("cat /etc/fstab")
    assert_that(result.stdout).matches(
        (
            r".* {mount_dir} nfs4 nfsvers=4.1,rsize=1048576,wsize=1048576,hard,"
            r"timeo=30,retrans=2,noresvport,_netdev 0 0"
        ).format(mount_dir=mount_dir)
    )
