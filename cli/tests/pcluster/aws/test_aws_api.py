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
#
# This module contains all the classes representing the Resources objects.
# These objects are obtained from the configuration file through a conversion based on the Schema classes.
#
from datetime import datetime

import pytest
from assertpy import assert_that

from pcluster.aws.common import AWSExceptionHandler, ImageNotFoundError, StackNotFoundError
from tests.pcluster.aws.dummy_aws_api import _DummyAWSApi, mock_aws_api
from tests.pcluster.test_utils import FAKE_NAME
from tests.utils import MockedBoto3Request

FAKE_STACK_NAME = "parallelcluster-name"
FAKE_IMAGE_ID = "ami-1234567"


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.aws.common.boto3"


@pytest.mark.parametrize(
    "response,is_error",
    [
        (
            StackNotFoundError(function_name="describe_stack", stack_name=FAKE_STACK_NAME),
            True,
        ),
        ({"Stacks": [{"StackName": FAKE_STACK_NAME, "CreationTime": 0, "StackStatus": "CREATED"}]}, False),
    ],
)
def test_stack_exists(mocker, response, is_error):
    """Verify that CfnClient.stack_exists behaves as expected."""
    should_exist = not is_error
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", side_effect=response)
    assert_that(_DummyAWSApi().instance().cfn.stack_exists(FAKE_STACK_NAME)).is_equal_to(should_exist)


@pytest.mark.parametrize(
    "response,is_error",
    [
        (
            ImageNotFoundError(function_name="describe_images"),
            True,
        ),
        ({"Images": [{"ImageId": FAKE_IMAGE_ID}]}, False),
    ],
)
def test_image_exists(mocker, response, is_error):
    """Verify that EC2Client.image_exists behaves as expected."""
    should_exist = not is_error
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.describe_images", side_effect=response)
    assert_that(_DummyAWSApi().instance().ec2.image_exists(FAKE_IMAGE_ID)).is_equal_to(should_exist)


def test_retry_on_boto3_throttling(boto3_stubber, mocker):
    @AWSExceptionHandler.retry_on_boto3_throttling
    def describe_stack_resources(client):
        client.describe_stack_resources(StackName=FAKE_NAME)

    sleep_mock = mocker.patch("pcluster.utils.time.sleep")
    mocked_requests = [
        MockedBoto3Request(
            method="describe_stack_resources",
            response="Error",
            expected_params={"StackName": FAKE_NAME},
            generate_error=True,
            error_code="Throttling",
        ),
        MockedBoto3Request(
            method="describe_stack_resources",
            response="Error",
            expected_params={"StackName": FAKE_NAME},
            generate_error=True,
            error_code="Throttling",
        ),
        MockedBoto3Request(method="describe_stack_resources", response={}, expected_params={"StackName": FAKE_NAME}),
    ]
    client = boto3_stubber("cloudformation", mocked_requests)
    describe_stack_resources(client)
    sleep_mock.assert_called_with(5)


FAKE_SSM_PARAMETER = "fake-ssm-parameter-name"


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(
            {
                "Parameter": {
                    "Name": FAKE_SSM_PARAMETER,
                    "Type": "SecureString",
                    "Value": "EncryptedValue",
                    "Version": 1,
                    "LastModifiedDate": datetime(2023, 3, 3),
                    "ARN": f"arn:aws:ssm:us-east-1:111111111111:parameter/{FAKE_SSM_PARAMETER}",
                    "DataType": "text",
                }
            },
            id="SSM GetParameter returns the correct response on success",
        )
    ],
)
def test_ssm_get_parameter(mocker, response):
    """Verify that SsmClient.get_parameter behaves as expected."""
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ssm.SsmClient.get_parameter", side_effect=response)
    assert_that(_DummyAWSApi().instance().ssm.get_parameter(FAKE_SSM_PARAMETER)).is_equal_to(response)
