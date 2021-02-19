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

import pytest

from common.boto3.common import AWSClientError
from pcluster.validators.kms_validators import KmsKeyValidator
from tests.pcluster.boto3.dummy_boto3 import DummyAWSApi
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "kms_key_id, expected_message",
    [
        ("9e8a129be-0e46-459d-865b-3a5bf974a22k", None),
        (
            "9e7a129be-0e46-459d-865b-3a5bf974a22k",
            "Key 'arn:aws:kms:us-east-1:12345678:key/9e7a129be-0e46-459d-865b-3a5bf974a22k' does not exist",
        ),
    ],
)
def test_kms_key_validator(mocker, kms_key_id, expected_message):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch(
        "common.boto3.kms.KmsClient.describe_key",
        side_effect=AWSClientError(function_name="describe_key", message=expected_message)
        if expected_message
        else None,
    )

    actual_failures = KmsKeyValidator().execute(kms_key_id)
    assert_failure_messages(actual_failures, expected_message)
