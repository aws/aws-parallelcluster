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
#
# This module contains all the classes representing the Resources objects.
# These objects are obtained from the configuration file through a conversion based on the Schema classes.
#

from abc import ABC, abstractmethod
from enum import Enum


class FailureLevel(Enum):
    """Validation failure level."""

    ERROR = 40
    WARNING = 30
    INFO = 20


class ValidationResult:
    """Represent the result of the validation."""

    def __init__(self, message: str, level: FailureLevel):
        self.message = message
        self.level = level


class ConfigValidationError(Exception):
    """Configuration file validation error."""

    def __init__(self, validation_result: ValidationResult):
        message = f"{validation_result.level.name}: {validation_result.message}"
        super().__init__(message)


class Validator(ABC):
    """Abstract validator. The children must implement the validate method."""

    def __init__(self, raise_on_error=False):
        self._failures = []
        self._raise_on_error = raise_on_error

    def _add_failure(self, message: str, level: FailureLevel):
        result = ValidationResult(message, level)
        if self._raise_on_error:
            raise ConfigValidationError(result)
        self._failures.append(result)

    def execute(self, *arg, **kwargs):
        """Entry point of all validators to verify all input params are valid."""
        self._validate(*arg, **kwargs)
        return self._failures

    @abstractmethod
    def _validate(self, *args, **kwargs):
        """Must be implemented with specific validation logic."""
        pass
