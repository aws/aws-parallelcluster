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
from collections import Counter
from typing import List, Union

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.validators.common import FailureLevel, Validator


class SecurityGroupsValidator(Validator):
    """Security groups validator."""

    def _validate(self, security_group_ids: List[str]):
        if security_group_ids:
            for sg_id in security_group_ids:
                try:
                    AWSApi.instance().ec2.describe_security_group(sg_id)
                except AWSClientError as e:
                    self._add_failure(str(e), FailureLevel.ERROR)


class SubnetsValidator(Validator):
    """
    Subnets validator.

    Check that all subnets in the input list belong to the same VPC.
    Also, check that said VPC supports DNS resolution via the Amazon DNS server and assigning DNS hostnames to
    instances.
    """

    def _validate(self, subnet_ids: List[str]):
        try:
            subnets = AWSApi.instance().ec2.describe_subnets(subnet_ids=subnet_ids)

            # Check all subnets are in the same VPC
            vpc_id = None
            for subnet in subnets:
                if vpc_id is None:
                    vpc_id = subnet["VpcId"]
                elif vpc_id != subnet["VpcId"]:
                    self._add_failure(
                        "Subnet {0} is not in VPC {1}. Please make sure all subnets are in the same VPC.".format(
                            subnet["SubnetId"], vpc_id
                        ),
                        FailureLevel.ERROR,
                    )

            # Check for DNS support in the VPC
            if not AWSApi.instance().ec2.is_enable_dns_support(vpc_id):
                self._add_failure(f"DNS Support is not enabled in the VPC {vpc_id}.", FailureLevel.ERROR)
            if not AWSApi.instance().ec2.is_enable_dns_hostnames(vpc_id):
                self._add_failure(f"DNS Hostnames not enabled in the VPC {vpc_id}.", FailureLevel.ERROR)

        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)


class QueueSubnetsValidator(Validator):
    """
    Queue Subnets validator.

    Check that there is no duplicate subnet id in the subnet_ids list.
    Check that subnets in a queue belong to different AZs (EC2 Fleet requests do not support multiple subnets
    in the same AZ).
    """

    @staticmethod
    def _find_azs_with_multiple_subnets(az_subnet_ids_mapping):
        return {az: subnet_ids for az, subnet_ids in az_subnet_ids_mapping.items() if len(subnet_ids) > 1}

    def _validate(self, queue_name, subnet_ids: List[str], az_subnet_ids_mapping: dict):
        # Test if there are duplicate IDs in subnet_ids
        if len(set(subnet_ids)) < len(subnet_ids):
            duplicate_ids = [subnet_id for subnet_id, count in Counter(subnet_ids).items() if count > 1]
            self._add_failure(
                "The following Subnet Ids are specified multiple times in the SubnetId's configuration of the '{0}' "
                "queue: '{1}'. Please remove the duplicate subnet Ids from the queue's SubnetId configuration.".format(
                    queue_name,
                    ", ".join(duplicate_ids),
                ),
                FailureLevel.ERROR,
            )

        # Test if the subnets are all in different AZs
        try:
            azs_with_multiple_subnets = self._find_azs_with_multiple_subnets(az_subnet_ids_mapping)
            if len(azs_with_multiple_subnets) > 0:
                self._add_failure(
                    "SubnetIds configured for the '{0}' queue contains two or more subnets in the same Availability "
                    "Zone: '{1}'. Please make sure all subnets configured for the queue are in different Availability"
                    " Zones.".format(
                        queue_name,
                        "; ".join(
                            f"{az}: {', '.join(subnets)}" for az, subnets in sorted(azs_with_multiple_subnets.items())
                        ),
                    ),
                    FailureLevel.ERROR,
                )

        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)


