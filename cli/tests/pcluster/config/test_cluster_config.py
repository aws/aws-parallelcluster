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

from pcluster.config.cluster_config import Config
from pcluster.validators.common import FailureLevel, Validator


class FakeInfoValidator(Validator):
    """Dummy validator of info level."""

    def __call__(self, value: str):
        self._add_failure(f"Wrong value {value}.", FailureLevel.INFO)
        return self._failures


class FakeCriticalValidator(Validator):
    """Dummy validator of critical level."""

    def __call__(self, value: str):
        self._add_failure(f"Critical error {value}.", FailureLevel.CRITICAL)
        return self._failures


class FakeComplexValidator(Validator):
    """Dummy validator requiring multiple parameters as input."""

    def __call__(self, fake_attribute: str, other_attribute: str):
        self._add_failure(f"Combination {fake_attribute} - {other_attribute}.", FailureLevel.WARNING)
        return self._failures


def _assert_validation_result(result, expected_level, expected_message):
    """Assert that validation results is the expected one, by checking level and message."""
    assert_that(result.level).is_equal_to(expected_level)
    assert_that(result.message).contains(expected_message)


def test_config_validate():
    """Verify that validators are executed in the right order according to priorities with the expected params."""

    class FakeConfig(Config):
        """Fake configuration class to test validators."""

        def __init__(self):
            super().__init__()
            self.fake_attribute = "fake-value"
            self.other_attribute = "other-value"
            self._register_validator(FakeCriticalValidator, priority=10, value=self.fake_attribute)
            self._register_validator(FakeInfoValidator, priority=2, value=self.other_attribute)
            self._register_validator(
                FakeComplexValidator,
                priority=5,
                fake_attribute=self.fake_attribute,
                other_attribute=self.other_attribute,
            )

    fake_config = FakeConfig()
    validation_failures = fake_config.validate()

    # Verify high prio is the first of the list
    _assert_validation_result(validation_failures[0], FailureLevel.CRITICAL, "Critical error fake-value.")
    _assert_validation_result(validation_failures[1], FailureLevel.WARNING, "Combination fake-value - other-value.")
    _assert_validation_result(validation_failures[2], FailureLevel.INFO, "Wrong value other-value.")
