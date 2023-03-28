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
import asyncio
from typing import List

import pytest
from assertpy import assert_that

from pcluster.config.common import Resource
from pcluster.validators.common import AsyncValidator, FailureLevel, Validator, ValidatorContext


class FakeInfoValidator(Validator):
    """Dummy validator of info level."""

    def _validate(self, param):
        self._add_failure(f"Wrong value {param}.", FailureLevel.INFO)


class FakeErrorValidator(Validator):
    """Dummy validator of error level."""

    def _validate(self, param):
        self._add_failure(f"Error {param}.", FailureLevel.ERROR)


class FakeAsyncInfoValidator(AsyncValidator):
    """Dummy validator of info level."""

    async def _validate_async(self, param):
        await asyncio.sleep(0.2)
        self._add_failure(f"Wrong async value {param}.", FailureLevel.INFO)


class FakeAsyncErrorValidator(AsyncValidator):
    """Dummy validator of error level."""

    async def _validate_async(self, param):
        await asyncio.sleep(0.5)
        self._add_failure(f"Error async {param}.", FailureLevel.ERROR)
        pass


class FakeComplexValidator(Validator):
    """Dummy validator requiring multiple parameters as input."""

    def _validate(self, fake_attribute, other_attribute):
        self._add_failure(f"Combination {fake_attribute} - {other_attribute}.", FailureLevel.WARNING)


class FakePropertyValidator(Validator):
    """Dummy property validator of info level."""

    def _validate(self, property_value: str):
        self._add_failure(f"Wrong value {property_value}.", FailureLevel.INFO)


class FakeFaultyValidator(Validator):
    """Dummy validator that raises an unexpected error."""

    def _validate(self, param: str):
        raise RuntimeError("dummy fault")


def assert_validation_result(result, expected_level, expected_message):
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

        def _register_validators(self, context: ValidatorContext = None):
            self._register_validator(FakeErrorValidator, param=self.fake_attribute)
            self._register_validator(
                FakeComplexValidator,
                fake_attribute=self.fake_attribute,
                other_attribute=self.other_attribute,
            )
            self._register_validator(FakeInfoValidator, param=self.other_attribute)

    fake_resource = FakeResource()
    validation_failures = fake_resource.validate()

    # Verify high prio is the first of the list
    assert_validation_result(validation_failures[0], FailureLevel.ERROR, "Error fake-value.")
    assert_validation_result(validation_failures[1], FailureLevel.WARNING, "Combination fake-value - other-value.")
    assert_validation_result(validation_failures[2], FailureLevel.INFO, "Wrong value other-value.")


def test_resource_validate_unexpected_error():
    """Verify that an unexpected error thrown by a validator does not interrupt the validation process."""

    class FakeResource(Resource):
        """Fake resource class to test validators."""

        def __init__(self):
            super().__init__()
            self.fake_attribute = "fake-value"
            self.other_attribute = "other-value"

        def _register_validators(self, context: ValidatorContext = None):
            self._register_validator(FakeErrorValidator, param=self.fake_attribute)
            self._register_validator(FakeFaultyValidator, param=self.fake_attribute)
            self._register_validator(FakeInfoValidator, param=self.other_attribute)

    fake_resource = FakeResource()
    validation_failures = fake_resource.validate()

    # Verify high prio is the first of the list
    assert_validation_result(validation_failures[0], FailureLevel.ERROR, "Error fake-value.")
    assert_validation_result(validation_failures[1], FailureLevel.ERROR, "dummy fault")
    assert_validation_result(validation_failures[2], FailureLevel.INFO, "Wrong value other-value.")


def test_async_resource_validation():
    """Verify that sync and async validators are executed in the right order according to priorities."""

    class FakeResource(Resource):
        """Fake resource class to test validators."""

        def __init__(self):
            super().__init__()
            self.fake_attribute = "fake-value"
            self.other_attribute = "other-value"

        def _register_validators(self, context: ValidatorContext = None):
            self._register_validator(FakeErrorValidator, param=self.fake_attribute)
            self._register_validator(FakeInfoValidator, param=self.other_attribute)
            self._register_validator(FakeAsyncErrorValidator, param=self.fake_attribute)
            self._register_validator(FakeAsyncInfoValidator, param=self.other_attribute)

    fake_resource = FakeResource()
    validation_failures = fake_resource.validate()

    assert_validation_result(validation_failures[0], FailureLevel.ERROR, "Error fake-value.")
    assert_validation_result(validation_failures[1], FailureLevel.INFO, "Wrong value other-value.")
    assert_validation_result(validation_failures[2], FailureLevel.ERROR, "Error async fake-value.")
    assert_validation_result(validation_failures[3], FailureLevel.INFO, "Wrong async value other-value.")


