# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from troposphere import GetAtt, Output, Ref, Template
from troposphere.ec2 import LaunchTemplate, LaunchTemplateData, NetworkInterfaces, SecurityGroup
from utils import generate_stack_name, get_compute_nodes_instance_ids


@pytest.fixture(scope="class")
def override_resources_stack(cfn_stacks_factory, request, region, vpc_stack, instance):
    """
    Create a CFN stack with security groups and launch templates for LaunchSpecificationOverrides testing.

    Creates 3 launch templates for different use cases:
    - EFA enabled + override SG on primary NIC (Use Case 1/2)
    - EFA enabled + override SG on secondary NIC (Use Case 1/2 with non-primary card)
    - EFA disabled + override InterfaceType + SG on primary NIC (Use Case 3/4)
    """
    template = Template()
    template.set_version()
    template.set_description("Launch templates for LaunchSpecificationOverrides integration test")

    private_subnet_id = vpc_stack.cfn_outputs.get(
        "PrivateSubnetId", vpc_stack.get_private_subnet()
    )

    # Security group used by all override launch templates
    override_sg = template.add_resource(
        SecurityGroup(
            "OverrideSecurityGroup",
            GroupDescription="Security group for LaunchSpecificationOverrides test",
            VpcId=vpc_stack.cfn_outputs["VpcId"],
        )
    )

    # LT 1: EFA enabled, override SG on primary NIC only
    lt_efa_primary = template.add_resource(
        LaunchTemplate(
            "LtEfaOverridePrimary",
            LaunchTemplateData=LaunchTemplateData(
                NetworkInterfaces=[
                    NetworkInterfaces(
                        DeviceIndex=0,
                        NetworkCardIndex=0,
                        Groups=[Ref(override_sg)],
                    ),
                ],
            ),
        )
    )

    # LT 2: EFA enabled, override SG on secondary NIC (requires InstanceType)
    lt_efa_secondary = template.add_resource(
        LaunchTemplate(
            "LtEfaOverrideSecondary",
            LaunchTemplateData=LaunchTemplateData(
                InstanceType=instance,
                NetworkInterfaces=[
                    NetworkInterfaces(
                        DeviceIndex=1,
                        NetworkCardIndex=1,
                        Groups=[Ref(override_sg)],
                        InterfaceType="efa-only",
                        SubnetId=private_subnet_id,
                    ),
                ],
            ),
        )
    )

    # LT 3: EFA disabled, override InterfaceType to efa + SG on primary NIC
    lt_no_efa = template.add_resource(
        LaunchTemplate(
            "LtNoEfaOverride",
            LaunchTemplateData=LaunchTemplateData(
                NetworkInterfaces=[
                    NetworkInterfaces(
                        DeviceIndex=0,
                        NetworkCardIndex=0,
                        Groups=[Ref(override_sg)],
                        InterfaceType="efa",
                    ),
                ],
            ),
        )
    )

    # Outputs
    template.add_output(Output("OverrideSecurityGroupId", Value=Ref(override_sg)))
    template.add_output(Output("LtEfaOverridePrimaryId", Value=Ref(lt_efa_primary)))
    template.add_output(Output("LtEfaOverridePrimaryVersion", Value=GetAtt(lt_efa_primary, "LatestVersionNumber")))
    template.add_output(Output("LtEfaOverrideSecondaryId", Value=Ref(lt_efa_secondary)))
    template.add_output(Output("LtEfaOverrideSecondaryVersion", Value=GetAtt(lt_efa_secondary, "LatestVersionNumber")))
    template.add_output(Output("LtNoEfaOverrideId", Value=Ref(lt_no_efa)))
    template.add_output(Output("LtNoEfaOverrideVersion", Value=GetAtt(lt_no_efa, "LatestVersionNumber")))

    stack = CfnStack(
        name=generate_stack_name("integ-tests-lt-override", request.config.getoption("stackname_suffix")),
        region=region,
        template=template.to_json(),
    )
    cfn_stacks_factory.create_stack(stack)

    yield stack

    cfn_stacks_factory.delete_stack(stack.name, region)


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_multiple_nics(
    region,
    pcluster_config_reader,
    test_datadir,
    clusters_factory,
    scheduler_commands_factory,
    override_resources_stack,
):
    outputs = override_resources_stack.cfn_outputs
    override_sg_id = outputs["OverrideSecurityGroupId"]

    cluster_config = pcluster_config_reader(
        lt_efa_override_primary=outputs["LtEfaOverridePrimaryId"],
        lt_efa_override_primary_version=outputs["LtEfaOverridePrimaryVersion"],
        lt_efa_override_secondary=outputs["LtEfaOverrideSecondaryId"],
        lt_efa_override_secondary_version=outputs["LtEfaOverrideSecondaryVersion"],
        lt_no_efa_override=outputs["LtNoEfaOverrideId"],
        lt_no_efa_override_version=outputs["LtNoEfaOverrideVersion"],
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    _test_head_node_nics(remote_command_executor, region)
    _test_compute_node_nics(cluster, region, remote_command_executor, scheduler_commands)
    _test_overrides_file_exists(remote_command_executor)
    _test_override_primary_nic_sg(cluster, region, "cr-efa-override-primary", override_sg_id)
    _test_override_secondary_nic_sg(cluster, region, "cr-efa-override-secondary", override_sg_id)
    _test_override_no_efa_primary_nic(cluster, region, "cr-no-efa-override", override_sg_id)


# ---------------------------------------------------------------------------
# Existing NIC tests (unchanged)
# ---------------------------------------------------------------------------

def _get_private_ip_addresses(instance_id):
    ec2_client = boto3.client("ec2")
    instance_info = ec2_client.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]
    return [
        ip_address["PrivateIpAddress"]
        for nic in instance_info["NetworkInterfaces"]
        for ip_address in nic["PrivateIpAddresses"]
    ]


