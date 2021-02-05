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

from pcluster.utils import InstanceTypeInfo


def assert_failure_messages(actual_failures, expected_messages):
    """Check failure messages."""
    if expected_messages:
        if isinstance(expected_messages, str):
            expected_messages = [expected_messages]
        for expected_message in expected_messages:
            # Either check the regex of expected_message match actual failure or check the whole strings are equal.
            # This is to deal with strings having regex symbols (e.g. "[") inside
            assert_that(
                any(re.search(expected_message, actual_failure.message) for actual_failure in actual_failures)
                or any(expected_message == actual_failure.message for actual_failure in actual_failures)
            ).is_true()
    else:
        assert_that(actual_failures).is_empty()


def mock_instance_type_info(mocker, instance_type):
    mocker.patch(
        "pcluster.validators.awsbatch_validators.InstanceTypeInfo.init_from_instance_type",
        return_value=InstanceTypeInfo(
            {
                "InstanceType": instance_type,
                "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2},
                "NetworkInfo": {"EfaSupported": False},
            }
        ),
    )
