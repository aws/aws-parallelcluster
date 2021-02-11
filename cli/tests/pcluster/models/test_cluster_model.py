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

from typing import List

from assertpy import assert_that

from pcluster.models.cluster import Resource
from pcluster.validators.common import FailureLevel, Validator


class FakeInfoValidator(Validator):
    """Dummy validator of info level."""

    def _validate(self, param):
        self._add_failure(f"Wrong value {param}.", FailureLevel.INFO)


class FakeErrorValidator(Validator):
    """Dummy validator of error level."""

    def _validate(self, param):
        self._add_failure(f"Error {param}.", FailureLevel.ERROR)


class FakeComplexValidator(Validator):
    """Dummy validator requiring multiple parameters as input."""

    def _validate(self, fake_attribute, other_attribute):
        self._add_failure(f"Combination {fake_attribute} - {other_attribute}.", FailureLevel.WARNING)


class FakePropertyValidator(Validator):
    """Dummy property validator of info level."""

    def _validate(self, property_value: str):
        self._add_failure(f"Wrong value {property_value}.", FailureLevel.INFO)


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
            self.fake_attribute = "fake-value"
            self.other_attribute = "other-value"

        def _register_validators(self):
            self._add_validator(FakeErrorValidator, priority=10, param=self.fake_attribute)
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
    _assert_validation_result(validation_failures[0], FailureLevel.ERROR, "Error fake-value.")
    _assert_validation_result(validation_failures[1], FailureLevel.WARNING, "Combination fake-value - other-value.")
    _assert_validation_result(validation_failures[2], FailureLevel.INFO, "Wrong value other-value.")


def test_dynamic_property_validate():
    """Verify that validators of dynamic parameters are working as expected."""

    class FakeResource(Resource):
        """Fake resource class to test validators."""

        def __init__(self):
            super().__init__()
            self.deps_value = ""

        def _register_validators(self):
            self._add_validator(FakePropertyValidator, property_value=self.dynamic_attribute)

        @property
        def dynamic_attribute(self):
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


def test_nested_resource_validate():
    """Verify that validators of nested resources are executed correctly."""

    class FakeNestedResource(Resource):
        """Fake nested resource class to test validators."""

        def __init__(self, fake_value):
            super().__init__()
            self.fake_attribute = fake_value

        def _register_validators(self):
            self._add_validator(FakeErrorValidator, param=self.fake_attribute)

    class FakeParentResource(Resource):
        """Fake resource class to test validators."""

        def __init__(self, nested_resource: FakeNestedResource, list_of_resources: List[FakeNestedResource]):
            super().__init__()
            self.fake_resource = nested_resource
            self.other_attribute = "other-value"
            self.list_of_resources = list_of_resources

        def _register_validators(self):
            self._add_validator(FakeInfoValidator, param=self.other_attribute)

    fake_resource = FakeParentResource(FakeNestedResource("value1"), [FakeNestedResource("value2")])
    validation_failures = fake_resource.validate()

    # Verify children failures are executed first
    _assert_validation_result(validation_failures[0], FailureLevel.ERROR, "Error value1.")
    _assert_validation_result(validation_failures[1], FailureLevel.ERROR, "Error value2.")
    _assert_validation_result(validation_failures[2], FailureLevel.INFO, "Wrong value other-value.")
