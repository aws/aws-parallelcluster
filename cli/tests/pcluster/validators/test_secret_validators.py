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
from unittest.mock import MagicMock

import pytest

from pcluster.aws.common import AWSClientError
from pcluster.validators.common import FailureLevel
from pcluster.validators.secret_validators import MungeKeySecretArnValidator
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.validators.utils import assert_failure_messages, assert_failure_level


@pytest.mark.parametrize(
    "munge_key_secret_arn, region, mock_response, expected_response, error_from_aws_service, expected_failure_level",
    [
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret",
            "us-west-2",
            {"SecretString": "validBase64Value"},
            "",
            None,
            None,
        ),
        (
            "arn:aws:otherService:us-west-2:123456789012:secret:testSecret",
            "us-west-2",
            {"SecretString": "validBase64Value"},
            "The secret arn:aws:otherService:us-west-2:123456789012:secret:testSecret is not supported "
            "in region us-west-2.",
            None,
            FailureLevel.ERROR,
        ),
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:otherResource:testSecret",
            "us-west-2",
            {"SecretString": "validBase64Value"},
            "The secret arn:aws:secretsmanager:us-west-2:123456789012:otherResource:testSecret is not supported"
            " in region us-west-2.",
            None,
            FailureLevel.ERROR,
        ),
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret",
            "us-west-2",
            {"SecretString": "invalidBase64"},
            "The secret arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret does not contain"
            " valid Base64 encoded data.",
            None,
            FailureLevel.ERROR,
        ),
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret",
            "us-west-2",
            {"SecretString": "validBase64Value"},
            "The secret arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret does not exist.",
            "ResourceNotFoundExceptionSecrets",
            FailureLevel.ERROR,
        ),
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret",
            "us-west-2",
            {"SecretString": "validBase64Value"},
            "Cannot validate secret arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret due to "
            "lack of permissions. Please refer to ParallelCluster official documentation for more information.",
            "AccessDeniedException",
            FailureLevel.WARNING,
        ),
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret",
            "us-west-2",
            {"SecretString": "validBase64Value"},
            "Cannot validate secret arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret. "
            "Please refer to ParallelCluster official documentation for more information.",
            "ANOTHER_ERROR",
            FailureLevel.WARNING,
        ),
    ],
)
def test_munge_key_secret_arn_validator(
    munge_key_secret_arn,
    region,
    mock_response,
    expected_response,
    error_from_aws_service,
    expected_failure_level,
    mocker,
):
    # Setting up the mock of secretsmanager
    mocker.patch("boto3.client")

    mocker.patch("pcluster.aws.secretsmanager.SecretsManagerClient.get_secret_value", return_value=mock_response)
    if error_from_aws_service:
        mocker.patch(
            "pcluster.aws.secretsmanager.SecretsManagerClient.describe_secret",
            side_effect=AWSClientError(
                function_name="A_FUNCTION_NAME", error_code=str(error_from_aws_service), message="AN_ERROR_MESSAGE"
            ),
        )
    else:
        mocker.patch(
            "pcluster.aws.secretsmanager.SecretsManagerClient.describe_secret",
            return_value={
                "ARN": "arn:aws:secretsmanager:us-east-1:111111111111:secret:Secret-xxxxxxxx-xxxxx",
                "Name": "dummy_secret",
                "Description": "Dummy Secret",
                "LastChangedDate": "2022-08-01T10:00:00+00:00",
                "LastAccessedDate": "2022-08-02T02:00:00+00:00",
                "Tags": [],
                "VersionIdsToStages": {"12345678-1234-abcd-1234-567890abcdef": ["AWSCURRENT"]},
                "CreatedDate": "2022-08-01T10:00:00+00:00",
            }
        )

    actual_response = MungeKeySecretArnValidator().execute(munge_key_secret_arn, region)
    assert_failure_messages(actual_response, expected_response)
    assert_failure_level(actual_response, expected_failure_level)
