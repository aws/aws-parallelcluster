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
from typing import Dict, List

from pcluster.validators.common import FailureLevel, Validator

# SLURM SETTINGS are case-insensitive - keep them lowercase since they are compared with setting.lower()
SLURM_SETTINGS_DENY_LIST = {
    "SlurmConf": {
        "Global": [
            "communicationparameters",
            "grestypes",
            "jobcomppass",
            "launchparameters",
            "reconfigflags",
            "resumefailprogram",
            "resumeprogram",
            "resumetimeout",
            "slurmctldhost",
            "slurmctldlogfile",
            "slurmctldparameters",
            "slurmdlogfile",
            "slurmuser",
            "suspendprogram",
            "suspendtime",
            "taskplugin",
            "treewidth",
        ],
        "Accounting": [
            "accountingstoragetype",
            "accountingstoragehost",
            "accountingstorageport",
            "accountingstorageuser",
            "jobacctgathertype",
        ],
    },
    "Queue": {
        "Global": ["nodes", "partitionname", "resumetimeout", "state", "suspendtime"],
    },
    "ComputeResource": {
        "Global": ["cpus", "features", "gres", "nodeaddr", "nodehostname", "nodename", "state"],
    },
}


class CustomSlurmSettingLevel(str, Enum):
    """
    Custom Slurm Settings level.

    This enum defines the scope where the custom settings are defined.
    """

    SLURM_CONF = "SlurmConf"
    QUEUE = "Queue"
    COMPUTE_RESOURCE = "ComputeResource"


class CustomSlurmSettingContext(Enum):
    """
    Custom Slurm Settings context.

    This enum defines the context where the custom settings are relevant (useful for validation purposes only).
    """

    GLOBAL = "Global"
    ACCOUNTING = "Accounting"


class CustomSlurmSettingsValidator(Validator):
    """
    Custom Slurm Settings validator.

    Validate custom settings in Slurm ComputeResource and Queue.
    """

    def _validate(self, custom_settings: List[Dict], deny_list: List[str], settings_level: CustomSlurmSettingLevel):
        denied_settings = set()

        for custom_settings_dict in custom_settings:
            for custom_setting in list(custom_settings_dict.keys()):
                if custom_setting.lower() in deny_list:
                    denied_settings.add(custom_setting)
        if len(denied_settings) > 0:
            settings = ",".join(sorted(denied_settings))
            self._add_failure(
                f"Using the following custom Slurm settings at {settings_level} level is not allowed: {settings}",
                FailureLevel.ERROR,
            )


class CustomSlurmSettingsWarning(Validator):
    """
    Custom Slurm Settings Warning.

    This validator emits a warning message if custom settings are enabled.
    The message is displayed only once no matter how many times instances of the validator are created.
    """

    signaled = False

    def _validate(self):
        if not CustomSlurmSettingsWarning.signaled:
            self._add_failure(
                "Custom Slurm settings are in use: please monitor the cluster carefully.",
                FailureLevel.WARNING,
            )
            CustomSlurmSettingsWarning.signaled = True


class CustomSlurmSettingsIncludeFileOnlyValidator(Validator):
    """
    Custom Slurm Settings Include File Only validator.

    This validator returns an error if the CustomSlurmSettingsIncludeFile configuration parameter
    is used together with the CustomSlurmSettings under SlurmSettings.
    """

    def _validate(self, custom_settings: List[Dict], include_file_url: str):
        if custom_settings and include_file_url:
            self._add_failure(
                "CustomSlurmsettings and CustomSlurmSettingsIncludeFile cannot be used together "
                "under SlurmSettings.",
                FailureLevel.ERROR,
            )
