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
from common.aws.aws_resources import InstanceInfo
from common.boto3.common import AWSClientError, AWSExceptionHandler, Boto3Client
from pcluster import utils
from pcluster.constants import PCLUSTER_IMAGE_NAME_TAG
from pcluster.utils import Cache, InstanceTypeInfo


class Ec2Client(Boto3Client):
    """Implement EC2 Boto3 client."""

    def __init__(self):
        super().__init__("ec2")

    @AWSExceptionHandler.handle_client_exception
    def describe_instance_type(self, instance_type):
        """Return instance type info."""
        return self._client.describe_instance_types(InstanceTypes=[instance_type]).get("InstanceTypes")[0]

    @AWSExceptionHandler.handle_client_exception
    @Cache.cached
    def describe_instance_type_offerings(self, filters=None):
        """Return a list of instance types."""
        kwargs = {"Filters": filters} if filters else {}
        return [
            response.get("InstanceType")
            for response in self._paginate_results(self._client.describe_instance_type_offerings, **kwargs)
        ]

    @AWSExceptionHandler.handle_client_exception
    @Cache.cached
    def get_default_instance_type(self):
        """If current region support free tier, return the free tier instance type. Otherwise, return t3.micro."""
        free_tier_instance_type = self._client.describe_instance_types(
            Filters=[
                {"Name": "free-tier-eligible", "Values": ["true"]},
                {"Name": "current-generation", "Values": ["true"]},
            ]
        )
        return (
            free_tier_instance_type["InstanceTypes"][0]["InstanceType"]
            if free_tier_instance_type["InstanceTypes"]
            else "t3.micro"
        )

    @AWSExceptionHandler.handle_client_exception
    def describe_subnets(self, subnet_ids):
        """Return a list of subnets."""
        return list(self._paginate_results(self._client.describe_subnets, SubnetIds=subnet_ids))

    @AWSExceptionHandler.handle_client_exception
    @Cache.cached
    def get_subnet_avail_zone(self, subnet_id):
        """Return the availability zone associated to the given subnet."""
        subnets = self.describe_subnets([subnet_id])
        if subnets:
            return subnets[0].get("AvailabilityZone")
        raise AWSClientError(function_name="describe_subnets", message=f"Subnet {subnet_id} not found")

    @AWSExceptionHandler.handle_client_exception
    @Cache.cached
    def get_subnet_vpc(self, subnet_id):
        """Return a vpc associated to the given subnet."""
        subnets = self.describe_subnets([subnet_id])
        if subnets:
            return subnets[0].get("VpcId")
        raise AWSClientError(function_name="describe_subnets", message=f"Subnet {subnet_id} not found")

    @AWSExceptionHandler.handle_client_exception
    def describe_image(self, ami_id):
        """Return a dict of ami info."""
        result = self._client.describe_images(ImageIds=[ami_id])
        if result.get("Images"):
            return result.get("Images")[0]
        raise AWSClientError(function_name="describe_image", message=f"Image {ami_id} not found")

    @AWSExceptionHandler.handle_client_exception
    def describe_images(self, ami_ids, filters, owners):
        """Return a list of dict of ami info."""
        result = self._client.describe_images(ImageIds=ami_ids, Filters=filters, Owners=owners)
        if result.get("Images"):
            return result.get("Images")
        raise AWSClientError(function_name="describe_images", message="No image matching the search criteria found")

    def image_exists(self, image_name):
        """Return a boolean describing whether or not an image with the given search criteria exists."""
        filters = [{"Name": "tag:" + PCLUSTER_IMAGE_NAME_TAG, "Values": [image_name]}]
        owners = ["self"]
        try:
            self.describe_images(ami_ids=[], filters=filters, owners=owners)
            return True
        except AWSClientError as e:
            if "No image matching the search criteria found" in str(e):
                return False
            raise e

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
            "alinux2": "amzn2-hvm",
            "centos7": "centos7-hvm",
            "centos8": "centos8-hvm",
            "ubuntu1804": "ubuntu-1804-lts-hvm",
        }
        return "aws-parallelcluster-{version}-{suffix}-{arch}".format(
            version=utils.get_installed_version(), suffix=suffixes[os], arch=architecture
        )

    @AWSExceptionHandler.handle_client_exception
    def terminate_instances(self, instance_ids):
        """Terminate list of EC2 instances."""
        return self._client.terminate_instances(InstanceIds=instance_ids)

    @AWSExceptionHandler.handle_client_exception
    def list_instance_ids(self, filters):
        """Retrieve a filtered list of instance ids."""
        return [
            instance.get("InstanceId")
            for result in self._paginate_results(self._client.describe_instances, Filters=filters)
            for instance in result.get("Instances")
        ]

    @AWSExceptionHandler.handle_client_exception
    def describe_instances(self, filters):
        """Retrieve a filtered list of instances."""
        return [
            InstanceInfo(instance)
            for result in self._paginate_results(self._client.describe_instances, Filters=filters)
            for instance in result.get("Instances")
        ]
