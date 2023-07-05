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
import logging
from typing import Any, List, Tuple

from pcluster.aws.common import AWSExceptionHandler, Boto3Client

LOGGER = logging.getLogger(__name__)


class ElbClient(Boto3Client):
    """Implement ELB Boto3 client."""

    def __init__(self):
        super().__init__("elbv2")

    @AWSExceptionHandler.handle_client_exception
    def list_load_balancers(self):
        """Retrieve a list of load balancers using pagination."""
        balancers, next_marker = self._describe_load_balancers()
        while next_marker is not None:
            next_balancers, next_marker = self._describe_load_balancers(next_marker)
            balancers.extend(next_balancers)
        return balancers

    @AWSExceptionHandler.handle_client_exception
    def _describe_load_balancers(self, next_marker=None) -> Tuple[List[Any], str]:
        """Retrieve a list of load balancers."""
        describe_load_balancers_kwargs = {}
        if next_marker:
            describe_load_balancers_kwargs["Marker"] = next_marker
        response = self._client.describe_load_balancers(**describe_load_balancers_kwargs)
        return response["LoadBalancers"], response.get("NextMarker")

    @AWSExceptionHandler.handle_client_exception
    def describe_tags(self, load_balancer_arns: []):
        """Retrieve a list of tags associated to the load balancer arns provided as parameter."""
        """You can specify up to 20 load balancer arns in a single call."""
        tags_response = self._client.describe_tags(ResourceArns=load_balancer_arns)
        return tags_response.get("TagDescriptions")

    @AWSExceptionHandler.handle_client_exception
    def describe_target_groups(self, load_balancer_arn: str):
        """Retrieve a list of target groups associated to the load balancer arn provided as parameter."""
        target_group = self._client.describe_target_groups(LoadBalancerArn=load_balancer_arn)
        return target_group.get("TargetGroups")

    @AWSExceptionHandler.handle_client_exception
    def describe_target_health(self, target_group_arn: str):
        """Retrieve a list of target health associated to the target group arn provided as parameter."""
        target_group_health = self._client.describe_target_health(TargetGroupArn=target_group_arn)
        return target_group_health.get("TargetHealthDescriptions")
