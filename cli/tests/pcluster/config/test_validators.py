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
from tests.common import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.config.validators.boto3"


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
    mocker.patch(
        "pcluster.config.validators.get_supported_features",
        return_value={"instances": ["t2.micro"], "baseos": ["alinux"], "schedulers": ["awsbatch"]},
    )
    config_parser_dict = {"cluster default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "instance_type, expected_message",
    [
        ("wrong_instance_type", "has an invalid value"),
        ("t2.micro", None),
        ("c4.xlarge", None),
        ("c5.xlarge", "has an invalid value"),  # to verify mock is working
    ],
)
def test_instance_type_validator(mocker, instance_type, expected_message):
    mocker.patch("pcluster.config.validators.list_ec2_instance_types", return_value=["t2.micro", "c4.xlarge"])
    config_parser_dict = {"cluster default": {"compute_instance_type": instance_type}}
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
    "region, expected_message",
    [
        # validate awsbatch not supported regions
        ("ap-northeast-3", "scheduler is not supported in the .* region"),
        ("eu-north-1", "scheduler is not supported in the .* region"),
        ("cn-north-1", "scheduler is not supported in the .* region"),
        ("cn-northwest-1", "scheduler is not supported in the .* region"),
        ("us-gov-east-1", "scheduler is not supported in the .* region"),
        ("us-gov-west-1", "scheduler is not supported in the .* region"),
        # test some awsbatch supported regions
        ("eu-west-1", None),
        ("us-east-1", None),
    ],
)
def test_scheduler_validator(mocker, region, expected_message):
    mocker.patch(
        "pcluster.config.validators.get_supported_features",
        return_value={"instances": ["t2.micro"], "baseos": ["alinux"], "schedulers": ["awsbatch"]},
    )
    # we need to set the region in the environment because it takes precedence respect of the config file
    os.environ["AWS_DEFAULT_REGION"] = region
    config_parser_dict = {"cluster default": {"scheduler": "awsbatch"}}
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
    ],
)
def test_efs_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": {"efs_settings": "default"}, "efs default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"volume_iops": 1, "volume_size": 1}, None),
        ({"volume_iops": 51, "volume_size": 1}, "IOPS to volume size ratio of .* is too hig"),
        ({"volume_iops": 1, "volume_size": 20}, None),
        ({"volume_iops": 1001, "volume_size": 20}, "IOPS to volume size ratio of .* is too hig"),
    ],
)
def test_raid_volume_iops_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": {"raid_settings": "default"}, "raid default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"imported_file_chunk_size": 1024, "import_path": "test"}, None),
        (
            {"imported_file_chunk_size": 1024},
            "When specifying 'imported_file_chunk_size', the 'import_path' option must be specified",
        ),
        ({"export_path": "test", "import_path": "test"}, None),
        ({"export_path": "test"}, "When specifying 'export_path', the 'import_path' option must be specified"),
    ],
)
def test_fsx_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": {"fsx_settings": "default"}, "fsx default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"storage_capacity": 1}, "Capacity for FSx lustre filesystem, minimum of 3,600 GB, increments of 3,600 GB"),
        ({"storage_capacity": 3600}, None),
        ({"storage_capacity": 3601}, "Capacity for FSx lustre filesystem, minimum of 3,600 GB, increments of 3,600 GB"),
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
            {"imported_file_chunk_size": 0, "import_path": "test-import"},
            "has a minimum size of 1 MiB, and max size of 512,000 MiB",
        ),
        ({"imported_file_chunk_size": 1, "import_path": "test-import"}, None),
        ({"imported_file_chunk_size": 10, "import_path": "test-import"}, None),
        ({"imported_file_chunk_size": 512000, "import_path": "test-import"}, None),
        (
            {"imported_file_chunk_size": 512001, "import_path": "test-import"},
            "has a minimum size of 1 MiB, and max size of 512,000 MiB",
        ),
    ],
)
def test_fsx_imported_file_chunk_size_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": {"fsx_settings": "default"}, "fsx default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"enable_efa": "NONE"}, "invalid value"),
        ({"enable_efa": "compute"}, "is required to set the 'compute_instance_type'"),
        ({"enable_efa": "compute", "compute_instance_type": "t2.large"}, "is required to set the 'placement_group'"),
        (
            {"enable_efa": "compute", "compute_instance_type": "t2.large", "base_os": "centos6"},
            "it is required to set the 'base_os'",
        ),
        (
            {
                "enable_efa": "compute",
                "compute_instance_type": "t2.large",
                "base_os": "centos6",
                "scheduler": "awsbatch",
            },
            "it is required to set the 'scheduler'",
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
        ),
    ],
)
def test_efa_validator(mocker, section_dict, expected_message):
    mocker.patch("pcluster.config.validators.get_supported_features", return_value={"instances": ["t2.large"]})

    config_parser_dict = {"cluster default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


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
    mocker.patch("pcluster.config.validators.get_supported_features", return_value={"instances": ["t2.micro"]})

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
        "cluster default": {"enable_efa": "compute", "placement_group": "DYNAMIC", "vpc_settings": "default"},
        "vpc default": {"vpc_security_group_id": "sg-12345678"},
    }
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)
