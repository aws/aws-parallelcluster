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
import re

from pcluster.aws.common import AWSExceptionHandler, Boto3Client, Cache


class ResourceGroupsClient(Boto3Client):
    """Implement Resource Groups Boto3 client."""

    def __init__(self):
        super().__init__("resource-groups")

    @AWSExceptionHandler.handle_client_exception
    @Cache.cached
    def get_capacity_reservation_ids_from_group_resources(self, group):
        """Return a list of capacity reservation ids."""
        capacity_reservation_ids = []
        resources = self._client.list_group_resources(Group=group)["Resources"]
        for resource in resources:
            if resource["Identifier"]["ResourceType"] == "AWS::EC2::CapacityReservation":
                capacity_reservation_ids.append(
                    re.match(
                        "arn:.*:.*:.*:.*:.*(?P<reservation_id>cr-.*)", resource["Identifier"]["ResourceArn"]
                    ).group("reservation_id")
                )
        return capacity_reservation_ids

    @AWSExceptionHandler.handle_client_exception
    @Cache.cached
    def get_group_configuration(self, group):
        """Return the group config or throw an exception if not a Service Linked Group."""
        return self._client.get_group_configuration(Group=group)
