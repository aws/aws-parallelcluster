# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import os

import pytest

import tests.pcluster.config.utils as utils
from assertpy import assert_that
from pcluster.config.validators import DCV_MESSAGES
from tests.common import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.config.validators.boto3"


def _mock_efa_supported_instances(mocker):
    mocker.patch("pcluster.config.validators.get_supported_features", return_value={"instances": ["t2.large"]})


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        # traditional scheduler
        ({"scheduler": "sge", "initial_queue_size": 1, "max_queue_size": 2, "maintain_initial_size": True}, None),
        (
            {"scheduler": "sge", "initial_queue_size": 3, "max_queue_size": 2, "maintain_initial_size": True},
            "initial_queue_size must be fewer than or equal to max_queue_size",
        ),
        (
            {"scheduler": "sge", "initial_queue_size": 3, "max_queue_size": 2, "maintain_initial_size": False},
            "initial_queue_size must be fewer than or equal to max_queue_size",
        ),
        # awsbatch
        ({"scheduler": "awsbatch", "min_vcpus": 1, "desired_vcpus": 2, "max_vcpus": 3}, None),
        (
            {"scheduler": "awsbatch", "min_vcpus": 3, "desired_vcpus": 2, "max_vcpus": 3},
            "desired_vcpus must be greater than or equal to min_vcpus",
        ),
        (
            {"scheduler": "awsbatch", "min_vcpus": 1, "desired_vcpus": 4, "max_vcpus": 3},
            "desired_vcpus must be fewer than or equal to max_vcpus",
        ),
        (
            {"scheduler": "awsbatch", "min_vcpus": 4, "desired_vcpus": 4, "max_vcpus": 3},
            "max_vcpus must be greater than or equal to min_vcpus",
        ),
    ],
)
def test_cluster_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "instance_type, expected_message", [("t2.micro", None), ("c4.xlarge", None), ("c5.xlarge", "is not supported")]
)
def test_ec2_instance_type_validator(mocker, instance_type, expected_message):
    config_parser_dict = {"cluster default": {"master_instance_type": instance_type}}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "scheduler, instance_type, expected_message",
    [
        ("sge", "t2.micro", None),
        ("sge", "c4.xlarge", None),
        ("sge", "c5.xlarge", "is not supported"),
        # NOTE: compute_instance_type_validator calls ec2_instance_type_validator only if the scheduler is not awsbatch
        ("awsbatch", "t2.micro", None),
        ("awsbatch", "c4.xlarge", "is not supported"),
        ("awsbatch", "t2", None),  # t2 family
        ("awsbatch", "optimal", None),
    ],
)
def test_compute_instance_type_validator(mocker, scheduler, instance_type, expected_message):
    config_parser_dict = {"cluster default": {"scheduler": scheduler, "compute_instance_type": instance_type}}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


def test_ec2_key_pair_validator(mocker, boto3_stubber):
    describe_key_pairs_response = {
        "KeyPairs": [
            {"KeyFingerprint": "12:bf:7c:56:6c:dd:4f:8c:24:45:75:f1:1b:16:54:89:82:09:a4:26", "KeyName": "key1"}
        ]
    }
    mocked_requests = [
        MockedBoto3Request(
            method="describe_key_pairs", response=describe_key_pairs_response, expected_params={"KeyNames": ["key1"]}
        )
    ]
    boto3_stubber("ec2", mocked_requests)

    # TODO test with invalid key
    config_parser_dict = {"cluster default": {"key_name": "key1"}}
    utils.assert_param_validator(mocker, config_parser_dict)


