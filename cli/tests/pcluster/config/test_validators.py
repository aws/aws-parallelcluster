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
import datetime
import os
import re

import pytest

import tests.pcluster.config.utils as utils
from assertpy import assert_that
from pcluster.config.validators import (
    DCV_MESSAGES,
    FSX_MESSAGES,
    FSX_SUPPORTED_ARCHITECTURES_OSES,
    architecture_os_validator,
    disable_hyperthreading_architecture_validator,
    instances_architecture_compatibility_validator,
    intel_hpc_architecture_validator,
)
from tests.common import MockedBoto3Request
from tests.pcluster.config.defaults import DefaultDict


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


@pytest.mark.parametrize(
    "image_architecture, bad_ami_message, bad_architecture_message",
    [
        ("x86_64", None, None),
        (
            "arm64",
            None,
            "incompatible with the architecture supported by the instance type chosen for the master server",
        ),
        (
            "arm64",
            "Unable to get information for AMI",
            "incompatible with the architecture supported by the instance type chosen for the master server",
        ),
    ],
)
def test_ec2_ami_validator(mocker, boto3_stubber, image_architecture, bad_ami_message, bad_architecture_message):
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
                "Architecture": image_architecture,
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
            method="describe_images",
            response=describe_images_response,
            expected_params={"ImageIds": ["ami-12345678"]},
            generate_error=bad_ami_message,
        )
    ]
    boto3_stubber("ec2", mocked_requests)

    # TODO test with invalid key
    config_parser_dict = {"cluster default": {"custom_ami": "ami-12345678"}}
    expected_message = bad_ami_message or bad_architecture_message
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


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
        ("cn-northwest-1", "alinux2", "awsbatch", None),
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
        ("eu-west-1", "alinux2", "awsbatch", None),
        # verify sge supports all the OSes
        ("eu-west-1", "centos6", "sge", None),
        ("eu-west-1", "centos7", "sge", None),
        ("eu-west-1", "ubuntu1604", "sge", None),
        ("eu-west-1", "ubuntu1804", "sge", None),
        ("eu-west-1", "alinux", "sge", None),
        ("eu-west-1", "alinux2", "sge", None),
        # verify slurm supports all the OSes
        ("eu-west-1", "centos6", "slurm", None),
        ("eu-west-1", "centos7", "slurm", None),
        ("eu-west-1", "ubuntu1604", "slurm", None),
        ("eu-west-1", "ubuntu1804", "slurm", None),
        ("eu-west-1", "alinux", "slurm", None),
        ("eu-west-1", "alinux2", "slurm", None),
        # verify torque supports all the OSes
        ("eu-west-1", "centos6", "torque", None),
        ("eu-west-1", "centos7", "torque", None),
        ("eu-west-1", "ubuntu1604", "torque", None),
        ("eu-west-1", "ubuntu1804", "torque", None),
        ("eu-west-1", "alinux", "torque", None),
        ("eu-west-1", "alinux2", "torque", None),
    ],
)
def test_scheduler_validator(mocker, capsys, region, base_os, scheduler, expected_message):
    # we need to set the region in the environment because it takes precedence respect of the config file
    os.environ["AWS_DEFAULT_REGION"] = region
    config_parser_dict = {"cluster default": {"base_os": base_os, "scheduler": scheduler}}
    # Deprecation warning should be printed for sge and torque
    expected_warning = None
    wiki_url = "https://github.com/aws/aws-parallelcluster/wiki/Deprecation-of-SGE-and-Torque-in-ParallelCluster"
    if scheduler in ["sge", "torque"]:
        expected_warning = ".{0}. is scheduled to be deprecated.*{1}".format(scheduler, wiki_url)
    utils.assert_param_validator(mocker, config_parser_dict, expected_message, capsys, expected_warning)


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


