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
from troposphere import Ref, Template
from troposphere.ec2 import SecurityGroup, SecurityGroupIngress
from utils import check_head_node_security_group, generate_stack_name, get_username_for_os


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
            any(security_group["GroupName"].startswith(cluster.name) for security_group in instance["SecurityGroups"])
        ).is_true()
    logging.info("Asserting the security group of pcluster on the head node is aligned with ssh_from")
    check_head_node_security_group(region, cluster, 22, ssh_from)


@pytest.mark.usefixtures("os", "instance")
def test_overwrite_sg(region, scheduler, custom_security_group, pcluster_config_reader, clusters_factory):
    """Test vpc_security_group_id overwrites pcluster default sg on head and compute nodes, efs, fsx"""
    custom_security_group_id = custom_security_group.cfn_resources["SecurityGroupResource"]
    cluster_config = pcluster_config_reader(vpc_security_group_id=custom_security_group_id)
    cluster = clusters_factory(cluster_config)
    ec2_client = boto3.client("ec2", region_name=region)
    instances = _get_instances_by_security_group(ec2_client, custom_security_group_id)
    logging.info("Asserting that head node and compute node has and only has the custom security group")
    assert_that(instances).is_length(3 if scheduler == "slurm" else 2)
    for instance in instances:
        assert_that(instance["SecurityGroups"]).is_length(1)

    if scheduler != "awsbatch":
        # FSx is not supported when using AWS Batch as a scheduler
        logging.info("Collecting security groups of the FSx")
        fsx_id = cluster.cfn_resources["FSX0"]
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
    efs_id = cluster.cfn_resources["EFS0"]
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

    if scheduler == "slurm":
        _check_connections_between_head_node_and_compute_nodes(cluster)
        # Update the cluster by removing the custom security group from head node.
        # As a result, head node uses pcluster created security group while compute nodes use custom security group.
        # The aim is to test that the pcluster creates proper inbound rules in the head node security group to allow
        # access from compute security groups.
        updated_config_file = pcluster_config_reader(
            config_file="pcluster.config.update.yaml",
            vpc_security_group_id=custom_security_group_id,
        )
        cluster.update(str(updated_config_file), force_update="true")
        _check_connections_between_head_node_and_compute_nodes(cluster)


def _check_connections_between_head_node_and_compute_nodes(cluster):
    username = get_username_for_os(cluster.os)
    head_node = cluster.describe_cluster_instances(node_type="HeadNode")[0]
    head_node_public_ip = head_node.get("publicIpAddress")
    head_node_private_ip = head_node.get("privateIpAddress")
    head_node_username_ip = f"{username}@{head_node_public_ip}"
    head_node_remote_command_executor = RemoteCommandExecutor(cluster)

    compute_nodes = cluster.describe_cluster_instances(node_type="Compute")
    for compute_node in compute_nodes:
        compute_node_ip = compute_node.get("privateIpAddress")
        ping_ip = "ping {0} -c 5"
        head_node_remote_command_executor.run_remote_command(ping_ip.format(compute_node_ip))
        compute_remote_command_executor = RemoteCommandExecutor(
            cluster, compute_node_ip=compute_node_ip, bastion=head_node_username_ip
        )
        compute_remote_command_executor.run_remote_command(ping_ip.format(head_node_private_ip))
        for other_compute_node in compute_nodes:
            other_compute_node_ip = other_compute_node.get("privateIpAddress")
            compute_remote_command_executor.run_remote_command(ping_ip.format(other_compute_node_ip))


@pytest.fixture(scope="class")
def custom_security_group(vpc_stack, region, request, cfn_stacks_factory):
    template = Template()
    template.set_version("2010-09-09")
    template.set_description("custom security group stack for testing additional_sg and vpc_security_group_id")
    vpc_id = vpc_stack.cfn_outputs["VpcId"]
    security_group = template.add_resource(
        SecurityGroup(
            "SecurityGroupResource",
            GroupDescription="custom security group for testing additional_sg and vpc_security_group_id",
            VpcId=vpc_id,
        )
    )
    cidr_block_association_set = boto3.client("ec2").describe_vpcs(VpcIds=[vpc_id])["Vpcs"][0][
        "CidrBlockAssociationSet"
    ]
    # Allow inbound connection within the VPC
    for index, cidr_block_association in enumerate(cidr_block_association_set):
        vpc_cidr = cidr_block_association["CidrBlock"]
        template.add_resource(
            SecurityGroupIngress(
                f"SecurityGroupIngressResource{index}",
                IpProtocol="-1",
                FromPort=0,
                ToPort=65535,
                CidrIp=vpc_cidr,
                GroupId=Ref(security_group),
            )
        )
    # Allow all inbound SSH connection
    template.add_resource(
        SecurityGroupIngress(
            "SecurityGroupSSHIngressResource",
            IpProtocol="tcp",
            FromPort=22,
            ToPort=22,
            GroupId=Ref(security_group),
            CidrIp="0.0.0.0/0",
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
    page_iterator = paginator.paginate(Filters=[{"Name": "network-interface.group-id", "Values": [security_group_id]}])
    instances = []
    for page in page_iterator:
        for reservation in page["Reservations"]:
            instances.extend(reservation["Instances"])
    return instances
