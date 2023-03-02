# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from datetime import datetime

import pytest
from assertpy import assert_that

from pcluster.aws.ssm import SsmClient
from tests.utils import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.aws.common.boto3"


def test_get_parameter(boto3_stubber):
    parameter_name = "mocked_parameter_name"
    expected_response = {
        "Parameter": {
            "Name": parameter_name,
            "Type": "string",
            "Value": "string",
            "Version": 123,
            "LastModifiedDate": datetime(2023, 3, 3),
            "ARN": "string",
            "DataType": "string",
        }
    }
    mocked_requests = [
        MockedBoto3Request(
            method="get_parameter",
            expected_params={"Name": parameter_name},
            response=expected_response,
            generate_error=False,
            error_code=None,
        ),
    ]
    boto3_stubber("ssm", mocked_requests)
    actual_response = SsmClient().get_parameter(parameter_name)
    assert_that(actual_response).is_equal_to(expected_response)
