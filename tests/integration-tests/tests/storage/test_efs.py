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
from troposphere import Ref, Template, ec2
from troposphere.efs import MountTarget
from utils import generate_stack_name, get_vpc_snakecase_value

from tests.storage.storage_common import (
    test_efs_correctly_mounted,
    verify_directory_correctly_shared,
    write_file_into_efs,
)


@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_efs_compute_az(region, pcluster_config_reader, clusters_factory, vpc_stack, scheduler_commands_factory):
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
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    test_efs_correctly_mounted(remote_command_executor, mount_dir)
    _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_efs_same_az(region, pcluster_config_reader, clusters_factory, vpc_stack, scheduler_commands_factory):
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
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    test_efs_correctly_mounted(remote_command_executor, mount_dir)
    _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


@pytest.mark.usefixtures("scheduler", "instance")
def test_multiple_efs(
    os,
    region,
    efs_stack_factory,
    mount_target_stack_factory,
    pcluster_config_reader,
    clusters_factory,
    vpc_stack,
    request,
    key_name,
    cfn_stacks_factory,
    scheduler_commands_factory,
    run_benchmarks,
):
    """
    Test when efs_fs_id is provided in the config file, the existing efs can be correctly mounted.

    To verify the efs is the existing efs, the test expects a file with random ran inside the efs mounted
    """
    # Names of files that will be written from separate instance. The test checks the cluster nodes can access them.
    existing_efs_filenames = []
    existing_efs_mount_dirs = []
    if request.config.getoption("benchmarks") and os == "alinux2":
        # Only create more EFS when benchmarks are specified. Limiting OS to reduce cost of too many file systems
        num_existing_efs = 50
    else:
        num_existing_efs = 2
    existing_efs_ids = efs_stack_factory(num_existing_efs)
    if request.config.getoption("benchmarks"):
        mount_target_stack_factory(existing_efs_ids)
    existing_efs_filenames.extend(
        write_file_into_efs(
            region, vpc_stack, existing_efs_ids, request, key_name, cfn_stacks_factory, mount_target_stack_factory
        )
    )
    for i in range(num_existing_efs):
        existing_efs_mount_dirs.append(f"/existing_efs_mount_dir_{i}")

    new_efs_mount_dirs = ["/shared"]  # OSU benchmark relies on /shared directory

    _assert_subnet_az_relations(region, vpc_stack, expected_in_same_az=False)

    cluster_config = pcluster_config_reader(
        existing_efs_mount_dirs=existing_efs_mount_dirs,
        existing_efs_ids=existing_efs_ids,
        new_efs_mount_dirs=new_efs_mount_dirs,
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    all_mount_dirs = existing_efs_mount_dirs + new_efs_mount_dirs
    for mount_dir in all_mount_dirs:
        logging.info("Testing efs {0} is correctly mounted".format(mount_dir))
        result = remote_command_executor.run_remote_command("df | grep '{0}'".format(mount_dir))
        assert_that(result.stdout).contains(mount_dir)

        test_efs_correctly_mounted(remote_command_executor, mount_dir)
        _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)
    for i in range(num_existing_efs):
        remote_command_executor.run_remote_command(f"cat {existing_efs_mount_dirs[i]}/{existing_efs_filenames[i]}")

    run_benchmarks(remote_command_executor, scheduler_commands)


def _add_mount_targets(subnet_ids, efs_ids, security_group, template):
    subnet_response = boto3.client("ec2").describe_subnets(SubnetIds=subnet_ids)["Subnets"]
    for efs_index, efs_id in enumerate(efs_ids):
        availability_zones_with_mount_target = set()
        for mount_target in boto3.client("efs").describe_mount_targets(FileSystemId=efs_id)["MountTargets"]:
            availability_zones_with_mount_target.add(mount_target["AvailabilityZoneName"])
        for subnet_index, subnet in enumerate(subnet_response):
            if subnet["AvailabilityZone"] not in availability_zones_with_mount_target:
                # One and only one mount target should be created in each availability zone.
                depends_on_arg = {}
                resources = list(template.resources.keys())
                max_concurrency = 10
                if len(resources) >= max_concurrency:
                    # Create at most 10 resources in parallel.
                    depends_on_arg = {"DependsOn": [resources[-max_concurrency]]}
                template.add_resource(
                    MountTarget(
                        f"MountTargetResourceEfs{efs_index}Subnet{subnet_index}",
                        FileSystemId=efs_id,
                        SubnetId=subnet["SubnetId"],
                        SecurityGroups=[Ref(security_group)],
                        **depends_on_arg,
                    )
                )
                availability_zones_with_mount_target.add(subnet["AvailabilityZone"])


@pytest.fixture(scope="class")
def mount_target_stack_factory(cfn_stacks_factory, request, region, vpc_stack):
    """
    EFS mount target stack.

    Create mount targets in all availability zones of vpc_stack
    """
    created_stacks = []

    def create_mount_targets(efs_ids):
        template = Template()
        template.set_version("2010-09-09")
        template.set_description("Mount targets stack")

        # Create a security group that allows all communication between the mount targets and instances in the VPC
        vpc_id = vpc_stack.cfn_outputs["VpcId"]
        security_group = template.add_resource(
            ec2.SecurityGroup(
                "SecurityGroupResource",
                GroupDescription="custom security group for EFS mount targets",
                VpcId=vpc_id,
            )
        )
        # Allow inbound connection though NFS port within the VPC
        cidr_block_association_set = boto3.client("ec2").describe_vpcs(VpcIds=[vpc_id])["Vpcs"][0][
            "CidrBlockAssociationSet"
        ]
        for index, cidr_block_association in enumerate(cidr_block_association_set):
            vpc_cidr = cidr_block_association["CidrBlock"]
            template.add_resource(
                ec2.SecurityGroupIngress(
                    f"SecurityGroupIngressResource{index}",
                    IpProtocol="-1",
                    FromPort=2049,
                    ToPort=2049,
                    CidrIp=vpc_cidr,
                    GroupId=Ref(security_group),
                )
            )

        # Create mount targets
        subnet_ids = [value for key, value in vpc_stack.cfn_outputs.items() if key.endswith("SubnetId")]
        _add_mount_targets(subnet_ids, efs_ids, security_group, template)

        stack_name = generate_stack_name("integ-tests-mount-targets", request.config.getoption("stackname_suffix"))
        stack = CfnStack(name=stack_name, region=region, template=template.to_json())
        cfn_stacks_factory.create_stack(stack)
        created_stacks.append(stack)
        return stack.name

    yield create_mount_targets

    if not request.config.getoption("no_delete"):
        for stack in created_stacks:
            cfn_stacks_factory.delete_stack(stack.name, region)


def _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands):
    logging.info("Testing efs correctly mounted on compute nodes")
    verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


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
