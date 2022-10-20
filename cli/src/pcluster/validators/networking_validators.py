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
    """Subnets validator."""

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


class ElasticIpValidator(Validator):
    """Elastic Ip validator."""

    def _validate(self, elastic_ip: Union[str, bool]):
        if isinstance(elastic_ip, str):
            try:
                AWSApi.instance().ec2.get_eip_allocation_id(elastic_ip)
            except AWSClientError as e:
                self._add_failure(str(e), FailureLevel.ERROR)


class SingleSubnetValidator(Validator):
    """Validate all queues reference the same subnet."""

    def _validate(self, queues_subnets):
        subnet_ids = {tuple(set(queue_subnets)) for queue_subnets in queues_subnets}
        if len(subnet_ids) > 1:
            self._add_failure("The SubnetId used for all of the queues should be the same.", FailureLevel.ERROR)
