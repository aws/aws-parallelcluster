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

import configparser
import pytest
from assertpy import assert_that

import tests.pcluster.config.utils as utils
from pcluster.config.cfn_param_types import CfnParam, CfnSection
from pcluster.config.mappings import ALLOWED_VALUES, FSX
from pcluster.config.validators import (
    DCV_MESSAGES,
    EBS_VOLUME_TYPE_TO_VOLUME_SIZE_BOUNDS,
    FSX_MESSAGES,
    FSX_SUPPORTED_ARCHITECTURES_OSES,
    LOGFILE_LOGGER,
    architecture_os_validator,
    compute_resource_validator,
    disable_hyperthreading_architecture_validator,
    efa_gdr_validator,
    efa_os_arch_validator,
    fsx_ignored_parameters_validator,
    instances_architecture_compatibility_validator,
    intel_hpc_architecture_validator,
    queue_validator,
    settings_validator,
)
from pcluster.constants import FSX_HDD_THROUGHPUT, FSX_SSD_THROUGHPUT
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


# FIXME Moved
@pytest.mark.parametrize(
    "instance_type, expected_message", [("t2.micro", None), ("c4.xlarge", None), ("c5.xlarge", "is not supported")]
)
def test_ec2_instance_type_validator(mocker, instance_type, expected_message):
    config_parser_dict = {"cluster default": {"compute_instance_type": instance_type}}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize("instance_type, expected_message", [("t2.micro", None), ("c4.xlarge", None)])