def _test_head_node_nics(remote_command_executor, region):
    token = remote_command_executor.run_remote_command(
        "sudo curl --retry 3 --retry-delay 0  --fail -s -X PUT 'http://169.254.169.254/latest/api/token' "
        "-H 'X-aws-ec2-metadata-token-ttl-seconds: 300'"
    ).stdout

    head_node_instance_id = remote_command_executor.run_remote_command(
        f'sudo curl --retry 3 --retry-delay 0  --fail -s -H "X-aws-ec2-metadata-token: {token}" '
        "http://169.254.169.254/latest/meta-data/instance-id"
    ).stdout

    head_node_ip_addresses = _get_private_ip_addresses(head_node_instance_id)
    logging.info("Head node IP addresses: %s", head_node_ip_addresses)
    ip_a_result = remote_command_executor.run_remote_command("ip a | col -b").stdout

    for ip_address in head_node_ip_addresses:
        assert_that(ip_a_result).matches(".* inet {0}.*".format(ip_address))


def _test_compute_node_nics(cluster, region, remote_command_executor, scheduler_commands):
    compute_instance_id = get_compute_nodes_instance_ids(cluster.cfn_name, region)[0]
    compute_ip_addresses = _get_private_ip_addresses(compute_instance_id)
    logging.info("Compute node IP addresses: %s", compute_ip_addresses)
    for ip_address in compute_ip_addresses:
        _test_compute_node_nic(ip_address, remote_command_executor, scheduler_commands)


def _test_compute_node_nic(ip_address, remote_command_executor, scheduler_commands):
    result = remote_command_executor.run_remote_command("ping -c 5 {0}".format(ip_address))
    assert_that(result.stdout).matches(".*5 packets transmitted, 5 received, 0% packet loss,.*")
    result = remote_command_executor.run_remote_command(
        "ssh -o StrictHostKeyChecking=no -q {0} echo Hello".format(ip_address)
    )
    assert_that(result.stdout).matches("Hello")
    results = {}
    sites = ["amazon.com", "google.com", "github.com"]
    for site in sites:
        results[site] = _check_ping(scheduler_commands, remote_command_executor, ip_address, site)
    assert any(results.values()), f"Ping test failed for all sites. Results: {results}"


def _check_ping(scheduler_commands, remote_command_executor, ip_address, site):
    result = scheduler_commands.submit_command(
        f"ping -I {ip_address} -c 5 {site} > /shared/ping_{ip_address}_{site}.out"
    )
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    result = remote_command_executor.run_remote_command(f"cat /shared/ping_{ip_address}_{site}.out")
    return "5 packets transmitted, 5 received, 0% packet loss" in result.stdout


# ---------------------------------------------------------------------------
# LaunchSpecificationOverrides verification helpers
# ---------------------------------------------------------------------------

