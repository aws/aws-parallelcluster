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

import operator
from abc import ABC, abstractmethod
from enum import Enum
from typing import List


# ----------------- Params ----------------- #


class Param:
    """Custom class to wrap a value and add more attributes."""

    def __init__(self, value, default=None, valid: bool = True):
        """
        Initialize param by adding internal attributes.

        implied attribute is useful for distinguishing values implied vs specified by a user.
        """
        if value is None and default is not None:
            self.value = default
            self.implied = True
        else:
            self.value = value
            self.implied = False
        self.valid = valid


# ----------------- Validators ----------------- #


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

    def _fail(self, message, level):
        raise ConfigValidationError

    def _add_failure(self, message: str, level: FailureLevel, failed_params: List[Param] = ()):
        result = ValidationResult(message, level)
        for param in failed_params:
            param.valid = False
        if self._raise_on_error:
            raise ConfigValidationError(result)
        self._failures.append(result)

    def execute(self, *arg, **kwargs):
        """Entry point of all validators to verify all input params are valid."""
        for _, param in kwargs.items():
            if isinstance(param, Param):
                if not param.valid:
                    return self._failures
        self._validate(*arg, **kwargs)
        return self._failures

    @abstractmethod
    def _validate(self, *args, **kwargs):
        """Must be implemented with specific validation logic."""
        pass


# ----------------- Resources ----------------- #


class _ResourceValidator(ABC):
    """Represent a generic validator for a resource attribute or object. It's a module private class."""

    def __init__(self, validator_class: Validator, priority: int = 1, **kwargs):
        """Initialize validator. Note: Validators with higher priorities will be executed first."""
        self.validator_class = validator_class
        self.priority = priority
        self.validator_args = kwargs


class Resource(ABC):
    """Represent an abstract Resource entity."""

    def __init__(self):
        self.__validators: List[_ResourceValidator] = []
        self._validation_failures: List[ValidationResult] = []

    def _register_validators(self):
        """
        Register the validators.

        Method to be implemented in Resources. It will be called before executing the validation.
        """
        pass

    def validate(self, raise_on_error=False):
        """Execute registered validators, ordered by priority (high prio --> executed first)."""
        # Cleanup failures
        self._validation_failures.clear()

        # Call validators for nested resources
        for attr, value in self.__dict__.items():
            if isinstance(value, Resource):
                # Validate nested Resources
                self._validation_failures.extend(value.validate())
            if isinstance(value, List) and value:
                # Validate nested lists of Resources
                for item in self.__getattribute__(attr):
                    if isinstance(item, Resource):
                        self._validation_failures.extend(item.validate())

        # Update validators to be executed according to current status of the model and order by priority
        self.__validators.clear()
        self._register_validators()
        self.__validators = sorted(self.__validators, key=operator.attrgetter("priority"), reverse=True)

        # Execute validators and add results in validation_failures array
        for validator in self.__validators:
            # Execute it by passing all the arguments
            self._validation_failures.extend(
                validator.validator_class(raise_on_error=raise_on_error).execute(**validator.validator_args)
            )

        return self._validation_failures

    def _add_validator(self, validator_class: Validator, priority: int = 1, **kwargs):
        """Store validator to be executed at validation execution."""
        self.__validators.append(_ResourceValidator(validator_class, priority=priority, **kwargs))

    def __repr__(self):
        """Return a human readable representation of the Resource object."""
        return "<{name}({attributes})>".format(
            name=self.__class__.__name__,
            attributes=",".join(f"{attr}={value}" for attr, value in self.__dict__.items()),
        )


# ------------ Common resources between ImageBuilder an Cluster models ----------- #


class BaseTag(Resource):
    """Represent the Tag configuration."""

    def __init__(
        self,
        key: str = None,
        value: str = None,
    ):
        super().__init__()
        self.key = Param(key)
        self.value = Param(value)
