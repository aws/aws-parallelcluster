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
from collections import namedtuple

import pytest
from assertpy import assert_that

from pcluster.aws.aws_resources import ImageInfo, InstanceTypeInfo
from pcluster.aws.common import AWSClientError
from pcluster.config.cluster_config import CapacityReservationTarget, CapacityType, PlacementGroup
from pcluster.validators.ec2_validators import (
    AmiOsCompatibleValidator,
    CapacityReservationResourceGroupValidator,
    CapacityReservationValidator,
    CapacityTypeValidator,
    InstanceTypeAcceleratorManufacturerValidator,
    InstanceTypeBaseAMICompatibleValidator,
    InstanceTypeMemoryInfoValidator,
    InstanceTypePlacementGroupValidator,
    InstanceTypeValidator,
    KeyPairValidator,
    PlacementGroupCapacityReservationValidator,
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
            ImageInfo({"Tags": [{"Key": "parallelcluster:os", "Value": "ubuntu2004"}]}),
            "The OS of node AMI ami-111111111111 is ubuntu2004, it is not compatible with cluster OS alinux2.",
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
            "The PlacementGroup feature must be enabled (Enabled: true) in order "
            "to assign a Name or Id parameter.  Please either remove the Name/Id parameter to disable the "
            "feature, set Enabled: true to enable it, or remove the Enabled parameter to imply it is enabled "
            "with the Name/Id given",
        ),
        (
            PlacementGroup(enabled=False, name="test"),
            {
                "PlacementGroups": [
                    {"GroupName": "test", "State": "available", "Strategy": "cluster", "GroupId": "pg-0123"}
                ]
            },
            None,
            "The PlacementGroup feature must be enabled (Enabled: true) in order "
            "to assign a Name or Id parameter.  Please either remove the Name/Id parameter to disable the "
            "feature, set Enabled: true to enable it, or remove the Enabled parameter to imply it is enabled "
            "with the Name/Id given",
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
            "Capacity reservation .* must have the same instance type as c5.xlarge.",
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
            "Capacity reservation .* must have the same instance type as c5.xlarge.",
        ),
        (
            "m5.xlarge",
            "us-east-1b",
            "c5.xlarge",
            "us-east-1a",
            "Capacity reservation .* must use the same availability zone as subnet",
        ),
        (
            "m5.xlarge",
            "us-east-1b",
            None,
            "us-east-1a",
            "The CapacityReservationId parameter can only be used with the InstanceType parameter.",
        ),
        (
            "m5.xlarge",
            "us-east-1b",
            "",
            "us-east-1a",
            "The CapacityReservationId parameter can only be used with the InstanceType parameter.",
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


mock_good_config = {"GroupConfiguration": {"Configuration": [{"Type": "AWS::EC2::CapacityReservationPool"}]}}

mock_bad_config = {"GroupConfiguration": {"Configuration": [{"Type": "AWS::EC2::MockService"}]}}

at_least_one_capacity_reservation_error_message = (
    "Capacity reservation resource group .* must have at least one capacity reservation for c5.xlarge."
)
capacity_reservation = namedtuple("CapacityReservation", "id instance_type az")


@pytest.mark.parametrize(
    "capacity_reservations_in_resource_group, group_configuration, desired_instance_type, subnet_az_map, "
    "expected_message",
    [
        (
            [capacity_reservation(id="cr-good", instance_type="c5.xlarge", az="us-east-1b")],
            mock_good_config,
            ["c5.xlarge"],
            {"subnet-123": "us-east-1b"},
            None,
        ),
        (
            [
                capacity_reservation(id="cr-bad-1", instance_type="c5.xlarge", az="us-east-1b"),
                capacity_reservation(id="cr-good", instance_type="c5.xlarge", az="us-east-1b"),
                capacity_reservation(id="cr-bad-2", instance_type="c5.xlarge", az="us-east-1b"),
            ],
            mock_good_config,
            ["c5.xlarge"],
            {"subnet-123": "us-east-1b"},
            None,
        ),
        (
            [],
            mock_good_config,
            ["c5.xlarge"],
            {"subnet-123": "us-east-1b"},
            at_least_one_capacity_reservation_error_message,
        ),
        (
            [capacity_reservation(id="cr-bad-1", instance_type="m5.xlarge", az="us-east-1b")],
            mock_good_config,
            ["c5.xlarge"],
            {"subnet-123": "us-east-1b"},
            at_least_one_capacity_reservation_error_message,
        ),
        (
            [
                capacity_reservation(id="cr-bad-1", instance_type="m5.xlarge", az="us-east-1b"),
                capacity_reservation(id="cr-bad-2", instance_type="m5.xlarge", az="us-east-1b"),
            ],
            mock_good_config,
            ["c5.xlarge"],
            {"subnet-123": "us-east-1b"},
            at_least_one_capacity_reservation_error_message,
        ),
        (
            [
                capacity_reservation(id="cr-good", instance_type="c5.xlarge", az="us-east-1b"),
            ],
            mock_bad_config,
            ["c5.xlarge"],
            {"subnet-123": "us-east-1b"},
            "Capacity reservation resource group (arn:aws:resource-groups:eu-west-1:12345678:group/skip_dummy) must be "
            "a Service Linked Group created from the AWS CLI.  See "
            "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/create-cr-group.html for more details.",
        ),
        (
            [
                capacity_reservation(id="cr-good", instance_type="c5.xlarge", az="us-east-1b"),
            ],
            "AWSClientError",
            ["c5.xlarge"],
            {"subnet-123": "us-east-1b"},
            "Capacity reservation resource group (arn:aws:resource-groups:eu-west-1:12345678:group/skip_dummy) must be"
            " a Service Linked Group created from the AWS CLI.  See "
            "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/create-cr-group.html for more details.",
        ),
        (
            [
                capacity_reservation(id="cr-test-1", instance_type="c5.xlarge", az="us-east-1b"),
            ],
            mock_good_config,
            ["c5.xlarge"],
            {"subnet-123": "us-east-1b", "subnet-456": "us-east-1a"},
            "Queue 'TestQueue' has a subnet configuration mapping to the following availability zones: 'us-east-1a' "
            "but the Capacity Reservation Group 'arn:aws:resource-groups:eu-west-1:12345678:group/skip_dummy' "
            "reserves capacity in these availability zones: 'us-east-1b'. Consider adding capacity reservations in "
            "all the availability zones covered by the queue.",
        ),
        (
            [
                capacity_reservation(id="cr-test-1", instance_type="c5.xlarge", az="us-east-1b"),
            ],
            mock_good_config,
            ["c5.xlarge"],
            {"subnet-123": "us-east-1c", "subnet-456": "us-east-1a"},
            "Queue 'TestQueue' has a subnet configuration mapping to the following availability zones: "
            "'(subnet-123: us-east-1c), (subnet-456: us-east-1a)' but the Capacity Reservation Resource Group "
            "'arn:aws:resource-groups:eu-west-1:12345678:group/skip_dummy' has reservations in these availability "
            "zones: 'us-east-1b'. You can either add a capacity reservation in the availability zones that the subnets "
            "are in or remove the Capacity Reservation from the Cluster Configuration.",
        ),
        (
            [
                capacity_reservation(id="cr-test-1", instance_type="c5.xlarge", az="us-east-1b"),
                capacity_reservation(id="cr-test-2", instance_type="c5.xlarge", az="us-east-1d"),
            ],
            mock_good_config,
            ["c5.xlarge"],
            {"subnet-123": "us-east-1c", "subnet-456": "us-east-1a"},
            "Queue 'TestQueue' has a subnet configuration mapping to the following availability zones: "
            "'(subnet-123: us-east-1c), (subnet-456: us-east-1a)' but the Capacity Reservation Resource Group "
            "'arn:aws:resource-groups:eu-west-1:12345678:group/skip_dummy' has reservations in these availability "
            "zones: 'us-east-1b, us-east-1d'. You can either add a capacity reservation in the availability zones "
            "that the subnets are in or remove the Capacity Reservation from the Cluster Configuration.",
        ),
        (
            [
                capacity_reservation(id="cr-test-1", instance_type="c5.xlarge", az="us-east-1b"),
                capacity_reservation(id="cr-test-2", instance_type="c5.xlarge", az="us-east-1d"),
            ],
            mock_good_config,
            ["c5.xlarge"],
            {"subnet-123": "us-east-1b", "subnet-456": "us-east-1d"},
            "",
        ),
        # Include CRs with instance types that have reservations in SOME of the AZs
        (
            [
                capacity_reservation(id="cr-test-1", instance_type="c5.xlarge", az="us-east-1b"),
                capacity_reservation(id="cr-test-2", instance_type="c5n.xlarge", az="us-east-1d"),
            ],
            mock_good_config,
            ["c5.xlarge", "c5n.xlarge"],
            {"subnet-123": "us-east-1b", "subnet-456": "us-east-1d"},
            "The Capacity Reservation Resource Group 'arn:aws:resource-groups:eu-west-1:12345678:group/skip_dummy' "
            "has reservations for these InstanceTypes and Availability Zones: '(c5.xlarge: us-east-1b), "
            "(c5n.xlarge: us-east-1d)'. Please consider that the cluster can launch instances in these "
            "Availability Zones that have no capacity reservations in the Resource Group for the given instance types: "
            "'{us-east-1b: ['c5n.xlarge']}, {us-east-1d: ['c5.xlarge']}'.",
        ),
        # Include CRs with instance types that have reservations in SOME of the AZs
        # and one of the Subnets/AZs in NOT covered by any of the CRs
        (
            [
                capacity_reservation(id="cr-test-1", instance_type="c5.xlarge", az="us-east-1b"),
                capacity_reservation(id="cr-test-2", instance_type="c5n.xlarge", az="us-east-1d"),
            ],
            mock_good_config,
            ["c5.xlarge", "c5n.xlarge"],
            {"subnet-123": "us-east-1b", "subnet-456": "us-east-1d", "subnet-789": "us-east-1c"},
            "The Capacity Reservation Resource Group 'arn:aws:resource-groups:eu-west-1:12345678:group/skip_dummy' "
            "has reservations for these InstanceTypes and Availability Zones: '(c5.xlarge: us-east-1b), "
            "(c5n.xlarge: us-east-1d)'. Please consider that the cluster can launch instances in these "
            "Availability Zones that have no capacity reservations in the Resource Group for the given instance types: "
            "'{us-east-1b: ['c5n.xlarge']}, {us-east-1c: ['c5.xlarge', 'c5n.xlarge']}, {us-east-1d: ['c5.xlarge']}'.",
        ),
    ],
)
def test_capacity_reservation_resource_group_validator(
    mocker,
    capacity_reservations_in_resource_group,
    group_configuration,
    desired_instance_type,
    subnet_az_map,
    expected_message,
):
    mock_aws_api(mocker)
    mocker.patch(
        "pcluster.aws.resource_groups.ResourceGroupsClient.get_capacity_reservation_ids_from_group_resources",
        side_effect=lambda group: [cr.id for cr in capacity_reservations_in_resource_group],
    )
    mocker.patch(
        "pcluster.aws.resource_groups.ResourceGroupsClient.get_group_configuration",
        side_effect=AWSClientError("mock-func", "mock-error")
        if group_configuration == "AWSClientError"
        else lambda group: group_configuration,
    )

    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_capacity_reservations",
        side_effect=lambda capacity_reservation_ids: [
            {"CapacityReservationId": cr.id, "InstanceType": cr.instance_type, "AvailabilityZone": cr.az}
            for cr in capacity_reservations_in_resource_group
        ],
    )
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_subnet_avail_zone",
        side_effect=lambda subnet_id: subnet_az_map.get(subnet_id),
    )
    actual_failures = CapacityReservationResourceGroupValidator().execute(
        capacity_reservation_resource_group_arn="arn:aws:resource-groups:eu-west-1:12345678:group/skip_dummy",
        instance_types=desired_instance_type,
        subnet_ids=subnet_az_map.keys(),
        queue_name="TestQueue",
        subnet_id_az_mapping=subnet_az_map,
    )
    assert_failure_messages(actual_failures, expected_message)


