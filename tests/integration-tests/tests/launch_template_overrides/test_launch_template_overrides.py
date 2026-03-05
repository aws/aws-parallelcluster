# Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from utils import generate_stack_name, get_compute_nodes_instance_ids

from tests.common.assertions import assert_head_node_is_running, assert_no_errors_in_logs

def _create_override_launch_template(ec2_client, subnet_id, security_group_id, stack_name):
    """
    Create a launch template with 18 EFA network interfaces for testing LaunchSpecificationOverrides.

    Args:
        ec2_client: boto3 EC2 client
        subnet_id: Subnet ID to use for network interfaces
        security_group_id: Security group ID to use for network interfaces
        stack_name: Stack name to use for naming the launch template

    Returns:
        Tuple of (launch_template_id, version)
    """
    # Create network interfaces configuration with 2 interfaces:
    # - First interface (DeviceIndex 0): regular ENI (no InterfaceType specified)
    # - Second interface (DeviceIndex 1): efa-only
    network_interfaces = [
        {
            "DeviceIndex": 0,
            "SubnetId": subnet_id,
            "Groups": [security_group_id],
        },
        {
            "DeviceIndex": 1,
            "InterfaceType": "efa-only",
            "SubnetId": subnet_id,
            "Groups": [security_group_id],
        },
    ]

    response = ec2_client.create_launch_template(
        LaunchTemplateName=f"{stack_name}-override-lt",
        LaunchTemplateData={
            "NetworkInterfaces": network_interfaces,
        },
        TagSpecifications=[
            {
                "ResourceType": "launch-template",
                "Tags": [
                    {"Key": "Name", "Value": f"{stack_name}-override-lt"},
                    {"Key": "parallelcluster:test", "Value": "launch-template-overrides"},
                ],
            }
        ],
    )

    launch_template_id = response["LaunchTemplate"]["LaunchTemplateId"]
    version = response["LaunchTemplate"]["LatestVersionNumber"]

    logging.info(f"Created override launch template {launch_template_id} version {version}")
    return launch_template_id, version


def _delete_launch_template(ec2_client, launch_template_id):
    """Delete the launch template created for testing."""
    try:
        ec2_client.delete_launch_template(LaunchTemplateId=launch_template_id)
        logging.info(f"Deleted launch template {launch_template_id}")
    except Exception as e:
        logging.warning(f"Failed to delete launch template {launch_template_id}: {e}")


@pytest.fixture()
def override_launch_template(request, region, vpc_stack):
    """Fixture to create and cleanup the override launch template."""
    ec2_client = boto3.client("ec2", region_name=region)
    stack_name = generate_stack_name("integ-tests-lt-override", request.config.getoption("stackname_suffix"))

    # Get subnet and create a security group for the launch template
    subnet_id = vpc_stack.get_private_subnet()

    # Create a simple security group that allows all traffic (simplest config that works)
    vpc_id = vpc_stack.cfn_outputs["VpcId"]
    sg_response = ec2_client.create_security_group(
        GroupName=f"{stack_name}-override-sg",
        Description="Security group for launch template override test",
        VpcId=vpc_id,
        TagSpecifications=[
            {
                "ResourceType": "security-group",
                "Tags": [
                    {"Key": "Name", "Value": f"{stack_name}-override-sg"},
                    {"Key": "parallelcluster:test", "Value": "launch-template-overrides"},
                ],
            }
        ],
    )
    security_group_id = sg_response["GroupId"]

    # Allow all inbound traffic
    ec2_client.authorize_security_group_ingress(
        GroupId=security_group_id,
        IpPermissions=[
            {
                "IpProtocol": "-1",
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }
        ],
    )

    launch_template_id, version = _create_override_launch_template(
        ec2_client, subnet_id, security_group_id, stack_name
    )

    yield {
        "launch_template_id": launch_template_id,
        "version": version,
        "security_group_id": security_group_id,
        "subnet_id": subnet_id,
    }

    # Cleanup
    _delete_launch_template(ec2_client, launch_template_id)
    try:
        ec2_client.delete_security_group(GroupId=security_group_id)
        logging.info(f"Deleted security group {security_group_id}")
    except Exception as e:
        logging.warning(f"Failed to delete security group {security_group_id}: {e}")


