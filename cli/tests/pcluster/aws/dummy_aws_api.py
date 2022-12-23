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
from pcluster.aws.aws_resources import FsxFileSystemInfo, InstanceTypeInfo
from pcluster.aws.cfn import CfnClient
from pcluster.aws.common import AWSClientError
from pcluster.aws.dynamo import DynamoResource
from pcluster.aws.ec2 import Ec2Client
from pcluster.aws.efs import EfsClient
from pcluster.aws.fsx import FSxClient
from pcluster.aws.iam import IamClient
from pcluster.aws.imagebuilder import ImageBuilderClient
from pcluster.aws.kms import KmsClient
from pcluster.aws.logs import LogsClient
from pcluster.aws.resource_groups import ResourceGroupsClient
from pcluster.aws.route53 import Route53Client
from pcluster.aws.s3 import S3Client
from pcluster.aws.s3_resource import S3Resource
from pcluster.aws.secretsmanager import SecretsManagerClient
from pcluster.aws.sts import StsClient


class _DummyInstanceTypeInfo(InstanceTypeInfo):
    def __init__(
        self,
        instance_type,
        gpu_count=0,
        interfaces_count=1,
        vcpus=1,
        supported_architectures=None,
        efa_supported=False,
        ebs_optimized=False,
        ec2memory_size_in_mib=4096,
    ):
        super().__init__(instance_type_data={})
        self._gpu_count = gpu_count
        self._max_network_interface_count = interfaces_count
        self._vcpus = vcpus
        self._supported_architectures = supported_architectures if supported_architectures else ["x86_64"]
        self._efa_supported = efa_supported
        self._instance_type = instance_type
        self._ebs_optimized = ebs_optimized
        self._ec2memory_size_in_mib = ec2memory_size_in_mib

    def gpu_count(self):
        return self._gpu_count

    def max_network_interface_count(self):
        return self._max_network_interface_count

    def default_threads_per_core(self):
        # There are more instance types, but for the simplicity of the mock,
        # we consider only t2 as having one thread per core.
        return 1 if self._instance_type.startswith("t2") else 2

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

    def ec2memory_size_in_mib(self):
        return self._ec2memory_size_in_mib

    def instance_storage_supported(self):
        # There are more instance types supporting instance storage.
        # But for the simplicity of the mock, only c5d is considered.
        return True if self._instance_type.startswith("c5d") else False


class _DummyAWSApi(AWSApi):
    def __init__(self, non_happy=False):
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        self._ec2 = _DummyEc2Client()
        self._efs = _DummyEfsClient()
        self._fsx = _DummyFSxClient(non_happy)
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
        self._resource_groups = _DummyResourceGroupsClient()
        self._secretsmanager = _DummySecretsManagerClient()


class _DummyCfnClient(CfnClient):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass


class _DummyEc2Client(Ec2Client):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        self.capacity_reservations_cache = {
            "cr-54321fcdbd5971234": {"InstanceType": "t2.micro", "AvailabilityZone": "string"},
            "cr-321456cdbd597f551": {"InstanceType": "t2.micro", "AvailabilityZone": "string"},
            "cr-123": {"InstanceType": "t2.micro", "AvailabilityZone": "string"},
            "cr-234": {"InstanceType": "t2.micro", "AvailabilityZone": "string"},
        }
        self.security_groups_cache = {}

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

    def describe_volume(self, volume_id):
        return {
            "Attachments": [
                {
                    "Device": "dev-01",
                    "InstanceId": "instance-01",
                    "State": "attached",
                    "VolumeId": "vol-01",
                    "DeleteOnTermination": True,
                },
            ],
            "AvailabilityZone": "az-1",
            "Encrypted": False,
            "KmsKeyId": "kms-key",
            "Size": 123,
            "SnapshotId": "snapshot-123",
            "State": "available",
            "VolumeId": "vol-123",
            "Iops": 123,
            "Tags": [
                {"Key": "string", "Value": "string"},
            ],
            "VolumeType": "gp3",
            "MultiAttachEnabled": False,
            "Throughput": 123,
        }

    def get_subnet_vpc(self, subnet_id):
        return "vpc-123"

    def get_eip_allocation_id(self, eip):
        return "eipalloc-123"


class _DummyEfsClient(EfsClient):
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

    def get_efs_mount_target_security_groups(self, target_id):
        return ["sg-12345678", "sg-23456789"]


class _DummyFSxClient(FSxClient):
    def __init__(self, non_happy=False):
        """Override Parent constructor. No real boto3 client is created."""
        self.non_happy = non_happy
        pass

    def get_filesystem_info(self, fsx_fs_id):
        return {
            "DNSName": "dummy-fsx-dns-name",
            "LustreConfiguration": {
                "MountName": "dummy-fsx-mount-name",
            },
        }

    def describe_volumes(self, volume_ids):
        """Describe FSx volumes."""
        if self.non_happy:
            raise AWSClientError(function_name="describe_volumes", message="describing volumes is unauthorized")

        result = []
        for volume_id in volume_ids:
            result.append(
                {
                    "FileSystemId": "fs-12345678123456789",
                    "VolumeId": volume_id,
                    "OntapConfiguration": {"StorageVirtualMachineId": "svm-123", "JunctionPath": "/vol1"},
                    "OpenZFSConfiguration": {"VolumePath": "/fsx"},
                }
            )
        return result

    def get_file_systems_info(self, fsx_fs_ids):
        result = []
        for file_system_id in fsx_fs_ids:
            result.append(
                FsxFileSystemInfo(
                    {
                        "FileSystemType": "LUSTRE",
                        "LustreConfiguration": {"MountName": "abcdef"},
                        "FileSystemId": file_system_id,
                        "SubnetIds": ["subnet-1"],
                    }
                )
            )
        return result

    def describe_storage_virtual_machines(self, storage_virtual_machine_ids):
        """Describe storage virtual machines."""
        result = []
        for _ in storage_virtual_machine_ids:
            result.append({"Endpoints": {"Nfs": {"DNSName": "abcd"}}})
        return result


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


class _DummyResourceGroupsClient(ResourceGroupsClient):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass

    def get_capacity_reservation_ids_from_group_resources(self, group):
        """Return a list of capacity reservation ids."""
        return (
            ["cr-123", "cr-234"]
            if group != "skip_dummy"
            else super().get_capacity_reservation_ids_from_group_resources(group)
        )


class _DummySecretsManagerClient(SecretsManagerClient):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        self._client = None

    def describe_secret(self, secret_arn):
        return {
            "ARN": "arn:aws:secretsmanager:us-east-1:111111111111:secret:Secret-xxxxxxxx-xxxxx",
            "Name": "dummy_secret",
            "Description": "Dummy Secret",
            "LastChangedDate": "2022-08-01T10:00:00+00:00",
            "LastAccessedDate": "2022-08-02T02:00:00+00:00",
            "Tags": [],
            "VersionIdsToStages": {"12345678-1234-abcd-1234-567890abcdef": ["AWSCURRENT"]},
            "CreatedDate": "2022-08-01T10:00:00+00:00",
        }


def mock_aws_api(mocker, mock_instance_type_info=True, non_happy=False):
    """Mock AWS Api."""
    mocker.patch("pcluster.aws.aws_api.AWSApi.instance", return_value=_DummyAWSApi(non_happy))
    if mock_instance_type_info:
        mocker.patch("pcluster.aws.ec2.Ec2Client.get_instance_type_info", side_effect=_DummyInstanceTypeInfo)