def test_ec2_ami_validator(mocker, boto3_stubber):
    describe_images_response = {
        "Images": [
            {
                "VirtualizationType": "paravirtual",
                "Name": "My server",
                "Hypervisor": "xen",
                "ImageId": "ami-12345678",
                "RootDeviceType": "ebs",
                "State": "available",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/sda1",
                        "Ebs": {
                            "DeleteOnTermination": True,
                            "SnapshotId": "snap-1234567890abcdef0",
                            "VolumeSize": 8,
                            "VolumeType": "standard",
                        },
                    }
                ],
                "Architecture": "x86_64",
                "ImageLocation": "123456789012/My server",
                "KernelId": "aki-88aa75e1",
                "OwnerId": "123456789012",
                "RootDeviceName": "/dev/sda1",
                "Public": False,
                "ImageType": "machine",
                "Description": "An AMI for my server",
            }
        ]
    }
    mocked_requests = [
        MockedBoto3Request(
            method="describe_images", response=describe_images_response, expected_params={"ImageIds": ["ami-12345678"]}
        )
    ]
    boto3_stubber("ec2", mocked_requests)

    # TODO test with invalid key
    config_parser_dict = {"cluster default": {"custom_ami": "ami-12345678"}}
    utils.assert_param_validator(mocker, config_parser_dict)


def test_ec2_ebs_snapshot_validator(mocker, boto3_stubber):
    describe_snapshots_response = {
        "Snapshots": [
            {
                "Description": "This is my snapshot",
                "Encrypted": False,
                "VolumeId": "vol-049df61146c4d7901",
                "State": "completed",
                "VolumeSize": 8,
                "StartTime": "2014-02-28T21:28:32.000Z",
                "Progress": "100%",
                "OwnerId": "012345678910",
                "SnapshotId": "snap-1234567890abcdef0",
            }
        ]
    }
    mocked_requests = [
        MockedBoto3Request(
            method="describe_snapshots",
            response=describe_snapshots_response,
            expected_params={"SnapshotIds": ["snap-1234567890abcdef0"]},
        )
    ]
    boto3_stubber("ec2", mocked_requests)

    # TODO test with invalid key
    config_parser_dict = {
        "cluster default": {"ebs_settings": "default"},
        "ebs default": {"shared_dir": "test", "ebs_snapshot_id": "snap-1234567890abcdef0"},
    }
    utils.assert_param_validator(mocker, config_parser_dict)


def test_ec2_volume_validator(mocker, boto3_stubber):
    describe_volumes_response = {
        "Volumes": [
            {
                "AvailabilityZone": "us-east-1a",
                "Attachments": [
                    {
                        "AttachTime": "2013-12-18T22:35:00.000Z",
                        "InstanceId": "i-1234567890abcdef0",
                        "VolumeId": "vol-12345678",
                        "State": "attached",
                        "DeleteOnTermination": True,
                        "Device": "/dev/sda1",
                    }
                ],
                "Encrypted": False,
                "VolumeType": "gp2",
                "VolumeId": "vol-049df61146c4d7901",
                "State": "available",  # TODO add test with "in-use"
                "SnapshotId": "snap-1234567890abcdef0",
                "CreateTime": "2013-12-18T22:35:00.084Z",
                "Size": 8,
            }
        ]
    }
    mocked_requests = [
        MockedBoto3Request(
            method="describe_volumes",
            response=describe_volumes_response,
            expected_params={"VolumeIds": ["vol-12345678"]},
        )
    ]
    boto3_stubber("ec2", mocked_requests)

    # TODO test with invalid key
    config_parser_dict = {
        "cluster default": {"ebs_settings": "default"},
        "ebs default": {"shared_dir": "test", "ebs_volume_id": "vol-12345678"},
    }
    utils.assert_param_validator(mocker, config_parser_dict)


