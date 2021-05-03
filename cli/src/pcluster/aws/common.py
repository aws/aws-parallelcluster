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

import functools
import logging
from abc import ABC
from enum import Enum

import boto3
from botocore.exceptions import BotoCoreError, ClientError, ParamValidationError

LOGGER = logging.getLogger(__name__)


class AWSClientError(Exception):
    """Error during execution of some AWS calls."""

    class ErrorCode(Enum):
        """Error codes for AWS ClientError."""

        VALIDATION_ERROR = "ValidationError"
        REQUEST_LIMIT_EXCEEDED = "RequestLimitExceeded"
        THROTTLING_EXCEPTION = "ThrottlingException"

        @classmethod
        def throttling_error_codes(cls):
            """Return a set of error codes returned when service rate limits are exceeded."""
            return {cls.REQUEST_LIMIT_EXCEEDED.value, cls.THROTTLING_EXCEPTION.value}

    def __init__(self, function_name: str, message: str, error_code: str = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.function_name = function_name


class ImageNotFoundError(AWSClientError):
    """Error during describe image if image is not found."""

    def __init__(self, function_name: str):
        super().__init__(function_name=function_name, message="No image matching the search criteria found")


class StackNotFoundError(AWSClientError):
    """Error during describe stack if stack is not found."""

    def __init__(self, function_name: str, stack_name: str):
        super().__init__(function_name=function_name, message=f"Stack with id {stack_name} does not exist")


class AWSExceptionHandler:
    """AWS Exception handler."""

    @staticmethod
    def handle_client_exception(func):
        """Handle Boto3 errors, can be used as a decorator."""

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ParamValidationError as validation_error:
                error = AWSClientError(
                    func.__name__,
                    "Error validating parameter. Failed with exception: {0}".format(str(validation_error)),
                )
            except BotoCoreError as e:
                error = AWSClientError(func.__name__, str(e))
            except ClientError as e:
                # add request id
                error = AWSClientError(func.__name__, e.response["Error"]["Message"], e.response["Error"]["Code"])
            LOGGER.error("Encountered error when performing boto3 call in %s: %s", error.function_name, error.message)
            raise error

        return wrapper


class Boto3Client(ABC):
    """Abstract Boto3 client."""

    def __init__(self, client_name: str):
        self._client = boto3.client(client_name)

    def _paginate_results(self, method, **kwargs):
        """
        Return a generator for a boto3 call, this allows pagination over an arbitrary number of responses.

        :param method: boto3 method
        :param kwargs: arguments to method
        :return: generator with boto3 results
        """
        paginator = self._client.get_paginator(method.__name__)
        for page in paginator.paginate(**kwargs).result_key_iters():
            for result in page:
                yield result


class Boto3Resource(ABC):
    """Abstract Boto3 resource."""

    def __init__(self, resource_name: str):
        self._resource = boto3.resource(resource_name)
