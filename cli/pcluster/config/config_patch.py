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
from collections import namedtuple

from pcluster.config.param_types import Updatability as Upd

# Represents a single parameter change in a ConfigPatch instance
Change = namedtuple("Change", ["section_key", "section_label", "param_key", "old_value", "new_value", "updatability"])


class ConfigPatch(object):
    """
    Represents the Diff Patch between two PclusterConfig instances.

    To be successfully created, it is mandatory that the base PclusterConfig instance can be "adapted" to the target
    one, which means that all its sections can be matched to the base PClusterConfig instance's sections.
    """

    IGNORED_SECTIONS = ["global", "aliases"]  # Sections ignored for patch creation

    def __init__(self, base_config, target_config):
        """
        Create a ConfigPatch.

        Tries creating a ConfigPatch instance to describe the changes needed to update a pre-existing base_config
        to the new settings contained in target_config.
        :param base_config: The base configuration, f.i. as reconstructed from CloudFormation
        :param target_config: The target configuration, f.i. as loaded from configuration file
        """
        self.base_config = base_config
        self.target_config = target_config
        self.changes = []
        self._adapt()
        self._compare()

    def _adapt(self):
        """
        Adapt the base config to the target one.

        The adaptation process involves restoring sections labels in the base config to make them match the ones in the
        target config. If this process cannot be done, for instance because one or more sections cannot be found and/or
        relabeled in the target config, an exception will be thrown.
        """
        for section_key in self.base_config.get_section_keys():
            if section_key not in ConfigPatch.IGNORED_SECTIONS:
                for _, base_section in self.base_config.get_sections(section_key).items():
                    target_section = self._get_target_section(base_section)
                    if not target_section:
                        raise Exception(
                            "Could not match base conf section {0} with target conf".format(base_section.key)
                        )
                    else:
                        base_section.label = target_section.label

        for section_key in self.target_config.get_section_keys():
            if section_key not in ConfigPatch.IGNORED_SECTIONS:
                for _, target_section in self.target_config.get_sections(section_key).items():
                    base_section = self.base_config.get_section(target_section.key, target_section.label)
                    if not base_section:
                        raise Exception(
                            "Could not match target conf section {0} with base conf".format(target_section.key)
                        )

    def _compare(self):
        """Compare the target config to the source."""
        for section_key in self.target_config.get_section_keys():
            if section_key not in ConfigPatch.IGNORED_SECTIONS:
                for _, section in self.target_config.get_sections(section_key).items():
                    for _, param in section.params.items():
                        base_section = self.base_config.get_section(section.key, section.label)
                        base_value = base_section.get_param(param.key).value if base_section else None
                        target_value = param.value

                        if base_value != target_value:
                            self.changes.append(
                                Change(
                                    section.key,
                                    section.label,
                                    param.key,
                                    base_value,
                                    param.value,
                                    param.get_updatability(),
                                )
                            )

    @property
    def updatability(self):
        """Get the updatability of the ConfigPatch."""
        return max(change.updatability for change in self.changes) if len(self.changes) else Upd.ALLOWED

    def _create_default_target_session(self, base_section):
        # create a default target session of same type of base_section
        section_definition = base_section.definition
        section_type = section_definition.get("type")
        section = section_type(
            section_definition=section_definition, pcluster_config=self.target_config, section_label=base_section.label
        )
        self.target_config.add_section(section)
        return section

    def _get_target_section_by_param(self, section_key, param_key, param_value):
        section = None
        sections = self.target_config.get_sections(section_key)
        for _, s in sections.items():
            param = s.get_param(param_key)
            if param and param.value == param_value:
                section = s
                break
        return section

    def _get_target_section(self, base_section):
        section = None
        key_param = base_section.key_param
        if key_param:
            # EBS sections are looked by shared dir
            key_param_value = base_section.get_param_value(key_param)
            section = self._get_target_section_by_param(base_section.key, key_param, key_param_value)
        else:
            # All other sections are matched only if exactly one is found
            sections = self.target_config.get_sections(base_section.key)
            if len(sections) == 1:
                section = next(iter(sections.values()))

        # If section is not present in target config we can build a default section to allow comparison
        # but only if it is a section without key_param
        if not section and not key_param:
            section = self._create_default_target_session(base_section)

        return section
