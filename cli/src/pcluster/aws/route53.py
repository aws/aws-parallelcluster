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
from pcluster.aws.common import AWSClientError, AWSExceptionHandler, Boto3Client, Cache


class Route53Client(Boto3Client):
    """Route53 Boto3 client."""

    def __init__(self):
        super().__init__("route53")

    @AWSExceptionHandler.handle_client_exception
    @Cache.cached
    def get_hosted_zone(self, hosted_zone_id):
        """
        Return Domain name.

        :param hosted_zone_id: Hosted zone Id
        :return: hosted zone info
        """
        return self._client.get_hosted_zone(Id=hosted_zone_id)

    @AWSExceptionHandler.handle_client_exception
    @Cache.cached
    def get_hosted_zone_domain_name(self, hosted_zone_id):
        """Return the availability zone associated to the given subnet."""
        hosted_zone_info = self.get_hosted_zone(hosted_zone_id)
        if hosted_zone_info:
            return hosted_zone_info.get("HostedZone").get("Name")
        raise AWSClientError(
            function_name="get_hosted_zone_domain_name", message=f"Hosted zone {hosted_zone_id} not found"
        )

    @AWSExceptionHandler.handle_client_exception
    @Cache.cached
    def get_vpc_ids(self, hosted_zone_id):
        """Return list of vpc ids related to the hosted zone."""
        hosted_zone_info = self.get_hosted_zone(hosted_zone_id)
        if hosted_zone_info:
            return [vpc.get("VPCId") for vpc in hosted_zone_info.get("VPCs")]
        raise AWSClientError(function_name="get_vpc_ids", message=f"Hosted zone {hosted_zone_id} not found")

    @AWSExceptionHandler.handle_client_exception
    @Cache.cached
    def is_private_zone(self, hosted_zone_id):
        """Return list of vpc ids related to the hosted zone."""
        hosted_zone_info = self.get_hosted_zone(hosted_zone_id)
        if hosted_zone_info:
            return hosted_zone_info.get("HostedZone").get("Config").get("PrivateZone")
        raise AWSClientError(function_name="is_private_zone", message=f"Hosted zone {hosted_zone_id} not found")
