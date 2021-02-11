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

from common.boto3.common import AWSClientError, AWSExceptionHandler, Boto3Client
from pcluster import utils
from pcluster.utils import Cache, InstanceTypeInfo


class Ec2Client(Boto3Client):
    """Implement EC2 Boto3 client."""

    def __init__(self):
        super().__init__("ec2")

    @AWSExceptionHandler.handle_client_exception
    def describe_instance_type_offerings(self):
        """Return a list of instance types."""
        return [
            offering.get("InstanceType")
            for offering in self._paginate_results(self._client.describe_instance_type_offerings)
        ]

    @AWSExceptionHandler.handle_client_exception
    def describe_subnets(self, subnet_ids):
        """Return a list of subnets."""
        return self._paginate_results(self._client.describe_subnets, SubnetIds=subnet_ids)

    @AWSExceptionHandler.handle_client_exception
    def describe_image(self, ami_id):
        """Return a dict of ami info."""
        result = self._client.describe_images(ImageIds=[ami_id])
        if result.get("Images"):
            return result.get("Images")[0]
        raise AWSClientError(function_name="describe_image", message=f"Image {ami_id} not found")

    @AWSExceptionHandler.handle_client_exception
    def describe_key_pair(self, key_name):
        """Return the given key, if exists."""
        return self._client.describe_key_pairs(KeyNames=[key_name])

    @AWSExceptionHandler.handle_client_exception
    def describe_placement_group(self, group_name):
        """Return the given placement group, if exists."""
        return self._client.describe_placement_group(GroupNames=[group_name])

    @AWSExceptionHandler.handle_client_exception
    def describe_vpc_attribute(self, vpc_id, attribute):
        """Return the attribute of the VPC."""
        return self._client.describe_vpc_attribute(VpcId=vpc_id, Attribute=attribute)

    def is_enable_dns_support(self, vpc_id):
        """Return the value of EnableDnsSupport of the VPC."""
        return (
            self.describe_vpc_attribute(vpc_id=vpc_id, attribute="enableDnsSupport")
            .get("EnableDnsSupport")
            .get("Value")
        )

    def is_enable_dns_hostnames(self, vpc_id):
        """Return the value of EnableDnsHostnames of the VPC."""
        return (
            self.describe_vpc_attribute(vpc_id=vpc_id, attribute="enableDnsHostnames")
            .get("EnableDnsHostnames")
            .get("Value")
        )

    @AWSExceptionHandler.handle_client_exception
    @Cache.cached
    def get_instance_type_info(self, instance_type):
        """Return the results of calling EC2's DescribeInstanceTypes API for the given instance type."""
        return InstanceTypeInfo(
            self._client.describe_instance_types(InstanceTypes=[instance_type]).get("InstanceTypes")[0]
        )

    @AWSExceptionHandler.handle_client_exception
    @Cache.cached
    def get_official_image_id(self, os, architecture):
        """Return the id of the current official image, for the provided os-architecture combination."""
        images = self._client.describe_images(
            Filters=[
                {"Name": "name", "Values": ["{0}*".format(self.get_official_image_name_prefix(os, architecture))]},
                {"Name": "owner-alias", "Values": ["amazon"]},
            ],
        ).get("Images")
        return images[0].get("ImageId") if images else None

    def get_official_image_name_prefix(self, os, architecture):
        """Return the prefix of the current official image, for the provided os-architecture combination."""
        suffixes = {
            "alinux": "amzn-hvm",
            "alinux2": "amzn2-hvm",
            "centos7": "centos7-hvm",
            "centos8": "centos8-hvm",
            "ubuntu1604": "ubuntu-1604-lts-hvm",
            "ubuntu1804": "ubuntu-1804-lts-hvm",
        }
        return "aws-parallelcluster-{version}-{suffix}-{arch}".format(
            version=utils.get_installed_version(), suffix=suffixes[os], arch=architecture
        )
