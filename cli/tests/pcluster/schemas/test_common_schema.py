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

from pcluster.schemas.common_schema import ImdsSchema, validate_json_format


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