@pytest.mark.parametrize(
    "region, base_os, scheduler, expected_message",
    [
        # verify awsbatch supported regions
        ("ap-northeast-3", "alinux", "awsbatch", "scheduler is not supported in the .* region"),
        ("us-gov-east-1", "alinux", "awsbatch", "scheduler is not supported in the .* region"),
        ("us-gov-west-1", "alinux", "awsbatch", "scheduler is not supported in the .* region"),
        ("eu-west-1", "alinux", "awsbatch", None),
        ("us-east-1", "alinux", "awsbatch", None),
        ("eu-north-1", "alinux", "awsbatch", None),
        ("cn-north-1", "alinux", "awsbatch", None),
        ("cn-northwest-1", "alinux", "awsbatch", None),
        # verify traditional schedulers are supported in all the regions
        ("cn-northwest-1", "alinux", "sge", None),
        ("ap-northeast-3", "alinux", "sge", None),
        ("cn-northwest-1", "alinux", "slurm", None),
        ("ap-northeast-3", "alinux", "slurm", None),
        ("cn-northwest-1", "alinux", "torque", None),
        ("ap-northeast-3", "alinux", "torque", None),
        # verify awsbatch supported OSes
        ("eu-west-1", "centos6", "awsbatch", "scheduler supports the following Operating Systems"),
        ("eu-west-1", "centos7", "awsbatch", "scheduler supports the following Operating Systems"),
        ("eu-west-1", "ubuntu1604", "awsbatch", "scheduler supports the following Operating Systems"),
        ("eu-west-1", "ubuntu1804", "awsbatch", "scheduler supports the following Operating Systems"),
        ("eu-west-1", "alinux", "awsbatch", None),
        # verify sge supports all the OSes
        ("eu-west-1", "centos6", "sge", None),
        ("eu-west-1", "centos7", "sge", None),
        ("eu-west-1", "ubuntu1604", "sge", None),
        ("eu-west-1", "ubuntu1804", "sge", None),
        ("eu-west-1", "alinux", "sge", None),
        # verify slurm supports all the OSes
        ("eu-west-1", "centos6", "slurm", None),
        ("eu-west-1", "centos7", "slurm", None),
        ("eu-west-1", "ubuntu1604", "slurm", None),
        ("eu-west-1", "ubuntu1804", "slurm", None),
        ("eu-west-1", "alinux", "slurm", None),
        # verify torque supports all the OSes
        ("eu-west-1", "centos6", "torque", None),
        ("eu-west-1", "centos7", "torque", None),
        ("eu-west-1", "ubuntu1604", "torque", None),
        ("eu-west-1", "ubuntu1804", "torque", None),
        ("eu-west-1", "alinux", "torque", None),
    ],
)
def test_scheduler_validator(mocker, region, base_os, scheduler, expected_message):
    # we need to set the region in the environment because it takes precedence respect of the config file
    os.environ["AWS_DEFAULT_REGION"] = region
    config_parser_dict = {"cluster default": {"base_os": base_os, "scheduler": scheduler}}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


def test_placement_group_validator(mocker, boto3_stubber):
    describe_placement_groups_response = {
        "PlacementGroups": [{"GroupName": "my-cluster", "State": "available", "Strategy": "cluster"}]
    }
    mocked_requests = [
        MockedBoto3Request(
            method="describe_placement_groups",
            response=describe_placement_groups_response,
            expected_params={"GroupNames": ["my-cluster"]},
        )
    ]
    boto3_stubber("ec2", mocked_requests)

    # TODO test with invalid group name
    config_parser_dict = {"cluster default": {"placement_group": "my-cluster"}}
    utils.assert_param_validator(mocker, config_parser_dict)


def test_url_validator(mocker, boto3_stubber):
    head_object_response = {
        "AcceptRanges": "bytes",
        "ContentType": "text/html",
        "LastModified": "Thu, 16 Apr 2015 18:19:14 GMT",
        "ContentLength": 77,
        "VersionId": "null",
        "ETag": '"30a6ec7e1a9ad79c203d05a589c8b400"',
        "Metadata": {},
    }
    mocked_requests = [
        MockedBoto3Request(
            method="head_object", response=head_object_response, expected_params={"Bucket": "test", "Key": "test.json"}
        )
    ]
    boto3_stubber("s3", mocked_requests)

    mocker.patch("pcluster.config.validators.urllib.request.urlopen")
    tests = [("s3://test/test.json", None), ("http://test/test.json", None)]
    for template_url, expected_message in tests:
        config_parser_dict = {"cluster default": {"template_url": template_url}}
        utils.assert_param_validator(mocker, config_parser_dict, expected_message)