mock_odcrs = [
    {
        "CapacityReservationId": "cr-123",
        "InstanceType": "mock-type",
        "AvailabilityZone": "mock-zone",
    },
    {
        "CapacityReservationId": "cr-321",
        "InstanceType": "mock-type",
        "AvailabilityZone": "mock-zone",
        "PlacementGroupArn": "mock-acct/mock-arn",
    },
    {
        "CapacityReservationId": "cr-456",
        "InstanceType": "mock-type-2",
        "AvailabilityZone": "mock-zone",
        "PlacementGroupArn": "mock-acct/mock-arn",
    },
]


@pytest.mark.parametrize(
    "placement_group, odcr, subnets, instance_types, odcr_list, "
    "multi_az_enabled, subnet_id_az_mapping, expected_message",
    [
        (None, None, "mock-subnet-1", ["mock-type"], mock_odcrs[:2], False, {"mock-subnet-1": "us-east-1"}, None),
        (
            None,
            CapacityReservationTarget(capacity_reservation_id="cr-123"),
            ["mock-subnet-1"],
            ["mock-type"],
            mock_odcrs[:2],
            False,
            {"mock-subnet-1": "us-east-1"},
            None,
        ),
        (
            None,
            CapacityReservationTarget(capacity_reservation_resource_group_arn="cr-123"),
            ["mock-subnet-1"],
            ["mock-type", "mock-type-2"],
            mock_odcrs[:3],
            False,
            {"mock-subnet-1": "us-east-1"},
            None,
        ),
        (
            None,
            CapacityReservationTarget(capacity_reservation_id="cr-123"),
            ["mock-subnet-1"],
            ["mock-type", "mock-type-2"],
            mock_odcrs[:2],
            False,
            {"mock-subnet-1": "us-east-1"},
            "There are no open or targeted ODCRs that match the instance_type 'mock-type-2' in 'us-east-1' and "
            "no placement group provided. Please either provide a placement group or add an ODCR that does not target "
            "a placement group and targets the instance type.",
        ),
        (
            "mock-placement",
            CapacityReservationTarget(capacity_reservation_id="cr-123"),
            ["mock-subnet-2"],
            ["mock-type"],
            mock_odcrs[:2],
            False,
            {"mock-subnet-1": "us-east-1"},
            "When using an open or targeted capacity reservation with an unrelated placement group, "
            "insufficient capacity errors may occur due to placement constraints outside of the "
            "reservation even if the capacity reservation has remaining capacity. Please consider either "
            "not using a placement group for the compute resource or creating a new capacity reservation "
            "in a related placement group.",
        ),
        (
            "test",
            CapacityReservationTarget(capacity_reservation_id="cr-123"),
            ["mock-subnet-3"],
            ["mock-type"],
            mock_odcrs[1:2],
            False,
            {"mock-subnet-1": "us-east-1"},
            "The placement group provided 'test' targets the 'mock-type' instance type but there "
            "are no ODCRs included in the resource group that target that instance type.",
        ),
        (
            "test-2",
            CapacityReservationTarget(capacity_reservation_id="cr-123"),
            ["mock-subnet-3"],
            ["mock-type"],
            mock_odcrs[1:2],
            False,
            {"mock-subnet-1": "us-east-1"},
            "The placement group provided 'test-2' targets the 'mock-type' instance type but there "
            "are no ODCRs included in the resource group that target that instance type.",
        ),
        (
            None,
            CapacityReservationTarget(capacity_reservation_resource_group_arn="cr-123"),
            ["mock-subnet-1", "mock-subnet-2"],
            ["mock-type", "mock-type-2"],
            mock_odcrs[:3],
            True,
            {"mock-subnet-1": "us-east-1"},
            None,
        ),
        (
            None,
            CapacityReservationTarget(capacity_reservation_resource_group_arn="cr-123"),
            ["mock-subnet-1", "mock-subnet-2"],
            ["mock-type"],
            mock_odcrs[:3],
            True,
            {"mock-subnet-1": "us-east-1"},
            None,
        ),
    ],
)
def test_placement_group_capacity_reservation_validator(
    mocker,
    placement_group,
    odcr,
    subnets,
    instance_types,
    odcr_list,
    multi_az_enabled,
    subnet_id_az_mapping,
    expected_message,
):
    mock_aws_api(mocker)
    desired_availability_zone = "mock-zone"
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_capacity_reservations",
        side_effect=lambda capacity_reservation_ids: odcr_list,
    )
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_subnet_avail_zone",
        return_value=desired_availability_zone,
    )
    actual_failure = PlacementGroupCapacityReservationValidator().execute(
        placement_group=placement_group,
        odcr=odcr,
        subnet=subnets[0],
        instance_types=instance_types,
        multi_az_enabled=multi_az_enabled,
        subnet_id_az_mapping=subnet_id_az_mapping,
    )
    assert_failure_messages(actual_failure, expected_message)


