# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import copy
import logging
import re
import sys
from collections import namedtuple
from typing import List

from pcluster.config.update_policy import UpdatePolicy
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.schemas.common_schema import BaseSchema

# Represents a single parameter change in a ConfigPatch instance
Change = namedtuple("Change", ["path", "key", "old_value", "new_value", "update_policy", "is_list"])

# Patch for deepcopy bug - Issue10076 in Python < 3.7
# see https://bugs.python.org/issue10076
# see https://docs.python.org/3/whatsnew/3.7.html#re
if sys.version_info <= (3, 7):
    copy._deepcopy_dispatch[type(re.compile(""))] = lambda r, _: r  # pylint: disable=protected-access

LOGGER = logging.getLogger(__name__)


class ConfigPatch:
    """
    Represents the Diff Patch between two PclusterConfig instances.

    The two configurations that must be provided to create the patch are:
        - base_config: the original configuration
        - target_config: the target configuration; namely the new configuration wanted by the user.

    The patch will contain all the changes that will be needed to transform the base configuration into the target one.
    Together with each change, a check will be performed based on the Update Policy of the related parameter and a check
    result will be returned with one of the following values:
        - SUCCEEDED: The change can be safely done
        - ACTION NEEDED: The change could be done but an action is needed from the user to unlock it
        - FAILED: The change cannot be safely done

    Once created, a ConfigPatch can be checked against an existing CloudFormation stack using the check() method. The
    output of a check will contain the following information:
        - A boolean telling if the new configuration can be safely applied
        - A list of change rows with all the information to build a detailed report
    """

    def __init__(self, cluster, base_config: dict, target_config: dict):
        """
        Create a ConfigPatch.

        :param base_config: The base configuration, f.i. from S3 bucket
        :param target_config: The target configuration, f.i. as loaded from configuration file
        """
        self.cluster = cluster
        # Cached condition results
        self.condition_results = {}

        # Make a deep copy of the basic and target configurations to avoid changing the original ones
        self.base_config = copy.deepcopy(base_config)
        self.target_config = copy.deepcopy(target_config)

        self.cluster_schema = ClusterSchema(cluster_name=cluster.name)
        self.changes = []
        self._compare()

    @property
    def stack_name(self):
        """Get the name of the stack this patch is referred to."""
        return self.cluster.stack_name

    @property
    def cluster_name(self):
        """Get the cluster name from the base configuration file, if any."""
        return self.cluster.name

    def _compare(self):
        """
        Compare target with base configuration.

        All detected changes are added to the internal changes list, ready to be checked  through the public check()
        method.
        """
        self._compare_section(self.base_config, self.target_config, self.cluster_schema, param_path=[])

    def _compare_section(self, base_section: dict, target_section: dict, section_schema: BaseSchema, param_path: List):
        """
        Compare the provided base and target sections and append the detected changes to the internal changes list.

        :param base_section: The section in the base configuration
        :param target_section: The corresponding section in the target configuration
        :param section_schema: schema corresponding to the section to be analyzed (contains all the resources/params)
        :param param_path: A list on which the items correspond to the path of the param in the configuration schema
        """
        for _, field_obj in section_schema.declared_fields.items():
            data_key = field_obj.data_key
            is_nested_section = hasattr(field_obj, "nested")
            is_list = hasattr(field_obj, "many") and field_obj.many

            change_update_policy = field_obj.metadata.get("update_policy", UpdatePolicy.UNSUPPORTED)

            if is_nested_section:
                if is_list:
                    self._compare_list(
                        base_section, target_section, param_path, data_key, field_obj, change_update_policy
                    )
                else:
                    # Single nested section
                    target_value = target_section.get(data_key, None) if target_section else None
                    base_value = base_section.get(data_key, None) if base_section else None

                    if target_value and base_value:
                        self._compare_nested_section(param_path, data_key, base_value, target_value, field_obj)
                    elif target_value or base_value:
                        # One section has been added or removed
                        if change_update_policy is UpdatePolicy.IGNORED:
                            # Traverse config if UpdatePolicy is IGNORED
                            self._compare_nested_section(param_path, data_key, base_value, target_value, field_obj)
                        else:
                            # Add section change information
                            self.changes.append(
                                Change(
                                    param_path,
                                    data_key,
                                    base_value if base_value else "-",
                                    target_value if target_value else "-",
                                    change_update_policy,
                                    is_list=False,
                                )
                            )
            else:
                # Simple param
                target_value = target_section.get(data_key, None) if target_section else None
                base_value = base_section.get(data_key, None) if base_section else None

                if target_value != base_value:
                    # Add param change information
                    self.changes.append(
                        Change(param_path, data_key, base_value, target_value, change_update_policy, is_list=False)
                    )

    def _compare_nested_section(self, param_path, data_key, base_value, target_value, field_obj):
        # Compare nested sections and params
        nested_path = copy.deepcopy(param_path)
        nested_path.append(data_key)
        self._compare_section(base_value, target_value, field_obj.schema, nested_path)

    def _compare_list(self, base_section, target_section, param_path, data_key, field_obj, change_update_policy):
        """
        Compare list of nested section (e.g. list of queues) by comparing the items with the same update_key.

        If update_key is not set we're considering Name as identifier.
        """
        update_key = field_obj.metadata.get("update_key")

        # Compare items in the list by searching the right item to compare through update_key value
        # First, compare all sections from target vs base config and mark visited base sections.
        for target_nested_section in target_section.get(data_key, []):
            update_key_value = target_nested_section.get(update_key)
            base_nested_section = next(
                (
                    nested_section
                    for nested_section in base_section.get(data_key, [])
                    if nested_section.get(update_key) == update_key_value
                ),
                None,
            )
            if base_nested_section:
                nested_path = copy.deepcopy(param_path)
                nested_path.append(f"{data_key}[{update_key_value}]")
                self._compare_section(base_nested_section, target_nested_section, field_obj.schema, nested_path)
                base_nested_section["visited"] = True
            else:
                self.changes.append(
                    Change(
                        param_path,
                        data_key,
                        None,
                        target_nested_section,
                        change_update_policy,
                        is_list=True,
                    )
                )
        # Then, compare all non visited base sections vs target config.
        for base_nested_section in base_section.get(data_key, []):
            if not base_nested_section.get("visited", False):
                self.changes.append(
                    Change(
                        param_path,
                        data_key,
                        base_nested_section,
                        None,
                        change_update_policy,
                        is_list=True,
                    )
                )

    @property
    def update_policy_level(self):
        """
        Get the max update policy level of the ConfigPatch.

        This method provides a static indication of the actual applicability of the patch and it's meant for testing
        purposes. The real applicability of a patch, which involves dynamic condition checks, must be performed
        by calling the check() method.
        """
        return (
            max(change.update_policy.level for change in self.changes)
            if len(self.changes) > 0
            else UpdatePolicy.SUPPORTED.level
        )

    def check(self):
        """
        Check the patch against the existing cluster stack.

        All changes in the patch are checked against the existing cluster; their conditions are verified and a detailed
        report is generated. Each line of the report will contain all the details about the detected change, together
        with the corresponding reason if the change is not applicable and any action needed to unlock the problem.

        :return: A tuple containing the patch applicability and the report rows.
        """
        rows = [
            ["param_path", "parameter", "old value", "new value", "check", "reason", "action_needed", "update_policy"]
        ]

        patch_allowed = True

        for change in self.changes:
            check_result, reason, action_needed, print_change = change.update_policy.check(change, self)

            if check_result != UpdatePolicy.CheckResult.SUCCEEDED:
                patch_allowed = False

            if print_change:
                rows.append(
                    [
                        change.path,
                        change.key,
                        change.old_value,
                        change.new_value,
                        check_result.value,
                        reason,
                        action_needed,
                        change.update_policy.name,
                    ]
                )

        return patch_allowed, rows

    @staticmethod
    def build_config_param_path(path, parameter):
        """Compose the parameter path following the YAML Path standard.

        Standard: https://github.com/wwkimball/yamlpath/wiki/Segments-of-a-YAML-Path#yaml-path-standard
        """
        yaml_path = []
        if path:
            yaml_path.extend(path)
        if parameter:
            yaml_path.append(parameter)
        return ".".join(yaml_path)

    @staticmethod
    def generate_json_change_set(changes):
        """Generate JSON change set.

        Generate JSON change set from changes
        """
        change_attributes = {key: index for index, key in enumerate(changes[0])}
        changes_list = []
        for change in changes[1:]:
            parameter = ConfigPatch.build_config_param_path(
                change[change_attributes["param_path"]], change[change_attributes["parameter"]]
            )
            new_value = change[change_attributes["new value"]]
            old_value = change[change_attributes["old value"]]
            update_policy = change[change_attributes["update_policy"]]
            changes_list.append(
                {
                    "parameter": parameter,
                    "requestedValue": new_value,
                    "currentValue": old_value,
                    "updatePolicy": update_policy,
                }
            )

        return {"changeSet": changes_list}
