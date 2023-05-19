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
            "epilog",
            "grestypes",
            "launchparameters",
            "prolog",
            "reconfigflags",
            "resumefailprogram",
            "resumeprogram",
            "resumetimeout",
            "slurmctldhost",
            "slurmctldlogfile",
            "slurmctldparameters",
            "slurmdlogfile",
            "slurmuser",
            "suspendexcnodes",
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
        "Global": ["cpus", "features", "gres", "nodeaddr", "nodehostname", "nodename", "state", "weight"],
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


class CustomSlurmNodeNamesValidator(Validator):
    """
    Custom Slurm Nodelists Names validator.

    This validator ensures that any eventual custom node list passed via SlurmSettings/CustomSlurmSettings
    does not contain the `-st-` or `-dy-` patterns in the node names, as this would cause the ParallelCluster
    daemons to interfere with them.
    """

    def _validate(self, custom_settings: List[Dict]):
        bad_nodelists = []

        for custom_settings_dict in custom_settings:
            # Here we validate also the corner case where users provide `NodeName` multiple times with more than
            # one combination of cases (e.g. `NodeName` and `nodename`)
            nodenames = [custom_settings_dict[key] for key in custom_settings_dict.keys() if key.lower() == "nodename"]
            for nodename in nodenames:
                if ("-st-" in nodename) or ("-dy-" in nodename):
                    bad_nodelists.append(nodename)

        if bad_nodelists:
            nodelists = ", ".join(sorted(bad_nodelists))
            self._add_failure(
                f"Substrings '-st-' and '-dy-' in node names are reserved for nodes managed by ParallelCluster. "
                f"Please rename the following custom Slurm nodes: {nodelists}",
                FailureLevel.ERROR,
            )


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


class SlurmNodePrioritiesWarningValidator(Validator):
    """
    Slurm Node Weights Warning Validator.

    This validator checks, within a queue, whether any dynamic nodes have lower node weights than any static
    nodes and throws a warning if that's the case.
    """

    def _validate(self, queue_name: str, compute_resources: List[Dict]):
        static_priorities = {cr.name: cr.static_node_priority for cr in compute_resources}
        dynamic_priorities = {cr.name: cr.dynamic_node_priority for cr in compute_resources}
        max_static = max(static_priorities.values())
        min_dynamic = min(dynamic_priorities.values())

        bad_static_priorities = {key: value for key, value in static_priorities.items() if value >= min_dynamic}
        bad_dynamic_priorities = {key: value for key, value in dynamic_priorities.items() if value <= max_static}

        if bad_static_priorities or bad_dynamic_priorities:
            self._add_failure(
                f"Some compute resources in queue {queue_name} have static nodes with higher or equal priority than "
                f"other dynamic nodes in the same queue. "
                f"The following static node priorities are higher than or equal to the minimum dynamic priority "
                f"({min_dynamic}): {bad_static_priorities}. "
                f"The following dynamic node priorities are lower than or equal to the maximum static priority "
                f"({max_static}): {bad_dynamic_priorities}.",
                FailureLevel.WARNING,
            )
