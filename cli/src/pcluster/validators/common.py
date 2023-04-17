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
import asyncio
import functools
from abc import ABC, abstractmethod
from enum import Enum
from typing import List

ASYNC_TIMED_VALIDATORS_DEFAULT_TIMEOUT_SEC = 10


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
    """Abstract validator. The children must implement the _validate method."""

    def __init__(self):
        self._failures = []

    def _add_failure(self, message: str, level: FailureLevel):
        result = ValidationResult(message, level, self.type)
        self._failures.append(result)

    @property
    def type(self):
        """Identify the type of validator."""
        return self.__class__.__name__

    def execute(self, *arg, **kwargs) -> List[ValidationResult]:
        """Entry point of all validators to verify all input params are valid."""
        self._validate(*arg, **kwargs)
        return self._failures

    @abstractmethod
    def _validate(self, *args, **kwargs):
        """
        Must be implemented with specific validation logic.

        Use _add_failure to add failures to the list of failures returned by execute.
        """
        pass


class AsyncValidator(Validator):
    """Abstract validator that supports *also* async execution. Children must implement the _validate_async method."""

    def __init__(self):
        super().__init__()

    def _validate(self, *arg, **kwargs):
        asyncio.get_event_loop().run_until_complete(self._validate_async(*arg, **kwargs))
        return self._failures

    async def execute_async(self, *arg, **kwargs) -> List[ValidationResult]:
        """Entry point of all async validators to verify all input params are valid."""
        await self._validate_async(*arg, **kwargs)
        return self._failures

    @abstractmethod
    async def _validate_async(self, *args, **kwargs):
        """
        Must be implemented with specific validation logic.

        Use _add_failure to add failures to the list of failures returned by execute or execute_async when awaited.
        """
        pass


def get_async_timed_validator_type_for(validator_type: type) -> AsyncValidator:
    """
    Return the type decorating the given validator with timeout support.

    The enriched _validate_async will accept an additional timeout parameter.
    If not provided will default to ASYNC_TIMED_VALIDATORS_DEFAULT_TIMEOUT_SEC.

    Since validators async execution is coroutine based with preemptive multitasking,
    the effective time to fail the validator for timeout may exceed the requested one.
    """
    class_name = f"AsyncTimed{validator_type.__name__}"

    if class_name not in globals():
        class_bases = validator_type.__bases__
        class_dict = dict(validator_type.__dict__)

        def _async_timed_validate(original_method):
            @functools.wraps(original_method)
            async def _validate_async(self: AsyncValidator, *args, **kwargs):
                timeout = kwargs.pop("timeout", ASYNC_TIMED_VALIDATORS_DEFAULT_TIMEOUT_SEC)
                try:
                    await asyncio.wait_for(original_method(self, *args, **kwargs), timeout=timeout)
                except asyncio.TimeoutError:
                    self._add_failure(  # pylint: disable=protected-access
                        f"Validation of ({kwargs}) timed out after {timeout} seconds.", FailureLevel.WARNING
                    )

            return _validate_async

        class_dict["_validate_async"] = _async_timed_validate(class_dict["_validate_async"])

        schema_class_type = type(class_name, class_bases, class_dict)
        globals()[class_name] = schema_class_type
    else:
        schema_class_type = globals()[class_name]
    return schema_class_type


class ValidatorContext:
    """Context containing information about cluster environment meant to be passed to validators."""

    def __init__(self, head_node_instance_id: str = None, during_update: bool = None):
        self.head_node_instance_id = head_node_instance_id
        self.during_update = during_update
