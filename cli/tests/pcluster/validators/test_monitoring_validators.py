# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import pytest

from pcluster.config.cluster_config import Monitoring
from pcluster.validators.monitoring_validators import ComputeConsoleLoggingValidator
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "monitoring, expected_message",
    [
        (Monitoring(compute_console_logging_enabled=True, compute_console_logging_max_sample_size=50), None),
        (
            Monitoring(
                compute_console_logging_enabled=False,
            ),
            None,
        ),
        (Monitoring(compute_console_logging_max_sample_size=-5), None),
        (Monitoring(compute_console_logging_max_sample_size=100), None),
        (
            Monitoring(compute_console_logging_enabled=False, compute_console_logging_max_sample_size=50),
            "ComputeConsoleLoggingMaxSampleSize can not be set when setting ComputeConsoleLoggingEnabled is False. "
            "Please either remove ComputeConsoleLoggingMaxSampleSize or set ComputeConsoleLoggingEnabled to True.",
        ),
    ],
)
def test_compute_console_logging_validator(monitoring, expected_message):
    actual_failures = ComputeConsoleLoggingValidator().execute(monitoring)
    assert_failure_messages(actual_failures, expected_message)