def test_head_node_instance_type_validator(mocker, instance_type, expected_message):
    config_parser_dict = {"cluster default": {"master_instance_type": instance_type}}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "scheduler, instance_type, expected_message, expected_warnings",
    [
        ("sge", "t2.micro", None, None),
        ("sge", "c4.xlarge", None, None),
        ("sge", "c5.xlarge", "is not supported", None),
        # NOTE: compute_instance_type_validator calls ec2_instance_type_validator only if the scheduler is not awsbatch
        ("awsbatch", "t2.micro", None, None),
        ("awsbatch", "c4.xlarge", "is not supported", None),
        ("awsbatch", "t2", None, None),  # t2 family
        ("awsbatch", "optimal", None, None),
        ("sge", "p4d.24xlarge", None, "has 4 Network Interfaces."),
        ("slurm", "p4d.24xlarge", None, None),
    ],
)
def test_compute_instance_type_validator(mocker, scheduler, instance_type, expected_message, expected_warnings):
    config_parser_dict = {"cluster default": {"scheduler": scheduler, "compute_instance_type": instance_type}}
    extra_patches = {
        "pcluster.config.validators.InstanceTypeInfo.max_network_interface_count": 4
        if instance_type == "p4d.24xlarge"
        else 1,
    }
    utils.assert_param_validator(
        mocker, config_parser_dict, expected_message, expected_warnings, extra_patches=extra_patches
    )


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
            "incompatible with the architecture supported by the instance type chosen for the head node",
        ),
        (
            "arm64",
            "Unable to get information for AMI",
            "incompatible with the architecture supported by the instance type chosen for the head node",
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


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"tags": {"key": "value", "key2": "value2"}}, None),
        (
            {"tags": {"key": "value", "Version": "value2"}},
            r"Version.*reserved",
        ),
    ],
)
def test_tags_validator(mocker, capsys, section_dict, expected_message):
    config_parser_dict = {"cluster default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_error=expected_message)


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
        ("us-gov-east-1", "alinux", "awsbatch", None),
        ("us-gov-west-1", "alinux", "awsbatch", None),
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
        ("eu-west-1", "centos7", "awsbatch", "scheduler supports the following Operating Systems"),
        ("eu-west-1", "centos8", "awsbatch", "scheduler supports the following Operating Systems"),
        ("eu-west-1", "ubuntu1604", "awsbatch", "scheduler supports the following Operating Systems"),
        ("eu-west-1", "ubuntu1804", "awsbatch", "scheduler supports the following Operating Systems"),
        ("eu-west-1", "alinux", "awsbatch", None),
        ("eu-west-1", "alinux2", "awsbatch", None),
        # verify sge supports all the OSes
        ("eu-west-1", "centos7", "sge", None),
        ("eu-west-1", "centos8", "sge", None),
        ("eu-west-1", "ubuntu1604", "sge", None),
        ("eu-west-1", "ubuntu1804", "sge", None),
        ("eu-west-1", "alinux", "sge", None),
        ("eu-west-1", "alinux2", "sge", None),
        # verify slurm supports all the OSes
        ("eu-west-1", "centos7", "slurm", None),
        ("eu-west-1", "centos8", "slurm", None),
        ("eu-west-1", "ubuntu1604", "slurm", None),
        ("eu-west-1", "ubuntu1804", "slurm", None),
        ("eu-west-1", "alinux", "slurm", None),
        ("eu-west-1", "alinux2", "slurm", None),
        # verify torque supports all the OSes
        ("eu-west-1", "centos7", "torque", None),
        ("eu-west-1", "centos8", "torque", None),
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
    "config, num_calls, error_code, bucket, expected_message",
    [
        (
            {
                "cluster default": {"fsx_settings": "fsx"},
                "fsx fsx": {
                    "storage_capacity": 1200,
                    "import_path": "s3://test/test1/test2",
                    "export_path": "s3://test/test1/test2",
                    "auto_import_policy": "NEW",
                },
            },
            2,
            None,
            {"Bucket": "test"},
            "AutoImport is not supported for cross-region buckets.",
        ),
        (
            {
                "cluster default": {"fsx_settings": "fsx"},
                "fsx fsx": {
                    "storage_capacity": 1200,
                    "import_path": "s3://test/test1/test2",
                    "export_path": "s3://test/test1/test2",
                    "auto_import_policy": "NEW",
                },
            },
            2,
            "NoSuchBucket",
            {"Bucket": "test"},
            "The S3 bucket 'test' does not appear to exist.",
        ),
        (
            {
                "cluster default": {"fsx_settings": "fsx"},
                "fsx fsx": {
                    "storage_capacity": 1200,
                    "import_path": "s3://test/test1/test2",
                    "export_path": "s3://test/test1/test2",
                    "auto_import_policy": "NEW",
                },
            },
            2,
            "AccessDenied",
            {"Bucket": "test"},
            "You do not have access to the S3 bucket",
        ),
    ],
)
def test_auto_import_policy_validator(mocker, boto3_stubber, config, num_calls, error_code, bucket, expected_message):
    os.environ["AWS_DEFAULT_REGION"] = "eu-west-1"
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
    get_bucket_location_response = {
        "ResponseMetadata": {
            "LocationConstraint": "af-south1",
        }
    }
    mocked_requests = []
    for _ in range(num_calls):
        mocked_requests.append(
            MockedBoto3Request(method="head_bucket", response=head_bucket_response, expected_params=bucket)
        )
    if error_code is None:
        mocked_requests.append(
            MockedBoto3Request(
                method="get_bucket_location", response=get_bucket_location_response, expected_params=bucket
            )
        )
    else:
        mocked_requests.append(
            MockedBoto3Request(
                method="get_bucket_location",
                response=get_bucket_location_response,
                expected_params=bucket,
                generate_error=error_code is not None,
                error_code=error_code,
            )
        )

    boto3_stubber("s3", mocked_requests)

    utils.assert_param_validator(mocker, config, expected_message)


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
        ({"volume_type": "io1", "volume_size": 20, "volume_iops": 120}, None),
        (
            {"volume_type": "io1", "volume_size": 20, "volume_iops": 90},
            "IOPS rate must be between 100 and 64000 when provisioning io1 volumes.",
        ),
        (
            {"volume_type": "io1", "volume_size": 20, "volume_iops": 64001},
            "IOPS rate must be between 100 and 64000 when provisioning io1 volumes.",
        ),
        ({"volume_type": "io1", "volume_size": 20, "volume_iops": 1001}, "IOPS to volume size ratio of .* is too high"),
        ({"volume_type": "io2", "volume_size": 20, "volume_iops": 120}, None),
        (
            {"volume_type": "io2", "volume_size": 20, "volume_iops": 90},
            "IOPS rate must be between 100 and 256000 when provisioning io2 volumes.",
        ),
        (
            {"volume_type": "io2", "volume_size": 20, "volume_iops": 256001},
            "IOPS rate must be between 100 and 256000 when provisioning io2 volumes.",
        ),
        (
            {"volume_type": "io2", "volume_size": 20, "volume_iops": 20001},
            "IOPS to volume size ratio of .* is too high",
        ),
        ({"volume_type": "gp3", "volume_size": 20, "volume_iops": 3000}, None),
        (
            {"volume_type": "gp3", "volume_size": 20, "volume_iops": 2900},
            "IOPS rate must be between 3000 and 16000 when provisioning gp3 volumes.",
        ),
        (
            {"volume_type": "gp3", "volume_size": 20, "volume_iops": 16001},
            "IOPS rate must be between 3000 and 16000 when provisioning gp3 volumes.",
        ),
        (
            {"volume_type": "gp3", "volume_size": 20, "volume_iops": 10001},
            "IOPS to volume size ratio of .* is too high",
        ),
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
        "fsx fsx": {
            "storage_capacity": 1200,
            "fsx_kms_key_id": kms_key_id,
            "deployment_type": "PERSISTENT_1",
            "per_unit_storage_throughput": 50,
        },
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
                "per_unit_storage_throughput": 50,
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
            {"deployment_type": "PERSISTENT_1", "storage_capacity": 1200},
            None,
            "'per_unit_storage_throughput' must be specified when 'deployment_type = PERSISTENT_1'",
            0,
        ),
        (
            {
                "storage_capacity": 1200,
                "per_unit_storage_throughput": "50",
                "deployment_type": "PERSISTENT_1",
                "automatic_backup_retention_days": 2,
            },
            None,
            None,
            0,
        ),
        (
            {
                "storage_capacity": 1200,
                "deployment_type": "PERSISTENT_1",
                "per_unit_storage_throughput": "50",
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
            "When specifying 'daily_automatic_backup_start_time', "
            "the 'automatic_backup_retention_days' option must be specified",
            0,
        ),
        (
            {"storage_capacity": 1200, "deployment_type": "PERSISTENT_1", "copy_tags_to_backups": True},
            None,
            "When specifying 'copy_tags_to_backups', the 'automatic_backup_retention_days' option must be specified",
            0,
        ),
        (
            {"storage_capacity": 1200, "deployment_type": "PERSISTENT_1", "copy_tags_to_backups": False},
            None,
            "When specifying 'copy_tags_to_backups', the 'automatic_backup_retention_days' option must be specified",
            0,
        ),
        (
            {"daily_automatic_backup_start_time": "03:00", "copy_tags_to_backups": True},
            None,
            "When specifying 'daily_automatic_backup_start_time', "
            "the 'automatic_backup_retention_days' option must be specified",
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
        (
            {
                "deployment_type": "SCRATCH_1",
                "storage_type": "HDD",
                "per_unit_storage_throughput": 12,
                "storage_capacity": 1200,
                "drive_cache_type": "READ",
            },
            None,
            "For HDD filesystems, 'deployment_type' must be 'PERSISTENT_1'",
            0,
        ),
        (
            {
                "deployment_type": "PERSISTENT_1",
                "storage_type": "HDD",
                "per_unit_storage_throughput": 50,
                "storage_capacity": 1200,
                "drive_cache_type": "READ",
            },
            None,
            "For HDD filesystems, 'per_unit_storage_throughput' can only have the following values: {0}".format(
                FSX_HDD_THROUGHPUT
            ),
            0,
        ),
        (
            {
                "deployment_type": "PERSISTENT_1",
                "storage_type": "SSD",
                "per_unit_storage_throughput": 12,
                "storage_capacity": 1200,
            },
            None,
            "For SSD filesystems, 'per_unit_storage_throughput' can only have the following values: {0}".format(
                FSX_SSD_THROUGHPUT
            ),
            0,
        ),
        (
            {
                "deployment_type": "PERSISTENT_1",
                "storage_type": "SSD",
                "per_unit_storage_throughput": 50,
                "storage_capacity": 1200,
                "drive_cache_type": "NONE",
            },
            None,
            "The configuration parameter 'drive_cache_type' has an invalid value 'NONE'",
            0,
        ),
        (
            {
                "deployment_type": "PERSISTENT_1",
                "storage_type": "SSD",
                "per_unit_storage_throughput": 50,
                "storage_capacity": 1200,
            },
            None,
            None,
            0,
        ),
        (
            {
                "deployment_type": "PERSISTENT_1",
                "per_unit_storage_throughput": 50,
                "storage_capacity": 1200,
                "drive_cache_type": "READ",
            },
            None,
            "'drive_cache_type' features can be used only with HDD filesystems",
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
    if expected_error:
        expected_error = re.escape(expected_error)
    utils.assert_param_validator(mocker, config_parser_dict, expected_error=expected_error)


@pytest.mark.parametrize(
    "section_dict, expected_error, expected_warning",
    [
        (
            {"storage_capacity": 1, "deployment_type": "SCRATCH_1"},
            "Capacity for FSx SCRATCH_1 filesystem is 1,200 GB, 2,400 GB or increments of 3,600 GB",
            None,
        ),
        ({"storage_capacity": 1200, "deployment_type": "SCRATCH_1"}, None, None),
        ({"storage_capacity": 2400, "deployment_type": "SCRATCH_1"}, None, None),
        ({"storage_capacity": 3600, "deployment_type": "SCRATCH_1"}, None, None),
        (
            {"storage_capacity": 3600, "deployment_type": "SCRATCH_2"},
            "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB",
            None,
        ),
        (
            {"storage_capacity": 3600, "deployment_type": "PERSISTENT_1", "per_unit_storage_throughput": 50},
            "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB",
            None,
        ),
        (
            {"storage_capacity": 3601, "deployment_type": "PERSISTENT_1", "per_unit_storage_throughput": 50},
            "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB",
            None,
        ),
        ({"storage_capacity": 7200}, None, None),
        (
            {"deployment_type": "SCRATCH_1"},
            "When specifying 'fsx' section, the 'storage_capacity' option must be specified",
            None,
        ),
        (
            {
                "storage_type": "HDD",
                "deployment_type": "PERSISTENT_1",
                "storage_capacity": 1801,
                "per_unit_storage_throughput": 40,
            },
            "Capacity for FSx PERSISTENT HDD 40 MB/s/TiB file systems is increments of 1,800 GiB",
            None,
        ),
        (
            {
                "storage_type": "HDD",
                "deployment_type": "PERSISTENT_1",
                "storage_capacity": 6001,
                "per_unit_storage_throughput": 12,
            },
            "Capacity for FSx PERSISTENT HDD 12 MB/s/TiB file systems is increments of 6,000 GiB",
            None,
        ),
        (
            {
                "storage_type": "HDD",
                "deployment_type": "PERSISTENT_1",
                "storage_capacity": 1800,
                "per_unit_storage_throughput": 40,
            },
            None,
            None,
        ),
        (
            {
                "storage_type": "HDD",
                "deployment_type": "PERSISTENT_1",
                "storage_capacity": 6000,
                "per_unit_storage_throughput": 12,
            },
            None,
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
        ({"enable_intel_hpc_platform": "true", "base_os": "centos8"}, None),
        ({"enable_intel_hpc_platform": "true", "base_os": "alinux"}, "it is required to set the 'base_os'"),
        ({"enable_intel_hpc_platform": "true", "base_os": "alinux2"}, "it is required to set the 'base_os'"),
        ({"enable_intel_hpc_platform": "true", "base_os": "ubuntu1604"}, "it is required to set the 'base_os'"),
        ({"enable_intel_hpc_platform": "true", "base_os": "ubuntu1804"}, "it is required to set the 'base_os'"),
        # intel hpc disabled, you can use any os
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
        ({"enable_efa": "compute", "scheduler": "sge"}, "is required to set the 'compute_instance_type'", None),
        (
            {"enable_efa": "compute", "compute_instance_type": "t2.large", "scheduler": "sge"},
            None,
            "You may see better performance using a cluster placement group",
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
                "scheduler": "sge",
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
                "scheduler": "sge",
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
    "cluster_dict, expected_error",
    [
        # EFAGDR without EFA
        (
            {"enable_efa_gdr": "compute"},
            "The parameter 'enable_efa_gdr' can be used only in combination with 'enable_efa'",
        ),
        # EFAGDR with EFA
        ({"enable_efa": "compute", "enable_efa_gdr": "compute"}, None),
        # EFA withoud EFAGDR
        ({"enable_efa": "compute"}, None),
    ],
)
def test_efa_gdr_validator(cluster_dict, expected_error):
    config_parser_dict = {
        "cluster default": cluster_dict,
    }

    config_parser = configparser.ConfigParser()
    config_parser.read_dict(config_parser_dict)

    pcluster_config = utils.init_pcluster_config_from_configparser(config_parser, False, auto_refresh=False)
    enable_efa_gdr_value = pcluster_config.get_section("cluster").get_param_value("enable_efa_gdr")

    errors, warnings = efa_gdr_validator("enable_efa_gdr", enable_efa_gdr_value, pcluster_config)
    if expected_error:
        assert_that(errors[0]).matches(expected_error)
    else:
        assert_that(errors).is_empty()


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
            "scheduler": "sge",
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
            "Invalid number of 'ebs' sections specified. Max 5 expected.",
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
        ("ubuntu1604", "t2.medium", None, "Please double check the 'base_os' configuration parameter", None),
        ("centos7", "t2.medium", None, None, None),
        ("centos8", "t2.medium", None, None, None),
        ("ubuntu1804", "t2.medium", None, None, None),
        ("ubuntu1804", "t2.medium", "1.2.3.4/32", None, None),
        ("centos7", "t2.medium", "0.0.0.0/0", None, None),
        ("centos8", "t2.medium", "0.0.0.0/0", None, None),
        ("alinux2", "t2.medium", None, None, None),
        ("alinux2", "t2.nano", None, None, "is recommended to use an instance type with at least"),
        ("alinux2", "t2.micro", None, None, "is recommended to use an instance type with at least"),
        ("ubuntu1804", "m6g.xlarge", None, None, None),
        ("alinux2", "m6g.xlarge", None, None, None),
        ("centos7", "m6g.xlarge", None, "Please double check the 'base_os' configuration parameter", None),
        ("centos8", "m6g.xlarge", None, None, None),
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

    architectures = ["x86_64"] if instance_type.startswith("t2") else ["arm64"]
    extra_patches = {
        "pcluster.config.validators.get_supported_instance_types": ["t2.nano", "t2.micro", "t2.medium", "m6g.xlarge"],
        "pcluster.config.validators.get_supported_architectures_for_instance_type": architectures,
        "pcluster.config.cfn_param_types.get_supported_architectures_for_instance_type": architectures,
        "pcluster.config.validators.get_supported_os_for_architecture": [base_os],
    }
    utils.assert_param_validator(
        mocker, config_parser_dict, expected_error, capsys, expected_warning, extra_patches=extra_patches
    )
    access_from_error_msg = DCV_MESSAGES["warnings"]["access_from_world"].format(port=8443)
    assert_that(access_from_error_msg in caplog.text).is_equal_to(not access_from or access_from == "0.0.0.0/0")


@pytest.mark.parametrize(
    "architecture, base_os, expected_message",
    [
        # Supported combinations
        ("x86_64", "alinux", None),
        ("x86_64", "alinux2", None),
        ("x86_64", "centos7", None),
        ("x86_64", "centos8", None),
        ("x86_64", "ubuntu1604", None),
        ("x86_64", "ubuntu1804", None),
        ("arm64", "ubuntu1804", None),
        ("arm64", "alinux2", None),
        ("arm64", "centos8", None),
        # Unsupported combinations
        (
            "UnsupportedArchitecture",
            "alinux2",
            FSX_MESSAGES["errors"]["unsupported_architecture"].format(
                supported_architectures=list(FSX_SUPPORTED_ARCHITECTURES_OSES.keys())
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
        "pcluster.config.cfn_param_types.get_supported_architectures_for_instance_type": [architecture],
        "pcluster.config.validators.get_supported_architectures_for_instance_type": [architecture],
        "pcluster.config.validators.get_supported_os_for_architecture": [base_os],
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
        ("centos8", None),
        ("ubuntu1604", None),
        ("ubuntu1804", None),
        ("alinux", "alinux.*will reach end-of-life in late 2020"),
    ],
)
def test_base_os_validator(mocker, capsys, base_os, expected_warning):
    config_parser_dict = {"cluster default": {"base_os": base_os}}
    utils.assert_param_validator(mocker, config_parser_dict, capsys=capsys, expected_warning=expected_warning)


@pytest.mark.parametrize(
    "cluster_section_dict, expected_message",
    [
        # SIT cluster, perfectly fine
        ({"scheduler": "slurm"}, None),
        # HIT cluster with one queue
        ({"scheduler": "slurm", "queue_settings": "queue1"}, None),
        ({"scheduler": "slurm", "queue_settings": "queue1,queue2,queue3,queue4,queue5"}, None),
        ({"scheduler": "slurm", "queue_settings": "queue1, queue2"}, None),
        (
            {"scheduler": "slurm", "queue_settings": "queue1,queue2,queue3,queue4,queue5,queue6"},
            "Invalid number of 'queue' sections specified. Max 5 expected.",
        ),
        (
            {"scheduler": "slurm", "queue_settings": "queue_1"},
            (
                "Invalid queue name 'queue_1'. Queue section names can be at most 30 chars long, must begin with"
                " a letter and only contain lowercase letters, digits and hyphens. It is forbidden to use"
                " 'default' as a queue section name."
            ),
        ),
        (
            {"scheduler": "slurm", "queue_settings": "default"},
            (
                "Invalid queue name 'default'. Queue section names can be at most 30 chars long, must begin with"
                " a letter and only contain lowercase letters, digits and hyphens. It is forbidden to use"
                " 'default' as a queue section name."
            ),
        ),
        (
            {"scheduler": "slurm", "queue_settings": "queue1, default"},
            (
                "Invalid queue name '.*'. Queue section names can be at most 30 chars long, must begin with"
                " a letter and only contain lowercase letters, digits and hyphens. It is forbidden to use"
                " 'default' as a queue section name."
            ),
        ),
        (
            {"scheduler": "slurm", "queue_settings": "QUEUE"},
            (
                "Invalid queue name 'QUEUE'. Queue section names can be at most 30 chars long, must begin with"
                " a letter and only contain lowercase letters, digits and hyphens. It is forbidden to use"
                " 'default' as a queue section name."
            ),
        ),
        (
            {"scheduler": "slurm", "queue_settings": "aQUEUEa"},
            (
                "Invalid queue name 'aQUEUEa'. Queue section names can be at most 30 chars long, must begin with"
                " a letter and only contain lowercase letters, digits and hyphens. It is forbidden to use"
                " 'default' as a queue section name."
            ),
        ),
        ({"scheduler": "slurm", "queue_settings": "my-default-queue"}, None),
    ],
)
def test_queue_settings_validator(mocker, cluster_section_dict, expected_message):
    config_parser_dict = {"cluster default": cluster_section_dict}
    if cluster_section_dict.get("queue_settings"):
        for i, queue_name in enumerate(cluster_section_dict["queue_settings"].split(",")):
            config_parser_dict["queue {0}".format(queue_name.strip())] = {
                "compute_resource_settings": "cr{0}".format(i),
                "disable_hyperthreading": True,
                "enable_efa": True,
            }
            config_parser_dict["compute_resource cr{0}".format(i)] = {"instance_type": "t2.micro"}

    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "cluster_dict, queue_dict, expected_error_messages, expected_warning_messages",
    [
        (
            {"queue_settings": "default"},
            {"compute_resource_settings": "cr1,cr2", "enable_efa": True, "disable_hyperthreading": True},
            [
                "Duplicate instance type 't2.micro' found in queue 'default'. "
                "Compute resources in the same queue must use different instance types"
            ],
            [
                "EFA was enabled on queue 'default', but instance type 't2.micro' "
                "defined in compute resource settings cr1 does not support EFA.",
                "EFA was enabled on queue 'default', but instance type 't2.micro' "
                "defined in compute resource settings cr2 does not support EFA.",
            ],
        ),
        (
            {"queue_settings": "default"},
            {"compute_resource_settings": "cr3,cr4", "enable_efa": True, "disable_hyperthreading": True},
            [
                "Duplicate instance type 'c4.xlarge' found in queue 'default'. "
                "Compute resources in the same queue must use different instance types"
            ],
            [
                "EFA was enabled on queue 'default', but instance type 'c4.xlarge' "
                "defined in compute resource settings cr3 does not support EFA.",
                "EFA was enabled on queue 'default', but instance type 'c4.xlarge' "
                "defined in compute resource settings cr4 does not support EFA.",
            ],
        ),
        (
            {"queue_settings": "default"},
            {"compute_resource_settings": "cr1,cr3", "enable_efa": True, "disable_hyperthreading": True},
            None,
            [
                "EFA was enabled on queue 'default', but instance type 't2.micro' "
                "defined in compute resource settings cr1 does not support EFA.",
                "EFA was enabled on queue 'default', but instance type 'c4.xlarge' "
                "defined in compute resource settings cr3 does not support EFA.",
            ],
        ),
        (
            {"queue_settings": "default"},
            {"compute_resource_settings": "cr2,cr4", "enable_efa": True, "disable_hyperthreading": True},
            None,
            [
                "EFA was enabled on queue 'default', but instance type 't2.micro' "
                "defined in compute resource settings cr2 does not support EFA.",
                "EFA was enabled on queue 'default', but instance type 'c4.xlarge' "
                "defined in compute resource settings cr4 does not support EFA.",
            ],
        ),
        (
            {"queue_settings": "default"},
            {"compute_resource_settings": "cr2,cr4", "enable_efa": True, "enable_efa_gdr": True},
            None,
            [
                "EFA was enabled on queue 'default', but instance type 't2.micro' "
                "defined in compute resource settings cr2 does not support EFA.",
                "EFA GDR was enabled on queue 'default', but instance type 't2.micro' "
                "defined in compute resource settings cr2 does not support EFA GDR.",
                "EFA was enabled on queue 'default', but instance type 'c4.xlarge' "
                "defined in compute resource settings cr4 does not support EFA.",
                "EFA GDR was enabled on queue 'default', but instance type 'c4.xlarge' "
                "defined in compute resource settings cr4 does not support EFA GDR.",
            ],
        ),
        (
            {"queue_settings": "default"},
            {"compute_resource_settings": "efa_instance", "enable_efa_gdr": True},
            ["The parameter 'enable_efa_gdr' can be used only in combination with 'enable_efa'"],
            None,
        ),
        ({"queue_settings": "default"}, {"compute_resource_settings": "cr1"}, None, None),
        (
            {"queue_settings": "default", "enable_efa": "compute", "disable_hyperthreading": True},
            {"compute_resource_settings": "cr1", "enable_efa": True, "disable_hyperthreading": True},
            [
                "Parameter 'enable_efa' can be used only in 'cluster' or in 'queue' section",
                "Parameter 'disable_hyperthreading' can be used only in 'cluster' or in 'queue' section",
            ],
            [
                "EFA was enabled on queue 'default', but instance type 't2.micro' "
                "defined in compute resource settings cr1 does not support EFA."
            ],
        ),
        (
            {
                "queue_settings": "default",
                "enable_efa": "compute",
                "enable_efa_gdr": "compute",
                "disable_hyperthreading": True,
            },
            {
                "compute_resource_settings": "cr1",
                "enable_efa": False,
                "enable_efa_gdr": False,
                "disable_hyperthreading": False,
            },
            [
                "Parameter 'enable_efa' can be used only in 'cluster' or in 'queue' section",
                "Parameter 'enable_efa_gdr' can be used only in 'cluster' or in 'queue' section",
                "Parameter 'disable_hyperthreading' can be used only in 'cluster' or in 'queue' section",
            ],
            None,
        ),
        (
            {"queue_settings": "default"},
            {"compute_resource_settings": "efa_instance", "enable_efa": True},
            None,
            None,
        ),
    ],
)
def test_queue_validator(cluster_dict, queue_dict, expected_error_messages, expected_warning_messages):
    config_parser_dict = {
        "cluster default": cluster_dict,
        "queue default": queue_dict,
        "compute_resource cr1": {"instance_type": "t2.micro"},
        "compute_resource cr2": {"instance_type": "t2.micro"},
        "compute_resource cr3": {"instance_type": "c4.xlarge"},
        "compute_resource cr4": {"instance_type": "c4.xlarge"},
        "compute_resource efa_instance": {"instance_type": "p3dn.24xlarge"},
    }

    config_parser = configparser.ConfigParser()
    config_parser.read_dict(config_parser_dict)

    pcluster_config = utils.init_pcluster_config_from_configparser(config_parser, False, auto_refresh=False)

    efa_instance_compute_resource = pcluster_config.get_section("compute_resource", "efa_instance")
    if efa_instance_compute_resource:
        # Override `enable_efa` and `enable_efa_gdr` default value for instance with efa support
        efa_instance_compute_resource.get_param("enable_efa").value = True
        efa_instance_compute_resource.get_param("enable_efa_gdr").value = True

    errors, warnings = queue_validator("queue", "default", pcluster_config)

    if expected_error_messages:
        assert_that(expected_error_messages).is_equal_to(errors)
    else:
        assert_that(errors).is_empty()

    if expected_warning_messages:
        assert_that(expected_warning_messages).is_equal_to(warnings)
    else:
        assert_that(warnings).is_empty()


@pytest.mark.parametrize(
    "param_value, expected_message",
    [
        (
            "section1!2",
            "Invalid label 'section1!2' in param 'queue_settings'. "
            "Section labels can only contain alphanumeric characters, dashes or underscores.",
        ),
        (
            "section!123456789abcdefghijklmnopqrstuvwxyz_123456789abcdefghijklmnopqrstuvwxyz_",
            "Invalid label 'section!123456789...' in param 'queue_settings'. "
            "Section labels can only contain alphanumeric characters, dashes or underscores.",
        ),
        ("section-1", None),
        ("section_1", None),
        (
            "section_123456789abcdefghijklmnopqrstuvwxyz_123456789abcdefghijklmnopqrstuvwxyz_",
            "Invalid label 'section_123456789...' in param 'queue_settings'. "
            "The maximum length allowed for section labels is 64 characters",
        ),
    ],
)
def test_settings_validator(param_value, expected_message):
    errors, warnings = settings_validator("queue_settings", param_value, None)
    if expected_message:
        assert_that(errors and len(errors) == 1).is_true()
        assert_that(errors[0]).is_equal_to(expected_message)
    else:
        assert_that(errors).is_empty()


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"min_count": -1, "initial_count": -1}, "Parameter 'min_count' must be 0 or greater than 0"),
        (
            {"min_count": 0, "initial_count": 1, "spot_price": -1.1},
            "Parameter 'spot_price' must be 0 or greater than 0",
        ),
        (
            {"min_count": 1, "max_count": 0, "initial_count": 1},
            "Parameter 'max_count' must be greater than or equal to 'min_count'",
        ),
        ({"min_count": 0, "max_count": 0, "initial_count": 0}, "Parameter 'max_count' must be 1 or greater than 1"),
        ({"min_count": 1, "max_count": 2, "spot_price": 1.5, "initial_count": 1}, None),
        (
            {"min_count": 2, "max_count": 4, "initial_count": 1},
            "Parameter 'initial_count' must be greater than or equal to 'min_count'",
        ),
        (
            {"min_count": 2, "max_count": 4, "initial_count": 5},
            "Parameter 'initial_count' must be lower than or equal to 'max_count'",
        ),
    ],
)
def test_compute_resource_validator(mocker, section_dict, expected_message):
    config_parser_dict = {
        "cluster default": {"queue_settings": "default"},
        "queue default": {"compute_resource_settings": "default"},
        "compute_resource default": section_dict,
    }

    config_parser = configparser.ConfigParser()
    config_parser.read_dict(config_parser_dict)

    mocker.patch(
        "pcluster.config.cfn_param_types.get_supported_architectures_for_instance_type", return_value=["x86_64"]
    )
    instance_type_info_mock = mocker.MagicMock()
    mocker.patch(
        "pcluster.config.cfn_param_types.InstanceTypeInfo.init_from_instance_type", return_value=instance_type_info_mock
    )
    instance_type_info_mock.max_network_interface_count.return_value = 1
    mocker.patch("pcluster.config.validators.get_supported_architectures_for_instance_type", return_value=["x86_64"])

    pcluster_config = utils.init_pcluster_config_from_configparser(config_parser, False)

    errors, warnings = compute_resource_validator("compute_resource", "default", pcluster_config)

    if expected_message:
        assert_that(expected_message in errors)
    else:
        assert_that(errors).is_empty()


@pytest.mark.parametrize(
    "cluster_section_dict, sections_dict, expected_message",
    [
        (
            {"vpc_settings": "vpc1, vpc2"},
            {"vpc vpc1": {}, "vpc vpc2": {}},
            "The value of 'vpc_settings' parameter is invalid. It can only contain a single vpc section label",
        ),
        (
            {"efs_settings": "efs1, efs2"},
            {"efs efs1": {}, "efs efs2": {}},
            "The value of 'efs_settings' parameter is invalid. It can only contain a single efs section label",
        ),
    ],
)
def test_single_settings_validator(mocker, cluster_section_dict, sections_dict, expected_message):
    config_parser_dict = {"cluster default": cluster_section_dict}
    if sections_dict:
        for key, section in sections_dict.items():
            config_parser_dict[key] = section
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


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
    expected_messages,
):
    """Run a test for a validator that's concerned with the architecture param."""
    mocked_pcluster_config = make_pcluster_config_mock(mocker, config)
    errors, warnings = validator(param_name, param_val, mocked_pcluster_config)

    mocked_pcluster_config.get_section.assert_called_once_with(constrained_param_section)
    mocked_pcluster_config.get_section.side_effect(constrained_param_section).get_param_value.assert_called_with(
        constrained_param_name
    )
    assert_that(len(warnings)).is_equal_to(0)
    assert_that(len(errors)).is_equal_to(len(expected_messages))
    for error, expected_message in zip(errors, expected_messages):
        assert_that(error).matches(re.escape(expected_message))


@pytest.mark.parametrize(
    "enabled, architecture, expected_message",
    [
        (True, "x86_64", []),
        (True, "arm64", ["instance types and an AMI that support these architectures"]),
        (False, "x86_64", []),
        (False, "arm64", []),
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
        ("alinux", "x86_64", []),
        ("alinux2", "x86_64", []),
        ("centos7", "x86_64", []),
        ("centos8", "x86_64", []),
        ("ubuntu1604", "x86_64", []),
        ("ubuntu1804", "x86_64", []),
        # Only a subset of OSes supported for arm64
        ("alinux", "arm64", ["arm64 is only supported for the following operating systems"]),
        ("alinux2", "arm64", []),
        ("centos7", "arm64", ["arm64 is only supported for the following operating systems"]),
        ("centos8", "arm64", []),
        ("ubuntu1604", "arm64", ["arm64 is only supported for the following operating systems"]),
        ("ubuntu1804", "arm64", []),
    ],
)
def test_architecture_os_validator(mocker, base_os, architecture, expected_message):
    """Verify that the correct set of OSes is supported for each supported architecture."""
    config_dict = {"cluster": {"base_os": base_os, "architecture": architecture}}
    run_architecture_validator_test(
        mocker, config_dict, "cluster", "architecture", "base_os", base_os, architecture_os_validator, expected_message
    )


@pytest.mark.parametrize(
    "disable_hyperthreading, architecture, expected_message",
    [
        (True, "x86_64", []),
        (False, "x86_64", []),
        (
            True,
            "arm64",
            ["disable_hyperthreading is only supported on instance types that support these architectures"],
        ),
        (False, "arm64", []),
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
    "head_node_architecture, compute_architecture, compute_instance_type, expected_message",
    [
        # Single compute_instance_type
        ("x86_64", "x86_64", "c5.xlarge", []),
        (
            "x86_64",
            "arm64",
            "m6g.xlarge",
            ["none of which are compatible with the architecture supported by the master_instance_type"],
        ),
        (
            "arm64",
            "x86_64",
            "c5.xlarge",
            ["none of which are compatible with the architecture supported by the master_instance_type"],
        ),
        ("arm64", "arm64", "m6g.xlarge", []),
        ("x86_64", "x86_64", "optimal", []),
        # Function to get supported architectures shouldn't be called because compute_instance_type arg
        # are instance families.
        ("x86_64", None, "m6g", []),
        ("x86_64", None, "c5", []),
        # The validator must handle the case where compute_instance_type is a CSV list
        ("arm64", "arm64", "m6g.xlarge,r6g.xlarge", []),
        (
            "x86_64",
            "arm64",
            "m6g.xlarge,r6g.xlarge",
            ["none of which are compatible with the architecture supported by the master_instance_type"] * 2,
        ),
    ],
)
def test_instances_architecture_compatibility_validator(
    mocker, caplog, head_node_architecture, compute_architecture, compute_instance_type, expected_message
):
    def internal_is_instance_type(itype):
        return "." in itype or itype == "optimal"

    supported_architectures_patch = mocker.patch(
        "pcluster.config.validators.get_supported_architectures_for_instance_type", return_value=[compute_architecture]
    )
    is_instance_type_patch = mocker.patch(
        "pcluster.config.validators.is_instance_type_format", side_effect=internal_is_instance_type
    )
    logger_patch = mocker.patch.object(LOGFILE_LOGGER, "debug")
    run_architecture_validator_test(
        mocker,
        {"cluster": {"architecture": head_node_architecture}},
        "cluster",
        "architecture",
        "compute_instance_type",
        compute_instance_type,
        instances_architecture_compatibility_validator,
        expected_message,
    )
    compute_instance_types = compute_instance_type.split(",")
    non_instance_families = [
        instance_type for instance_type in compute_instance_types if internal_is_instance_type(instance_type)
    ]
    assert_that(supported_architectures_patch.call_count).is_equal_to(len(non_instance_families))
    assert_that(logger_patch.call_count).is_equal_to(len(compute_instance_types) - len(non_instance_families))
    assert_that(is_instance_type_patch.call_count).is_equal_to(len(compute_instance_types))


@pytest.mark.parametrize(
    "section_dict, bucket, num_calls, expected_error",
    [
        (
            {
                "fsx_backup_id": "backup-0ff8da96d57f3b4e3",
                "deployment_type": "PERSISTENT_1",
                "per_unit_storage_throughput": 50,
            },
            None,
            0,
            "When restoring an FSx Lustre file system from backup, 'deployment_type' cannot be specified.",
        ),
        (
            {"fsx_backup_id": "backup-0ff8da96d57f3b4e3", "storage_capacity": 7200},
            None,
            0,
            "When restoring an FSx Lustre file system from backup, 'storage_capacity' cannot be specified.",
        ),
        (
            {
                "fsx_backup_id": "backup-0ff8da96d57f3b4e3",
                "deployment_type": "PERSISTENT_1",
                "per_unit_storage_throughput": 100,
            },
            None,
            0,
            "When restoring an FSx Lustre file system from backup, 'per_unit_storage_throughput' cannot be specified.",
        ),
        (
            {
                "fsx_backup_id": "backup-0ff8da96d57f3b4e3",
                "imported_file_chunk_size": 1024,
                "export_path": "s3://test",
                "import_path": "s3://test",
            },
            {"Bucket": "test"},
            2,
            "When restoring an FSx Lustre file system from backup, 'imported_file_chunk_size' cannot be specified.",
        ),
        (
            {
                "fsx_backup_id": "backup-0ff8da96d57f3b4e3",
                "fsx_kms_key_id": "somekey",
                "deployment_type": "PERSISTENT_1",
                "per_unit_storage_throughput": 50,
            },
            None,
            0,
            "When restoring an FSx Lustre file system from backup, 'fsx_kms_key_id' cannot be specified.",
        ),
        (
            {
                "fsx_backup_id": "backup-00000000000000000",
                "deployment_type": "PERSISTENT_1",
                "per_unit_storage_throughput": 50,
            },
            None,
            0,
            "Failed to retrieve backup with Id 'backup-00000000000000000'",
        ),
    ],
)
def test_fsx_lustre_backup_validator(mocker, boto3_stubber, section_dict, bucket, num_calls, expected_error):
    valid_key_id = "backup-0ff8da96d57f3b4e3"
    describe_backups_response = {
        "Backups": [
            {
                "BackupId": valid_key_id,
                "Lifecycle": "AVAILABLE",
                "Type": "USER_INITIATED",
                "CreationTime": 1594159673.559,
                "FileSystem": {
                    "StorageCapacity": 7200,
                    "StorageType": "SSD",
                    "LustreConfiguration": {"DeploymentType": "PERSISTENT_1", "PerUnitStorageThroughput": 200},
                },
            }
        ]
    }

    if bucket:
        _head_bucket_stubber(mocker, boto3_stubber, bucket, num_calls)
    generate_describe_backups_error = section_dict.get("fsx_backup_id") != valid_key_id
    fsx_mocked_requests = [
        MockedBoto3Request(
            method="describe_backups",
            response=expected_error if generate_describe_backups_error else describe_backups_response,
            expected_params={"BackupIds": [section_dict.get("fsx_backup_id")]},
            generate_error=generate_describe_backups_error,
        )
    ]
    boto3_stubber("fsx", fsx_mocked_requests)

    if "fsx_kms_key_id" in section_dict:
        describe_key_response = {"KeyMetadata": {"KeyId": section_dict.get("fsx_kms_key_id")}}
        kms_mocked_requests = [
            MockedBoto3Request(
                method="describe_key",
                response=describe_key_response,
                expected_params={"KeyId": section_dict.get("fsx_kms_key_id")},
            )
        ]
        boto3_stubber("kms", kms_mocked_requests)

    config_parser_dict = {"cluster default": {"fsx_settings": "default"}, "fsx default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_error=expected_error)


#########
#
# ignored FSx params validator test
#
# Testing a validator that requires the fsx_fs_id parameter to be specified requires a lot of
# boto3 stubbing due to the complexity contained in the fsx_id_validator.
#
# Thus, the following code mocks the pcluster_config object passed to the validator functions
# and calls the validator directly.
#
#########


@pytest.mark.parametrize(
    "section_dict, expected_error",
    [
        ({"fsx_fs_id": "fs-0123456789abcdef0", "shared_dir": "/fsx"}, None),
        (
            {"fsx_fs_id": "fs-0123456789abcdef0", "shared_dir": "/fsx", "storage_capacity": 3600},
            "storage_capacity is ignored when specifying an existing Lustre file system",
        ),
    ],
)
def test_fsx_ignored_parameters_validator(mocker, section_dict, expected_error):
    mocked_pcluster_config = utils.get_mocked_pcluster_config(mocker)
    fsx_section = CfnSection(FSX, mocked_pcluster_config, "default")
    for param_key, param_value in section_dict.items():
        param = FSX.get("params").get(param_key).get("type", CfnParam)
        param.value = param_value
        fsx_section.set_param(param_key, param)
    mocked_pcluster_config.add_section(fsx_section)
    errors, warnings = fsx_ignored_parameters_validator("fsx", "default", mocked_pcluster_config)
    assert_that(warnings).is_empty()
    if expected_error:
        assert_that(errors[0]).matches(expected_error)
    else:
        assert_that(errors).is_empty()


@pytest.mark.parametrize(
    "section_dict, expected_error",
    [
        ({"volume_type": "standard", "volume_size": 15}, None),
        ({"volume_type": "standard", "volume_size": 0}, "The size of standard volumes must be at least 1 GiB"),
        ({"volume_type": "standard", "volume_size": 1025}, "The size of standard volumes can not exceed 1024 GiB"),
        ({"volume_type": "io1", "volume_size": 15}, None),
        ({"volume_type": "io1", "volume_size": 3}, "The size of io1 volumes must be at least 4 GiB"),
        ({"volume_type": "io1", "volume_size": 16385}, "The size of io1 volumes can not exceed 16384 GiB"),
        ({"volume_type": "io2", "volume_size": 15}, None),
        ({"volume_type": "io2", "volume_size": 3}, "The size of io2 volumes must be at least 4 GiB"),
        ({"volume_type": "io2", "volume_size": 65537}, "The size of io2 volumes can not exceed 65536 GiB"),
        ({"volume_type": "gp2", "volume_size": 15}, None),
        ({"volume_type": "gp2", "volume_size": 0}, "The size of gp2 volumes must be at least 1 GiB"),
        ({"volume_type": "gp2", "volume_size": 16385}, "The size of gp2 volumes can not exceed 16384 GiB"),
        ({"volume_type": "gp3", "volume_size": 15}, None),
        ({"volume_type": "gp3", "volume_size": 0}, "The size of gp3 volumes must be at least 1 GiB"),
        ({"volume_type": "gp3", "volume_size": 16385}, "The size of gp3 volumes can not exceed 16384 GiB"),
        ({"volume_type": "st1", "volume_size": 500}, None),
        ({"volume_type": "st1", "volume_size": 20}, "The size of st1 volumes must be at least 500 GiB"),
        ({"volume_type": "st1", "volume_size": 16385}, "The size of st1 volumes can not exceed 16384 GiB"),
        ({"volume_type": "sc1", "volume_size": 500}, None),
        ({"volume_type": "sc1", "volume_size": 20}, "The size of sc1 volumes must be at least 500 GiB"),
        ({"volume_type": "sc1", "volume_size": 16385}, "The size of sc1 volumes can not exceed 16384 GiB"),
    ],
)
def test_ebs_volume_type_size_validator(mocker, section_dict, caplog, expected_error):
    config_parser_dict = {"cluster default": {"ebs_settings": "default"}, "ebs default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_error)


def test_ebs_allowed_values_all_have_volume_size_bounds():
    """Ensure that all known EBS volume types are accounted for by the volume size validator."""
    allowed_values_all_have_volume_size_bounds = set(ALLOWED_VALUES["volume_types"]) <= set(
        EBS_VOLUME_TYPE_TO_VOLUME_SIZE_BOUNDS.keys()
    )
    assert_that(allowed_values_all_have_volume_size_bounds).is_true()


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"volume_type": "io1", "volume_size": 20, "volume_iops": 120}, None),
        (
            {"volume_type": "io1", "volume_size": 20, "volume_iops": 90},
            "IOPS rate must be between 100 and 64000 when provisioning io1 volumes.",
        ),
        (
            {"volume_type": "io1", "volume_size": 20, "volume_iops": 64001},
            "IOPS rate must be between 100 and 64000 when provisioning io1 volumes.",
        ),
        ({"volume_type": "io1", "volume_size": 20, "volume_iops": 1001}, "IOPS to volume size ratio of .* is too high"),
        ({"volume_type": "io2", "volume_size": 20, "volume_iops": 120}, None),
        (
            {"volume_type": "io2", "volume_size": 20, "volume_iops": 90},
            "IOPS rate must be between 100 and 256000 when provisioning io2 volumes.",
        ),
        (
            {"volume_type": "io2", "volume_size": 20, "volume_iops": 256001},
            "IOPS rate must be between 100 and 256000 when provisioning io2 volumes.",
        ),
        (
            {"volume_type": "io2", "volume_size": 20, "volume_iops": 20001},
            "IOPS to volume size ratio of .* is too high",
        ),
        ({"volume_type": "gp3", "volume_size": 20, "volume_iops": 3000}, None),
        (
            {"volume_type": "gp3", "volume_size": 20, "volume_iops": 2900},
            "IOPS rate must be between 3000 and 16000 when provisioning gp3 volumes.",
        ),
        (
            {"volume_type": "gp3", "volume_size": 20, "volume_iops": 16001},
            "IOPS rate must be between 3000 and 16000 when provisioning gp3 volumes.",
        ),
        (
            {"volume_type": "gp3", "volume_size": 20, "volume_iops": 10001},
            "IOPS to volume size ratio of .* is too high",
        ),
    ],
)
def test_ebs_volume_iops_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": {"ebs_settings": "default"}, "ebs default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, snapshot_size, state, partition, expected_warning, expected_error, "
    "raise_error_when_getting_snapshot_info",
    [
        (
            {"volume_size": 100, "ebs_snapshot_id": "snap-1234567890abcdef0"},
            50,
            "completed",
            "aws-cn",
            "The specified volume size is larger than snapshot size. In order to use the full capacity of the "
            "volume, you'll need to manually resize the partition "
            "according to this doc: "
            "https://docs.amazonaws.cn/AWSEC2/latest/UserGuide/recognize-expanded-volume-linux.html",
            None,
            False,
        ),
        (
            {"volume_size": 100, "ebs_snapshot_id": "snap-1234567890abcdef0"},
            50,
            "completed",
            "aws-us-gov",
            "The specified volume size is larger than snapshot size. In order to use the full capacity of the "
            "volume, you'll need to manually resize the partition "
            "according to this doc: "
            "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/recognize-expanded-volume-linux.html",
            None,
            False,
        ),
        (
            {"volume_size": 100, "ebs_snapshot_id": "snap-1234567890abcdef0"},
            50,
            "incompleted",
            "aws-us-gov",
            "Snapshot snap-1234567890abcdef0 is in state 'incompleted' not 'completed'",
            None,
            False,
        ),
        ({"ebs_snapshot_id": "snap-1234567890abcdef0"}, 50, "completed", "partition", None, None, False),
        (
            {"volume_size": 100, "ebs_snapshot_id": "snap-1234567891abcdef0"},
            120,
            "completed",
            "aws-us-gov",
            None,
            "The EBS volume size of the section 'default' must not be smaller than 120, because it is the size of the "
            "provided snapshot snap-1234567891abcdef0",
            False,
        ),
        (
            {"volume_size": 100, "ebs_snapshot_id": "snap-1234567890abcdef0"},
            None,
            "completed",
            "aws-cn",
            None,
            "Unable to get volume size for snapshot snap-1234567890abcdef0",
            False,
        ),
        (
            {"ebs_snapshot_id": "snap-1234567890abcdef0"},
            20,
            "completed",
            "aws",
            None,
            "some message",
            True,
        ),
    ],
)
def test_ebs_volume_size_snapshot_validator(
    section_dict,
    snapshot_size,
    state,
    partition,
    mocker,
    expected_warning,
    expected_error,
    raise_error_when_getting_snapshot_info,
    capsys,
):
    ebs_snapshot_id = section_dict["ebs_snapshot_id"]

    describe_snapshots_response = {
        "Description": "This is my snapshot",
        "Encrypted": False,
        "VolumeId": "vol-049df61146c4d7901",
        "State": state,
        "VolumeSize": snapshot_size,
        "StartTime": "2014-02-28T21:28:32.000Z",
        "Progress": "100%",
        "OwnerId": "012345678910",
        "SnapshotId": ebs_snapshot_id,
    }
    mocker.patch("pcluster.config.cfn_param_types.get_ebs_snapshot_info", return_value=describe_snapshots_response)
    if raise_error_when_getting_snapshot_info:
        mocker.patch("pcluster.config.validators.get_ebs_snapshot_info", side_effect=Exception(expected_error))
    else:
        mocker.patch("pcluster.config.validators.get_ebs_snapshot_info", return_value=describe_snapshots_response)
    mocker.patch(
        "pcluster.config.validators.get_partition", return_value="aws-cn" if partition == "aws-cn" else "aws-us-gov"
    )
    config_parser_dict = {"cluster default": {"ebs_settings": "default"}, "ebs default": section_dict}
    utils.assert_param_validator(
        mocker, config_parser_dict, expected_error=expected_error, capsys=capsys, expected_warning=expected_warning
    )


