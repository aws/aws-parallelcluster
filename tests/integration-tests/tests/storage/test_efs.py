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

import boto3
import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from tests.common.schedulers_common import get_scheduler_commands
from tests.storage.storage_common import verify_directory_correctly_shared
from utils import get_vpc_snakecase_value


# For EFS tests, only use regions defined in AVAILABILITY_ZONE_OVERRIDES in conftest
# Otherwise we cannot control the AZs of the subnets to properly test EFS.
@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm", "awsbatch"])
@pytest.mark.oss(["alinux2"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_efs_compute_az(region, scheduler, pcluster_config_reader, clusters_factory, vpc_stacks):
    """
    Test when compute subnet is in a different AZ from master subnet.

    A compute mount target should be created and the efs correctly mounted on compute.
    """
    _assert_subnet_az_relations(region, vpc_stacks, expected_in_same_az=False)
    mount_dir = "efs_mount_dir"
    cluster_config = pcluster_config_reader(mount_dir=mount_dir)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    mount_dir = "/" + mount_dir
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_efs_correctly_mounted(remote_command_executor, mount_dir)
    _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


@pytest.mark.regions(["us-east-1", "cn-north-1"])
@pytest.mark.instances(["c4.xlarge", "c5.xlarge"])
@pytest.mark.schedulers(["slurm", "awsbatch"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_efs_same_az(region, scheduler, pcluster_config_reader, clusters_factory, vpc_stacks):
    """
    Test when compute subnet is in the same AZ as master subnet.

    No compute mount point needed and the efs correctly mounted on compute.
    """
    _assert_subnet_az_relations(region, vpc_stacks, expected_in_same_az=True)
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


def _assert_subnet_az_relations(region, vpc_stacks, expected_in_same_az):
    vpc = get_vpc_snakecase_value(region, vpc_stacks)
    master_subnet_id = vpc["public_subnet_id"]
    compute_subnet_id = vpc["private_subnet_id"] if expected_in_same_az else vpc["private_additional_cidr_subnet_id"]
    master_subnet_az = boto3.resource("ec2", region_name=region).Subnet(master_subnet_id).availability_zone
    compute_subnet_az = boto3.resource("ec2", region_name=region).Subnet(compute_subnet_id).availability_zone
    if expected_in_same_az:
        assert_that(master_subnet_az).is_equal_to(compute_subnet_az)
    else:
        assert_that(master_subnet_az).is_not_equal_to(compute_subnet_az)