@pytest.mark.parametrize(
    "instance_type, instance_type_data, expected_message, logger_message",
    [
        (
            "p4d.24xlarge",
            {
                "InstanceType": "p4d.24xlarge",
                "GpuInfo": {
                    "Gpus": [
                        {"Name": "A100", "Manufacturer": "NVIDIA", "Count": 8, "MemoryInfo": {"SizeInMiB": 40960}}
                    ],
                    "TotalGpuMemoryInMiB": 327680,
                },
            },
            None,
            "",
        ),
        (
            "dl1.24xlarge",
            {
                "InstanceType": "dl1.24xlarge",
                "GpuInfo": {
                    "Gpus": [
                        {
                            "Name": "Gaudi HL-205",
                            "Manufacturer": "Habana",
                            "Count": 8,
                            "MemoryInfo": {"SizeInMiB": 32768},
                        }
                    ],
                    "TotalGpuMemoryInMiB": 262144,
                },
            },
            "The accelerator manufacturer 'Habana' for instance type 'dl1.24xlarge' is not supported.",
            "offers native support for NVIDIA manufactured GPUs only.* GPU Info: .*Please "
            "make sure to use a custom AMI",
        ),
        (
            "g4ad.16xlarge",
            {
                "InstanceType": "g4ad.16xlarge",
                "GpuInfo": {
                    "Gpus": [
                        {
                            "Name": "Radeon Pro V520",
                            "Manufacturer": "AMD",
                            "Count": 4,
                            "MemoryInfo": {"SizeInMiB": 8192},
                        }
                    ],
                    "TotalGpuMemoryInMiB": 32768,
                },
            },
            "The accelerator manufacturer 'AMD' for instance type 'g4ad.16xlarge' is not supported.",
            "offers native support for NVIDIA manufactured GPUs only.* GPU Info: .*Please "
            "make sure to use a custom AMI",
        ),
        (
            "t2.medium",
            {
                "InstanceType": "t2.medium",
            },
            None,
            "",
        ),
        (
            "inf1.24xlarge",
            {
                "InstanceType": "inf1.24xlarge",
                "InferenceAcceleratorInfo": {
                    "Accelerators": [{"Count": 16, "Name": "Inferentia", "Manufacturer": "AWS"}]
                },
            },
            None,
            "",
        ),
        (
            "noexist.24xlarge",
            {
                "InstanceType": "noexist.24xlarge",
                "InferenceAcceleratorInfo": {
                    "Accelerators": [{"Count": 8, "Name": "Inferentia", "Manufacturer": "Company"}]
                },
            },
            "The accelerator manufacturer 'Company' for instance type 'noexist.24xlarge' is not supported.",
            "offers native support for 'AWS' manufactured Inference Accelerators only.* accelerator info: .*Please "
            "make sure to use a custom AMI",
        ),
    ],
)
def test_instance_type_accelerator_manufacturer_validator(
    mocker, instance_type, instance_type_data, expected_message, logger_message, caplog
):
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.list_instance_types", return_value=[instance_type])

    actual_failures = InstanceTypeAcceleratorManufacturerValidator().execute(instance_type, instance_type_data)
    assert_failure_messages(actual_failures, expected_message)
    if logger_message:
        assert_that(caplog.text).matches(logger_message)


