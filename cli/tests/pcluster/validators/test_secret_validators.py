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

from pcluster.aws.common import AWSClientError
from pcluster.validators.common import FailureLevel
from pcluster.validators.secret_validators import ArnServiceAndResourceValidator, MungeKeySecretSizeAndBase64Validator
from tests.pcluster.validators.utils import assert_failure_level, assert_failure_messages


@pytest.mark.parametrize(
    "arn, region, expected_service, expected_resource, expected_response",
    [
        (
            "arn:aws:valid_service:us-west-2:123456789012:valid_resource:valid_resource_name",
            "us-west-2",
            "valid_service",
            "valid_resource",
            None,
        ),
        (
            "arn:aws:valid_service:us-west-2:123456789012:invalid_resource:valid_resource_name",
            "us-west-2",
            "valid_service",
            "valid_resource",
            "The arn:aws:valid_service:us-west-2:123456789012:invalid_resource:valid_resource_name "
            "is not supported in region us-west-2.",
        ),
        (
            "arn:aws:invalid_service:us-west-2:123456789012:valid_resource:valid_resource_name",
            "us-west-2",
            "valid_service",
            "valid_resource",
            "The arn:aws:invalid_service:us-west-2:123456789012:valid_resource:valid_resource_name "
            "is not supported in region us-west-2.",
        ),
    ],
)
def test_arn_service_and_resource_validator(
    arn,
    region,
    expected_service,
    expected_resource,
    expected_response,
):
    actual_response = ArnServiceAndResourceValidator().execute(
        arn,
        region,
        expected_service,
        expected_resource,
    )
    assert_failure_messages(actual_response, expected_response)


@pytest.mark.parametrize(
    "munge_key_secret_arn, mock_response, expected_response, error_from_aws_service, expected_failure_level",
    [
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret",
            # In Base64 encoding:
            # - Every 3 bytes of input are represented as 4 characters in the encoded string.
            # - The length of the encoded string must be a multiple of 4.
            # - Valid Base64 characters include upper/lowercase letters,
            #   numbers, '+', '/', and possibly trailing '=' padding chars.
            # - The '=' padding is used if the number of bytes being encoded is not divisible by 3.
            # Given these rules:
            # - "validBase64" is valid because its length is a multiple of 4 and uses valid Base64 characters.
            # - "invalidBase64" is invalid because its length is not a multiple of 4.
            {"SecretString": "validBase641234567890123456789012345678901234567"},
            "",
            None,
            None,
        ),
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret",
            {"SecretString": "validBase64Value"},
            "The size of the decoded munge key in the secret "
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret is 96 bits. "
            "Please use a key with a size between 256 and 8192 bits.",
            None,
            FailureLevel.ERROR,
        ),
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret",
            {"SecretString": "invalidBase641234567890123456789012345678901234567"},
            "The content of the secret "
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret is not a valid Base64 encoded string. "
            "Please refer to the ParallelCluster official documentation for more information.",
            None,
            FailureLevel.ERROR,
        ),
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret",
            {"SecretString": "invalidBase641234567890123456789012345678901234567[]"},
            "The content of the secret "
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret is not a valid Base64 encoded string. "
            "Please refer to the ParallelCluster official documentation for more information.",
            None,
            FailureLevel.ERROR,
        ),
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret",
            {"SecretString": "validBase641234567890123456789012345678901234567"},
            "The secret arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret does not exist.",
            "ResourceNotFoundExceptionSecrets",
            FailureLevel.ERROR,
        ),
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret",
            {"SecretString": "validBase641234567890123456789012345678901234567"},
            "Cannot validate secret arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret due to "
            "lack of permissions. Please refer to ParallelCluster official documentation for more information.",
            "AccessDeniedException",
            FailureLevel.WARNING,
        ),
        (
            "arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret",
            {"SecretString": "validBase641234567890123456789012345678901234567"},
            "Cannot validate secret arn:aws:secretsmanager:us-west-2:123456789012:secret:testSecret. "
            "Please refer to ParallelCluster official documentation for more information.",
            "ANOTHER_ERROR",
            FailureLevel.WARNING,
        ),
    ],
)
def test_munge_key_secret_arn_validator(
    munge_key_secret_arn,
    mock_response,
    expected_response,
    error_from_aws_service,
    expected_failure_level,
    mocker,
):
    # Setting up the mock of secretsmanager
    mocker.patch("boto3.client")

    if error_from_aws_service:
        mocker.patch(
            "pcluster.aws.secretsmanager.SecretsManagerClient.get_secret_value",
            side_effect=AWSClientError(
                function_name="A_FUNCTION_NAME", error_code=str(error_from_aws_service), message="AN_ERROR_MESSAGE"
            ),
        )
    else:
        mocker.patch("pcluster.aws.secretsmanager.SecretsManagerClient.get_secret_value", return_value=mock_response)

    actual_response = MungeKeySecretSizeAndBase64Validator().execute(munge_key_secret_arn)
    assert_failure_messages(actual_response, expected_response)
    assert_failure_level(actual_response, expected_failure_level)