def test_ec2_vpc_id_validator(mocker, boto3_stubber):
    mocked_requests = []

    # mock describe_vpc boto3 call
    describe_vpc_response = {
        "Vpcs": [
            {
                "VpcId": "vpc-12345678",
                "InstanceTenancy": "default",
                "Tags": [{"Value": "Default VPC", "Key": "Name"}],
                "State": "available",
                "DhcpOptionsId": "dopt-4ef69c2a",
                "CidrBlock": "172.31.0.0/16",
                "IsDefault": True,
            }
        ]
    }
    mocked_requests.append(
        MockedBoto3Request(
            method="describe_vpcs", response=describe_vpc_response, expected_params={"VpcIds": ["vpc-12345678"]}
        )
    )

    # mock describe_vpc_attribute boto3 call
    describe_vpc_attribute_response = {
        "VpcId": "vpc-12345678",
        "EnableDnsSupport": {"Value": True},
        "EnableDnsHostnames": {"Value": True},
    }
    mocked_requests.append(
        MockedBoto3Request(
            method="describe_vpc_attribute",
            response=describe_vpc_attribute_response,
            expected_params={"VpcId": "vpc-12345678", "Attribute": "enableDnsSupport"},
        )
    )
    mocked_requests.append(
        MockedBoto3Request(
            method="describe_vpc_attribute",
            response=describe_vpc_attribute_response,
            expected_params={"VpcId": "vpc-12345678", "Attribute": "enableDnsHostnames"},
        )
    )
    boto3_stubber("ec2", mocked_requests)

    # TODO mock and test invalid vpc-id
    for vpc_id, expected_message in [("vpc-12345678", None)]:
        config_parser_dict = {"cluster default": {"vpc_settings": "default"}, "vpc default": {"vpc_id": vpc_id}}
        utils.assert_param_validator(mocker, config_parser_dict, expected_message)


def test_ec2_subnet_id_validator(mocker, boto3_stubber):
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
    mocked_requests = [
        MockedBoto3Request(
            method="describe_subnets",
            response=describe_subnets_response,
            expected_params={"SubnetIds": ["subnet-12345678"]},
        )
    ]
    boto3_stubber("ec2", mocked_requests)

    # TODO test with invalid key
    config_parser_dict = {
        "cluster default": {"vpc_settings": "default"},
        "vpc default": {"master_subnet_id": "subnet-12345678"},
    }
    utils.assert_param_validator(mocker, config_parser_dict)