@pytest.mark.usefixtures("instance", "os", "scheduler")
def test_launch_template_overrides(
    region,
    os,
    pcluster_config_reader,
    clusters_factory,
    scheduler_commands_factory,
    override_launch_template,
    vpc_stack,
):
    """
    Test that LaunchSpecificationOverrides properly applies a custom launch template to compute nodes.

    This test:
    1. Creates a launch template with 16 EFA network interfaces configured with a specific subnet and security group
    2. Creates a cluster with c5n.18xlarge instances that references this launch template via LaunchSpecificationOverrides
    3. Runs a job on the compute nodes
    4. Verifies that the compute nodes have the expected network interface configuration from the override
    """

    # Create cluster config with the override launch template
    cluster_config = pcluster_config_reader(
        override_launch_template_id=override_launch_template["launch_template_id"],
        override_launch_template_version=override_launch_template["version"],
    )
    cluster = clusters_factory(cluster_config)

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    # Submit a job to run on compute nodes
    result = scheduler_commands.submit_command("hostname", partition="queue1")
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    # Verify network interface configuration on compute nodes (similar to _test_efa_eni_configuration)
    _test_launch_template_override_eni_configuration(cluster, region, override_launch_template)


def _test_launch_template_override_eni_configuration(cluster, region, override_launch_template):
    """Verify compute nodes have the expected network interface configuration from the launch template override.

    Efa enabled is set to false, but with the launch template override, an efa-only interface will be configured.
    With the launch template override specifying 2 interfaces:
    - First interface (DeviceIndex 0): regular ENI
    - Second interface (DeviceIndex 1): efa-only
    - All ENIs should use the security group from the override launch template
    """
    ec2_client = boto3.client("ec2", region_name=region)
    compute_instance_ids = get_compute_nodes_instance_ids(cluster.cfn_name, region)

    assert_that(compute_instance_ids).described_as("Should have at least one compute node").is_not_empty()

    expected_security_group = override_launch_template["security_group_id"]

    for instance_id in compute_instance_ids:
        instance_info = ec2_client.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]
        enis = instance_info["NetworkInterfaces"]
        logging.info(f"Instance {instance_id} has {len(enis)} ENIs")

        efa_only_enis = []
        regular_enis = []
        for eni in enis:
            interface_type = eni.get("InterfaceType", "interface")
            private_ips = eni.get("PrivateIpAddresses", [])
            attachment = eni.get("Attachment", {})
            network_card_index = attachment.get("NetworkCardIndex", 0)
            device_index = attachment.get("DeviceIndex", 0)
            security_groups = [sg["GroupId"] for sg in eni.get("Groups", [])]

            logging.info(
                f"  ENI {eni['NetworkInterfaceId']}: InterfaceType={interface_type}, "
                f"PrivateIPs={len(private_ips)}, NetworkCardIndex={network_card_index}, "
                f"DeviceIndex={device_index}, SecurityGroups={security_groups}"
            )

            if interface_type == "efa-only":
                efa_only_enis.append(eni)
            else:
                regular_enis.append(eni)

            # Verify security group from override is applied
            assert_that(security_groups).described_as(
                f"ENI {eni['NetworkInterfaceId']} should have the override security group"
            ).contains(expected_security_group)

        # Verify we have 2 ENIs as specified in the override launch template
        assert_that(len(enis)).described_as(
            f"Instance {instance_id} should have 2 ENIs from the launch template override"
        ).is_equal_to(2)

        # Verify we have 1 regular ENI and 1 efa-only ENI
        assert_that(len(regular_enis)).described_as(
            f"Instance {instance_id} should have 1 regular ENI"
        ).is_equal_to(1)

        assert_that(len(efa_only_enis)).described_as(
            f"Instance {instance_id} should have 1 efa-only ENI"
        ).is_equal_to(1)