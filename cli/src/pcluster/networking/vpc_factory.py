# Copyright 2018-2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import functools
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError


class VpcFactory:
    """This class handles vpc automation related to pcluster."""

    class _ExceptionHandler:
        @staticmethod
        def handle_client_exception(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except (BotoCoreError, ClientError) as e:
                    print("ERROR during handling of the VPC in the {0} phase.".format(func.__name__))
                    print(e.response["Error"]["Message"])
                    sys.exit(1)

            return wrapper

    @_ExceptionHandler.handle_client_exception
    def __init__(self, aws_region_name):
        """
        Inizialize the VpcHandler with the specified region.

        :param aws_region_name: the region in which you want to use the VpcHandler
        """
        self.__client = boto3.client("ec2", region_name=aws_region_name)
        self.ec2 = boto3.resource("ec2", region_name=aws_region_name)

    @_ExceptionHandler.handle_client_exception
    def create(self, cidr_block="10.0.0.0/16"):
        """
        Create a vpc for the given region name.

        :return: the id of the created vpc
        :raise RuntimeError: if some problems occurred during vpc creation
        """
        response = self.__client.create_vpc(CidrBlock=cidr_block)
        return response["Vpc"]["VpcId"]

    @_ExceptionHandler.handle_client_exception
    def setup(self, vpc_id, name=None):
        """
        Set the parameters necessary for a vpc to be pcluster-compatible.

        :param vpc_id: the target vpc_id
        :param name: the name that you want to give to the vpc
        :raise RuntimeError: if some problems occurred during the operation
        """
        vpc = self.ec2.Vpc(vpc_id)
        if name:
            self.ec2.create_tags(Resources=[vpc_id], Tags=[{"Key": "Name", "Value": name}])
        vpc.modify_attribute(EnableDnsHostnames={"Value": True})
        vpc.modify_attribute(EnableDnsSupport={"Value": True})

    @_ExceptionHandler.handle_client_exception
    def check(self, vpc_id):
        """
        Check whether the given vpc respects the condition needed for pcluster.

        :param vpc_id: the target vpc_id
        :return: True if the vpc is pcluster compatible
        :raise RuntimeError: if some problems occurred during the operation
        """
        vpc = self.ec2.Vpc(vpc_id)
        dns_resolution = vpc.describe_attribute(Attribute="enableDnsSupport")["EnableDnsSupport"]["Value"]
        dns_hostnames = vpc.describe_attribute(Attribute="enableDnsHostnames")["EnableDnsHostnames"]["Value"]

        if not dns_hostnames:
            print("DNS Hostnames of the VPC {0} must be set to True".format(vpc_id))
        if not dns_resolution:
            print("DNS Resolution of the VPC {0} must be set to True".format(vpc_id))
        if vpc.dhcp_options_id == "default":
            print("DHCP options of the VPC {0} must be set.".format(vpc_id))

        # default is equal to NO dhcp options set
        return dns_resolution and dns_hostnames and vpc.dhcp_options_id != "default"
