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
from pcluster.aws.common import AWSExceptionHandler, Boto3Resource


class DynamoResource(Boto3Resource):
    """DynamoDB Boto3 resource."""

    def __init__(self):
        super().__init__("dynamodb")

    @AWSExceptionHandler.handle_client_exception
    def get_item(self, table_name, key):
        """Get item from a DynamoDB table."""
        return self._resource.Table(table_name).get_item(ConsistentRead=True, Key=key)

    @AWSExceptionHandler.handle_client_exception
    def put_item(self, table_name, item, condition_expression=None):
        """Put item into a DynamoDB table."""
        optional_args = {}
        if condition_expression:
            optional_args["ConditionExpression"] = condition_expression
        self._resource.Table(table_name).put_item(Item=item, **optional_args)

    @AWSExceptionHandler.handle_client_exception
    def update_item(
        self,
        table_name,
        key,
        update_expression=None,
        expression_attribute_names=None,
        expression_attribute_values=None,
        condition_expression=None,
    ):
        """Update item into a DynamoDB table."""
        optional_args = {}
        if update_expression:
            optional_args["UpdateExpression"] = update_expression
        if expression_attribute_names:
            optional_args["ExpressionAttributeNames"] = expression_attribute_names
        if expression_attribute_values:
            optional_args["ExpressionAttributeValues"] = expression_attribute_values
        if condition_expression:
            optional_args["ConditionExpression"] = condition_expression
        self._resource.Table(table_name).update_item(Key=key, **optional_args)
