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
import os

from common.aws.aws_api import AWSApi
from common.boto3.cfn import CfnClient
from common.boto3.ec2 import Ec2Client
from common.boto3.imagebuilder import ImageBuilderClient
from common.boto3.kms import KmsClient
from common.boto3.s3 import S3Client
from pcluster.utils import InstanceTypeInfo


class DummyInstanceTypeInfo(InstanceTypeInfo):
    def __init__(
        self,
        instance_type,
        gpu_count=0,
        interfaces_count=1,
        default_threads_per_core=1,
        vcpus=1,
        supported_architectures=None,
        efa_supported=False,
        ebs_optimized=False,
    ):
        self._gpu_count = gpu_count
        self._max_network_interface_count = interfaces_count
        self._default_threads_per_core = default_threads_per_core
        self._vcpus = vcpus
        self._supported_architectures = supported_architectures if supported_architectures else ["x86_64"]
        self._efa_supported = efa_supported
        self._instance_type = instance_type
        self._ebs_optimized = ebs_optimized

    def gpu_count(self):
        return self._gpu_count

    def max_network_interface_count(self):
        return self._max_network_interface_count

    def default_threads_per_core(self):
        return self._default_threads_per_core

    def vcpus_count(self):
        return self._vcpus

    def supported_architecture(self):
        return self._supported_architectures

    def is_efa_supported(self):
        return self._efa_supported

    def instance_type(self):
        return self._instance_type

    def is_ebs_optimized(self):
        return self._ebs_optimized


class DummyAWSApi(AWSApi):
    def __init__(self):
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        self.ec2 = dummy_ec2_client()
        self.efs = dummy_efs_client()
        self.cfn = dummy_cfn_client()
        self.s3 = dummy_s3_client()
        self.imagebuilder = dummy_imagebuilder_client()
        self.kms = dummy_kms_client()
        # TODO: mock all clients


class DummyCfnClient(CfnClient):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


class DummyEc2Client(Ec2Client):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass

    def get_instance_type_info(self, instance_type):
        return DummyInstanceTypeInfo(instance_type)

    def get_official_image_id(self, os, architecture):
        return "dummy-ami-id"

    def describe_subnets(self, subnet_ids):
        return [
            {
                "AvailabilityZone": "string",
                "AvailabilityZoneId": "string",
                "SubnetId": "subnet-123",
                "VpcId": "vpc-123",
            },
        ]

    def get_subnet_vpc(self, subnet_id):
        return "vpc-123"


class DummyEfsClient(Ec2Client):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass

    def get_efs_mount_target_id(self, efs_fs_id, avail_zone):
        mt_id = None
        efs_ids_mount_targets = {
            "dummy-efs-1": {
                "dummy-az-1": "dummy-efs-mt-1",
                "dummy-az-2": "dummy-efs-mt-2",
            }
        }

        mt_dict = efs_ids_mount_targets.get(efs_fs_id)
        if mt_dict:
            mt_id = mt_dict.get(avail_zone)

        return mt_id


class DummyS3Client(S3Client):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


class DummyImageBuilderClient(ImageBuilderClient):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


class DummyKmsClient(KmsClient):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


def dummy_ec2_client():
    return DummyEc2Client()


def dummy_efs_client():
    return DummyEfsClient()


def dummy_cfn_client():
    return DummyCfnClient()


def dummy_s3_client():
    return DummyS3Client()


def dummy_imagebuilder_client():
    return DummyImageBuilderClient()


def dummy_kms_client():
    return DummyKmsClient()


def mock_aws_api():
    AWSApi._instance = DummyAWSApi()