def _find_instance_by_compute_resource(cluster, region, compute_resource_name):
    """Find the EC2 instance launched by a specific compute resource."""
    ec2_client = boto3.client("ec2", region_name=region)
    compute_instance_ids = get_compute_nodes_instance_ids(cluster.cfn_name, region)
    for instance_id in compute_instance_ids:
        instance_info = ec2_client.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]
        tags = {tag["Key"]: tag["Value"] for tag in instance_info.get("Tags", [])}
        if tags.get("parallelcluster:compute-resource-name") == compute_resource_name:
            return instance_info
    return None


def _get_nic_by_device_index(instance_info, device_index):
    """Get a NIC from instance info by device index."""
    for nic in instance_info["NetworkInterfaces"]:
        if nic["Attachment"]["DeviceIndex"] == device_index:
            return nic
    return None


def _get_sg_ids(nic):
    """Extract security group IDs from a NIC."""
    return [sg["GroupId"] for sg in nic["Groups"]]


def _test_overrides_file_exists(remote_command_executor):
    """Verify pcluster_run_instances_overrides.json exists on head node."""
    result = remote_command_executor.run_remote_command(
        "sudo cat /opt/slurm/etc/pcluster/pcluster_run_instances_overrides.json"
    )
    assert_that(result.stdout).is_not_empty()
    logging.info("pcluster_run_instances_overrides.json content: %s", result.stdout)


def _test_override_primary_nic_sg(cluster, region, compute_resource_name, expected_sg_id):
    """
    Use Case 1/2: EFA enabled, override SG on primary NIC.

    Verify the override security group is applied to the primary NIC (DeviceIndex 0).
    """
    instance_info = _find_instance_by_compute_resource(cluster, region, compute_resource_name)
    assert_that(instance_info).described_as(
        f"Expected to find instance for compute resource {compute_resource_name}"
    ).is_not_none()

    primary_nic = _get_nic_by_device_index(instance_info, 0)
    assert_that(primary_nic).is_not_none()
    sg_ids = _get_sg_ids(primary_nic)
    logging.info(
        "CR %s primary NIC SGs: %s (expected %s)", compute_resource_name, sg_ids, expected_sg_id
    )
    assert_that(sg_ids).contains(expected_sg_id)


def _test_override_secondary_nic_sg(cluster, region, compute_resource_name, expected_sg_id):
    """
    Use Case 1/2 (non-primary card): EFA enabled, override SG on secondary NIC.

    Verify the override security group is applied to a secondary NIC (DeviceIndex 1).
    """
    instance_info = _find_instance_by_compute_resource(cluster, region, compute_resource_name)
    assert_that(instance_info).described_as(
        f"Expected to find instance for compute resource {compute_resource_name}"
    ).is_not_none()

    secondary_nic = _get_nic_by_device_index(instance_info, 1)
    assert_that(secondary_nic).described_as(
        f"Expected to find secondary NIC (DeviceIndex 1) on {compute_resource_name}"
    ).is_not_none()
    sg_ids = _get_sg_ids(secondary_nic)
    logging.info(
        "CR %s secondary NIC SGs: %s (expected %s)", compute_resource_name, sg_ids, expected_sg_id
    )
    assert_that(sg_ids).contains(expected_sg_id)


def _test_override_no_efa_primary_nic(cluster, region, compute_resource_name, expected_sg_id):
    """
    Use Case 3/4: EFA disabled, override InterfaceType + SG on primary NIC.

    Verify the override security group is applied and the InterfaceType is overridden to efa.
    """
    instance_info = _find_instance_by_compute_resource(cluster, region, compute_resource_name)
    assert_that(instance_info).described_as(
        f"Expected to find instance for compute resource {compute_resource_name}"
    ).is_not_none()

    primary_nic = _get_nic_by_device_index(instance_info, 0)
    assert_that(primary_nic).is_not_none()

    # Verify override SG
    sg_ids = _get_sg_ids(primary_nic)
    logging.info(
        "CR %s (no-efa) primary NIC SGs: %s (expected %s)", compute_resource_name, sg_ids, expected_sg_id
    )
    assert_that(sg_ids).contains(expected_sg_id)

    # Verify InterfaceType was overridden to efa (EFA was disabled in cluster config)
    interface_type = primary_nic.get("InterfaceType", "")
    logging.info(
        "CR %s (no-efa) primary NIC InterfaceType: %s (expected efa)", compute_resource_name, interface_type
    )
    assert_that(interface_type).is_equal_to("efa")
