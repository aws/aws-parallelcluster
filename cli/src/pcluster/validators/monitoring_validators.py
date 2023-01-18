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
    """Security groups validator."""

    def _validate(self, log):
        if not log.cloud_watch.enabled and log.rotation.enabled:
            self._add_failure(
                "Cloudwatch Logging is disabled but Log Rotation is enabled. Logs will be rotated and removed from the "
                "cluster once they reach a certain size. If you want to keep logs locally within the cluster, please "
                "set `Monitoring / Logs / Rotation / Enabled` to false.",
                FailureLevel.WARNING,
            )
