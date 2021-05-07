#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
from datetime import datetime

import pytest
from assertpy import assert_that

from pcluster.aws.cfn import CfnClient
from pcluster.aws.common import AWSClientError
from tests.utils import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.aws.common.boto3"


class TestCfnClient:
    @pytest.mark.parametrize(
        "next_token, describe_stacks_response, expected_stacks",
        [
            (None, {"Stacks": []}, set()),
            (
                None,
                {
                    "Stacks": [
                        {
                            "StackName": "name1",
                            "CreationTime": datetime.now(),
                            "StackStatus": "CREATE_IN_PROGRESS",
                            "Tags": [{"Key": "Version", "Value": "3.0.0"}],
                        },
                        {"StackName": "name2", "CreationTime": datetime.now(), "StackStatus": "CREATE_IN_PROGRESS"},
                        {
                            "StackName": "name3",
                            "CreationTime": datetime.now(),
                            "StackStatus": "CREATE_IN_PROGRESS",
                            "Tags": [{"Key": "Version", "Value": "3.0.0"}],
                            "ParentId": "id",
                        },
                    ],
                },
                {"name1"},
            ),
            (
                "token",
                {
                    "Stacks": [
                        {
                            "StackName": "name1",
                            "CreationTime": datetime.now(),
                            "StackStatus": "CREATE_IN_PROGRESS",
                            "Tags": [{"Key": "Version", "Value": "3.0.0"}],
                        },
                        {
                            "StackName": "name2",
                            "CreationTime": datetime.now(),
                            "StackStatus": "CREATE_IN_PROGRESS",
                            "Tags": [{"Key": "Version", "Value": "2.0.0"}],
                        },
                    ],
                    "NextToken": "token",
                },
                {"name1", "name2"},
            ),
            ("invalid", Exception(), set()),
        ],
    )
    def test_list_pcluster_stacks(self, set_env, boto3_stubber, next_token, describe_stacks_response, expected_stacks):
        set_env("AWS_DEFAULT_REGION", "us-east-1")

        expected_describe_stacks_params = {} if not next_token else {"NextToken": next_token}
        generate_error = isinstance(describe_stacks_response, Exception)
        mocked_requests = [
            MockedBoto3Request(
                method="describe_stacks",
                response=describe_stacks_response if not generate_error else "error",
                expected_params=expected_describe_stacks_params,
                generate_error=generate_error,
                error_code="error" if generate_error else None,
            )
        ]
        boto3_stubber("cloudformation", mocked_requests)

        if not generate_error:
            stacks, next_token = CfnClient().list_pcluster_stacks(next_token=next_token)
            assert_that(next_token).is_equal_to(describe_stacks_response.get("NextToken"))
            assert_that({s["StackName"] for s in stacks}).is_equal_to(expected_stacks)
        else:
            with pytest.raises(AWSClientError) as e:
                CfnClient().list_pcluster_stacks(next_token=next_token)
            assert_that(e.value.error_code).is_equal_to("error")
