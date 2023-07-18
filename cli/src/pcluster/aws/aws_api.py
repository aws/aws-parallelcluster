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

from pcluster.aws.batch import BatchClient
from pcluster.aws.cfn import CfnClient
from pcluster.aws.dynamo import DynamoResource
from pcluster.aws.ec2 import Ec2Client
from pcluster.aws.efs import EfsClient
from pcluster.aws.elb import ElbClient
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
from pcluster.aws.ssm import SsmClient
from pcluster.aws.sts import StsClient


class AWSApi:
    """
    Proxy class for all AWS API clients used in the CLI.

    A singleton instance can be retrieved from everywhere in the code by calling AWSApi.instance().
    Specific API client wrappers are provided through properties of this instance; for instance AWSApi.instance().ec2
    will return the client wrapper for EC2 service.
    """

    _instance = None

    def __init__(self):
        self.aws_region = os.environ.get("AWS_DEFAULT_REGION")

        self._batch = None
        self._cfn = None
        self._ec2 = None
        self._efs = None
        self._elb = None
        self._fsx = None
        self._dynamodb = None
        self._s3 = None  # pylint: disable=C0103
        self._kms = None
        self._imagebuilder = None
        self._sts = None
        self._s3_resource = None
        self._iam = None
        self._ddb_resource = None
        self._logs = None
        self._route53 = None
        self._secretsmanager = None
        self._ssm = None
        self._resource_groups = None

    @property
    def cfn(self):
        """CloudFormation client."""  # noqa: D403
        if not self._cfn:
            self._cfn = CfnClient()
        return self._cfn

    @property
    def batch(self):
        """AWS Batch client."""
        if not self._batch:
            self._batch = BatchClient()
        return self._batch

    @property
    def ec2(self):
        """EC2 client."""
        if not self._ec2:
            self._ec2 = Ec2Client()
        return self._ec2

    @property
    def efs(self):
        """EFS client."""
        if not self._efs:
            self._efs = EfsClient(ec2_client=self.ec2)
        return self._efs

    @property
    def elb(self):
        """ELB client."""
        if not self._elb:
            self._elb = ElbClient()
        return self._elb

    @property
    def fsx(self):
        """FSX client."""
        if not self._fsx:
            self._fsx = FSxClient()
        return self._fsx

    @property
    def s3(self):  # pylint: disable=C0103
        """S3 client."""
        if not self._s3:
            self._s3 = S3Client()
        return self._s3

    @property
    def kms(self):
        """KMS client."""
        if not self._kms:
            self._kms = KmsClient()
        return self._kms

    @property
    def imagebuilder(self):
        """ImageBuilder client."""  # noqa: D403
        if not self._imagebuilder:
            self._imagebuilder = ImageBuilderClient()
        return self._imagebuilder

    @property
    def sts(self):
        """STS client."""
        if not self._sts:
            self._sts = StsClient()
        return self._sts

    @property
    def s3_resource(self):
        """S3Resource client."""
        if not self._s3_resource:
            self._s3_resource = S3Resource()
        return self._s3_resource

    @property
    def iam(self):
        """IAM client."""
        if not self._iam:
            self._iam = IamClient()
        return self._iam

    @property
    def ddb_resource(self):
        """DynamoResource client."""  # noqa: D403
        if not self._ddb_resource:
            self._ddb_resource = DynamoResource()
        return self._ddb_resource

    @property
    def logs(self):
        """Log client."""
        if not self._logs:
            self._logs = LogsClient()
        return self._logs

    @property
    def route53(self):
        """Route53 client."""
        if not self._route53:
            self._route53 = Route53Client()
        return self._route53

    @property
    def secretsmanager(self):
        """Secrets Manager client."""
        if not self._secretsmanager:
            self._secretsmanager = SecretsManagerClient()
        return self._secretsmanager

    @property
    def ssm(self):
        """SSM client."""
        if not self._ssm:
            self._ssm = SsmClient()
        return self._ssm

    @property
    def resource_groups(self):
        """Resource Groups client."""
        if not self._resource_groups:
            self._resource_groups = ResourceGroupsClient()
        return self._resource_groups

    @staticmethod
    def instance():
        """Return the singleton AWSApi instance."""
        if not AWSApi._instance or AWSApi._instance.aws_region != os.environ.get("AWS_DEFAULT_REGION"):
            AWSApi._instance = AWSApi()
        return AWSApi._instance

    @staticmethod
    def reset():
        """Reset the instance to clear all caches."""
        AWSApi._instance = None
