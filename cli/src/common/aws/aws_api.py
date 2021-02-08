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

from common.boto3.ec2 import Ec2Client
from common.boto3.efs import EfsClient
from common.boto3.s3 import S3Client


class AWSApi:
    """
    Proxy class for all AWS API clients used in the CLI.

    A singleton instance can be retrieved from everywhere in the code by calling AWSApi.instance().
    Specific API client wrappers are provided through properties of this instance; for instance AWSApi.instance().ec2
    will return the client wrapper for EC2 service.
    """

    _instance = None

    def __init__(self):
        self.ec2 = Ec2Client()
        self.efs = EfsClient(ec2_client=self.ec2)
        # pylint: disable=C0103
        self.s3 = S3Client()

    @staticmethod
    def instance():
        """Return the singleton AWSApi instance."""
        if not AWSApi._instance:
            AWSApi._instance = AWSApi()
        return AWSApi._instance