def test_url_validator(mocker, boto3_stubber, capsys):
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

    # Test S3 URI in custom_chef_cookbook.
    tests = [
        (
            "s3://test/cookbook.tgz",
            None,
            MockedBoto3Request(
                method="head_object",
                response=head_object_response,
                expected_params={"Bucket": "test", "Key": "cookbook.tgz"},
            ),
        ),
        (
            "s3://failure/cookbook.tgz",
            (
                "WARNING: The configuration parameter 'custom_chef_cookbook' generated the following warnings:\n"
                "The S3 object does not exist or you do not have access to it.\n"
                "Please make sure the cluster nodes have access to it."
            ),
            MockedBoto3Request(
                method="head_object",
                response=head_object_response,
                expected_params={"Bucket": "failure", "Key": "cookbook.tgz"},
                generate_error=True,
                error_code=404,
            ),
        ),
    ]

    for custom_chef_cookbook_url, expected_message, mocked_request in tests:
        boto3_stubber("s3", mocked_request)
        mocker.patch("pcluster.config.validators.urllib.request.urlopen")
        config_parser_dict = {
            "cluster default": {
                "scheduler": "slurm",
                "s3_read_resource": "arn:aws:s3:::test*",
                "custom_chef_cookbook": custom_chef_cookbook_url,
            }
        }
        utils.assert_param_validator(mocker, config_parser_dict, capsys=capsys, expected_warning=expected_message)


@pytest.mark.parametrize(
    "config, num_calls, bucket, expected_message",
    [
        (
            {
                "cluster default": {"fsx_settings": "fsx"},
                "fsx fsx": {
                    "storage_capacity": 1200,
                    "import_path": "s3://test/test1/test2",
                    "export_path": "s3://test/test1/test2",
                },
            },
            2,
            {"Bucket": "test"},
            None,
        ),
        (
            {
                "cluster default": {"fsx_settings": "fsx"},
                "fsx fsx": {
                    "storage_capacity": 1200,
                    "import_path": "http://test/test.json",
                    "export_path": "s3://test/test1/test2",
                },
            },
            1,
            {"Bucket": "test"},
            "The value 'http://test/test.json' used for the parameter 'import_path' is not a valid S3 URI.",
        ),
    ],
)
def test_s3_validator(mocker, boto3_stubber, config, num_calls, bucket, expected_message):
    if bucket:
        _head_bucket_stubber(mocker, boto3_stubber, bucket, num_calls)
    utils.assert_param_validator(mocker, config, expected_message)


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
    "kms_key_id, expected_message",
    [
        ("9e8a129be-0e46-459d-865b-3a5bf974a22k", None),
        (
            "9e7a129be-0e46-459d-865b-3a5bf974a22k",
            "Key 'arn:aws:kms:us-east-1:12345678:key/9e7a129be-0e46-459d-865b-3a5bf974a22k' does not exist",
        ),
    ],
)
def test_kms_key_validator(mocker, boto3_stubber, kms_key_id, expected_message):
    _kms_key_stubber(mocker, boto3_stubber, kms_key_id, expected_message, 1)

    config_parser_dict = {
        "cluster default": {"fsx_settings": "fsx"},
        "fsx fsx": {"storage_capacity": 1200, "fsx_kms_key_id": kms_key_id, "deployment_type": "PERSISTENT_1"},
    }
    utils.assert_param_validator(
        mocker, config_parser_dict, expected_error=expected_message if expected_message else None
    )


def _kms_key_stubber(mocker, boto3_stubber, kms_key_id, expected_message, num_calls):
    describe_key_response = {
        "KeyMetadata": {
            "AWSAccountId": "1234567890",
            "Arn": "arn:aws:kms:us-east-1:1234567890:key/{0}".format(kms_key_id),
            "CreationDate": datetime.datetime(2019, 1, 10, 11, 25, 59, 128000),
            "Description": "",
            "Enabled": True,
            "KeyId": kms_key_id,
            "KeyManager": "CUSTOMER",
            "KeyState": "Enabled",
            "KeyUsage": "ENCRYPT_DECRYPT",
            "Origin": "AWS_KMS",
        }
    }
    mocked_requests = [
        MockedBoto3Request(
            method="describe_key",
            response=expected_message if expected_message else describe_key_response,
            expected_params={"KeyId": kms_key_id},
            generate_error=True if expected_message else False,
        )
    ] * num_calls
    boto3_stubber("kms", mocked_requests)