def test_ec2_security_group_validator(mocker, boto3_stubber):
    describe_security_groups_response = {
        "SecurityGroups": [
            {
                "IpPermissionsEgress": [],
                "Description": "My security group",
                "IpPermissions": [
                    {
                        "PrefixListIds": [],
                        "FromPort": 22,
                        "IpRanges": [{"CidrIp": "203.0.113.0/24"}],
                        "ToPort": 22,
                        "IpProtocol": "tcp",
                        "UserIdGroupPairs": [],
                    }
                ],
                "GroupName": "MySecurityGroup",
                "OwnerId": "123456789012",
                "GroupId": "sg-12345678",
            }
        ]
    }
    mocked_requests = [
        MockedBoto3Request(
            method="describe_security_groups",
            response=describe_security_groups_response,
            expected_params={"GroupIds": ["sg-12345678"]},
        )
    ]
    boto3_stubber("ec2", mocked_requests)

    # TODO test with invalid key
    config_parser_dict = {
        "cluster default": {"vpc_settings": "default"},
        "vpc default": {"vpc_security_group_id": "sg-12345678"},
    }
    utils.assert_param_validator(mocker, config_parser_dict)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        (
            {"throughput_mode": "bursting", "provisioned_throughput": 1024},
            "When specifying 'provisioned_throughput', the 'throughput_mode' must be set to 'provisioned'",
        ),
        ({"throughput_mode": "provisioned", "provisioned_throughput": 1024}, None),
        ({"shared_dir": "NONE"}, "NONE cannot be used as a shared directory"),
        ({"shared_dir": "/NONE"}, "/NONE cannot be used as a shared directory"),
        ({"shared_dir": "/efs"}, None),
    ],
)
def test_efs_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": {"efs_settings": "default"}, "efs default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        # Testing iops validator
        ({"volume_iops": 1, "volume_size": 1}, None),
        ({"volume_iops": 51, "volume_size": 1}, "IOPS to volume size ratio of .* is too hig"),
        ({"volume_iops": 1, "volume_size": 20}, None),
        ({"volume_iops": 1001, "volume_size": 20}, "IOPS to volume size ratio of .* is too hig"),
        # Testing shared_dir validator
        ({"shared_dir": "NONE"}, "NONE cannot be used as a shared directory"),
        ({"shared_dir": "/NONE"}, "/NONE cannot be used as a shared directory"),
        ({"shared_dir": "/raid"}, None),
    ],
)
def test_raid_validators(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": {"raid_settings": "default"}, "raid default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"imported_file_chunk_size": 1024, "import_path": "test", "storage_capacity": 1200}, None),
        (
            {"imported_file_chunk_size": 1024, "storage_capacity": 1200},
            "When specifying 'imported_file_chunk_size', the 'import_path' option must be specified",
        ),
        ({"export_path": "test", "import_path": "test", "storage_capacity": 1200}, None),
        (
            {"export_path": "test", "storage_capacity": 1200},
            "When specifying 'export_path', the 'import_path' option must be specified",
        ),
        ({"shared_dir": "NONE", "storage_capacity": 1200}, "NONE cannot be used as a shared directory"),
        ({"shared_dir": "/NONE", "storage_capacity": 1200}, "/NONE cannot be used as a shared directory"),
        ({"shared_dir": "/fsx"}, "the 'storage_capacity' option must be specified"),
        ({"shared_dir": "/fsx", "storage_capacity": 1200}, None),
    ],
)
def test_fsx_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": {"fsx_settings": "default"}, "fsx default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


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
            "does not satisfy mounting requirement",
        ),
    ],
)
def test_fsx_id_validator(mocker, boto3_stubber, fsx_vpc, ip_permissions, network_interfaces, expected_message):
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
    ] * 2

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

    config_parser_dict = {
        "cluster default": {"fsx_settings": "default", "vpc_settings": "default"},
        "vpc default": {"master_subnet_id": "subnet-12345678"},
        "fsx default": {"fsx_fs_id": "fs-0ff8da96d57f3b4e3"},
    }
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"enable_intel_hpc_platform": "true", "base_os": "centos7"}, None),
        ({"enable_intel_hpc_platform": "true", "base_os": "alinux"}, "it is required to set the 'base_os'"),
        ({"enable_intel_hpc_platform": "false", "base_os": "alinux"}, None),
    ],
)
def test_intel_hpc_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"storage_capacity": 1}, "Capacity for FSx lustre filesystem, 1,200 GB, 2,400 GB or increments of 3,600 GB"),
        ({"storage_capacity": 1200}, None),
        ({"storage_capacity": 2400}, None),
        ({"storage_capacity": 3600}, None),
        (
            {"storage_capacity": 3601},
            "Capacity for FSx lustre filesystem, 1,200 GB, 2,400 GB or increments of 3,600 GB",
        ),
        ({"storage_capacity": 7200}, None),
    ],
)
def test_fsx_storage_capacity_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": {"fsx_settings": "default"}, "fsx default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        (
            {"disable_hyperthreading": True, "extra_json": '{"cluster": {"cfn_scheduler_slots": "vcpus"}}'},
            "cfn_scheduler_slots cannot be set in addition to disable_hyperthreading = true",
        ),
        (
            {"disable_hyperthreading": True, "extra_json": '{"cluster": {"cfn_scheduler_slots": "cores"}}'},
            "cfn_scheduler_slots cannot be set in addition to disable_hyperthreading = true",
        ),
        (
            {"disable_hyperthreading": True, "extra_json": '{"cluster": {"cfn_scheduler_slots": 3}}'},
            "cfn_scheduler_slots cannot be set in addition to disable_hyperthreading = true",
        ),
        ({"disable_hyperthreading": True, "extra_json": '{"cluster": {"other_param": "fake_value"}}'}, None),
        ({"disable_hyperthreading": True}, None),
        ({"disable_hyperthreading": False, "extra_json": '{"cluster": {"cfn_scheduler_slots": "vcpus"}}'}, None),
        ({"disable_hyperthreading": False, "extra_json": '{"cluster": {"cfn_scheduler_slots": "cores"}}'}, None),
        ({"disable_hyperthreading": False, "extra_json": '{"cluster": {"cfn_scheduler_slots": 3}}'}, None),
    ],
)
def test_disable_hyperthreading_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        (
            {"imported_file_chunk_size": 0, "import_path": "test-import", "storage_capacity": 1200},
            "has a minimum size of 1 MiB, and max size of 512,000 MiB",
        ),
        ({"imported_file_chunk_size": 1, "import_path": "test-import", "storage_capacity": 1200}, None),
        ({"imported_file_chunk_size": 10, "import_path": "test-import", "storage_capacity": 1200}, None),
        ({"imported_file_chunk_size": 512000, "import_path": "test-import", "storage_capacity": 1200}, None),
        (
            {"imported_file_chunk_size": 512001, "import_path": "test-import", "storage_capacity": 1200},
            "has a minimum size of 1 MiB, and max size of 512,000 MiB",
        ),
    ],
)
def test_fsx_imported_file_chunk_size_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": {"fsx_settings": "default"}, "fsx default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_error, expected_warning",
    [
        ({"enable_efa": "NONE"}, "invalid value", None),
        ({"enable_efa": "compute"}, "is required to set the 'compute_instance_type'", None),
        (
            {"enable_efa": "compute", "compute_instance_type": "t2.large"},
            None,
            "You may see better performance using a cluster placement group",
        ),
        (
            {"enable_efa": "compute", "compute_instance_type": "t2.large", "base_os": "centos6"},
            "it is required to set the 'base_os'",
            None,
        ),
        (
            {
                "enable_efa": "compute",
                "compute_instance_type": "t2.large",
                "base_os": "alinux",
                "scheduler": "awsbatch",
            },
            "it is required to set the 'scheduler'",
            None,
        ),
        (
            {
                "enable_efa": "compute",
                "compute_instance_type": "t2.large",
                "base_os": "centos7",
                "scheduler": "slurm",
                "placement_group": "DYNAMIC",
            },
            None,
            None,
        ),
    ],
)
def test_efa_validator(mocker, capsys, section_dict, expected_error, expected_warning):
    _mock_efa_supported_instances(mocker)
    config_parser_dict = {"cluster default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_error, capsys, expected_warning)


@pytest.mark.parametrize(
    "ip_permissions, ip_permissions_egress, expected_message",
    [
        ([], [], "must allow all traffic in and out from itself"),
        (
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            [],
            "must allow all traffic in and out from itself",
        ),
        (
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            None,
        ),
        (
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
            [],
            "must allow all traffic in and out from itself",
        ),
    ],
)
def test_efa_validator_with_vpc_security_group(
    boto3_stubber, mocker, ip_permissions, ip_permissions_egress, expected_message
):
    _mock_efa_supported_instances(mocker)

    describe_security_groups_response = {
        "SecurityGroups": [
            {
                "IpPermissionsEgress": ip_permissions_egress,
                "Description": "My security group",
                "IpPermissions": ip_permissions,
                "GroupName": "MySecurityGroup",
                "OwnerId": "123456789012",
                "GroupId": "sg-12345678",
            }
        ]
    }
    mocked_requests = [
        MockedBoto3Request(
            method="describe_security_groups",
            response=describe_security_groups_response,
            expected_params={"GroupIds": ["sg-12345678"]},
        )
    ] * 2  # it is called two times, for vpc_security_group_id validation and to validate efa
    boto3_stubber("ec2", mocked_requests)

    config_parser_dict = {
        "cluster default": {
            "enable_efa": "compute",
            "compute_instance_type": "t2.large",
            "placement_group": "DYNAMIC",
            "vpc_settings": "default",
        },
        "vpc default": {"vpc_security_group_id": "sg-12345678"},
    }
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "cluster_section_dict, ebs_section_dict, expected_message",
    [
        (
            {"ebs_settings": "vol1, vol2, vol3, vol4, vol5, vol6"},
            {
                "vol1": {"shared_dir": "/vol1"},
                "vol2": {"shared_dir": "/vol2"},
                "vol3": {"shared_dir": "/vol3"},
                "vol4": {"shared_dir": "/vol4"},
                "vol5": {"shared_dir": "/vol5"},
                "vol6": {"shared_dir": "/vol6"},
            },
            "Currently only supports upto 5 EBS volumes",
        ),
        (
            {"ebs_settings": "vol1, vol2 "},
            {"vol1": {"shared_dir": "vol1"}, "vol2": {"volume_type": "io1"}},
            "When using more than 1 EBS volume, shared_dir is required under each EBS section",
        ),
        (
            {"ebs_settings": "vol1,vol2"},
            {"vol1": {"shared_dir": "/NONE"}, "vol2": {"shared_dir": "vol2"}},
            "/NONE cannot be used as a shared directory",
        ),
        (
            {"ebs_settings": "vol1, vol2 "},
            {"vol1": {"shared_dir": "/vol1"}, "vol2": {"shared_dir": "NONE"}},
            "NONE cannot be used as a shared directory",
        ),
    ],
)
def test_ebs_settings_validator(mocker, cluster_section_dict, ebs_section_dict, expected_message):
    config_parser_dict = {"cluster default": cluster_section_dict}
    if ebs_section_dict:
        for vol in ebs_section_dict:
            config_parser_dict["ebs {0}".format(vol)] = ebs_section_dict.get(vol)
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"shared_dir": "NONE"}, "NONE cannot be used as a shared directory"),
        ({"shared_dir": "/NONE"}, "/NONE cannot be used as a shared directory"),
        ({"shared_dir": "/NONEshared"}, None),
    ],
)
def test_shared_dir_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "base_os, access_from, expected_message",
    [
        ("alinux", None, "Please double check the 'base_os' configuration parameter"),
        ("centos6", None, "Please double check the 'base_os' configuration parameter"),
        ("ubuntu1604", None, "Please double check the 'base_os' configuration parameter"),
        ("centos7", None, None),
        ("ubuntu1804", None, None),
        ("ubuntu1804", "1.2.3.4/32", None),
        ("centos7", "0.0.0.0/0", None),
    ],
)
def test_dcv_enabled_validator(mocker, base_os, expected_message, access_from, caplog, capsys):
    config_parser_dict = {
        "cluster default": {"base_os": base_os, "dcv_settings": "dcv"},
        "dcv dcv": {"enable": "master"},
    }
    if access_from:
        config_parser_dict["dcv dcv"]["access_from"] = access_from

    utils.assert_param_validator(mocker, config_parser_dict, expected_message)
    access_from_error_msg = DCV_MESSAGES["warnings"]["access_from_world"].format(port=8443)
    assert_that(access_from_error_msg in caplog.text).is_equal_to(not access_from or access_from == "0.0.0.0/0")
