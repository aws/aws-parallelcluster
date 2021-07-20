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

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.aws_resources import InstanceTypeInfo
from pcluster.aws.cfn import CfnClient
from pcluster.aws.dynamo import DynamoResource
from pcluster.aws.ec2 import Ec2Client
from pcluster.aws.fsx import FSxClient
from pcluster.aws.iam import IamClient
from pcluster.aws.imagebuilder import ImageBuilderClient
from pcluster.aws.kms import KmsClient
from pcluster.aws.logs import LogsClient
from pcluster.aws.route53 import Route53Client
from pcluster.aws.s3 import S3Client
from pcluster.aws.s3_resource import S3Resource
from pcluster.aws.sts import StsClient


class _DummyInstanceTypeInfo(InstanceTypeInfo):
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


class _DummyAWSApi(AWSApi):
    def __init__(self):
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        self._ec2 = _DummyEc2Client()
        self._efs = _DummyEfsClient()
        self._fsx = _DummyFSxClient()
        self._cfn = _DummyCfnClient()
        self._s3 = _DummyS3Client()
        self._imagebuilder = _DummyImageBuilderClient()
        self._kms = _DummyKmsClient()
        self._sts = _DummyStsClient()
        self._s3_resource = _DummyS3Resource()
        self._iam = _DummyIamClient()
        self._batch = _DummyBatchClient()
        self._logs = _DummyLogsClient()
        self._ddb_resource = _DummyDynamoResource()
        self._route53 = _DummyRoute53Client()


class _DummyCfnClient(CfnClient):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


class _DummyEc2Client(Ec2Client):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass

    def get_official_image_id(self, os, architecture, filters=None):
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


class _DummyEfsClient(Ec2Client):
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


class _DummyFSxClient(FSxClient):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass

    def get_filesystem_info(self, fsx_fs_id):
        return {
            "DNSName": "dummy-fsx-dns-name",
            "LustreConfiguration": {
                "MountName": "dummy-fsx-mount-name",
            },
        }


class _DummyS3Client(S3Client):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


class _DummyImageBuilderClient(ImageBuilderClient):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


class _DummyKmsClient(KmsClient):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


class _DummyStsClient(StsClient):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


class _DummyS3Resource(S3Resource):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


class _DummyIamClient(IamClient):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


class _DummyDynamoResource(DynamoResource):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


class _DummyBatchClient(IamClient):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


class _DummyLogsClient(LogsClient):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


class _DummyRoute53Client(Route53Client):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


def mock_aws_api(mocker, mock_instance_type_info=True):
    """Mock AWS Api."""
    mocker.patch("pcluster.aws.aws_api.AWSApi.instance", return_value=_DummyAWSApi())
    if mock_instance_type_info:
        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.get_instance_type_info", return_value=_DummyInstanceTypeInfo("t2.micro")
        )
