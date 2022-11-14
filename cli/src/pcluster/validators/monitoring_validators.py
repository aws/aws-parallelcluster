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
from pcluster.validators.common import FailureLevel, Validator


class ComputeConsoleLoggingValidator(Validator):
    """Security groups validator."""

    def _validate(self, monitoring):
        if not monitoring.compute_console_logging_enabled and not monitoring.is_implied(
            "compute_console_logging_max_sample_size"
        ):
            self._add_failure(
                "ComputeConsoleLoggingMaxSampleSize can not be set when setting ComputeConsoleLoggingEnabled is False. "
                "Please either remove ComputeConsoleLoggingMaxSampleSize or set ComputeConsoleLoggingEnabled to True.",
                FailureLevel.ERROR,
            )
