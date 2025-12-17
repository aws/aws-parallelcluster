# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from pcluster.validators.common import FailureLevel
from pcluster.validators.dev_settings_validators import ExtraChefAttributesValidator
from tests.pcluster.validators.utils import assert_failure_level, assert_failure_messages


@pytest.mark.parametrize(
    "extra_chef_attributes, expected_message, expected_failure_level",
    [
        pytest.param(None, None, None, id="No extra chef attributes"),
        pytest.param('{"other_attribute": "value"}', None, None, id="in_place_update_on_fleet_enabled not set"),
    ],
)
def test_extra_chef_attributes_validator(extra_chef_attributes, expected_message, expected_failure_level):
    actual_failures = ExtraChefAttributesValidator().execute(extra_chef_attributes=extra_chef_attributes)
    assert_failure_messages(actual_failures, expected_message)
    if expected_failure_level:
        assert_failure_level(actual_failures, expected_failure_level)
