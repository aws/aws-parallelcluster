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
from pcluster.aws.common import AWSExceptionHandler, Boto3Client


class CostExplorerClient(Boto3Client):
    """Implement some functionalities of Cost Explorer boto3 client."""

    def __init__(self):
        super().__init__("ce")

    @AWSExceptionHandler.handle_client_exception
    def list_cost_allocation_tags(self):
        """Return a list of cost allocation tags."""
        return self._client.list_cost_allocation_tags()
