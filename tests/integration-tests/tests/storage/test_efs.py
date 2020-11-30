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
from cfn_stacks_factory import CfnStack
from remote_command_executor import RemoteCommandExecutor
from troposphere import Base64, Sub, Template
from troposphere.ec2 import Instance
from troposphere.efs import FileSystem, MountTarget
from utils import generate_stack_name, get_vpc_snakecase_value, random_alphanumeric

from tests.common.schedulers_common import get_scheduler_commands
from tests.common.utils import retrieve_latest_ami
from tests.storage.storage_common import verify_directory_correctly_shared


# For EFS tests, only use regions defined in AVAILABILITY_ZONE_OVERRIDES in conftest
# Otherwise we cannot control the AZs of the subnets to properly test EFS.
@pytest.mark.regions(["us-west-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm", "awsbatch"])
@pytest.mark.oss(["alinux2"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_efs_compute_az(region, scheduler, pcluster_config_reader, clusters_factory, vpc_stack):
    """
    Test when compute subnet is in a different AZ from head node subnet.

    A compute mount target should be created and the efs correctly mounted on compute.
    """
    _assert_subnet_az_relations(region, vpc_stack, expected_in_same_az=False)
    mount_dir = "efs_mount_dir"
    cluster_config = pcluster_config_reader(mount_dir=mount_dir)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    mount_dir = "/" + mount_dir
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_efs_correctly_mounted(remote_command_executor, mount_dir)
    _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


@pytest.mark.regions(["ap-northeast-1", "cn-north-1"])
@pytest.mark.instances(["c4.xlarge", "c5.xlarge"])
@pytest.mark.schedulers(["slurm", "awsbatch"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_efs_same_az(region, scheduler, pcluster_config_reader, clusters_factory, vpc_stack):
    """
    Test when compute subnet is in the same AZ as head node subnet.

    No compute mount point needed and the efs correctly mounted on compute.
    """
    _assert_subnet_az_relations(region, vpc_stack, expected_in_same_az=True)
    mount_dir = "efs_mount_dir"
    cluster_config = pcluster_config_reader(mount_dir=mount_dir)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    mount_dir = "/" + mount_dir
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_efs_correctly_mounted(remote_command_executor, mount_dir)
    _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


@pytest.mark.usefixtures("os", "instance")
def test_existing_efs(
    region,
    scheduler,
    efs_stack,
    pcluster_config_reader,
    clusters_factory,
    vpc_stack,
    request,
    key_name,
    cfn_stacks_factory,
):
    """
    Test when efs_fs_id is provided in the config file, the existing efs can be correctly mounted.

    To verify the efs is the existing efs, the test expects a file with random ran inside the efs mounted
    """
    file_name = _write_file_into_efs(region, vpc_stack, efs_stack, request, key_name, cfn_stacks_factory)

    _assert_subnet_az_relations(region, vpc_stack, expected_in_same_az=False)
    mount_dir = "/efs_mount_dir"
    cluster_config = pcluster_config_reader(
        mount_dir=mount_dir, efs_fs_id=efs_stack.cfn_resources["FileSystemResource"]
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # test file in efs exist
    logging.info("Testing efs {0} is correctly mounted".format(mount_dir))
    result = remote_command_executor.run_remote_command("df | grep '{0}'".format(mount_dir))
    assert_that(result.stdout).contains(mount_dir)

    remote_command_executor.run_remote_command(f"cat {mount_dir}/{file_name}")
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_efs_correctly_mounted(remote_command_executor, mount_dir)
    _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)
    remote_command_executor.run_remote_command(f"cat {mount_dir}/{file_name}")


@pytest.fixture(scope="class")
def efs_stack(cfn_stacks_factory, request, region):
    """EFS stack contains a single efs resource."""
    efs_template = Template()
    efs_template.set_version("2010-09-09")
    efs_template.set_description("EFS stack created for testing existing EFS")
    efs_template.add_resource(FileSystem("FileSystemResource"))
    stack = CfnStack(
        name=generate_stack_name("integ-tests-efs", request.config.getoption("stackname_suffix")),
        region=region,
        template=efs_template.to_json(),
    )
    cfn_stacks_factory.create_stack(stack)

    yield stack

    if not request.config.getoption("no_delete"):
        cfn_stacks_factory.delete_stack(stack.name, region)


def _write_file_into_efs(region, vpc_stack, efs_stack, request, key_name, cfn_stacks_factory):
    """Write file stack contains a mount target and a instance to write a empty file with random name into the efs."""
    write_file_template = Template()
    write_file_template.set_version("2010-09-09")
    write_file_template.set_description("Stack to write a file to the existing EFS")
    default_security_group_id = (
        boto3.client("ec2", region_name=region)
        .describe_security_groups(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_stack.cfn_outputs["VpcId"]]},
                {"Name": "group-name", "Values": ["default"]},
            ]
        )
        .get("SecurityGroups")[0]
        .get("GroupId")
    )
    write_file_template.add_resource(
        MountTarget(
            "MountTargetResource",
            FileSystemId=efs_stack.cfn_resources["FileSystemResource"],
            SubnetId=vpc_stack.cfn_outputs["PublicSubnetId"],
            SecurityGroups=[default_security_group_id],
        )
    )
    random_file_name = random_alphanumeric()
    user_data = (
        """
        #cloud-config
        package_update: true
        package_upgrade: true
        runcmd:
        - yum install -y amazon-efs-utils
        - yum install -y nfs-utils
        - file_system_id_1="""
        + efs_stack.cfn_resources["FileSystemResource"]
        + """
        - efs_mount_point_1=/mnt/efs/fs1
        - mkdir -p "${!efs_mount_point_1}"
        - mount -t efs ${!file_system_id_1}:/ ${!efs_mount_point_1}
        - touch ${!efs_mount_point_1}/"""
        + random_file_name
        + """
        - umount ${!efs_mount_point_1}
        - opt/aws/bin/cfn-signal -e $? --stack ${AWS::StackName} --resource InstanceToWriteEFS --region ${AWS::Region}
        """
    )
    write_file_template.add_resource(
        Instance(
            "InstanceToWriteEFS",
            CreationPolicy={"ResourceSignal": {"Timeout": "PT10M"}},
            ImageId=retrieve_latest_ami(region, "alinux2"),
            InstanceType="c5.xlarge",
            SubnetId=vpc_stack.cfn_outputs["PublicSubnetId"],
            UserData=Base64(Sub(user_data)),
            KeyName=key_name,
            DependsOn=["MountTargetResource"],
        )
    )
    write_file_stack = CfnStack(
        name=generate_stack_name("integ-tests-efs-write-file", request.config.getoption("stackname_suffix")),
        region=region,
        template=write_file_template.to_json(),
    )
    cfn_stacks_factory.create_stack(write_file_stack)

    cfn_stacks_factory.delete_stack(write_file_stack.name, region)

    return random_file_name


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


def _assert_subnet_az_relations(region, vpc_stack, expected_in_same_az):
    vpc = get_vpc_snakecase_value(vpc_stack)
    head_node_subnet_id = vpc["public_subnet_id"]
    compute_subnet_id = vpc["private_subnet_id"] if expected_in_same_az else vpc["private_additional_cidr_subnet_id"]
    head_node_subnet_az = boto3.resource("ec2", region_name=region).Subnet(head_node_subnet_id).availability_zone
    compute_subnet_az = boto3.resource("ec2", region_name=region).Subnet(compute_subnet_id).availability_zone
    if expected_in_same_az:
        assert_that(head_node_subnet_az).is_equal_to(compute_subnet_az)
    else:
        assert_that(head_node_subnet_az).is_not_equal_to(compute_subnet_az)
