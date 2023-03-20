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

from enum import Enum

from pcluster.validators.common import FailureLevel, Validator

# SLURM SETTINGS are case-insensitive - keep them lowercase since they are compared with setting.lower()
SLURM_SETTINGS_DENY_LIST = {
    "Queue": ["nodes", "partitionname", "resumetimeout", "state", "suspendtime"],
    "ComputeResource": ["cpus", "features", "gres", "nodeaddr", "nodehostname", "nodename", "state"],
}


class SlurmCustomSettingLevel(str, Enum):
    """
    Slurm Custom Settings level.

    This enum defines the scope where the custom settings are defined.
    """

    QUEUE = "Queue"
    COMPUTE_RESOURCE = "ComputeResource"


class SlurmCustomSettingsValidator(Validator):
    """
    Slurm Custom Settings validator.

    Validate custom settings in Slurm ComputeResource and Queue.
    """

    def _validate(self, custom_settings, deny_list, settings_level: SlurmCustomSettingLevel):
        denied_settings = set()

        for custom_setting in list(custom_settings.keys()):
            if custom_setting.lower() in deny_list:
                denied_settings.add(custom_setting)
        if len(denied_settings) > 0:
            settings = ",".join(sorted(denied_settings))
            self._add_failure(
                f"Using the following custom Slurm settings at {settings_level} level is not allowed: {settings}",
                FailureLevel.ERROR,
            )


class SlurmCustomSettingsWarning(Validator):
    """
    Slurm Custom Settings Warning.

    This validator emits a warning message if custom settings are enabled.
    The message is displayed only once no matter how many times instances of the validator are created.
    """

    signaled = False

    def _validate(self):
        if not SlurmCustomSettingsWarning.signaled:
            self._add_failure(
                "Custom Slurm settings are in use: please monitor the cluster carefully.",
                FailureLevel.WARNING,
            )
            SlurmCustomSettingsWarning.signaled = True
