# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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


class LogRotationValidator(Validator):
    """Log Rotation validator."""

    def _validate(self, log):
        if not log.cloud_watch.enabled and log.rotation.enabled:
            self._add_failure(
                "Cloudwatch Logging is disabled but Log Rotation is enabled. Logs will be rotated and removed from the "
                "cluster once they reach a certain size. If you want to keep logs locally within the cluster, please "
                "set `Monitoring / Logs / Rotation / Enabled` to false.",
                FailureLevel.WARNING,
            )


class DetailedMonitoringValidator(Validator):
    """Detailed Monitoring validator."""

    def _validate(self, is_detailed_monitoring_enabled):
        if is_detailed_monitoring_enabled:
            self._add_failure(
                "Detailed Monitoring is enabled for EC2 instances in your compute fleet. The Amazon EC2 console will "
                "display monitoring graphs with a 1-minute period for these instances. Note that this will increase "
                "the cost. If you want to avoid this and use basic monitoring instead, please set "
                "`Monitoring / DetailedMonitoring` to false.",
                FailureLevel.WARNING,
            )