@pytest.mark.parametrize(
    "section_dict, bucket, expected_error, num_calls",
    [
        (
            {"imported_file_chunk_size": 1024, "import_path": "s3://test", "storage_capacity": 1200},
            {"Bucket": "test"},
            None,
            1,
        ),
        (
            {"imported_file_chunk_size": 1024, "storage_capacity": 1200},
            None,
            "When specifying 'imported_file_chunk_size', the 'import_path' option must be specified",
            0,
        ),
        (
            {"export_path": "s3://test", "import_path": "s3://test", "storage_capacity": 1200},
            {"Bucket": "test"},
            None,
            2,
        ),
        (
            {"export_path": "s3://test", "storage_capacity": 1200},
            {"Bucket": "test"},
            "When specifying 'export_path', the 'import_path' option must be specified",
            0,
        ),
        ({"shared_dir": "NONE", "storage_capacity": 1200}, None, "NONE cannot be used as a shared directory", 0),
        ({"shared_dir": "/NONE", "storage_capacity": 1200}, None, "/NONE cannot be used as a shared directory", 0),
        ({"shared_dir": "/fsx"}, None, "the 'storage_capacity' option must be specified", 0),
        ({"shared_dir": "/fsx", "storage_capacity": 1200}, None, None, 0),
        (
            {
                "deployment_type": "PERSISTENT_1",
                "fsx_kms_key_id": "9e8a129be-0e46-459d-865b-3a5bf974a22k",
                "storage_capacity": 1200,
            },
            None,
            None,
            0,
        ),
        (
            {"deployment_type": "PERSISTENT_1", "per_unit_storage_throughput": 200, "storage_capacity": 1200},
            None,
            None,
            0,
        ),
        (
            {
                "deployment_type": "SCRATCH_2",
                "fsx_kms_key_id": "9e8a129be-0e46-459d-865b-3a5bf974a22k",
                "storage_capacity": 1200,
            },
            None,
            "'fsx_kms_key_id' can only be used when 'deployment_type = PERSISTENT_1'",
            1,
        ),
        (
            {"deployment_type": "SCRATCH_1", "per_unit_storage_throughput": 200, "storage_capacity": 1200},
            None,
            "'per_unit_storage_throughput' can only be used when 'deployment_type = PERSISTENT_1'",
            0,
        ),
        (
            {"storage_capacity": 1200, "deployment_type": "PERSISTENT_1", "automatic_backup_retention_days": 2},
            None,
            None,
            0,
        ),
        (
            {
                "storage_capacity": 1200,
                "deployment_type": "PERSISTENT_1",
                "automatic_backup_retention_days": 2,
                "daily_automatic_backup_start_time": "03:00",
                "copy_tags_to_backups": True,
            },
            None,
            None,
            0,
        ),
        (
            {"automatic_backup_retention_days": 2, "deployment_type": "SCRATCH_1"},
            None,
            "FSx automatic backup features can be used only with 'PERSISTENT_1' file systems",
            0,
        ),
        (
            {"daily_automatic_backup_start_time": "03:00"},
            None,
            "'automatic_backup_retention_days' must be greater than 0 if "
            + "'daily_automatic_backup_start_time' or 'copy_tags_to_backups' parameters are provided.",
            0,
        ),
        (
            {"storage_capacity": 1200, "deployment_type": "PERSISTENT_1", "copy_tags_to_backups": True},
            None,
            "'automatic_backup_retention_days' must be greater than 0 if "
            + "'daily_automatic_backup_start_time' or 'copy_tags_to_backups' parameters are provided.",
            0,
        ),
        (
            {"storage_capacity": 1200, "deployment_type": "PERSISTENT_1", "copy_tags_to_backups": False},
            None,
            "'automatic_backup_retention_days' must be greater than 0 if "
            + "'daily_automatic_backup_start_time' or 'copy_tags_to_backups' parameters are provided.",
            0,
        ),
        (
            {"daily_automatic_backup_start_time": "03:00", "copy_tags_to_backups": True},
            None,
            "'automatic_backup_retention_days' must be greater than 0 if "
            + "'daily_automatic_backup_start_time' or 'copy_tags_to_backups' parameters are provided.",
            0,
        ),
        (
            {
                "deployment_type": "PERSISTENT_1",
                "automatic_backup_retention_days": 2,
                "imported_file_chunk_size": 1024,
                "export_path": "s3://test",
                "import_path": "s3://test",
                "storage_capacity": 1200,
            },
            {"Bucket": "test"},
            "Backups cannot be created on S3-linked file systems",
            0,
        ),
        (
            {
                "deployment_type": "PERSISTENT_1",
                "automatic_backup_retention_days": 2,
                "export_path": "s3://test",
                "import_path": "s3://test",
                "storage_capacity": 1200,
            },
            {"Bucket": "test"},
            "Backups cannot be created on S3-linked file systems",
            0,
        ),
    ],
)
def test_fsx_validator(mocker, boto3_stubber, section_dict, bucket, expected_error, num_calls):
    if bucket:
        _head_bucket_stubber(mocker, boto3_stubber, bucket, num_calls)
    if "fsx_kms_key_id" in section_dict:
        _kms_key_stubber(mocker, boto3_stubber, section_dict.get("fsx_kms_key_id"), None, 0 if expected_error else 1)
    config_parser_dict = {"cluster default": {"fsx_settings": "default"}, "fsx default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_error=expected_error)


@pytest.mark.parametrize(
    "section_dict, expected_error, expected_warning",
    [
        (
            {"storage_capacity": 1, "deployment_type": "SCRATCH_1"},
            None,
            "Capacity for FSx SCRATCH_1 filesystem is 1,200 GB, 2,400 GB or increments of 3,600 GB",
        ),
        ({"storage_capacity": 1200, "deployment_type": "SCRATCH_1"}, None, None),
        ({"storage_capacity": 2400, "deployment_type": "SCRATCH_1"}, None, None),
        ({"storage_capacity": 3600, "deployment_type": "SCRATCH_1"}, None, None),
        (
            {"storage_capacity": 3600, "deployment_type": "SCRATCH_2"},
            None,
            "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB",
        ),
        (
            {"storage_capacity": 3600, "deployment_type": "PERSISTENT_1"},
            None,
            "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB",
        ),
        (
            {"storage_capacity": 3601, "deployment_type": "PERSISTENT_1"},
            None,
            "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB",
        ),
        ({"storage_capacity": 7200}, None, None),
        (
            {"deployment_type": "SCRATCH_1"},
            "When specifying 'fsx' section, the 'storage_capacity' option must be specified",
            None,
        ),
    ],
)
def test_fsx_storage_capacity_validator(mocker, boto3_stubber, capsys, section_dict, expected_error, expected_warning):
    config_parser_dict = {"cluster default": {"fsx_settings": "default"}, "fsx default": section_dict}
    utils.assert_param_validator(
        mocker, config_parser_dict, capsys=capsys, expected_error=expected_error, expected_warning=expected_warning
    )


def _head_bucket_stubber(mocker, boto3_stubber, bucket, num_calls):
    head_bucket_response = {
        "ResponseMetadata": {
            "AcceptRanges": "bytes",
            "ContentType": "text/html",
            "LastModified": "Thu, 16 Apr 2015 18:19:14 GMT",
            "ContentLength": 77,
            "VersionId": "null",
            "ETag": '"30a6ec7e1a9ad79c203d05a589c8b400"',
            "Metadata": {},
        }
    }
    mocked_requests = [
        MockedBoto3Request(method="head_bucket", response=head_bucket_response, expected_params=bucket)
    ] * num_calls
    boto3_stubber("s3", mocked_requests)
    mocker.patch("pcluster.config.validators.urllib.request.urlopen")


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
def test_intel_hpc_os_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": section_dict}
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
    "section_dict, bucket, expected_message",
    [
        (
            {"imported_file_chunk_size": 0, "import_path": "s3://test-import", "storage_capacity": 1200},
            None,
            "has a minimum size of 1 MiB, and max size of 512,000 MiB",
        ),
        (
            {"imported_file_chunk_size": 1, "import_path": "s3://test-import", "storage_capacity": 1200},
            {"Bucket": "test-import"},
            None,
        ),
        (
            {"imported_file_chunk_size": 10, "import_path": "s3://test-import", "storage_capacity": 1200},
            {"Bucket": "test-import"},
            None,
        ),
        (
            {"imported_file_chunk_size": 512000, "import_path": "s3://test-import", "storage_capacity": 1200},
            {"Bucket": "test-import"},
            None,
        ),
        (
            {"imported_file_chunk_size": 512001, "import_path": "s3://test-import", "storage_capacity": 1200},
            None,
            "has a minimum size of 1 MiB, and max size of 512,000 MiB",
        ),
    ],
)
def test_fsx_imported_file_chunk_size_validator(mocker, boto3_stubber, section_dict, bucket, expected_message):
    if bucket:
        _head_bucket_stubber(mocker, boto3_stubber, bucket, num_calls=1)
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
        (
            {
                "enable_efa": "compute",
                "compute_instance_type": "t2.large",
                "base_os": "alinux2",
                "scheduler": "slurm",
                "placement_group": "DYNAMIC",
            },
            None,
            None,
        ),
    ],
)
def test_efa_validator(boto3_stubber, mocker, capsys, section_dict, expected_error, expected_warning):
    if section_dict.get("enable_efa") != "NONE":
        mocked_requests = [
            MockedBoto3Request(
                method="describe_instance_types",
                response={"InstanceTypes": [{"InstanceType": "t2.large"}]},
                expected_params={"Filters": [{"Name": "network-info.efa-supported", "Values": ["true"]}]},
            )
        ]
        boto3_stubber("ec2", mocked_requests)
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
        ),
        MockedBoto3Request(
            method="describe_instance_types",
            response={"InstanceTypes": [{"InstanceType": "t2.large"}]},
            expected_params={"Filters": [{"Name": "network-info.efa-supported", "Values": ["true"]}]},
        ),
        MockedBoto3Request(
            method="describe_security_groups",
            response=describe_security_groups_response,
            expected_params={"GroupIds": ["sg-12345678"]},
        ),  # it is called two times, for vpc_security_group_id validation and to validate efa
    ]

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
    "base_os, instance_type, access_from, expected_error, expected_warning",
    [
        ("alinux", "t2.medium", None, "Please double check the 'base_os' configuration parameter", None),
        ("centos6", "t2.medium", None, "Please double check the 'base_os' configuration parameter", None),
        ("ubuntu1604", "t2.medium", None, "Please double check the 'base_os' configuration parameter", None),
        ("centos7", "t2.medium", None, None, None),
        ("ubuntu1804", "t2.medium", None, None, None),
        ("ubuntu1804", "t2.medium", "1.2.3.4/32", None, None),
        ("centos7", "t2.medium", "0.0.0.0/0", None, None),
        ("alinux2", "t2.medium", None, None, None),
        ("alinux2", "t2.nano", None, None, "is recommended to use an instance type with at least"),
        ("alinux2", "t2.micro", None, None, "is recommended to use an instance type with at least"),
    ],
)
def test_dcv_enabled_validator(
    mocker, base_os, instance_type, expected_error, expected_warning, access_from, caplog, capsys
):
    config_parser_dict = {
        "cluster default": {"base_os": base_os, "dcv_settings": "dcv"},
        "dcv dcv": {"enable": "master"},
    }
    if access_from:
        config_parser_dict["dcv dcv"]["access_from"] = access_from

    mocker.patch(
        "pcluster.config.validators.get_supported_instance_types", return_value=["t2.nano", "t2.micro", "t2.medium"]
    )
    utils.assert_param_validator(mocker, config_parser_dict, expected_error, capsys, expected_warning)
    access_from_error_msg = DCV_MESSAGES["warnings"]["access_from_world"].format(port=8443)
    assert_that(access_from_error_msg in caplog.text).is_equal_to(not access_from or access_from == "0.0.0.0/0")


