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
from cfn_stacks_factory import CfnStack, CfnStacksFactory
from remote_command_executor import RemoteCommandExecutor
from troposphere import Ref, Template
from troposphere.ec2 import SecurityGroup, SecurityGroupIngress
from utils import (
    check_node_security_group,
    create_hash_suffix,
    describe_cluster_security_groups,
    generate_stack_name,
    get_username_for_os,
)


@pytest.mark.usefixtures("os", "scheduler", "instance")
@pytest.mark.parametrize("assign_additional_security_groups", [True, False])
def test_additional_sg_and_ssh_from(
    region, custom_security_groups, pcluster_config_reader, clusters_factory, assign_additional_security_groups
):
    """
    Test when additional_sg ssh_from are provided in the config file

    The additional security group should be added to the head and compute nodes. The
    Test if HeadNode is replaced if we update the SecurityGroups and AdditionalSecurityGroups
    """
    number_of_sgs = 2

    custom_security_group_ids = custom_security_groups(number_of_sgs=number_of_sgs)
    default_security_group_id = custom_security_group_ids[0]

    ssh_from = "10.11.12.0/32"
    cluster_config = pcluster_config_reader(
        default_security_group_id=default_security_group_id,
        ssh_from=ssh_from,
        assign_additional_security_groups=assign_additional_security_groups,
    )
    cluster = clusters_factory(cluster_config)
    ec2_client = boto3.client("ec2", region_name=region)
    instances = _get_instances_by_security_group(ec2_client, default_security_group_id)
    logging.info("Asserting that head node and compute node has the additional security group")
    assert_that(instances).is_length(2)
    if assign_additional_security_groups:
        logging.info("Asserting the security group of pcluster is not overwritten by additional security group")
        for instance in instances:
            assert_that(
                any(
                    security_group["GroupName"].startswith(cluster.name)
                    for security_group in instance["SecurityGroups"]
                )
            ).is_true()
        logging.info("Asserting the security group of pcluster on the head node is aligned with ssh_from")
        check_node_security_group(region, cluster, 22, ssh_from)

    head_node_instance_id = cluster.head_node_instance_id
    logging.info(f"HeadNode of the {cluster} is {head_node_instance_id}")

    # Update the Security Groups of HeadNode check if the HeadNode instance is replaced.
    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update_sg.yaml",
        default_security_group_id=default_security_group_id,
        updated_security_group_id=custom_security_group_ids,
        ssh_from=ssh_from,
        assign_additional_security_groups=assign_additional_security_groups,
    )
    cluster.update(str(updated_config_file), force_update="true")
    logging.info("Verifying the HeadNode is not replaced after cluster update")
    assert_that(head_node_instance_id).is_equal_to(cluster.head_node_instance_id)


@pytest.mark.usefixtures("os", "instance")
def test_overwrite_sg(region, scheduler, custom_security_groups, pcluster_config_reader, clusters_factory):
    """Test vpc_security_group_id overwrites pcluster default sg on head and compute nodes, efs, fsx"""
    custom_security_group_id = custom_security_groups()[0]
    fsx_name, efs_name = "fsx", "efs"
    cluster_config = pcluster_config_reader(
        vpc_security_group_id=custom_security_group_id, fsx_name=fsx_name, efs_name=efs_name
    )
    cluster = clusters_factory(cluster_config)
    ec2_client = boto3.client("ec2", region_name=region)
    instances = _get_instances_by_security_group(ec2_client, custom_security_group_id)
    logging.info("Asserting that head node and compute node has and only has the custom security group")
    assert_that(instances).is_length(3 if scheduler == "slurm" else 2)
    for instance in instances:
        assert_that(instance["SecurityGroups"]).is_length(1)

    # FSx is not supported in US isolated regions or when using AWS Batch as a scheduler
    if "us-iso" not in region and scheduler != "awsbatch":
        logging.info("Collecting security groups of the FSx")
        fsx_id = cluster.cfn_resources[f"FSX{create_hash_suffix(fsx_name)}"]
        fsx_client = boto3.client("fsx", region_name=region)
        network_interface_id = fsx_client.describe_file_systems(FileSystemIds=[fsx_id])["FileSystems"][0][
            "NetworkInterfaceIds"
        ][0]
        fsx_security_groups = ec2_client.describe_network_interfaces(NetworkInterfaceIds=[network_interface_id])[
            "NetworkInterfaces"
        ][0]["Groups"]
        logging.info(
            "Asserting the network interface of FSx has only the dedicated security group "
            "allowing all traffic to itself and to the custom security group"
        )
        assert_that(fsx_security_groups).is_length(1)
        fsx_security_group = fsx_security_groups[0]
        fsx_security_group_id = fsx_security_group["GroupId"]

        _assert_security_group_rules(
            ec2_client,
            fsx_security_group_id,
            [fsx_security_group_id, custom_security_group_id],
        )

    logging.info("Collecting security groups of the EFS")
    efs_id = cluster.cfn_resources[f"EFS{create_hash_suffix(efs_name)}"]
    efs_client = boto3.client("efs", region_name=region)
    mount_target_ids = [
        mount_target["MountTargetId"]
        for mount_target in efs_client.describe_mount_targets(FileSystemId=efs_id)["MountTargets"]
    ]
    logging.info(
        "Asserting the mount targets of EFS have only the dedicated security group "
        "allowing all traffic to itself and to the custom security group"
    )
    for mount_target_id in mount_target_ids:
        mount_target_security_groups = efs_client.describe_mount_target_security_groups(MountTargetId=mount_target_id)[
            "SecurityGroups"
        ]
        assert_that(mount_target_security_groups).is_length(1)
        mount_target_security_group_id = mount_target_security_groups[0]
        _assert_security_group_rules(
            ec2_client,
            mount_target_security_group_id,
            [mount_target_security_group_id, custom_security_group_id],
        )

    if scheduler == "slurm":
        logging.info("Checking SSH connection between cluster nodes before cluster update")
        _check_connections_between_head_node_and_compute_nodes(cluster)
        # Update the cluster by removing the custom security group from head node.
        # As a result, head node uses pcluster created security group while compute nodes use custom security group.
        # The aim is to test that the pcluster creates proper inbound rules in the head node security group to allow
        # access from compute security groups.
        updated_config_file = pcluster_config_reader(
            config_file="pcluster.config.update.yaml",
            vpc_security_group_id=custom_security_group_id,
            fsx_name=fsx_name,
            efs_name=efs_name,
        )
        cluster.update(str(updated_config_file), force_update="true")
        logging.info("Checking SSH connection between cluster nodes after cluster update")
        _check_connections_between_head_node_and_compute_nodes(cluster)


