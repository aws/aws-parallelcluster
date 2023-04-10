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
from assertpy import assert_that
from marshmallow import ValidationError

from pcluster.config.common import BaseTag
from pcluster.constants import PCLUSTER_PREFIX
from pcluster.schemas.common_schema import (
    ImdsSchema,
    LambdaFunctionsVpcConfigSchema,
    validate_json_format,
    validate_no_duplicate_tag,
    validate_no_reserved_tag,
)


@pytest.mark.parametrize(
    "data, expected_value",
    [
        ('{"cluster": {"scheduler_slots": "cores"}}', True),
        ('{"cluster"}: {"scheduler_slots": "cores"}}', False),
    ],
)
def test_validate_json_format(data, expected_value):
    assert_that(validate_json_format(data)).is_equal_to(expected_value)


@pytest.mark.parametrize(
    "imds_support, failure_message",
    [
        ("unsupportedValue", "Must be one of"),
        ("v1.0", None),
        ("v2.0", None),
    ],
)
def test_imds_schema(imds_support, failure_message):
    imds_schema = {}

    if imds_support:
        imds_schema["ImdsSupport"] = imds_support

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            ImdsSchema().load(imds_schema)
    else:
        imds = ImdsSchema().load(imds_schema)
        assert_that(imds.imds_support).is_equal_to(imds_support)


@pytest.mark.parametrize(
    "lambda_functions_vpc_config, failure_message",
    [
        ({"SubnetIds": ["subnet-8e482ce8"], "SecurityGroupIds": ["sg-028d73ae220157d96"]}, None),
        ({"SubnetIds": ["subnet-8e482ce8"], "SecurityGroupIds": []}, "Length must be between"),
        ({"SubnetIds": [], "SecurityGroupIds": ["sg-028d73ae220157d96"]}, "Length must be between"),
        (
            {"SubnetIds": ["subnet-8e482ce8"], "SecurityGroupIds": [f"sg-028d73ae220157d9{i}" for i in range(7)]},
            "Length must be between",
        ),
        (
            {"SubnetIds": [f"subnet-8e482c{i}" for i in range(10, 27)], "SecurityGroupIds": ["sg-028d73ae220157d96"]},
            "Length must be between",
        ),
        (
            {"SubnetIds": ["invalid"], "SecurityGroupIds": ["sg-028d73ae220157d96"]},
            "String does not match expected pattern.",
        ),
        (
            {"SubnetIds": ["subnet-8e482ce8"], "SecurityGroupIds": ["invalid"]},
            "String does not match expected pattern.",
        ),
        ({}, "Missing data for required field"),
        ({"SecurityGroupIds": []}, "Missing data for required field"),
        ({"SubnetIds": ["subnet-8e482ce8"]}, "Missing data for required field"),
    ],
)
def test_lambda_functions_vpc_config_schema(lambda_functions_vpc_config, failure_message):
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            LambdaFunctionsVpcConfigSchema().load(lambda_functions_vpc_config)
    else:
        config = LambdaFunctionsVpcConfigSchema().load(lambda_functions_vpc_config)
        assert_that(config.security_group_ids).is_equal_to(lambda_functions_vpc_config.get("SecurityGroupIds"))
        assert_that(config.subnet_ids).is_equal_to(lambda_functions_vpc_config.get("SubnetIds"))


@pytest.mark.parametrize(
    "tags, failure_message",
    [
        ([], None),
        ([BaseTag(key="test", value="test")], None),
        ([BaseTag(key=f"{PCLUSTER_PREFIX}test", value="test")], f"The tag key prefix '{PCLUSTER_PREFIX}' is reserved"),
        ([BaseTag(key=f"test{PCLUSTER_PREFIX}", value="test")], None),
        ([{"key": "test", "value": "test"}], None),
        ([{"key": f"{PCLUSTER_PREFIX}test", "value": "test"}], f"The tag key prefix '{PCLUSTER_PREFIX}' is reserved"),
        ([{"key": f"test{PCLUSTER_PREFIX}", "value": "test"}], None),
        ([{"key": "test"}], None),
    ],
)
def test_validate_no_reserved_tag(tags, failure_message):
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            validate_no_reserved_tag(tags)
    else:
        validate_no_reserved_tag(tags)


@pytest.mark.parametrize(
    "tags, failure_message",
    [
        ([BaseTag(key="test1", value="test"), BaseTag(key="test2", value="test")], None),
        (
            [BaseTag(key="test1", value="test"), BaseTag(key="test1", value="test")],
            "Duplicate tag key \\(test1\\) detected. Tags keys should be unique within the Tags section.",
        ),
    ],
)
def test_validate_no_duplicate_tag(tags, failure_message):
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            validate_no_duplicate_tag(tags)
    else:
        validate_no_duplicate_tag(tags)
