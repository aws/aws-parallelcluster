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

    def _validate(self, queue_name, subnet_ids: List[str]):

        # Test if there are duplicate IDs in subnet_ids
        if len(set(subnet_ids)) < len(subnet_ids):
            self._add_failure(
                "The list of subnet IDs specified in queue {0} contains duplicate IDs.".format(queue_name),
                FailureLevel.ERROR,
            )

        # Test if the subnets are all in different AZs
        try:
            subnets = AWSApi.instance().ec2.describe_subnets(subnet_ids=subnet_ids)

            az_set = set()
            for subnet in subnets:
                az_set.add(subnet["AvailabilityZone"])

            if len(az_set) < len(subnet_ids):
                self._add_failure(
                    "Some of the subnet IDs specified in queue {0} are in the same AZ. Please make sure all subnets "
                    "are in different AZs.".format(queue_name),
                    FailureLevel.ERROR,
                )

        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)


class ElasticIpValidator(Validator):
    """Elastic Ip validator."""

    def _validate(self, elastic_ip: Union[str, bool]):
        if isinstance(elastic_ip, str):
            try:
                AWSApi.instance().ec2.get_eip_allocation_id(elastic_ip)
            except AWSClientError as e:
                self._add_failure(str(e), FailureLevel.ERROR)


class SingleSubnetValidator(Validator):
    """Validate only one subnet is used for compute resources with single instance type."""

    def _validate(self, queue_name, subnet_ids):
        if len(subnet_ids) > 1:
            self._add_failure(
                "At least one compute resource in queue {0} use a single instance type. "
                "Multi AZ configuration does not support single instance type. "
                "Please make sure to use the multiple instance type allocation.".format(queue_name),
                FailureLevel.ERROR,
            )


class MultiAzPlacementGroupValidator(Validator):
    """Validate a PlacementGroup is not specified when MultiAZ is enabled."""

    def _validate(self, multi_az_enabled: bool, placement_group_enabled: bool):
        if multi_az_enabled and placement_group_enabled:
            self._add_failure(
                "Multiple subnets configuration does not support specifying Placement Group. "
                "Either specify a single subnet or remove the Placement Group configuration.",
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
