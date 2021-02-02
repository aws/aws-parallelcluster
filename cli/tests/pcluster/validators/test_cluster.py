# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import pytest
from assertpy import assert_that

from pcluster.models.common import DynamicParam, Param
from pcluster.validators.cluster_validators import (
    ArchitectureOsValidator,
    AwsbatchInstancesArchitectureCompatibilityValidator,
    EfaOsArchitectureValidator,
    FsxNetworkingValidator,
    InstanceArchitectureCompatibilityValidator,
    SimultaneousMultithreadingArchitectureValidator,
)
from tests.common import MockedBoto3Request
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.validators.cluster_validators.boto3"


@pytest.mark.parametrize(
    "fsx_vpc, ip_permissions, network_interfaces, expected_message",
    [
        (  # working case, right vpc and sg, multiple network interfaces
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            ["eni-09b9460295ddd4e5f", "eni-001b3cef7c78b45c4"],
            None,
        ),
        (  # working case, right vpc and sg, single network interface
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # not working case --> no network interfaces
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            [],
            "doesn't have Elastic Network Interfaces attached",
        ),
        (  # not working case --> wrong vpc
            "vpc-06e4ab6c6ccWRONG",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            ["eni-09b9460295ddd4e5f"],
            "only support using FSx file system that is in the same VPC as the stack",
        ),
        (  # not working case --> wrong ip permissions in security group
            "vpc-06e4ab6c6cWRONG",
            [
                {
                    "PrefixListIds": [],
                    "FromPort": 22,
                    "IpRanges": [{"CidrIp": "203.0.113.0/24"}],
                    "ToPort": 22,
                    "IpProtocol": "tcp",
                    "UserIdGroupPairs": [],
                }
            ],
            ["eni-09b9460295ddd4e5f"],
            [
                "only support using FSx file system that is in the same VPC as the stack",
                "does not satisfy mounting requirement",
            ],
        ),
    ],
)
def test_fsx_network_validator(boto3_stubber, fsx_vpc, ip_permissions, network_interfaces, expected_message):
    describe_file_systems_response = {
        "FileSystems": [
            {
                "VpcId": fsx_vpc,
                "NetworkInterfaceIds": network_interfaces,
                "SubnetIds": ["subnet-12345678"],
                "FileSystemType": "LUSTRE",
                "CreationTime": 1567636453.038,
                "ResourceARN": "arn:aws:fsx:us-west-2:111122223333:file-system/fs-0ff8da96d57f3b4e3",
                "StorageCapacity": 3600,
                "LustreConfiguration": {"WeeklyMaintenanceStartTime": "4:07:00"},
                "FileSystemId": "fs-0ff8da96d57f3b4e3",
                "DNSName": "fs-0ff8da96d57f3b4e3.fsx.us-west-2.amazonaws.com",
                "OwnerId": "059623208481",
                "Lifecycle": "AVAILABLE",
            }
        ]
    }
    fsx_mocked_requests = [
        MockedBoto3Request(
            method="describe_file_systems",
            response=describe_file_systems_response,
            expected_params={"FileSystemIds": ["fs-0ff8da96d57f3b4e3"]},
        )
    ]
    boto3_stubber("fsx", fsx_mocked_requests)

    describe_subnets_response = {
        "Subnets": [
            {
                "AvailabilityZone": "us-east-2c",
                "AvailabilityZoneId": "use2-az3",
                "AvailableIpAddressCount": 248,
                "CidrBlock": "10.0.1.0/24",
                "DefaultForAz": False,
                "MapPublicIpOnLaunch": False,
                "State": "available",
                "SubnetId": "subnet-12345678",
                "VpcId": "vpc-06e4ab6c6cEXAMPLE",
                "OwnerId": "111122223333",
                "AssignIpv6AddressOnCreation": False,
                "Ipv6CidrBlockAssociationSet": [],
                "Tags": [{"Key": "Name", "Value": "MySubnet"}],
                "SubnetArn": "arn:aws:ec2:us-east-2:111122223333:subnet/subnet-12345678",
            }
        ]
    }
    ec2_mocked_requests = [
        MockedBoto3Request(
            method="describe_subnets",
            response=describe_subnets_response,
            expected_params={"SubnetIds": ["subnet-12345678"]},
        )
    ]

    if network_interfaces:
        network_interfaces_in_response = []
        for network_interface in network_interfaces:
            network_interfaces_in_response.append(
                {
                    "Association": {
                        "AllocationId": "eipalloc-01564b674a1a88a47",
                        "AssociationId": "eipassoc-02726ee370e175cea",
                        "IpOwnerId": "111122223333",
                        "PublicDnsName": "ec2-34-248-114-123.eu-west-1.compute.amazonaws.com",
                        "PublicIp": "34.248.114.123",
                    },
                    "Attachment": {
                        "AttachmentId": "ela-attach-0cf98331",
                        "DeleteOnTermination": False,
                        "DeviceIndex": 1,
                        "InstanceOwnerId": "amazon-aws",
                        "Status": "attached",
                    },
                    "AvailabilityZone": "eu-west-1a",
                    "Description": "Interface for NAT Gateway nat-0a8b0e0d28266841f",
                    "Groups": [{"GroupName": "default", "GroupId": "sg-12345678"}],
                    "InterfaceType": "nat_gateway",
                    "Ipv6Addresses": [],
                    "MacAddress": "0a:e5:8a:82:fd:24",
                    "NetworkInterfaceId": network_interface,
                    "OwnerId": "111122223333",
                    "PrivateDnsName": "ip-10-0-124-85.eu-west-1.compute.internal",
                    "PrivateIpAddress": "10.0.124.85",
                    "PrivateIpAddresses": [
                        {
                            "Association": {
                                "AllocationId": "eipalloc-01564b674a1a88a47",
                                "AssociationId": "eipassoc-02726ee370e175cea",
                                "IpOwnerId": "111122223333",
                                "PublicDnsName": "ec2-34-248-114-123.eu-west-1.compute.amazonaws.com",
                                "PublicIp": "34.248.114.123",
                            },
                            "Primary": True,
                            "PrivateDnsName": "ip-10-0-124-85.eu-west-1.compute.internal",
                            "PrivateIpAddress": "10.0.124.85",
                        }
                    ],
                    "RequesterId": "036872051663",
                    "RequesterManaged": True,
                    "SourceDestCheck": False,
                    "Status": "in-use",
                    "SubnetId": "subnet-12345678",
                    "TagSet": [],
                    "VpcId": fsx_vpc,
                }
            )
        describe_network_interfaces_response = {"NetworkInterfaces": network_interfaces_in_response}
        ec2_mocked_requests.append(
            MockedBoto3Request(
                method="describe_network_interfaces",
                response=describe_network_interfaces_response,
                expected_params={"NetworkInterfaceIds": network_interfaces},
            )
        )

        if fsx_vpc == "vpc-06e4ab6c6cEXAMPLE":
            # the describe security group is performed only if the VPC of the network interface is the same of the FSX
            describe_security_groups_response = {
                "SecurityGroups": [
                    {
                        "IpPermissionsEgress": ip_permissions,
                        "Description": "My security group",
                        "IpPermissions": ip_permissions,
                        "GroupName": "MySecurityGroup",
                        "OwnerId": "123456789012",
                        "GroupId": "sg-12345678",
                    }
                ]
            }
            ec2_mocked_requests.append(
                MockedBoto3Request(
                    method="describe_security_groups",
                    response=describe_security_groups_response,
                    expected_params={"GroupIds": ["sg-12345678"]},
                )
            )

    boto3_stubber("ec2", ec2_mocked_requests)

    actual_failures = FsxNetworkingValidator()(Param("fs-0ff8da96d57f3b4e3"), Param("subnet-12345678"))
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "simultaneous_multithreading, architecture, expected_message",
    [
        (True, "x86_64", None),
        (False, "x86_64", None),
        (
            True,
            "arm64",
            "Simultaneous Multithreading is only supported on instance types that support these architectures",
        ),
        (False, "arm64", None),
    ],
)
def test_simultaneous_multithreading_architecture_validator(
    simultaneous_multithreading, architecture, expected_message
):
    actual_failures = SimultaneousMultithreadingArchitectureValidator()(
        Param(simultaneous_multithreading), DynamicParam(lambda: architecture)
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "efa_enabled, os, architecture, expected_message",
    [
        (True, "alinux2", "x86_64", None),
        (True, "alinux2", "arm64", None),
        (True, "centos8", "x86_64", None),
        (
            True,
            "centos8",
            "arm64",
            "EFA currently not supported on centos8 for arm64 architecture",
        ),
        (False, "centos8", "arm64", None),
        (True, "ubuntu1804", "x86_64", None),
        (True, "ubuntu1804", "arm64", None),
    ],
)
def test_efa_os_architecture_validator(efa_enabled, os, architecture, expected_message):
    actual_failures = EfaOsArchitectureValidator()(Param(efa_enabled), Param(os), DynamicParam(lambda: architecture))
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "os, architecture, expected_message",
    [
        # All OSes supported for x86_64
        ("alinux", "x86_64", None),
        ("alinux2", "x86_64", None),
        ("centos7", "x86_64", None),
        ("centos8", "x86_64", None),
        ("ubuntu1604", "x86_64", None),
        ("ubuntu1804", "x86_64", None),
        # Only a subset of OSes supported for arm64
        ("alinux", "arm64", "arm64 is only supported for the following operating systems"),
        ("alinux2", "arm64", None),
        ("centos7", "arm64", "arm64 is only supported for the following operating systems"),
        ("centos8", "arm64", None),
        ("ubuntu1604", "arm64", "arm64 is only supported for the following operating systems"),
        ("ubuntu1804", "arm64", None),
    ],
)
def test_architecture_os_validator(os, architecture, expected_message):
    """Verify that the correct set of OSes is supported for each supported architecture."""
    actual_failures = ArchitectureOsValidator()(Param(os), DynamicParam(lambda: architecture))
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "head_node_architecture, compute_architecture, compute_instance_type, expected_message",
    [
        ("x86_64", "x86_64", "c5.xlarge", None),
        (
            "x86_64",
            "arm64",
            "m6g.xlarge",
            "none of which are compatible with the architecture supported by the head node instance type",
        ),
        (
            "arm64",
            "x86_64",
            "c5.xlarge",
            "none of which are compatible with the architecture supported by the head node instance type",
        ),
        ("arm64", "arm64", "m6g.xlarge", None),
    ],
)
def test_instance_architecture_compatibility_validator(
    mocker, head_node_architecture, compute_architecture, compute_instance_type, expected_message
):
    mocker.patch(
        "pcluster.validators.cluster_validators.get_supported_architectures_for_instance_type",
        return_value=[compute_architecture],
    )
    actual_failures = InstanceArchitectureCompatibilityValidator()(
        Param(compute_instance_type), DynamicParam(lambda: head_node_architecture)
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "head_node_architecture, compute_architecture, compute_instance_types, expected_message",
    [
        ("x86_64", "x86_64", "optimal", None),
        # Function to get supported architectures shouldn't be called because compute instance types arg
        # are instance families.
        ("x86_64", None, "m6g", "Not validating architecture"),
        ("x86_64", None, "c5", "Not validating architecture"),
        # The validator must handle the case where compute instance type is a CSV list
        ("arm64", "arm64", "m6g.xlarge,r6g.xlarge", None),
        (
            "x86_64",
            "arm64",
            "m6g.xlarge,r6g.xlarge",
            "none of which are compatible with the architecture supported by the head node instance type",
        ),
    ],
)
def test_awsbatch_instances_architecture_compatibility_validator(
    mocker, head_node_architecture, compute_architecture, compute_instance_types, expected_message
):
    def _internal_is_instance_type(itype):
        return "." in itype or itype == "optimal"

    supported_architectures_patch = mocker.patch(
        "pcluster.validators.cluster_validators.get_supported_architectures_for_instance_type",
        return_value=[compute_architecture],
    )
    is_instance_type_patch = mocker.patch(
        "pcluster.validators.cluster_validators.is_instance_type_format", side_effect=_internal_is_instance_type
    )

    instance_types = compute_instance_types.split(",")

    actual_failures = AwsbatchInstancesArchitectureCompatibilityValidator()(
        Param(compute_instance_types), DynamicParam(lambda: head_node_architecture)
    )
    assert_failure_messages(actual_failures, expected_message)
    if expected_message:
        assert_that(len(actual_failures)).is_equal_to(len(instance_types))

    non_instance_families = [
        instance_type for instance_type in instance_types if _internal_is_instance_type(instance_type)
    ]
    assert_that(supported_architectures_patch.call_count).is_equal_to(len(non_instance_families))
    assert_that(is_instance_type_patch.call_count).is_equal_to(len(instance_types))
