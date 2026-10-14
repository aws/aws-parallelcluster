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

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from tests.utils import MockedBoto3Request

BUCKET_NAME = "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete"
REGION = "eu-west-1"
CONFLICTING_OPERATION_ERROR_CODE = "OperationAborted"


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.aws.common.boto3"


@pytest.fixture(autouse=True)
def do_not_sleep_between_retries(mocker):
    """Keep the retry back-off out of the test runtime."""
    mocker.patch("pcluster.aws.common.time.sleep")


def _create_bucket_request(error_code=None):
    return MockedBoto3Request(
        method="create_bucket",
        response="Conflicting operation in progress" if error_code else {},
        expected_params={"Bucket": BUCKET_NAME, "CreateBucketConfiguration": {"LocationConstraint": REGION}},
        generate_error=error_code is not None,
        error_code=error_code,
    )


@pytest.mark.parametrize(
    "error_codes, expected_error_code",
    [
        pytest.param([CONFLICTING_OPERATION_ERROR_CODE] * 2, None, id="aborted call is reissued until it succeeds"),
        pytest.param([CONFLICTING_OPERATION_ERROR_CODE] * 5, CONFLICTING_OPERATION_ERROR_CODE, id="retries are capped"),
        pytest.param(["AccessDenied"], "AccessDenied", id="other errors are not retried"),
    ],
)
def test_create_bucket_retries_on_retryable_errors(boto3_stubber, error_codes, expected_error_code):
    """Only the S3 call that failed with a transient error is reissued."""
    mocked_requests = [_create_bucket_request(error_code=error_code) for error_code in error_codes]
    if not expected_error_code:
        mocked_requests.append(_create_bucket_request())
    # The stubber asserts that every mocked request is consumed, hence that the call is retried exactly as expected.
    boto3_stubber("s3", mocked_requests)

    if expected_error_code:
        with pytest.raises(AWSClientError) as exc_info:
            AWSApi.instance().s3.create_bucket(bucket_name=BUCKET_NAME, region=REGION)
        assert_that(exc_info.value.error_code).is_equal_to(expected_error_code)
    else:
        AWSApi.instance().s3.create_bucket(bucket_name=BUCKET_NAME, region=REGION)