@pytest.mark.parametrize(
    "cluster_section_dict, ebs_section_dict1, ebs_section_dict2, expected_message",
    [
        (
            {"shared_dir": "shared_directory", "ebs_settings": "vol1"},
            {"volume_size": 30},
            {},
            None,
        ),
        (
            {"shared_dir": "shared_directory", "ebs_settings": "vol1"},
            {"shared_dir": "shared_directory1"},
            {},
            "'shared_dir' can not be specified both in cluster section and EBS section",
        ),
        (
            {"shared_dir": "shared_directory", "ebs_settings": "vol1, vol2"},
            {"shared_dir": "shared_directory1", "volume_size": 30},
            {"shared_dir": "shared_directory2", "volume_size": 30},
            "'shared_dir' can not be specified in cluster section when using multiple EBS volumes",
        ),
        (
            {"ebs_settings": "vol1, vol2"},
            {"shared_dir": "shared_directory1", "volume_size": 30},
            {"shared_dir": "shared_directory2", "volume_size": 30},
            None,
        ),
        (
            {"ebs_settings": "vol1"},
            {"volume_size": 30},
            {},
            None,
        ),
        (
            {"ebs_settings": "vol1"},
            {},
            {},
            None,
        ),
        (
            {"shared_dir": "shared_directory"},
            {},
            {},
            None,
        ),
    ],
)
def test_duplicate_shared_dir_validator(
    mocker, cluster_section_dict, ebs_section_dict1, ebs_section_dict2, expected_message
):
    config_parser_dict = {
        "cluster default": cluster_section_dict,
        "ebs vol1": ebs_section_dict1,
        "ebs vol2": ebs_section_dict2,
    }

    utils.assert_param_validator(mocker, config_parser_dict, expected_error=expected_message)


