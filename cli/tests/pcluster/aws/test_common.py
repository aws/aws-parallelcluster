# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from assertpy import assert_that
from botocore.exceptions import ClientError

from pcluster.aws.common import AWSExceptionHandler

RETRYABLE_ERROR_CODE = "WhateverRetryableErrorCode"
NON_RETRYABLE_ERROR_CODE = "WhateverNonRetryableErrorCode"

MOCKED_RETRY_DELAY_SECONDS = 3.5


@pytest.fixture(autouse=True)
def mocked_sleep(mocker):
    """Keep the retry back-off out of the test runtime."""
    return mocker.patch("pcluster.aws.common.time.sleep")


@pytest.fixture()
def mocked_compute_retry_delay(mocker):
    return mocker.patch("pcluster.utils.compute_retry_delay", return_value=MOCKED_RETRY_DELAY_SECONDS)


def _client_error(error_code):
    return ClientError({"Error": {"Code": error_code, "Message": "message"}}, "SomeOperation")


def _retried_call(mocker, side_effect, **retry_kwargs):
    boto3_call = mocker.MagicMock(__name__="boto3_call", side_effect=side_effect)
    return AWSExceptionHandler.retry_on_boto3_error_codes({RETRYABLE_ERROR_CODE}, **retry_kwargs)(boto3_call)


@pytest.mark.parametrize(
    "error_codes, max_attempts, expected_calls, expected_error_code",
    [
        pytest.param([], 5, 1, None, id="successful call is not retried"),
        pytest.param(
            [NON_RETRYABLE_ERROR_CODE], 5, 1, NON_RETRYABLE_ERROR_CODE, id="other error codes are not retried"
        ),
        pytest.param([RETRYABLE_ERROR_CODE] * 2, 5, 3, None, id="retryable error is reissued until it succeeds"),
        pytest.param([RETRYABLE_ERROR_CODE] * 6, 5, 5, RETRYABLE_ERROR_CODE, id="retries are capped by max_attempts"),
        pytest.param(
            [RETRYABLE_ERROR_CODE, RETRYABLE_ERROR_CODE, NON_RETRYABLE_ERROR_CODE],
            5,
            3,
            NON_RETRYABLE_ERROR_CODE,
            id="retries stop as soon as an error code is not retryable",
        ),
    ],
)
def test_retry_on_boto3_error_codes(
    mocker, mocked_sleep, mocked_compute_retry_delay, error_codes, max_attempts, expected_calls, expected_error_code
):
    """Only the calls failing with one of the given error codes are reissued, up to max_attempts times."""
    side_effect = [_client_error(error_code) for error_code in error_codes] + ["response"]
    retried_call = _retried_call(mocker, side_effect, max_attempts=max_attempts)

    if expected_error_code:
        with pytest.raises(ClientError) as exc_info:
            retried_call()
        # The original boto3 error is propagated, so that callers can still inspect its error code.
        assert_that(exc_info.value.response["Error"]["Code"]).is_equal_to(expected_error_code)
    else:
        assert_that(retried_call()).is_equal_to("response")

    assert_that(retried_call.__wrapped__.call_count).is_equal_to(expected_calls)
    # Every attempt but the first one is preceded by a wait of the computed back-off delay.
    assert_that(mocked_sleep.call_args_list).is_equal_to(
        [mocker.call(MOCKED_RETRY_DELAY_SECONDS)] * (expected_calls - 1)
    )