@pytest.mark.usefixtures("os", "instance")
@pytest.mark.parametrize("assign_additional_security_groups", [True, False])
def test_login_node_security_groups(
    region, custom_security_groups, pcluster_config_reader, clusters_factory, assign_additional_security_groups
):
    """
    Test login node and network load balancer share the same SecurityGroups, AdditionalSecurityGroups, and SSH
    restrictions when defined in the config.

    Test that the network load balancer managed security group is referenced in an inbound rule of the
    login node managed security group.
    """
    default_security_group_id = custom_security_groups(number_of_sgs=1)[0]

    ssh_from = "10.11.12.0/32"
    cluster_config = pcluster_config_reader(
        default_security_group_id=default_security_group_id,
        ssh_from=ssh_from,
        assign_additional_security_groups=assign_additional_security_groups,
    )
    cluster = clusters_factory(cluster_config)
    ec2_client = boto3.client("ec2", region_name=region)
    elb_client = boto3.client("elbv2", region_name=region)

    instances = _get_instances_by_security_group(ec2_client, default_security_group_id)
    load_balancers = _get_load_balancer_by_security_group(elb_client, default_security_group_id)

    logging.info("Asserting that login node and load balancer have same AdditionalSecurityGroups or SecurityGroups")
    assert_that(len(instances) == 1).is_true()
    assert_that(len(load_balancers) == 1).is_true()

    if assign_additional_security_groups:
        security_groups = describe_cluster_security_groups(cluster.name, region)
        load_balancer_managed_security_group = None
        login_node_managed_security_group = None
        for security_group in security_groups:
            if "pool1LoadBalancerSecurityGroup" in security_group.get("GroupName"):
                load_balancer_managed_security_group = security_group
            if "pool1LoginNodesSecurityGroup" in security_group.get("GroupName"):
                login_node_managed_security_group = security_group

        logging.info("Asserting both the login node and load balancer have managed security group")

        assert_that(
            load_balancer_managed_security_group is not None and login_node_managed_security_group is not None
        ).is_true()

        assert_that(
            any(
                login_node_managed_security_group.get("GroupId") == security_group["GroupId"]
                for security_group in instances[0].get("SecurityGroups")
            )
        ).is_true()

        assert_that(
            load_balancer_managed_security_group.get("GroupId") in load_balancers[0].get("SecurityGroups")
        ).is_true()

        logging.info("Asserting the managed security groups of the load balancer and login node share SSH restriction")
        load_balancer_managed_rules = ec2_client.describe_security_group_rules(
            Filters=[{"Name": "group-id", "Values": [load_balancer_managed_security_group.get("GroupId")]}]
        )["SecurityGroupRules"]
        # Check login node SG
        check_node_security_group(region, cluster, 22, ssh_from, login_pool_name="pool1")
        # Check load balancer SG
        assert_that(
            any(ssh_from == rule.get("CidrIpv4") and rule.get("FromPort") == 22 for rule in load_balancer_managed_rules)
        ).is_true()

        logging.info(
            "Asserting that load balancer managed security group is referenced in an inbound rule "
            "of the login node managed security group"
        )
        for ip_permissions in login_node_managed_security_group.get("IpPermissions"):
            if ip_permissions.get("UserIdGroupPairs"):
                assert_that(
                    any(
                        load_balancer_managed_security_group.get("GroupId") == id_group_pairs.get("GroupId")
                        for id_group_pairs in ip_permissions.get("UserIdGroupPairs")
                    )
                ).is_true()


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
        logging.info(
            f"Checking SSH connection from head node ${head_node_private_ip} to compute node ${compute_node_ip}"
        )
        head_node_remote_command_executor.run_remote_command(ping_ip.format(compute_node_ip))
        compute_remote_command_executor = RemoteCommandExecutor(
            cluster, compute_node_ip=compute_node_ip, bastion=head_node_username_ip
        )
        logging.info(
            f"Checking SSH connection from compute node ${compute_node_ip} to head node ${head_node_private_ip}"
        )
        compute_remote_command_executor.run_remote_command(ping_ip.format(head_node_private_ip))
        for other_compute_node in compute_nodes:
            other_compute_node_ip = other_compute_node.get("privateIpAddress")
            logging.info(
                f"Checking SSH connection from compute node ${compute_node_ip} "
                f"and compute node ${other_compute_node_ip}"
            )
            compute_remote_command_executor.run_remote_command(ping_ip.format(other_compute_node_ip))