def test_dynamic_property_validate():
    """Verify that validators of dynamic parameters are working as expected."""

    class FakeResource(Resource):
        """Fake resource class to test validators."""

        def __init__(self):
            super().__init__()
            self.deps_value = ""

        def _register_validators(self, context: ValidatorContext = None):
            self._register_validator(FakePropertyValidator, property_value=self.dynamic_attribute)

        @property
        def dynamic_attribute(self):
            return f"dynamic-value: {self.deps_value}"

    fake_resource = FakeResource()
    validation_failures = fake_resource.validate()
    assert_validation_result(
        validation_failures[0], FailureLevel.INFO, f"Wrong value dynamic-value: {fake_resource.deps_value}."
    )

    fake_resource.deps_value = "test1"
    validation_failures = fake_resource.validate()
    assert_validation_result(
        validation_failures[0], FailureLevel.INFO, f"Wrong value dynamic-value: {fake_resource.deps_value}."
    )

    fake_resource.deps_value = "test2"
    validation_failures = fake_resource.validate()
    assert_validation_result(
        validation_failures[0], FailureLevel.INFO, f"Wrong value dynamic-value: {fake_resource.deps_value}."
    )


def test_nested_resource_validate():
    """Verify that validators of nested resources are executed correctly."""

    class FakeNestedResource(Resource):
        """Fake nested resource class to test validators."""

        def __init__(self, fake_value):
            super().__init__()
            self.fake_attribute = fake_value

        def _register_validators(self, context: ValidatorContext = None):
            self._register_validator(FakeErrorValidator, param=self.fake_attribute)

    class FakeParentResource(Resource):
        """Fake resource class to test validators."""

        def __init__(self, nested_resource: FakeNestedResource, list_of_resources: List[FakeNestedResource]):
            super().__init__()
            self.fake_resource = nested_resource
            self.other_attribute = "other-value"
            self.list_of_resources = list_of_resources

        def _register_validators(self, context: ValidatorContext = None):
            self._register_validator(FakeInfoValidator, param=self.other_attribute)

    fake_resource = FakeParentResource(FakeNestedResource("value1"), [FakeNestedResource("value2")])
    validation_failures = fake_resource.validate()

    # Verify children failures are executed first
    assert_validation_result(validation_failures[0], FailureLevel.ERROR, "Error value1.")
    assert_validation_result(validation_failures[1], FailureLevel.ERROR, "Error value2.")
    assert_validation_result(validation_failures[2], FailureLevel.INFO, "Wrong value other-value.")


@pytest.mark.parametrize(
    "value, default, expected_value, expected_implied",
    [
        ("abc", "default_value", "abc", False),
        (None, "default_value", "default_value", True),
        (5, 10, 5, False),
        (None, 10, 10, True),
    ],
)
def test_resource_params(value, default, expected_value, expected_implied):
    class TestBaseBaseResource(Resource):
        def __init__(self):
            super().__init__()

    class TestBaseResource(TestBaseBaseResource):
        def __init__(self):
            super().__init__()

    class TestResource(TestBaseResource):
        def __init__(self):
            super().__init__()
            self.test_attr = Resource.init_param(value=value, default=default)

    test_resource = TestResource()
    assert_that(test_resource.test_attr).is_equal_to(expected_value)
    assert_that(test_resource.is_implied("test_attr")).is_equal_to(expected_implied)

    param = test_resource.get_param("test_attr")
    assert_that(param).is_not_none()
    assert_that(param.value).is_equal_to(expected_value)
    assert_that(param.default).is_equal_to(default)

    test_resource.test_attr = "new_value"
    assert_that(test_resource.is_implied("test_attr")).is_false()

    param = test_resource.get_param("test_attr")
    assert_that(param).is_not_none()
    assert_that(param.value).is_equal_to("new_value")
    assert_that(param.default).is_equal_to(default)