@pytest.mark.parametrize(
    "architecture, base_os, expected_message",
    [
        # Supported combinations
        ("x86_64", "alinux", None),
        ("x86_64", "alinux2", None),
        ("x86_64", "centos7", None),
        ("x86_64", "ubuntu1604", None),
        ("x86_64", "ubuntu1804", None),
        ("arm64", "ubuntu1804", None),
        ("arm64", "alinux2", None),
        # Unsupported combinations
        (
            "UnsupportedArchitecture",
            "alinux2",
            FSX_MESSAGES["errors"]["unsupported_architecture"].format(
                supported_architectures=list(FSX_SUPPORTED_ARCHITECTURES_OSES.keys())
            ),
        ),
        (
            "x86_64",
            "centos6",
            FSX_MESSAGES["errors"]["unsupported_os"].format(
                architecture="x86_64", supported_oses=FSX_SUPPORTED_ARCHITECTURES_OSES.get("x86_64")
            ),
        ),
        (
            "arm64",
            "centos6",
            FSX_MESSAGES["errors"]["unsupported_os"].format(
                architecture="arm64", supported_oses=FSX_SUPPORTED_ARCHITECTURES_OSES.get("arm64")
            ),
        ),
        (
            "arm64",
            "centos7",
            FSX_MESSAGES["errors"]["unsupported_os"].format(
                architecture="arm64", supported_oses=FSX_SUPPORTED_ARCHITECTURES_OSES.get("arm64")
            ),
        ),
        (
            "arm64",
            "alinux",
            FSX_MESSAGES["errors"]["unsupported_os"].format(
                architecture="arm64", supported_oses=FSX_SUPPORTED_ARCHITECTURES_OSES.get("arm64")
            ),
        ),
        (
            "arm64",
            "ubuntu1604",
            FSX_MESSAGES["errors"]["unsupported_os"].format(
                architecture="arm64", supported_oses=FSX_SUPPORTED_ARCHITECTURES_OSES.get("arm64")
            ),
        ),
    ],
)
def test_fsx_architecture_os_validator(mocker, architecture, base_os, expected_message):
    config_parser_dict = {
        "cluster default": {"base_os": base_os, "fsx_settings": "fsx"},
        "fsx fsx": {"storage_capacity": 3200},
    }
    expected_message = re.escape(expected_message) if expected_message else None
    extra_patches = {
        "pcluster.config.param_types.get_supported_architectures_for_instance_type": [architecture],
        "pcluster.config.validators.get_supported_architectures_for_instance_type": [architecture],
    }
    utils.assert_param_validator(mocker, config_parser_dict, expected_message, extra_patches=extra_patches)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        (
            {"initial_queue_size": "0", "maintain_initial_size": True},
            "maintain_initial_size cannot be set to true if initial_queue_size is 0",
        ),
        (
            {"scheduler": "awsbatch", "maintain_initial_size": True},
            "maintain_initial_size is not supported when using awsbatch as scheduler",
        ),
    ],
)
def test_maintain_initial_size_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "base_os, expected_warning",
    [
        ("alinux2", None),
        ("centos7", None),
        ("ubuntu1604", None),
        ("ubuntu1804", None),
        ("centos6", "centos6.*will reach end-of-life in late 2020"),
        ("alinux", "alinux.*will reach end-of-life in late 2020"),
    ],
)
def test_base_os_validator(mocker, capsys, base_os, expected_warning):
    config_parser_dict = {"cluster default": {"base_os": base_os}}
    utils.assert_param_validator(mocker, config_parser_dict, capsys=capsys, expected_warning=expected_warning)


