# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import pytest
from boto3.dynamodb.conditions import Attr

from pcluster.aws.dynamo import DynamoResource


@pytest.fixture()
def mocked_dynamo_table(mocker):
    mock_table = mocker.MagicMock(autospec=True)
    mock_dynamo_resource = mocker.patch("boto3.resource")
    mock_dynamo_resource.return_value.Table.return_value = mock_table
    return mock_table


class TestDynamoDBResource:
    def test_get_item(self, set_env, mocked_dynamo_table):
        set_env("AWS_DEFAULT_REGION", "us-east-1")
        key = {"Id": "MyKey"}
        DynamoResource().get_item("table_name", key)
        mocked_dynamo_table.get_item.assert_called_with(ConsistentRead=True, Key=key)

    def test_put_item(self, set_env, mocked_dynamo_table):
        set_env("AWS_DEFAULT_REGION", "us-east-1")
        item = {"item": "myItem"}
        DynamoResource().put_item("table_name", item=item)
        mocked_dynamo_table.put_item.assert_called_with(Item=item)

        condition_expression = Attr("status").eq(str("status"))
        DynamoResource().put_item("table_name", item=item, condition_expression=condition_expression)
        mocked_dynamo_table.put_item.assert_called_with(Item=item, ConditionExpression=condition_expression)

    def test_update_item(self, set_env, mocked_dynamo_table):
        set_env("AWS_DEFAULT_REGION", "us-east-1")

        key = {"Id": "MyKey"}
        DynamoResource().update_item("table_name", key)
        mocked_dynamo_table.update_item.assert_called_with(Key=key)

        condition_expression = Attr("status").eq(str("status"))
        update_expression = "expression"
        expression_attribute_names = {"#dt": "name"}
        expression_attribute_values = {":s": "value"}
        DynamoResource().update_item(
            "table_name",
            key=key,
            update_expression=update_expression,
            expression_attribute_names=expression_attribute_names,
            expression_attribute_values=expression_attribute_values,
            condition_expression=condition_expression,
        )
        mocked_dynamo_table.update_item.assert_called_with(
            Key=key,
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values,
            ConditionExpression=condition_expression,
        )
