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

from pcluster.aws.aws_resources import ImageInfo, InstanceTypeInfo
from pcluster.aws.common import AWSClientError
from pcluster.config.cluster_config import CapacityType, PlacementGroup
from pcluster.validators.ec2_validators import (
    AmiOsCompatibleValidator,
    CapacityReservationResourceGroupValidator,
    CapacityReservationValidator,
    CapacityTypeValidator,
    InstanceTypeBaseAMICompatibleValidator,
    InstanceTypeMemoryInfoValidator,
    InstanceTypeValidator,
    KeyPairValidator,
    PlacementGroupNamingValidator,
)
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "instance_type, expected_message", [("t2.micro", None), ("c4.xlarge", None), ("c5.xlarge", "is not supported")]
)
def test_instance_type_validator(mocker, instance_type, expected_message):
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.list_instance_types", return_value=["t2.micro", "c4.xlarge"])

    actual_failures = InstanceTypeValidator().execute(instance_type)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "instance_type, instance_type_data, expected_message",
    [
        (
            "t2.medium",
            {
                "InstanceType": "t2.medium",
                "CurrentGeneration": True,
                "FreeTierEligible": False,
                "SupportedUsageClasses": ["on-demand", "spot"],
                "SupportedRootDeviceTypes": ["ebs"],
                "SupportedVirtualizationTypes": ["hvm"],
                "BareMetal": False,
                "Hypervisor": "xen",
                "ProcessorInfo": {
                    "SupportedArchitectures": ["i386", "x86_64"],
                    "SustainedClockSpeedInGhz": 2.3,
                },
                "VCpuInfo": {
                    "DefaultVCpus": 2,
                    "DefaultCores": 2,
                    "DefaultThreadsPerCore": 1,
                },
                "MemoryInfo": {"SizeInMiB": 4096},
                "InstanceStorageSupported": False,
                "EbsInfo": {
                    "EbsOptimizedSupport": "unsupported",
                    "EncryptionSupport": "supported",
                    "NvmeSupport": "unsupported",
                },
                "NetworkInfo": {
                    "NetworkPerformance": "Low to Moderate",
                    "MaximumNetworkInterfaces": 3,
                    "MaximumNetworkCards": 1,
                    "DefaultNetworkCardIndex": 0,
                    "NetworkCards": [
                        {
                            "NetworkCardIndex": 0,
                            "NetworkPerformance": "Low to Moderate",
                            "MaximumNetworkInterfaces": 3,
                        },
                    ],
                    "Ipv4AddressesPerInterface": 6,
                    "Ipv6AddressesPerInterface": 6,
                    "Ipv6Supported": True,
                    "EnaSupport": "unsupported",
                    "EfaSupported": False,
                    "EncryptionInTransitSupported": False,
                },
                "PlacementGroupInfo": {"SupportedStrategies": ["partition", "spread"]},
                "HibernationSupported": True,
                "BurstablePerformanceSupported": True,
                "DedicatedHostsSupported": False,
                "AutoRecoverySupported": True,
                "SupportedBootModes": ["legacy-bios"],
            },
            None,
        ),
        (
            "t2.medium",
            {
                "InstanceType": "t2.medium",
                "CurrentGeneration": True,
                "FreeTierEligible": False,
                "SupportedUsageClasses": ["on-demand", "spot"],
                "SupportedRootDeviceTypes": ["ebs"],
                "SupportedVirtualizationTypes": ["hvm"],
                "BareMetal": False,
                "Hypervisor": "xen",
                "ProcessorInfo": {
                    "SupportedArchitectures": ["i386", "x86_64"],
                    "SustainedClockSpeedInGhz": 2.3,
                },
                "VCpuInfo": {
                    "DefaultVCpus": 2,
                    "DefaultCores": 2,
                    "DefaultThreadsPerCore": 1,
                },
                "InstanceStorageSupported": False,
                "EbsInfo": {
                    "EbsOptimizedSupport": "unsupported",
                    "EncryptionSupport": "supported",
                    "NvmeSupport": "unsupported",
                },
                "NetworkInfo": {
                    "NetworkPerformance": "Low to Moderate",
                    "MaximumNetworkInterfaces": 3,
                    "MaximumNetworkCards": 1,
                    "DefaultNetworkCardIndex": 0,
                    "NetworkCards": [
                        {
                            "NetworkCardIndex": 0,
                            "NetworkPerformance": "Low to Moderate",
                            "MaximumNetworkInterfaces": 3,
                        },
                    ],
                    "Ipv4AddressesPerInterface": 6,
                    "Ipv6AddressesPerInterface": 6,
                    "Ipv6Supported": True,
                    "EnaSupport": "unsupported",
                    "EfaSupported": False,
                    "EncryptionInTransitSupported": False,
                },
                "PlacementGroupInfo": {"SupportedStrategies": ["partition", "spread"]},
                "HibernationSupported": True,
                "BurstablePerformanceSupported": True,
                "DedicatedHostsSupported": False,
                "AutoRecoverySupported": True,
                "SupportedBootModes": ["legacy-bios"],
            },
            "EC2 does not provide memory information for instance type 't2.medium'.",
        ),
        (
            "t2.medium",
            {
                "InstanceType": "t2.medium",
                "CurrentGeneration": True,
                "FreeTierEligible": False,
                "SupportedUsageClasses": ["on-demand", "spot"],
                "SupportedRootDeviceTypes": ["ebs"],
                "SupportedVirtualizationTypes": ["hvm"],
                "BareMetal": False,
                "Hypervisor": "xen",
                "ProcessorInfo": {
                    "SupportedArchitectures": ["i386", "x86_64"],
                    "SustainedClockSpeedInGhz": 2.3,
                },
                "VCpuInfo": {
                    "DefaultVCpus": 2,
                    "DefaultCores": 2,
                    "DefaultThreadsPerCore": 1,
                },
                "MemoryInfo": {},
                "InstanceStorageSupported": False,
                "EbsInfo": {
                    "EbsOptimizedSupport": "unsupported",
                    "EncryptionSupport": "supported",
                    "NvmeSupport": "unsupported",
                },
                "NetworkInfo": {
                    "NetworkPerformance": "Low to Moderate",
                    "MaximumNetworkInterfaces": 3,
                    "MaximumNetworkCards": 1,
                    "DefaultNetworkCardIndex": 0,
                    "NetworkCards": [
                        {
                            "NetworkCardIndex": 0,
                            "NetworkPerformance": "Low to Moderate",
                            "MaximumNetworkInterfaces": 3,
                        },
                    ],
                    "Ipv4AddressesPerInterface": 6,
                    "Ipv6AddressesPerInterface": 6,
                    "Ipv6Supported": True,
                    "EnaSupport": "unsupported",
                    "EfaSupported": False,
                    "EncryptionInTransitSupported": False,
                },
                "PlacementGroupInfo": {"SupportedStrategies": ["partition", "spread"]},
                "HibernationSupported": True,
                "BurstablePerformanceSupported": True,
                "DedicatedHostsSupported": False,
                "AutoRecoverySupported": True,
                "SupportedBootModes": ["legacy-bios"],
            },
            "EC2 does not provide memory information for instance type 't2.medium'.",
        ),
    ],
)
def test_instance_type_memory_info_validator(mocker, instance_type, instance_type_data, expected_message):
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.list_instance_types", return_value=["t2.medium"])

    actual_failures = InstanceTypeMemoryInfoValidator().execute(instance_type, instance_type_data)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "instance_type, parent_image, expected_message, ami_response, ami_side_effect, instance_response, "
    "instance_architectures",
    [
        (
            "c5.xlarge",
            "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
            None,
            {
                "ImageId": "ami-0185634c5a8a37250",
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "DeleteOnTermination": True,
                            "SnapshotId": "snap-0a20b6671bc5e3ead",
                            "VolumeSize": 25,
                            "VolumeType": "gp2",
                            "Encrypted": False,
                        },
                    }
                ],
            },
            None,
            ["m6g.xlarge", "c5.xlarge"],
            ["x86_64"],
        ),
        (
            "m6g.xlarge",
            "ami-0185634c5a8a37250",
            "AMI ami-0185634c5a8a37250's architecture \\(x86_64\\) is incompatible with the architecture supported by "
            "the instance type m6g.xlarge chosen \\(\\['arm64'\\]\\). "
            "Use either a different AMI or a different instance type.",
            {
                "ImageId": "ami-0185634c5a8a37250",
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "DeleteOnTermination": True,
                            "SnapshotId": "snap-0a20b6671bc5e3ead",
                            "VolumeSize": 25,
                            "VolumeType": "gp2",
                            "Encrypted": False,
                        },
                    }
                ],
            },
            None,
            ["m6g.xlarge", "c5.xlarge"],
            ["arm64"],
        ),
        (
            "m6g.xlarge",
            "ami-000000000000",
            "Invalid image 'ami-000000000000'",
            None,
            AWSClientError(function_name="describe_image", message="error"),
            ["m6g.xlarge", "c5.xlarge"],
            ["arm64"],
        ),
        (
            "p4d.24xlarge",
            "ami-0185634c5a8a37250",
            "The instance type 'p4d.24xlarge' is not supported.",
            {
                "ImageId": "ami-0185634c5a8a37250",
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "DeleteOnTermination": True,
                            "SnapshotId": "snap-0a20b6671bc5e3ead",
                            "VolumeSize": 25,
                            "VolumeType": "gp2",
                            "Encrypted": False,
                        },
                    }
                ],
            },
            None,
            ["m6g.xlarge", "c5.xlarge"],
            [],
        ),
    ],
)
def test_instance_type_base_ami_compatible_validator(
    mocker,
    instance_type,
    parent_image,
    expected_message,
    ami_response,
    ami_side_effect,
    instance_response,
    instance_architectures,
):
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mock_aws_api(mocker)
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image", return_value=ImageInfo(ami_response), side_effect=ami_side_effect
    )
    mocker.patch("pcluster.aws.ec2.Ec2Client.list_instance_types", return_value=instance_response)
    mocker.patch("pcluster.aws.ec2.Ec2Client.get_supported_architectures", return_value=instance_architectures)
    actual_failures = InstanceTypeBaseAMICompatibleValidator().execute(instance_type=instance_type, image=parent_image)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "key_pair, side_effect, expected_message",
    [
        ("key-name", None, None),
        (None, None, "If you do not specify a key pair"),
        ("c5.xlarge", AWSClientError(function_name="describe_key_pair", message="does not exist"), "does not exist"),
    ],
)
def test_key_pair_validator(mocker, key_pair, side_effect, expected_message):
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.describe_key_pair", return_value=key_pair, side_effect=side_effect)
    actual_failures = KeyPairValidator().execute(key_name=key_pair)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "capacity_type, supported_usage_classes, expected_message",
    [
        (CapacityType.ONDEMAND, ["ondemand", "spot"], None),
        (CapacityType.SPOT, ["ondemand", "spot"], None),
        (CapacityType.ONDEMAND, ["ondemand"], None),
        (CapacityType.SPOT, ["spot"], None),
        (CapacityType.SPOT, [], "Could not check support for usage class 'spot' with instance type 'instance-type'"),
        (
            CapacityType.ONDEMAND,
            [],
            "Could not check support for usage class 'ondemand' with instance type 'instance-type'",
        ),
        (CapacityType.SPOT, ["ondemand"], "Usage type 'spot' not supported with instance type 'instance-type'"),
        (CapacityType.ONDEMAND, ["spot"], "Usage type 'ondemand' not supported with instance type 'instance-type'"),
    ],
)
def test_capacity_type_validator(mocker, capacity_type, supported_usage_classes, expected_message):
    mock_aws_api(mocker)
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_instance_type_info",
        return_value=InstanceTypeInfo(
            {"InstanceType": "instance-type", "SupportedUsageClasses": supported_usage_classes}
        ),
    )
    actual_failures = CapacityTypeValidator().execute(capacity_type=capacity_type, instance_type="instance-type")
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "image_id, os, ami_info, expected_message",
    [
        ("ami-000000000000", "alinux2", ImageInfo({"Tags": [{"Key": "parallelcluster:os", "Value": "alinux2"}]}), None),
        (
            "ami-111111111111",
            "alinux2",
            ImageInfo({"Tags": [{"Key": "parallelcluster:os", "Value": "ubuntu1804"}]}),
            "The OS of node AMI ami-111111111111 is ubuntu1804, it is not compatible with cluster OS alinux2.",
        ),
        (
            "ami-222222222222",
            "alinux2",
            ImageInfo({"Tags": {}}),
            "Could not check node AMI ami-222222222222 OS and cluster OS alinux2 compatibility, "
            "please make sure they are compatible before cluster creation and update operations.",
        ),
    ],
)
def test_compute_ami_os_compatible_validator(mocker, image_id, os, ami_info, expected_message):
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.describe_image", return_value=ami_info)
    actual_failures = AmiOsCompatibleValidator().execute(image_id=image_id, os=os)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "placement_group, describe_placement_group_return, side_effect, expected_message",
    [
        (
            PlacementGroup(enabled=True, id="test"),
            {
                "PlacementGroups": [
                    {"GroupName": "test", "State": "available", "Strategy": "cluster", "GroupId": "pg-0123"}
                ]
            },
            None,
            None,
        ),
        (
            PlacementGroup(enabled=True, name="test"),
            {
                "PlacementGroups": [
                    {"GroupName": "test", "State": "available", "Strategy": "cluster", "GroupId": "pg-0123"}
                ]
            },
            None,
            None,
        ),
        (
            PlacementGroup(enabled=True),
            {
                "PlacementGroups": [
                    {"GroupName": "test", "State": "available", "Strategy": "cluster", "GroupId": "pg-0123"}
                ]
            },
            None,
            None,
        ),
        (
            PlacementGroup(id="test"),
            {
                "PlacementGroups": [
                    {"GroupName": "test", "State": "available", "Strategy": "cluster", "GroupId": "pg-0123"}
                ]
            },
            None,
            None,
        ),
        (
            PlacementGroup(name="test"),
            {
                "PlacementGroups": [
                    {"GroupName": "test", "State": "available", "Strategy": "cluster", "GroupId": "pg-0123"}
                ]
            },
            None,
            None,
        ),
        (
            PlacementGroup(id="test"),
            None,
            AWSClientError(function_name="describe_placement_group", message="The Placement Group 'test' is unknown"),
            "The Placement Group 'test' is unknown",
        ),
        (
            PlacementGroup(name="test"),
            None,
            AWSClientError(function_name="describe_placement_group", message="The Placement Group 'test' is unknown"),
            "The Placement Group 'test' is unknown",
        ),
        (
            PlacementGroup(enabled=False, id="test"),
            {
                "PlacementGroups": [
                    {"GroupName": "test", "State": "available", "Strategy": "cluster", "GroupId": "pg-0123"}
                ]
            },
            None,
            "The PlacementGroup feature must be enabled (Enabled: true) in order to assign a Name or Id parameter",
        ),
        (
            PlacementGroup(enabled=False, name="test"),
            {
                "PlacementGroups": [
                    {"GroupName": "test", "State": "available", "Strategy": "cluster", "GroupId": "pg-0123"}
                ]
            },
            None,
            "The PlacementGroup feature must be enabled (Enabled: true) in order to assign a Name or Id parameter",
        ),
        (
            PlacementGroup(enabled=True, id="test", name="test2"),
            {
                "PlacementGroups": [
                    {"GroupName": "test", "State": "available", "Strategy": "cluster", "GroupId": "pg-0123"}
                ]
            },
            None,
            "PlacementGroup Id cannot be set when setting PlacementGroup Name.  Please "
            "set either Id or Name but not both.",
        ),
    ],
)
def test_placement_group_validator(
    mocker, placement_group, describe_placement_group_return, side_effect, expected_message
):
    mock_aws_api(mocker)
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_placement_group",
        return_value=describe_placement_group_return,
        side_effect=side_effect,
    )
    actual_failures = PlacementGroupNamingValidator().execute(placement_group=placement_group)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "capacity_reservation_instance_type, capacity_reservation_availability_zone, "
    "instance_type, subnet_availability_zone, expected_message",
    [
        ("c5.xlarge", "us-east-1a", "c5.xlarge", "us-east-1a", None),
        # Wrong instance type
        (
            "m5.xlarge",
            "us-east-1a",
            "c5.xlarge",
            "us-east-1a",
            "Capacity reservation .* must has the same instance type as c5.xlarge.",
        ),
        # Wrong availability zone
        (
            "c5.xlarge",
            "us-east-1b",
            "c5.xlarge",
            "us-east-1a",
            "Capacity reservation .* must use the same availability zone as subnet",
        ),
        # Both instance type and availability zone are wrong
        (
            "m5.xlarge",
            "us-east-1b",
            "c5.xlarge",
            "us-east-1a",
            "Capacity reservation .* must has the same instance type as c5.xlarge.",
        ),
        (
            "m5.xlarge",
            "us-east-1b",
            "c5.xlarge",
            "us-east-1a",
            "Capacity reservation .* must use the same availability zone as subnet",
        ),
    ],
)
def test_capacity_reservation_validator(
    mocker,
    capacity_reservation_instance_type,
    capacity_reservation_availability_zone,
    instance_type,
    subnet_availability_zone,
    expected_message,
):
    mock_aws_api(mocker)
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_capacity_reservations",
        return_value=[
            {
                "InstanceType": capacity_reservation_instance_type,
                "AvailabilityZone": capacity_reservation_availability_zone,
            }
        ],
    )
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_subnet_avail_zone",
        return_value=subnet_availability_zone,
    )
    actual_failures = CapacityReservationValidator().execute(
        capacity_reservation_id="cr-123", instance_type=instance_type, subnet="subnet-123"
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "capacity_reservations_in_resource_group, expected_message",
    [
        (["cr-good"], None),
        (["cr-bad-1", "cr-good", "cr-bad-2"], None),
        (
            [],
            "Capacity reservation resource group .* must have at least one capacity reservation "
            "for c5.xlarge in the same availability zone as subnet subnet-123.",
        ),
        (
            ["cr-bad-1"],
            "Capacity reservation resource group .* must have at least one capacity reservation "
            "for c5.xlarge in the same availability zone as subnet subnet-123.",
        ),
        (
            ["cr-bad-1", "cr-bad-2"],
            "Capacity reservation resource group .* must have at least one capacity reservation "
            "for c5.xlarge in the same availability zone as subnet subnet-123.",
        ),
    ],
)
def test_capacity_reservation_resource_group_validator(
    mocker,
    capacity_reservations_in_resource_group,
    expected_message,
):
    mock_aws_api(mocker)
    mocker.patch(
        "pcluster.aws.resource_groups.ResourceGroupsClient.get_capacity_reservation_ids_from_group_resources",
        side_effect=lambda group: capacity_reservations_in_resource_group,
    )
    desired_instance_type = "c5.xlarge"
    desired_availability_zone = "us-east-1b"
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_capacity_reservations",
        side_effect=lambda capacity_reservation_ids: [
            {
                "CapacityReservationId": capacity_reservation_id,
                "InstanceType": desired_instance_type if "good" in capacity_reservation_id else "m5.xlarge",
                "AvailabilityZone": desired_availability_zone,
            }
            for capacity_reservation_id in capacity_reservation_ids
        ],
    )
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_subnet_avail_zone",
        return_value=desired_availability_zone,
    )
    actual_failures = CapacityReservationResourceGroupValidator().execute(
        capacity_reservation_resource_group_arn="skip_dummy", instance_type=desired_instance_type, subnet="subnet-123"
    )
    assert_failure_messages(actual_failures, expected_message)
