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

    INFO = 20
    WARNING = 30
    ERROR = 40

    def __str__(self):
        return str(self.name)


class ValidationResult:
    """Represent the result of the validation."""

    def __init__(self, message: str, level: FailureLevel, validator_type: str):
        self.message = message
        self.level = level
        self.validator_type = validator_type

    def __repr__(self):
        return f"ValidationResult(level={self.level}, message={self.message})"


class Validator(ABC):
    """Abstract validator. The children must implement the validate method."""

    def __init__(self):
        self._failures = []

    def _add_failure(self, message: str, level: FailureLevel):
        result = ValidationResult(message, level, self.type)
        self._failures.append(result)

    @property
    def type(self):
        """Identify the type of validator."""
        return self.__class__.__name__

    def execute(self, *arg, **kwargs):
        """Entry point of all validators to verify all input params are valid."""
        self._validate(*arg, **kwargs)
        return self._failures

    @abstractmethod
    def _validate(self, *args, **kwargs):
        """Must be implemented with specific validation logic."""
        pass


class ValidatorContext:
    """Context containing information about cluster environment meant to be passed to validators."""

    def __init__(self, head_node_instance_id: str = None):
        self.head_node_instance_id = head_node_instance_id
