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

from pcluster.validators.secret_validators import MungeKeySecretArnValidator
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "munge_key_secret_arn, region, mock_response, expected_response",
    [
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret",
            "us-west-2",
            {"SecretString": "validBase64Value"},
            "",
        ),
        (
            "arn:aws:otherService:us-west-2:123456789012:secret:testSecret",
            "us-west-2",
            {"SecretString": "validBase64Value"},
            "The secret arn:aws:otherService:us-west-2:123456789012:secret:testSecret is not supported in region us-west-2.",
        ),
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:otherResource:testSecret",
            "us-west-2",
            {"SecretString": "validBase64Value"},
            "The secret arn:aws:secretsmanager:us-west-2:123456789012:otherResource:testSecret is not supported in region us-west-2.",
        ),
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret",
            "us-west-2",
            {"SecretString": "invalidBase64"},
            "The secret arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret does not contain valid Base64 encoded data.",
        ),
    ],
)
def test_munge_key_secret_arn_validator(
    munge_key_secret_arn,
    region,
    mock_response,
    expected_response,
    mocker,
):
    # Setting up the mock of secretsmanager
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.secretsmanager.SecretsManagerClient.get_secret_value", return_value=mock_response)

    actual_response = MungeKeySecretArnValidator().execute(munge_key_secret_arn, region)
    assert_failure_messages(actual_response, expected_response)
