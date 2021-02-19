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
from common.aws.aws_api import AWSApi
from common.boto3.common import AWSClientError
from common.boto3.ec2 import Ec2Client
from common.boto3.imagebuilder import ImageBuilderClient
from common.boto3.kms import KmsClient
from common.boto3.s3 import S3Client


class DummyAWSApi(AWSApi):
    def __init__(self):
        self.ec2 = dummy_ec2_client()
        self.efs = dummy_efs_client()
        self.s3 = dummy_s3_client()
        self.imagebuilder = dummy_imagebuilder_client()
        self.kms = dummy_kms_client()
        # TODO: mock all clients


class DummyEc2Client(Ec2Client):
    def __init__(self):
        """Override Parent constructor. No real boto3 client is created."""
        pass

    def get_availability_zone_of_subnet(self, subnet_id):
        subnets_azs = {
            "dummy-subnet-1": "dummy-az-1",
            "dummy-subnet-2": "dummy-az-2",
            "dummy-subnet-3": "dummy-az-3",
        }
        availability_zone = subnets_azs.get(subnet_id, None)
        if not availability_zone:
            raise AWSClientError(
                self.get_availability_zone_of_subnet.__name__, "Invalid subnet ID: {0}".format(subnet_id)
            )
        return availability_zone


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


def dummy_ec2_client():
    return DummyEc2Client()


def dummy_efs_client():
    return DummyEfsClient()


def dummy_s3_client():
    return DummyS3Client()


def dummy_imagebuilder_client():
    return DummyImageBuilderClient()


def dummy_kms_client():
    return DummyKmsClient()


def mock_aws_api():
    AWSApi._instance = DummyAWSApi()