@pytest.fixture(scope="class")
def custom_security_groups(vpc_stack, region, request):
    stacks_factory = CfnStacksFactory(request.config.getoption("credential"))

    def _custom_security_groups(number_of_sgs=1):
        if request.config.getoption("custom_security_groups_stack_name"):
            stack = CfnStack(
                name=request.config.getoption("custom_security_groups_stack_name"), region=region, template=None
            )
        else:
            template = Template()
            template.set_version("2010-09-09")
            template.set_description("custom security group stack for testing additional_sg and vpc_security_group_id")
            vpc_id = vpc_stack.cfn_outputs["VpcId"]
            for sg_index in range(number_of_sgs):
                security_group = template.add_resource(
                    SecurityGroup(
                        f"SecurityGroup{sg_index}",
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
                            f"SecurityGroupIngress{sg_index}{index}",
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
                        f"SecurityGroupSSHIngress{sg_index}",
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
            stacks_factory.create_stack(stack)

        return [stack.cfn_resources[f"SecurityGroup{sg_index}"] for sg_index in range(number_of_sgs)]

    yield _custom_security_groups

    if not request.config.getoption("no_delete"):
        stacks_factory.delete_all_stacks()
    else:
        logging.warning("Skipping deletion of CFN stacks because --no-delete option is set")


def _get_instances_by_security_group(ec2_client, security_group_id):
    logging.info("Collecting security groups of the head node and compute node")
    paginator = ec2_client.get_paginator("describe_instances")
    page_iterator = paginator.paginate(Filters=[{"Name": "network-interface.group-id", "Values": [security_group_id]}])
    instances = []
    for page in page_iterator:
        for reservation in page["Reservations"]:
            instances.extend(reservation["Instances"])
    return instances


def _get_load_balancer_by_security_group(elb_client, security_group_id):
    logging.info("Collecting network load balancer")
    paginator = elb_client.get_paginator("describe_load_balancers")
    page_iterator = paginator.paginate()
    load_balancers = []
    for page in page_iterator:
        for load_balancer in page["LoadBalancers"]:
            if security_group_id in load_balancer["SecurityGroups"]:
                load_balancers.append(load_balancer)
    return load_balancers


def _assert_security_group_rules(ec2_client, security_group_id: str, referenced_security_group_ids: list):
    # We expect the FSx/EFS Security Group to have exactly 4 rules:
    #  * 2 rules (ingress and egress) allowing traffic to/from the FSx/EFS Security Group itself
    #  * 2 rules (ingress and egress) allowing traffic to/from the custom Security Group
    rules = ec2_client.describe_security_group_rules(Filters=[{"Name": "group-id", "Values": [security_group_id]}])[
        "SecurityGroupRules"
    ]
    for sg_id in referenced_security_group_ids:
        for is_egress in (True, False):
            match = [
                rule
                for rule in rules
                if rule["IsEgress"] == is_egress and rule["ReferencedGroupInfo"]["GroupId"] == sg_id
            ]
            assert_that(match).is_length(1)