@pytest.mark.parametrize(
    "extra_json, expected_message",
    [
        (
            {"extra_json": {"cluster": {"cfn_scheduler_slots": "1"}}},
            "It is highly recommended to use the disable_hyperthreading parameter in order to control the "
            "hyper-threading configuration in the cluster rather than using cfn_scheduler_slots in extra_json",
        ),
        (
            {"extra_json": {"cluster": {"cfn_scheduler_slots": "vcpus"}}},
            "It is highly recommended to use the disable_hyperthreading parameter in order to control the "
            "hyper-threading configuration in the cluster rather than using cfn_scheduler_slots in extra_json",
        ),
        (
            {"extra_json": {"cluster": {"cfn_scheduler_slots": "cores"}}},
            "It is highly recommended to use the disable_hyperthreading parameter in order to control the "
            "hyper-threading configuration in the cluster rather than using cfn_scheduler_slots in extra_json",
        ),
    ],
)
def test_extra_json_validator(mocker, capsys, extra_json, expected_message):
    config_parser_dict = {"cluster default": extra_json}
    utils.assert_param_validator(mocker, config_parser_dict, capsys=capsys, expected_warning=expected_message)


@pytest.mark.parametrize(
    "cluster_dict, architecture, expected_error",
    [
        ({"base_os": "alinux2", "enable_efa": "compute"}, "x86_64", None),
        ({"base_os": "alinux2", "enable_efa": "compute"}, "arm64", None),
        ({"base_os": "centos8", "enable_efa": "compute"}, "x86_64", None),
        (
            {"base_os": "centos8", "enable_efa": "compute"},
            "arm64",
            "EFA currently not supported on centos8 for arm64 architecture",
        ),
        ({"base_os": "ubuntu1804", "enable_efa": "compute"}, "x86_64", None),
        ({"base_os": "ubuntu1804", "enable_efa": "compute"}, "arm64", None),
    ],
)
def test_efa_os_arch_validator(mocker, cluster_dict, architecture, expected_error):
    mocker.patch(
        "pcluster.config.cfn_param_types.BaseOSCfnParam.get_instance_type_architecture", return_value=architecture
    )

    config_parser_dict = {"cluster default": cluster_dict}
    config_parser = configparser.ConfigParser()
    config_parser.read_dict(config_parser_dict)

    pcluster_config = utils.init_pcluster_config_from_configparser(config_parser, False, auto_refresh=False)
    pcluster_config.get_section("cluster").get_param("architecture").value = architecture
    enable_efa_value = pcluster_config.get_section("cluster").get_param_value("enable_efa")

    errors, warnings = efa_os_arch_validator("enable_efa", enable_efa_value, pcluster_config)
    if expected_error:
        assert_that(errors[0]).matches(expected_error)
    else:
        assert_that(errors).is_empty()


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"volume_type": "gp3", "volume_throughput": 125}, None),
        (
            {"volume_type": "gp3", "volume_throughput": 100},
            "Throughput must be between 125 MB/s and 1000 MB/s when provisioning gp3 volumes.",
        ),
        (
            {"volume_type": "gp3", "volume_throughput": 1001},
            "Throughput must be between 125 MB/s and 1000 MB/s when provisioning gp3 volumes.",
        ),
        ({"volume_type": "gp3", "volume_throughput": 125, "volume_iops": 3000}, None),
        (
            {"volume_type": "gp3", "volume_throughput": 760, "volume_iops": 3000},
            "Throughput to IOPS ratio of .* is too high",
        ),
        ({"volume_type": "gp3", "volume_throughput": 760, "volume_iops": 10000}, None),
    ],
)
def test_ebs_volume_throughput_validator(mocker, section_dict, expected_message):
    config_parser_dict = {"cluster default": {"ebs_settings": "default"}, "ebs default": section_dict}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)
