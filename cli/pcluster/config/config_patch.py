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

# Represents a single parameter change in a ConfigPatch instance
from pcluster import utils
from pcluster.config.update_policy import UpdatePolicy
from pcluster.utils import get_file_section_name

Change = namedtuple("Change", ["section_key", "section_label", "param_key", "old_value", "new_value", "update_policy"])

# Patch for deepcopy bug - Issue10076 in Pyhton < 3.7
# see https://bugs.python.org/issue10076
# see https://docs.python.org/3/whatsnew/3.7.html#re
if sys.version_info <= (3, 7):
    copy._deepcopy_dispatch[type(re.compile(""))] = lambda r, _: r

LOGGER = logging.getLogger(__name__)


class ConfigPatch(object):
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

    def __init__(self, base_config, target_config):
        """
        Create a ConfigPatch.

        :param base_config: The base configuration, f.i. as reconstructed from CloudFormation
        :param target_config: The target configuration, f.i. as loaded from configuration file
        """
        # Cached condition results
        self.condition_results = {}

        # Make a deep copy of the basic and target configurations to avoid changing the original ones
        self.base_config = copy.deepcopy(base_config)
        self.target_config = copy.deepcopy(target_config)

        # Disable autorefresh to avoid breakages due to changes made to the configurations when creating the patch
        self.base_config.auto_refresh = False
        self.target_config.auto_refresh = False

        self.changes = []
        self._compare()

    @property
    def stack_name(self):
        """Get the name of the stack this patch is referred to."""
        return (
            utils.get_stack_name(self.base_config.cluster_name) if hasattr(self.base_config, "cluster_name") else None
        )

    @property
    def config_file(self):
        """Get the name of the target configuration file, if any."""
        return self.target_config.config_file if hasattr(self.target_config, "config_file") else None

    @property
    def cluster_name(self):
        """Get the cluster name from the base configuration file, if any."""
        return self.base_config.cluster_name if hasattr(self.base_config, "cluster_name") else None

    def _compare(self):
        """
        Compare target with base configuration.

        All detected changes are added to the internal changes list, ready to be checked  through the public check()
        method.
        """
        # Remove ignored sections
        self._remove_ignored_sections(self.base_config)
        self._remove_ignored_sections(self.target_config)

        # First, compare all sections from target vs base config and mark visited base sections.
        for section_key in sorted(self.target_config.get_section_keys()):
            for section_label in sorted(self.target_config.get_sections(section_key).keys()):
                target_section = self.target_config.get_section(section_key, section_label)
                base_section = self._get_config_section(self.base_config, target_section)
                base_section.visited = True
                self._compare_section(base_section, target_section)

        # Then, compare all non visited base sections vs target config.
        for section_key in sorted(self.base_config.get_section_keys()):
            for section_label in sorted(self.base_config.get_sections(section_key).keys()):
                base_section = self.base_config.get_section(section_key, section_label)
                if not hasattr(base_section, "visited"):
                    target_section = self._get_config_section(self.target_config, base_section)
                    self._compare_section(base_section, target_section)

    def _compare_section(self, base_section, target_section):
        """
        Compare the provided base and target sections and append the detected changes to the internal changes list.

        :param base_section: The section in the base configuration
        :param target_section: The corresponding section in the target configuration
        """
        # If one of the two sections is marked as mock, all detected changes will also be mock
        mock_base_section = hasattr(base_section, "mock")
        mock_target_section = hasattr(target_section, "mock")
        mock_change = mock_base_section or mock_target_section

        for _, param in target_section.params.items():
            base_value = base_section.get_param_value(param.key)

            if param != base_section.get_param(param.key):
                # Mock changes are always considered supported (or ignored). Their purpose is just to show which
                # parameters are present in a section that has been added or removed. UpdatePolicy checks on related
                # settings parameters will determine whether adding or removing these sections is supported
                if mock_change and param.get_update_policy() != UpdatePolicy.IGNORED:
                    change_update_policy = UpdatePolicy.SUPPORTED
                else:
                    change_update_policy = param.get_update_policy()

                self.changes.append(
                    Change(
                        target_section.key,
                        target_section.label,
                        param.key,
                        base_value if not mock_base_section else "-",
                        param.value if not mock_target_section else "-",
                        change_update_policy,
                    )
                )

    def _remove_ignored_sections(self, config):
        # global file sections are ignored for patch creation
        for section_key in config.get_global_section_keys():
            config.remove_section(section_key)

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
            if len(self.changes)
            else UpdatePolicy.SUPPORTED.level
        )

    def _create_default_section(self, config, section):
        """
        Create a section of same type of the provided section, with all default parameter values.

        The purpose of this operation is to allow sections comparison when a section is missing in base or target
        configuration.

        :param config: The configuration lacking the section
        :param section: The section to create a default copy of
        """
        section_definition = section.definition
        section_type = section_definition.get("type")
        default_section = section_type(
            section_definition=section_definition, pcluster_config=config, section_label=section.label
        )

        default_section.mock = True
        return default_section

    def _get_config_section(self, config, section):
        """
        Get the section corresponding to the provided one in the specified configuration.

        If no section is found, a default copy of the provided section is created on the fly.

        :param config: The configuration where to get the section from
        :param section: The section to be matched
        :return: The matching section
        """
        section_key = section.key
        # We compare the cluster sections of base_config and target_config no matter the label change or not
        section_label = section.label if section_key != "cluster" else None
        config_section = config.get_section(section_key, section_label)

        # If section is not present in base config, a default copy is generated
        if not config_section:
            config_section = self._create_default_section(config, section)
        return config_section

    def check(self):
        """
        Check the patch against the existing cluster stack.

        All changes in the patch are checked against the existing cluster; their conditions are verified and a detailed
        report is generated. Each line of the report will contain all the details about the detected change, together
        with the corresponding reason if the change is not applicable and any action needed to unlock the problem.

        :return A tuple containing the patch applicability and the report rows.
        """
        rows = [["section", "parameter", "old value", "new value", "check", "reason", "action_needed"]]

        patch_allowed = True

        for change in self.changes:
            check_result, reason, action_needed, print_change = change.update_policy.check(change, self)

            if check_result != UpdatePolicy.CheckResult.SUCCEEDED:
                patch_allowed = False

            if print_change:
                section_name = get_file_section_name(change.section_key, change.section_label)
                rows.append(
                    [
                        section_name,
                        change.param_key,
                        change.old_value,
                        change.new_value,
                        check_result.value,
                        reason,
                        action_needed,
                    ]
                )

        return patch_allowed, rows
