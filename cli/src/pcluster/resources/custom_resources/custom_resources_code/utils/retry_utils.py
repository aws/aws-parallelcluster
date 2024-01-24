# Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with
#  the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import functools
import logging
import time

logger = logging.getLogger(__name__)


def retry(max_retries: int, wait_time_seconds: int):
    """
    Retry the decorated function.

    :param max_retries: maximum number of retries.
                        When reached the inner exception causing the failure is raised.
    :param wait_time_seconds: wait time between retries, in seconds.
    :return: None
    """

    def decorator_retry(func):
        @functools.wraps(func)
        def wrapper_retry(*args, **kwargs):
            retries = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Function {func.__name__} failed: {e}")
                    retries += 1
                    if retries < max_retries:
                        logger.info(f"Function {func.__name__} will be retried after {wait_time_seconds} seconds")
                        time.sleep(wait_time_seconds)
                    else:
                        break

            raise Exception(f"Max retries of function {func} exceeded")

        return wrapper_retry

    return decorator_retry
