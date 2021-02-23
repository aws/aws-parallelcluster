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

from common.boto3.common import AWSExceptionHandler, Boto3Client


class DynamodbClient(Boto3Client):
    """Implement DynamoDB Boto3 client."""

    def __init__(self):
        super().__init__("dynamodb")

    @AWSExceptionHandler.handle_client_exception
    def get_item(self, table_name, key_name):
        """Return item from a table."""
        return self._client.get_item(TableName=table_name, ConsistentRead=True, Key={"Id": key_name})