class ElasticIpValidator(Validator):
    """Elastic Ip validator."""

    def _validate(self, elastic_ip: Union[str, bool]):
        if isinstance(elastic_ip, str):
            if elastic_ip.lower() in ["true", "false"]:
                return
            try:
                AWSApi.instance().ec2.get_eip_allocation_id(elastic_ip)
            except AWSClientError as e:
                self._add_failure(str(e), FailureLevel.ERROR)


class SingleInstanceTypeSubnetValidator(Validator):
    """Validate only one subnet is used for compute resources with single instance type."""

    def _validate(self, queue_name, subnet_ids):
        if len(subnet_ids) > 1:
            self._add_failure(
                "At least one compute resource in the '{0}' queue is configured using the "
                "'ComputeResource/InstanceType' parameter to specify the Instance Type. Multiple subnets configuration "
                "is not supported when using 'ComputeResource/InstanceType', please use the "
                "'ComputeResource/Instances/InstanceType' configuration parameter for instance type "
                "allocation.".format(queue_name),
                FailureLevel.ERROR,
            )


class MultiAzPlacementGroupValidator(Validator):
    """Validate a PlacementGroup is not specified when MultiAZ is enabled."""

    def _validate(
        self, multi_az_enabled: bool, placement_group_enabled: bool, compute_resource_name: str, queue_name: str
    ):
        if multi_az_enabled and placement_group_enabled:
            self._add_failure(
                f"You have enabled PlacementGroups for the '{compute_resource_name}' Compute Resource on the "
                f"'{queue_name}' queue. PlacementGroups are not supported across Availability zones. Either remove the "
                "PlacementGroup configuration to use multiple subnets on the queue or specify only one subnet to "
                "use a PlacementGroup for compute resources.",
                FailureLevel.ERROR,
            )


class LambdaFunctionsVpcConfigValidator(Validator):
    """Validator of Pcluster Lambda functions' VPC configuration."""

    def _validate(self, security_group_ids: List[str], subnet_ids: List[str]):
        existing_security_groups = AWSApi.instance().ec2.describe_security_groups(security_group_ids)
        existing_subnets = AWSApi.instance().ec2.describe_subnets(subnet_ids)

        self._validate_all_security_groups_exist(existing_security_groups, security_group_ids)
        self._validate_all_subnets_exist(existing_subnets, subnet_ids)
        self._validate_all_resources_belong_to_the_same_vpc(existing_security_groups, existing_subnets)

    def _validate_all_resources_belong_to_the_same_vpc(self, existing_security_groups, existing_subnets):
        group_vpc_ids = {group["VpcId"] for group in existing_security_groups}
        subnet_vpc_ids = {subnet["VpcId"] for subnet in existing_subnets}
        if len(group_vpc_ids) > 1:
            self._add_failure(
                "The security groups associated to the Lambda are required to be in the same VPC.", FailureLevel.ERROR
            )
        if len(subnet_vpc_ids) > 1:
            self._add_failure(
                "The subnets associated to the Lambda are required to be in the same VPC.", FailureLevel.ERROR
            )
        if group_vpc_ids != subnet_vpc_ids:
            self._add_failure(
                "The security groups and subnets associated to the Lambda are required to be in the same VPC.",
                FailureLevel.ERROR,
            )

    def _validate_all_security_groups_exist(self, existing_security_groups, expected_security_group_ids):
        missing_security_group_ids = set(expected_security_group_ids) - {
            group["GroupId"] for group in existing_security_groups
        }
        if missing_security_group_ids:
            self._add_failure(
                "Some security groups associated to the Lambda are not present "
                f"in the account: {sorted(missing_security_group_ids)}.",
                FailureLevel.ERROR,
            )

    def _validate_all_subnets_exist(self, existing_subnets, expected_subnet_ids):
        missing_subnet_ids = set(expected_subnet_ids) - {subnet["SubnetId"] for subnet in existing_subnets}
        if missing_subnet_ids:
            self._add_failure(
                f"Some subnets associated to the Lambda are not present in the account: {sorted(missing_subnet_ids)}.",
                FailureLevel.ERROR,
            )
