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

from assertpy import assert_that

from pcluster.models.cluster import Resource
from pcluster.models.param import DynamicParam, Param
from pcluster.validators.common import FailureLevel, Validator


class FakeInfoValidator(Validator):
    """Dummy validator of info level."""

    def validate(self, param: Param):
        self._add_failure(f"Wrong value {param.value}.", FailureLevel.INFO)
        return self._failures


class FakeCriticalValidator(Validator):
    """Dummy validator of critical level."""

    def validate(self, param: Param):
        self._add_failure(f"Critical error {param.value}.", FailureLevel.CRITICAL)
        return self._failures


class FakeComplexValidator(Validator):
    """Dummy validator requiring multiple parameters as input."""

    def validate(self, fake_attribute: Param, other_attribute: Param):
        self._add_failure(f"Combination {fake_attribute.value} - {other_attribute.value}.", FailureLevel.WARNING)
        return self._failures


def _assert_validation_result(result, expected_level, expected_message):
    """Assert that validation results is the expected one, by checking level and message."""
    assert_that(result.level).is_equal_to(expected_level)
    assert_that(result.message).contains(expected_message)


def test_resource_validate():
    """Verify that validators are executed in the right order according to priorities with the expected params."""

    class FakeResource(Resource):
        """Fake resource class to test validators."""

        def __init__(self):
            super().__init__()
            self.fake_attribute = Param("fake-value")
            self.other_attribute = Param("other-value")
            self._add_validator(FakeCriticalValidator, priority=10, param=self.fake_attribute)
            self._add_validator(FakeInfoValidator, priority=2, param=self.other_attribute)
            self._add_validator(
                FakeComplexValidator,
                priority=5,
                fake_attribute=self.fake_attribute,
                other_attribute=self.other_attribute,
            )

    fake_resource = FakeResource()
    validation_failures = fake_resource.validate()

    # Verify high prio is the first of the list
    _assert_validation_result(validation_failures[0], FailureLevel.CRITICAL, "Critical error fake-value.")
    _assert_validation_result(validation_failures[1], FailureLevel.WARNING, "Combination fake-value - other-value.")
    _assert_validation_result(validation_failures[2], FailureLevel.INFO, "Wrong value other-value.")


def test_dynamic_property_validate():
    """Verify that validators of dynamic parameters are working as expected."""

    class FakeResource(Resource):
        """Fake resource class to test validators."""

        def __init__(self):
            super().__init__()
            self.dynamic_attribute = DynamicParam(value_calculator=self._fetch_dynamic_param)
            self.deps_value = ""
            self._add_validator(FakeInfoValidator, param=self.dynamic_attribute)

        def _fetch_dynamic_param(self):
            return f"dynamic-value: {self.deps_value}"

    fake_resource = FakeResource()
    validation_failures = fake_resource.validate()
    _assert_validation_result(
        validation_failures[0], FailureLevel.INFO, f"Wrong value dynamic-value: {fake_resource.deps_value}."
    )

    fake_resource.deps_value = "test1"
    validation_failures = fake_resource.validate()
    _assert_validation_result(
        validation_failures[0], FailureLevel.INFO, f"Wrong value dynamic-value: {fake_resource.deps_value}."
    )

    fake_resource.deps_value = "test2"
    validation_failures = fake_resource.validate()
    _assert_validation_result(
        validation_failures[0], FailureLevel.INFO, f"Wrong value dynamic-value: {fake_resource.deps_value}."
    )