#########
#
# architecture validator tests
#
# Two things make it difficult to test validators that key on architecture in the same way that:
# 1) architecture is a derived parameter and cannot be configured directly via the config file
# 2) many validators key on the architecture, which makes it impossible to test some combinations of
#    parameters for validators that run later than others, because those run earlier will have
#    already raised exceptions.
#
# Thus, the following code mocks the pcluster_config object passed to the validator functions
# and calls those functions directly (as opposed to patching functions and instantiating a config
# as would be done when running `pcluster create/update`).
#
#########


def get_default_pcluster_sections_dict():
    """Return a dict similar in structure to that of a cluster config file."""
    default_pcluster_sections_dict = {}
    for section_default_dict in DefaultDict:
        if section_default_dict.name == "pcluster":  # Get rid of the extra layer in this case
            default_pcluster_sections_dict["cluster"] = section_default_dict.value.get("cluster")
        else:
            default_pcluster_sections_dict[section_default_dict.name] = section_default_dict.value
    return default_pcluster_sections_dict


def make_pcluster_config_mock(mocker, config_dict):
    """Mock the calls that made on a pcluster_config by validator functions."""
    cluster_config_dict = get_default_pcluster_sections_dict()
    for section_key in config_dict:
        cluster_config_dict = utils.merge_dicts(cluster_config_dict.get(section_key), config_dict.get(section_key))

    section_to_mocks = {}
    for section_key, section_dict in config_dict.items():
        section_mock = mocker.MagicMock()
        section_mock.get_param_value.side_effect = lambda param: section_dict.get(param)
        section_to_mocks[section_key] = section_mock

    pcluster_config_mock = mocker.MagicMock()
    pcluster_config_mock.get_section.side_effect = lambda section: section_to_mocks.get(section)
    return pcluster_config_mock


