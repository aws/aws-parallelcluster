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
from troposphere import Ref, Template
from troposphere.ec2 import SecurityGroup, SecurityGroupIngress
from utils import check_headnode_security_group, generate_stack_name


@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_additional_sg_and_ssh_from(region, custom_security_group, pcluster_config_reader, clusters_factory):
    """
    Test when additional_sg ssh_from are provided in the config file

    The additional security group should be added to the head and compute nodes. The
    """
    custom_security_group_id = custom_security_group.cfn_resources["SecurityGroupResource"]
    ssh_from = "10.11.12.0/32"
    cluster_config = pcluster_config_reader(additional_sg=custom_security_group_id, ssh_from=ssh_from)
    cluster = clusters_factory(cluster_config)
    ec2_client = boto3.client("ec2", region_name=region)
    instances = _get_instances_by_security_group(ec2_client, custom_security_group_id)
    logging.info("Asserting that head node and compute node has the additional security group")
    assert_that(instances).is_length(2)
    logging.info("Asserting the security group of pcluster is not overwritten by additional seurity group")
    for instance in instances:
        assert_that(
            any(
                security_group["GroupName"].startswith("parallelcluster")
                for security_group in instance["SecurityGroups"]
            )
        ).is_true()
    logging.info("Asserting the security group of pcluster on the head node is aligned with ssh_from")
    check_headnode_security_group(region, cluster, 22, ssh_from)


@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_overwrite_sg(region, custom_security_group, pcluster_config_reader, clusters_factory):
    """Test vpc_security_group_id overwrites pcluster default sg on head and compute nodes, efs, fsx"""
    custom_security_group_id = custom_security_group.cfn_resources["SecurityGroupResource"]
    cluster_config = pcluster_config_reader(vpc_security_group_id=custom_security_group_id)
    cluster = clusters_factory(cluster_config)
    ec2_client = boto3.client("ec2", region_name=region)
    instances = _get_instances_by_security_group(ec2_client, custom_security_group_id)
    logging.info("Asserting that head node and compute node has and only has the custom security group")
    assert_that(instances).is_length(2)
    for instance in instances:
        assert_that(instance["SecurityGroups"]).is_length(1)

    cfn_client = boto3.client("cloudformation", region_name=region)

    logging.info("Collecting security groups of the FSx")
    fsx_id = cfn_client.describe_stack_resource(
        StackName=cluster.cfn_resources["FSXSubstack"], LogicalResourceId="FileSystem"
    )["StackResourceDetail"]["PhysicalResourceId"]
    fsx_client = boto3.client("fsx", region_name=region)
    network_interface_id = fsx_client.describe_file_systems(FileSystemIds=[fsx_id])["FileSystems"][0][
        "NetworkInterfaceIds"
    ][0]
    fsx_security_groups = ec2_client.describe_network_interfaces(NetworkInterfaceIds=[network_interface_id])[
        "NetworkInterfaces"
    ][0]["Groups"]
    logging.info("Asserting the network interface of FSx has and only has the custom security group")
    assert_that(fsx_security_groups[0]["GroupId"]).is_equal_to(custom_security_group_id)
    assert_that(fsx_security_groups).is_length(1)

    logging.info("Collecting security groups of the EFS")
    efs_id = cfn_client.describe_stack_resource(
        StackName=cluster.cfn_resources["EFSSubstack"], LogicalResourceId="EFSFS"
    )["StackResourceDetail"]["PhysicalResourceId"]
    efs_client = boto3.client("efs", region_name=region)
    mount_target_ids = [
        mount_target["MountTargetId"]
        for mount_target in efs_client.describe_mount_targets(FileSystemId=efs_id)["MountTargets"]
    ]
    logging.info("Asserting the mount targets of EFS has and only has the custom security group")
    for mount_target_id in mount_target_ids:
        mount_target_security_groups = efs_client.describe_mount_target_security_groups(MountTargetId=mount_target_id)[
            "SecurityGroups"
        ]
        assert_that(mount_target_security_groups[0]).is_equal_to(custom_security_group_id)
        assert_that(mount_target_security_groups).is_length(1)


@pytest.fixture(scope="class")
def custom_security_group(vpc_stack, region, request, cfn_stacks_factory):
    template = Template()
    template.set_version("2010-09-09")
    template.set_description("custom security group stack for testing additional_sg and vpc_security_group_id")
    security_group = template.add_resource(
        SecurityGroup(
            "SecurityGroupResource",
            GroupDescription="custom security group for testing additional_sg and vpc_security_group_id",
            VpcId=vpc_stack.cfn_outputs["VpcId"],
        )
    )
    template.add_resource(
        SecurityGroupIngress(
            "SecurityGroupIngressResource",
            IpProtocol="-1",
            FromPort=0,
            ToPort=65535,
            SourceSecurityGroupId=Ref(security_group),
            GroupId=Ref(security_group),
        )
    )
    stack = CfnStack(
        name=generate_stack_name("integ-tests-custom-sg", request.config.getoption("stackname_suffix")),
        region=region,
        template=template.to_json(),
    )
    cfn_stacks_factory.create_stack(stack)

    yield stack

    if not request.config.getoption("no_delete"):
        cfn_stacks_factory.delete_stack(stack.name, region)


def _get_instances_by_security_group(ec2_client, security_group_id):
    logging.info("Collecting security groups of the head node and compute node")
    paginator = ec2_client.get_paginator("describe_instances")
    page_iterator = paginator.paginate(
        Filters=[
            {
                "Name": "network-interface.group-id",
                "Values": [security_group_id],
            }
        ]
    )
    instances = []
    for page in page_iterator:
        for reservation in page["Reservations"]:
            instances.extend(reservation["Instances"])
    return instances
