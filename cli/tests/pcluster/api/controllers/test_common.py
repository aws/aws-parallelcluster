#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import os

import pytest
from assertpy import assert_that, fail

from pcluster.api.controllers.common import (
    assert_supported_operation,
    configure_aws_region,
    configure_aws_region_from_config,
)
from pcluster.api.errors import BadRequestException
from pcluster.constants import Operation


@pytest.mark.parametrize(
    "region, error",
    [("eu-west-1", None), ("eu-west-", "invalid or unsupported region"), (None, "region needs to be set")],
)
class TestConfigureAwsRegion:
    def test_validate_region_query(self, region, error):
        @configure_aws_region()
        def _decorated_func(region):
            pass

        if error:
            with pytest.raises(BadRequestException) as e:
                _decorated_func(region=region)
            assert_that(str(e.value.content)).contains(error)
        else:
            _decorated_func(region=region)
            assert_that(os.environ["AWS_DEFAULT_REGION"]).is_equal_to(region)

    def test_validate_region_env(self, region, error, set_env, unset_env):
        @configure_aws_region()
        def _decorated_func():
            pass

        if region:
            set_env("AWS_DEFAULT_REGION", region)
        if error:
            with pytest.raises(BadRequestException) as e:
                _decorated_func()
            assert_that(str(e.value.content)).contains(error)
        else:
            _decorated_func()
            assert_that(os.environ["AWS_DEFAULT_REGION"]).is_equal_to(region)


@pytest.mark.parametrize(
    "region, yaml, error",
    [
        ("eu-west-1", "Test: asdf", None),
        (None, "Region: eu-west-1", None),
        ("us-east-1", "Region: us-west-1", "region is set in both parameter and configuration"),
        ("eu-west-", "Test: asdf", "invalid or unsupported region"),
        (None, "Region: us-west-", "invalid or unsupported region"),
        (None, "Test: asdf", "region needs to be set"),
    ],
)
class TestConfigureAwsRegionFromConfig:
    def test_validate_region(self, region, yaml, error, set_env, unset_env):
        expected = "eu-west-1"

        if error:
            with pytest.raises(BadRequestException) as e:
                configure_aws_region_from_config(region, yaml)
            assert_that(str(e.value.content)).contains(error)
        else:
            configure_aws_region_from_config(region, yaml)
            assert_that(os.environ["AWS_DEFAULT_REGION"]).is_equal_to(expected)


def _get_test_assert_supported_operation_parameters():
    parameters = []
    for operation in Operation:
        regions_to_test = ["us-iso-east-1", "us-iso-west-1", "us-isob-east-1", "us-isoWHATEVER", "WHATEVER-ELSE"]
        for region in regions_to_test:
            if operation in [
                Operation.BUILD_IMAGE,
                Operation.DELETE_IMAGE,
                Operation.DESCRIBE_IMAGE,
                Operation.LIST_IMAGES,
                Operation.EXPORT_IMAGE_LOGS,
                Operation.GET_IMAGE_LOG_EVENTS,
                Operation.GET_IMAGE_STACK_EVENTS,
                Operation.LIST_IMAGE_LOG_STREAMS,
            ] and region.startswith("us-iso"):
                expected_support = False
            else:
                expected_support = True
            parameters.append((operation, region, expected_support))
    return parameters


@pytest.mark.parametrize("operation, region, expected_support", _get_test_assert_supported_operation_parameters())
def test_assert_supported_operation(mocker, operation, region, expected_support):
    if expected_support:
        try:
            assert_supported_operation(operation=operation, region=region)
        except Exception as e:
            fail(
                f"assert_supported_operation with operation {operation} and region {region} "
                f"raised an unexpected exception: {e}"
            )
    else:
        with pytest.raises(Exception) as exc:
            assert_supported_operation(operation=operation, region=region)
            assert_that(exc).is_instance_of(BadRequestException)
            assert_that(str(exc.value)).is_equal_to(
                f"The operation '{operation.value}' is not supported in region '{region}'."
            )