def run_architecture_validator_test(
    mocker,
    config,
    constrained_param_section,
    constrained_param_name,
    param_name,
    param_val,
    validator,
    expected_message,
):
    """Run a test for a validator that's concerned with the architecture param."""
    mocked_pcluster_config = make_pcluster_config_mock(mocker, config)
    errors, warnings = validator(param_name, param_val, mocked_pcluster_config)

    mocked_pcluster_config.get_section.assert_called_once_with(constrained_param_section)
    mocked_pcluster_config.get_section.side_effect(constrained_param_section).get_param_value.assert_called_with(
        constrained_param_name
    )
    assert_that(len(warnings)).is_equal_to(0)
    assert_that(len(errors)).is_equal_to(0 if expected_message is None else 1)
    if expected_message:
        assert_that(errors[0]).matches(re.escape(expected_message))


@pytest.mark.parametrize(
    "enabled, architecture, expected_message",
    [
        (True, "x86_64", None),
        (True, "arm64", "instance types and an AMI that support these architectures"),
        (False, "x86_64", None),
        (False, "arm64", None),
    ],
)
def test_intel_hpc_architecture_validator(mocker, enabled, architecture, expected_message):
    """Verify that setting enable_intel_hpc_platform is invalid when architecture != x86_64."""
    config_dict = {"cluster": {"enable_intel_hpc_platform": enabled, "architecture": architecture}}
    run_architecture_validator_test(
        mocker,
        config_dict,
        "cluster",
        "architecture",
        "enable_intel_hpc_platform",
        enabled,
        intel_hpc_architecture_validator,
        expected_message,
    )