@pytest.mark.parametrize(
    "instance_type, instance_type_data, placement_group_enabled, expected_message",
    [
        (
            "t3.large",
            {
                "InstanceType": "t3.large",
                "PlacementGroupInfo": {"SupportedStrategies": ["partition", "spread"]},
            },
            True,
            "The instance type 't3.large' doesn't support being launched in a cluster placement group.",
        ),
        (
            "t3.large",
            {
                "InstanceType": "t3.large",
                "PlacementGroupInfo": {"SupportedStrategies": ["partition", "spread"]},
            },
            False,
            "",
        ),
        (
            "c5.large",
            {
                "InstanceType": "c5.large",
                "PlacementGroupInfo": {"SupportedStrategies": ["cluster", "partition", "spread"]},
            },
            True,
            "",
        ),
        (
            "t3.large",
            {
                "InstanceType": "t3.large",
                "PlacementGroupInfo": {"SupportedStrategies": ["cluster", "partition", "spread"]},
            },
            False,
            "",
        ),
        (
            "noexist.24xlarge",
            {
                "InstanceType": "noexist.24xlarge",
                "PlacementGroupInfo": {},
            },
            True,
            "The instance type 'noexist.24xlarge' doesn't support being launched in a cluster placement group.",
        ),
        (
            "noexist.24xlarge",
            {
                "InstanceType": "noexist.24xlarge",
                "PlacementGroupInfo": {},
            },
            False,
            "",
        ),
    ],
)
def test_instance_type_placement_group_validator(
    mocker,
    instance_type,
    instance_type_data,
    placement_group_enabled,
    expected_message,
):
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.list_instance_types", return_value=[instance_type])

    actual_failures = InstanceTypePlacementGroupValidator().execute(
        instance_type, instance_type_data, placement_group_enabled
    )
    assert_failure_messages(actual_failures, expected_message)
