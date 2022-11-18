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
import re

from assertpy import assert_that

from pcluster.validators.common import FailureLevel


def assert_failure_messages(actual_failures, expected_messages):
    """Check failure messages."""
    if expected_messages:
        if isinstance(expected_messages, str):
            expected_messages = [expected_messages]
        for expected_message in expected_messages:
            # Either check the regex of expected_message match actual failure or check the whole strings are equal.
            # This is to deal with strings having regex symbols (e.g. "[") inside
            res = any(re.search(expected_message, actual_failure.message) for actual_failure in actual_failures) or any(
                expected_message == actual_failure.message for actual_failure in actual_failures
            )
            # PyTest truncates the full expected & failure messages if there is an error
            # These print statements ensure the full message is shown in the console if there is an assertion error
            print(f"Expected Message: {expected_message}")
            print(f"Actual Failures: {actual_failures}")
            assert_that(res).is_true()
    else:
        print(actual_failures)
        assert_that(actual_failures).is_empty()


def assert_failure_level(actual_failures, expected_failure_level):
    """Check failure level."""
    if expected_failure_level == FailureLevel.ERROR:
        at_least_one_error = any(actual_failure.level == FailureLevel.ERROR for actual_failure in actual_failures)
        assert_that(at_least_one_error).is_true()
    elif expected_failure_level == FailureLevel.WARNING:
        no_errors = all(actual_failure.level != FailureLevel.ERROR for actual_failure in actual_failures)
        at_least_one_warning = any(actual_failure.level == FailureLevel.WARNING for actual_failure in actual_failures)
        assert_that(no_errors and at_least_one_warning).is_true()
    elif expected_failure_level == FailureLevel.INFO:
        no_errors = all(actual_failure.level != FailureLevel.ERROR for actual_failure in actual_failures)
        no_warnings = all(actual_failure.level != FailureLevel.WARNING for actual_failure in actual_failures)
        at_least_one_info = any(actual_failure.level == FailureLevel.INFO for actual_failure in actual_failures)
        assert_that(no_errors and no_warnings and at_least_one_info).is_true()
    else:
        assert_that(actual_failures).is_empty()
