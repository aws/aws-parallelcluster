# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from typing import Dict, List

from pcluster.aws.common import AWSExceptionHandler, Boto3Client


class ResourceGroupsTaggingApiClient(Boto3Client):
    """Implement Resource Groups Tagging API Boto3 client."""

    def __init__(self):
        super().__init__("resourcegroupstaggingapi")

    @AWSExceptionHandler.handle_client_exception
    def get_resources(self, tag_filters: Dict[str, str], resource_type_filters: List[str] = None) -> List[str]:
        """
        Return a list of resource ARNs matching the given tag filters and resource type filters.

        :param tag_filters: dictionary of tag key/value pairs that resources must match (AND semantics).
        :param resource_type_filters: list of resource type filters (e.g. ["elasticloadbalancing:loadbalancer"]).
        :return: list of resource ARNs matching the filters.
        """
        arns = []
        kwargs = {
            "TagFilters": [{"Key": key, "Values": [value]} for key, value in tag_filters.items()],
        }
        if resource_type_filters:
            kwargs["ResourceTypeFilters"] = resource_type_filters

        pagination_tkn = ""
        while True:
            if pagination_tkn:
                kwargs["PaginationToken"] = pagination_tkn
            response = self._client.get_resources(**kwargs)
            arns.extend(resource["ResourceARN"] for resource in response.get("ResourceTagMappingList", []))
            pagination_tkn = response.get("PaginationToken", "")
            if not pagination_tkn:
                break
        return arns