@pytest.mark.parametrize(
    "base_os, architecture, expected_message",
    [
        # All OSes supported for x86_64
        ("alinux", "x86_64", None),
        ("alinux2", "x86_64", None),
        ("centos6", "x86_64", None),
        ("centos7", "x86_64", None),
        ("ubuntu1604", "x86_64", None),
        ("ubuntu1804", "x86_64", None),
        # Only a subset of OSes supported for x86_64
        ("alinux", "arm64", "arm64 is only supported for the following operating systems"),
        ("alinux2", "arm64", None),
        ("centos6", "arm64", "arm64 is only supported for the following operating systems"),
        ("centos7", "arm64", "arm64 is only supported for the following operating systems"),
        ("ubuntu1604", "arm64", "arm64 is only supported for the following operating systems"),
        ("ubuntu1804", "arm64", None),
    ],
)
def test_architecture_os_validator(mocker, base_os, architecture, expected_message):
    """Verify that the correct set of OSes is supported for each supported architecture."""
    config_dict = {"cluster": {"base_os": base_os, "architecture": architecture}}
    run_architecture_validator_test(
        mocker,
        config_dict,
        "cluster",
        "base_os",
        "architecture",
        architecture,
        architecture_os_validator,
        expected_message,
    )


@pytest.mark.parametrize(
    "disable_hyperthreading, architecture, expected_message",
    [
        (True, "x86_64", None),
        (False, "x86_64", None),
        (True, "arm64", "disable_hyperthreading is only supported on instance types that support these architectures"),
        (False, "arm64", None),
    ],
)
def test_disable_hyperthreading_architecture_validator(mocker, disable_hyperthreading, architecture, expected_message):
    config_dict = {"cluster": {"architecture": architecture, "disable_hyperthreading": disable_hyperthreading}}
    run_architecture_validator_test(
        mocker,
        config_dict,
        "cluster",
        "architecture",
        "disable_hyperthreading",
        disable_hyperthreading,
        disable_hyperthreading_architecture_validator,
        expected_message,
    )


@pytest.mark.parametrize(
    "master_architecture, compute_architecture, expected_message",
    [
        ("x86_64", "x86_64", None),
        ("x86_64", "arm64", "none of which are compatible with the architecture supported by the master_instance_type"),
        ("arm64", "x86_64", "none of which are compatible with the architecture supported by the master_instance_type"),
        ("arm64", "arm64", None),
    ],
)
def test_instances_architecture_compatibility_validator(
    mocker, master_architecture, compute_architecture, expected_message
):
    mocker.patch(
        "pcluster.config.validators.get_supported_architectures_for_instance_type", return_value=[compute_architecture]
    )
    run_architecture_validator_test(
        mocker,
        {"cluster": {"architecture": master_architecture}},
        "cluster",
        "architecture",
        "compute_instance_type",
        "some_instance_type",
        instances_architecture_compatibility_validator,
        expected_message,
    )
