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
import abc
import logging
import re
import sys
from abc import abstractmethod
from collections import OrderedDict
from enum import Enum

from configparser import NoSectionError

from pcluster.config.update_policy import UpdatePolicy
from pcluster.config.validators import settings_validator
from pcluster.utils import get_file_section_name

LOGGER = logging.getLogger(__name__)

if sys.version_info >= (3, 4):
    ABC = abc.ABC
else:
    ABC = abc.ABCMeta("ABC", (), {})


# ---------------------- StorageData ---------------------- #
class StorageData:
    """Class containing storage data for configuration persistence mechanisms, namely Cfn Params and Json."""

    def __init__(self, cfn_params=None, json_params=None, cfn_tags=None):
        self.cfn_params = cfn_params if cfn_params else {}
        self.json_params = json_params if json_params else {}
        self.cfn_tags = cfn_tags if cfn_tags else {}


# ---------------------- Visibility ---------------------- #
class Visibility(Enum):
    """Describes the visibility of a specific Param or Section."""

    PRIVATE = "PRIVATE"  # Internally used, not allowed in config file
    PUBLIC = "PUBLIC"  # Can be specified in config file


# ---------------------- Param ---------------------- #
class Param(ABC):
    """
    Base class for configuration parameters.

    Exposes the main interface to allow parameters to be loaded/written from configuration file and/or their specific
    data storage.
    """

    def __init__(self, section_key, section_label, param_key, param_definition, pcluster_config, owner_section=None):
        self.section_key = section_key
        self.section_label = section_label
        self.key = param_key
        self.definition = param_definition
        self.pcluster_config = pcluster_config
        self.owner_section = owner_section

        # initialize parameter value by using default specified in the mappings file
        self.value = None
        self._from_definition()

    def get_value_from_string(self, string_value):
        """Return internal representation starting from CFN/user-input value."""
        param_value = self.get_default_value()

        string_value = str(string_value).strip() if string_value else None

        if string_value and string_value != "NONE":
            param_value = string_value

        return param_value

    @abc.abstractmethod
    def from_storage(self, storage_params):
        """Load the param from the related storage data structure."""
        pass

    def _validate_section_label(self):
        """
        Validate the section label.

        Verifies that the section label begins by a letter, contains only alphanumeric characters and hyphens
        and if its length is at most 30.
        """
        if self.section_label != "" and not re.match(r"^[a-zA-Z][a-zA-Z0-9-\\_]{0,29}$", self.section_label):
            LOGGER.error(
                (
                    "Failed validation for section {0} {1}. Section names can be at most 30 chars long,"
                    " must begin with a letter and only contain alphanumeric characters, hyphens and underscores."
                ).format(self.section_key, self.section_label)
            )
            sys.exit(1)

    def from_file(self, config_parser):
        """
        Initialize parameter value from config_parser.

        :param config_parser: the configparser object from which get the parameter
        """
        section_name = get_file_section_name(self.section_key, self.section_label)
        if config_parser.has_option(section_name, self.key):

            if self.section_key not in self.pcluster_config.get_global_section_keys():
                self._validate_section_label()

            self.value = config_parser.get(section_name, self.key)
            self._check_allowed_values()

        return self

    @abc.abstractmethod
    def to_storage(self, storage_params):
        """Write the param to the related storage data structure."""
        pass

    def _from_definition(self):
        """Initialize parameter value by using default specified in the mapping file."""
        self.value = self.get_default_value()
        if self.value:
            LOGGER.debug("Setting default value '%s' for key '%s'", self.value, self.key)

    def _check_allowed_values(self):
        """Verify if the parameter value is one of the allowed values specified in the mapping file."""
        allowed_values = self.definition.get("allowed_values", None)
        if allowed_values:
            if isinstance(allowed_values, list):
                if self.value not in allowed_values:
                    self.pcluster_config.error(
                        "The configuration parameter '{0}' has an invalid value '{1}'\n"
                        "Allowed values are: {2}".format(self.key, self.value, allowed_values)
                    )
            else:
                # convert to regex
                if not re.compile(allowed_values).match(str(self.value)):
                    self.pcluster_config.error(
                        "The configuration parameter '{0}' has an invalid value '{1}'\n"
                        "Allowed values are: {2}".format(self.key, self.value, allowed_values)
                    )

    def validate(self):
        """Call validation functions for the parameter, if there."""
        if self.definition.get("required") and self.value is None:
            sys.exit("Configuration parameter '{0}' must have a value".format(self.key))

        for validation_func in self.definition.get("validators", []):
            if self.value is None:
                LOGGER.debug("Configuration parameter '%s' has no value", self.key)
            else:
                errors, warnings = validation_func(self.key, self.value, self.pcluster_config)
                if errors:
                    self.pcluster_config.error(
                        "The configuration parameter '{0}' generated the following errors:\n{1}".format(
                            self.key, "\n".join(errors)
                        )
                    )
                elif warnings:
                    self.pcluster_config.warn(
                        "The configuration parameter '{0}' generated the following warnings:\n{1}".format(
                            self.key, "\n".join(warnings)
                        )
                    )
                else:
                    LOGGER.debug("Configuration parameter '%s' is valid", self.key)

    def to_file(self, config_parser, write_defaults=False):
        """Set parameter in the config_parser in the right section."""
        section_name = get_file_section_name(self.section_key, self.section_label)
        if (
            self.value is not None
            and (write_defaults or self.value != self.get_default_value())
            and self.get_string_value()
        ):
            _ensure_section_existence(config_parser, section_name)
            config_parser.set(section_name, self.key, self.get_string_value())
        else:
            # remove parameter from config_parser if there
            try:
                config_parser.remove_option(section_name, self.key)
            except NoSectionError:
                pass

    def get_string_value(self):
        """Convert internal representation into string."""
        return str(self.value)

    def get_default_value(self):
        """
        Get default value from the Param definition.

        If the default value is a function, pass it the Section this parameter
        is contained within. Otherwise, pass the literal value, defaulting to
        None if not specified.
        """
        default = self.definition.get("default", None)
        if callable(default):
            # Assume that functions are used to set default values conditionally
            # based on the value of other parameters within the same section.
            # They are passed the Section object that they are a member of.
            section = self.pcluster_config.get_section(self.section_key, self.section_label)
            return default(section)

        return default

    def reset_value(self):
        """Reset parameter to default value."""
        self.value = self.get_default_value()

    def refresh(self):
        """
        Refresh the parameter's value.

        Does nothing by default. Subclasses can implement this method by updating parameter's value based on
        PClusterConfig status.
        """
        pass

    def get_update_policy(self):
        """Get the update policy of the parameter."""
        return self.definition.get("update_policy", UpdatePolicy.UNKNOWN)

    def __eq__(self, other):
        return other and (self.key == other.key) and self._value_eq(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def _value_eq(self, other):
        return self.value == other.value

    def get_storage_key(self):
        """
        Return the key by which the current param must be stored in the JSON.

        By default the param key is used as storage key.
        """
        return self.key


# ---------------------- SettingsParam ---------------------- #
class SettingsParam(Param):
    """
    Base class for Setting params.

    Settings params are a special type of Params which allow to link configuration sections to the current Section.
    For instance, queue_settings inside the Cluster Section specifies the Queue sections linked to the current Cluster
    section.
    """

    def __init__(self, section_key, section_label, param_key, param_definition, pcluster_config, owner_section=None):
        """Extend Param by adding info regarding the section referred by the settings."""
        self.referred_section_definition = param_definition.get("referred_section")
        self.referred_section_key = self.referred_section_definition.get("key")
        self.referred_section_type = self.referred_section_definition.get("type")
        param_definition.get("validators", []).append(settings_validator)
        super(SettingsParam, self).__init__(
            section_key, section_label, param_key, param_definition, pcluster_config, owner_section
        )

    def get_default_value(self):
        """
        Get default value.

        If the referred section has the "autocreate" attribute, it means that it is required to initialize
        the settings param and the related section with default values (i.e. vpc, scaling).
        """
        return "default" if self.referred_section_definition.get("autocreate", False) else None

    def _from_definition(self):
        self.value = self.get_default_value()
        if self.value:
            # the SettingsParam has a default value, it means that it is required to initialize
            # the related section with default values (e.g. vpc, scaling).
            LOGGER.debug("Initializing default Section '[%s %s]'", self.key, self.value)
            # Use the label defined in the SettingsParam definition
            if "," in self.value:
                self.pcluster_config.error(
                    "The default value of '{0}' parameter is invalid. "
                    "It can only contain a single {1} section label.".format(self.key, self.referred_section_key)
                )
            else:
                # initialize related section with default values
                section = self.referred_section_type(
                    self.referred_section_definition,
                    self.pcluster_config,
                    section_label=self.value,
                    parent_section=self.owner_section,
                )
                self.pcluster_config.add_section(section)

    def from_file(self, config_parser):
        """
        Initialize parameter value from config_parser.

        :param config_parser: the configparser object from which get the parameter
        """
        section_name = get_file_section_name(self.section_key, self.section_label)

        if config_parser.has_option(section_name, self.key):
            self.value = config_parser.get(section_name, self.key)
            if self.value:
                self._check_allowed_values()
                sections = []
                for section_label in self.value.split(","):
                    sections.append(
                        self.referred_section_type(
                            self.referred_section_definition,
                            self.pcluster_config,
                            section_label=section_label.strip(),
                            parent_section=self.owner_section,
                        ).from_file(config_parser=config_parser, fail_on_absence=True)
                    )
                self._add_sections(sections)

        return self

    def validate(self):
        """
        Validate the Settings Parameter.

        Overrides the default params validation mechanism by adding a default validation based on the number of expected
        sections. The implementation takes into account nested settings params so that the number of resources is
        validated per parent section rather than globally. So, for instance, for compute_resource_settings we check that
        no more than 3 compute resources are activated per queue, while the total number can be up to 15 (3 per queue
        section).
        """
        labels = None if not self.value else self.value.split(",")  # Section labels in the settings param
        max_resources = self.referred_section_definition.get("max_resources", 1)  # Max resources per parent section

        if labels and len(labels) > max_resources:
            self.pcluster_config.error(
                "Invalid number of '{0}' sections specified. Max {1} expected.".format(
                    self.referred_section_key, max_resources
                )
            )

        super(SettingsParam, self).validate()

    def _value_eq(self, other):
        """Compare settings labels ignoring positions and extra spaces."""
        value1 = self.value
        value2 = other.value if other else None
        if value1:
            value1 = ",".join(sorted([x.strip() for x in value1.split(",")]))
        if value2:
            value2 = ",".join(sorted([x.strip() for x in value2.split(",")]))
        return value1 == value2

    def _replace_default_section(self, section):
        """
        Remove default section and replace with the new one.

        Apart from multiple sections, which are managed in a specific way, normally only one section per key is allowed.
        Since some sections are created by default to make sure they are always present, calling this method ensures
        that any existing default section of the same type will be removed from the configuration before adding the new
        one.
        """
        self.pcluster_config.remove_section(
            self.referred_section_key, self.referred_section_definition.get("default_label")
        )
        self.pcluster_config.add_section(section)

    def _add_sections(self, sections):
        if self.referred_section_definition.get("max_resources", 1) == 1:
            # Single section management
            if len(sections) > 1:
                self.pcluster_config.error(
                    "The value of '{0}' parameter is invalid. "
                    "It can only contain a single {1} section label.".format(self.key, self.referred_section_key)
                )
            self._replace_default_section(sections[0])
        else:
            for section in sections:
                if self.pcluster_config.get_section(section.key, section.label):
                    self.pcluster_config.error(
                        "Multiple reference to section '[{0}]'. "
                        "Only one reference to each section is allowed from the same configuration file.".format(
                            get_file_section_name(section.key, section.label)
                        )
                    )
                self.pcluster_config.add_section(section)

    def refresh(self):
        """Update SettingsParam value to make it match actual sections in config."""
        sections_labels = [
            section.label
            for _, section in self.pcluster_config.get_sections(self.referred_section_key).items()
            if section.parent_section == self.owner_section or section.parent_section is None
        ]

        self.value = ",".join(sorted(sections_labels)) if sections_labels else None

    def to_file(self, config_parser, write_defaults=False):
        """Convert the param value into a section in the config_parser and initialize it."""
        section = self.pcluster_config.get_section(self.referred_section_key, self.value)
        if section:
            # evaluate all the parameters of the section and
            # add "*_settings = *" to the parent section
            # only if at least one parameter value is different from the default
            for param_key, param_definition in self.referred_section_definition.get("params").items():
                param_value = section.get_param_value(param_key)

                section_name = get_file_section_name(self.section_key, self.section_label)
                if not config_parser.has_option(section_name, self.key) and (
                    write_defaults or (param_value != param_definition.get("default", None))
                ):
                    _ensure_section_existence(config_parser, section_name)
                    config_parser.set(section_name, self.key, self.get_string_value())

            # create section
            section.to_file(config_parser)

    @property
    def referred_section_labels(self):
        """Return the referred section labels as a list of stripped element."""
        return [label.strip() for label in self.value.split(",")] if self.value else []


# ---------------------- Section ---------------------- #
class Section(ABC):
    """Base class to manage configuration sections (e.g vpc, scaling, aws, etc)."""

    def __init__(self, section_definition, pcluster_config, section_label=None, parent_section=None):
        self.definition = section_definition
        self.key = section_definition.get("key")
        self.autocreate = section_definition.get("autocreate", False)
        self._label = section_label or self.definition.get("default_label", "")
        # All sections have only 1 resource by default, which means they refer to a single Cfn resource or set
        # of resources
        self.max_resources = int(section_definition.get("max_resources", "1"))
        self.pcluster_config = pcluster_config

        self.parent_section = parent_section

        # initialize section parameters with default values
        self.params = OrderedDict({})
        self._from_definition()

    @property
    def label(self):
        """Get the section label."""
        return self._label

    @label.setter
    def label(self, label):
        """Set the section label. Marks the PclusterConfig parent for refreshing if called."""
        self._label = label
        self.pcluster_config._config_updated()

    def from_file(self, config_parser, fail_on_absence=False):
        """Initialize section configuration parameters by parsing config file."""
        params_definitions = self.definition.get("params")
        section_name = get_file_section_name(self.key, self.label)

        # Only params with PUBLIC visibility can be specified in config file
        public_param_keys = set(
            [
                key
                for key, definition in params_definitions.items()
                if definition.get("visibility", Visibility.PUBLIC) == Visibility.PUBLIC
            ]
        )

        if config_parser.has_section(section_name):
            for param_key, param_definition in params_definitions.items():
                param_type = param_definition.get("type", self.get_default_param_type())

                param = param_type(
                    self.key,
                    self.label,
                    param_key,
                    param_definition,
                    pcluster_config=self.pcluster_config,
                    owner_section=self,
                ).from_file(config_parser)
                self.add_param(param)

            not_valid_keys = [key for key, value in config_parser.items(section_name) if key not in public_param_keys]
            if not_valid_keys:
                self.pcluster_config.error(
                    "The configuration parameter{0} '{1}' {2} not allowed in the [{3}] section".format(
                        "s" if len(not_valid_keys) > 1 else "",
                        ",".join(not_valid_keys),
                        "are" if len(not_valid_keys) > 1 else "is",
                        section_name,
                    )
                )
        elif fail_on_absence:
            self.pcluster_config.error("Section '[{0}]' not found in the config file.".format(section_name))

        return self

    def _from_definition(self):
        """Initialize parameters with default values."""
        for param_key, param_definition in self.definition.get("params").items():
            param_type = param_definition.get("type", self.get_default_param_type())
            param = param_type(
                self.key, self.label, param_key, param_definition, self.pcluster_config, owner_section=self
            )
            self.add_param(param)

    def validate(self):
        """Call the validator function of the section and of all the parameters."""
        if self.params:
            section_name = get_file_section_name(self.key, self.label)
            LOGGER.debug("Validating section '[%s]'...", section_name)

            # validate section
            for validation_func in self.definition.get("validators", []):
                errors, warnings = validation_func(self.key, self.label, self.pcluster_config)
                if errors:
                    self.pcluster_config.error(
                        "The section [{0}] is wrongly configured\n" "{1}".format(section_name, "\n".join(errors))
                    )
                elif warnings:
                    self.pcluster_config.warn(
                        "The section [{0}] is wrongly configured\n{1}".format(section_name, "\n".join(warnings))
                    )
                else:
                    LOGGER.debug("Section '[%s]' is valid", section_name)

            # validate items
            LOGGER.debug("Validating parameters of section '[%s]'...", section_name)
            for param_key, param_definition in self.definition.get("params").items():
                param_type = param_definition.get("type", self.get_default_param_type())

                param = self.get_param(param_key)
                if param:
                    param.validate()
                else:
                    # define a default param and validate it
                    param_type(self.key, self.label, param_key, param_definition, self.pcluster_config).validate()
            LOGGER.debug("Parameters validation of section '[%s]' completed correctly.", section_name)

    def to_file(self, config_parser, write_defaults=False):
        """Create the section and add all the parameters in the config_parser."""
        section_name = get_file_section_name(self.key, self.label)

        for param_key, param_definition in self.definition.get("params").items():
            if param_definition.get("visibility", Visibility.PUBLIC) == Visibility.PUBLIC:
                param = self.get_param(param_key)
                if not param:
                    # generate a default param
                    param_type = param_definition.get("type", self.get_default_param_type())
                    param = param_type(self.key, self.label, param_key, param_definition, self.pcluster_config)

                if write_defaults or param.value != param_definition.get("default", None):
                    # add section in the config file only if at least one parameter value is different by the default
                    _ensure_section_existence(config_parser, section_name)

                param.to_file(config_parser, write_defaults)

    def add_param(self, param):
        """
        Add a Param to the Section.

        The internal representation is a dictionary like:
        {
            "key_name": Param,
            "base_os": Param,
            "use_public_ips": BoolParam,
            ...
        }
        :param param: the Param object to add to the Section
        """
        self.params[param.key] = param

    def get_param(self, param_key):
        """
        Return the Param object corresponding to the given key.

        :param param_key: the key to identify the Param object in the internal dictionary
        :return: a Param object
        """
        return self.params[param_key]

    def set_param(self, param_key, param_obj):
        """
        Set a new Param object at the given key.

        :param param_key: the key to identify the Param object in the internal dictionary
        :param param_obj: a Param object
        """
        self.params[param_key] = param_obj

    def get_param_value(self, param_key):
        """
        Return the value of the Param object corresponding to the given key.

        :param param_key: the key to identify the Param object in the internal dictionary
        :return: the value of the Param object or None if the param is not present in the Section
        """
        return self.get_param(param_key).value if self.get_param(param_key) else None

    def refresh(self):
        """Refresh all parameters."""
        for _, param in self.params.items():
            param.refresh()

    @abstractmethod
    def from_storage(self, storage_params):
        """Initialize section configuration parameters by parsing storage configuration."""
        pass

    @abstractmethod
    def to_storage(self, storage_params):
        """Convert section to storage representation."""
        pass

    @abstractmethod
    def get_default_param_type(self):
        """
        Get the default Param type managed by the Section type.

        If no "type" attribute is specified in mappings, parameters declared inside the current section will be assigned
        to this default type.
        """

    def has_metadata(self):
        """
        Tells if metadata information should be stored about the Section.

        By default metadata is stored for all cfn sections, while Json sections use their own mechanism.
        """
        return True


# ---------------------- Common functions ---------------------- #
def _ensure_section_existence(config_parser, section_name):
    """Add a section to the config_parser if not present."""
    if not config_parser.has_section(section_name):
        config_parser.add_section(section_name)
