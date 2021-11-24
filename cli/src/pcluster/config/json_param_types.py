# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from collections import OrderedDict

from pcluster import utils
from pcluster.config.param_types import Param, Section, SettingsParam

# ---------------------- Params ---------------------- #


class JsonParam(Param):
    """Base class to manage configuration parameters stored in Json format."""

    def get_value_type(self):
        """Return the type of the value managed by the Param."""
        return str

    def from_file(self, config_parser):
        """Load the param value from configuration file."""
        section_name = utils.get_file_section_name(self.section_key, self.section_label)
        if config_parser.has_option(section_name, self.key):
            try:
                self.value = self._parse_value(config_parser, section_name)
                self._check_allowed_values()
            except ValueError:
                self.pcluster_config.error(
                    "Configuration parameter '{0}' must be of '{1}' type".format(
                        self.key, self.get_value_type().__name__
                    )
                )

        return self

    def from_storage(self, storage_params):
        """Load the param from the provided Json storage params dict."""
        storage_value = _get_storage_subdict(self, storage_params.json_params).get(
            self.get_storage_key(), self.get_default_value()
        )
        self.value = storage_value
        return self

    def to_storage(self, storage_params):
        """Store the param into the provided Json storage params dict."""
        _get_storage_subdict(self, storage_params.json_params)[self.get_storage_key()] = self.value

    def _parse_value(self, config_parser, section_name):
        """Parse the value from config file, converting to the needed type for the specific param."""
        # No conversion is applied at base level
        return config_parser.get(section_name, self.key)


class IntJsonParam(JsonParam):
    """Base JsonParam to manage int parameters."""

    def get_value_type(self):
        """Return the type of the value managed by the Param."""
        return int

    def _parse_value(self, config_parser, section_name):
        """Parse the value from config file, converting to the needed type for the specific param."""
        # Convert value to Int
        return config_parser.getint(section_name, self.key)


class BooleanJsonParam(JsonParam):
    """Base JsonParam to manage boolean parameters."""

    def get_value_type(self):
        """Return the type of the value managed by the Param."""
        return bool

    def _parse_value(self, config_parser, section_name):
        """Parse the value from config file, converting to the needed type for the specific param."""
        # Convert value to boolean
        return config_parser.getboolean(section_name, self.key)

    def get_string_value(self):
        """Convert internal representation into string."""
        return self.get_default_value().lower() if self.value is None else str(bool(self.value)).lower()


class FloatJsonParam(JsonParam):
    """Base JsonParam to manage float parameters."""

    def get_value_type(self):
        """Return the type of the value managed by the Param."""
        return float

    def _parse_value(self, config_parser, section_name):
        """Parse the value from config file, converting to the needed type for the specific param."""
        # Convert value to Float
        return config_parser.getfloat(section_name, self.key)


class ScaleDownIdleTimeJsonParam(JsonParam):
    """JsonParam to manage scaledown_idletime for Json configuration."""

    def refresh(self):
        """Take the value from the scaledown_idletime cfn parameter."""
        self.value = self.owner_section.get_param("scaledown_idletime").value

    def get_storage_key(self):
        """Return the key by which the current param must be stored in the JSON."""
        return "scaledown_idletime"


class DefaultComputeQueueJsonParam(JsonParam):
    """JsonParam to manage default_queue parameter in cluster section."""

    def refresh(self):
        """Take the label of the first queue as value."""
        queue_settings_param = self.pcluster_config.get_section("cluster").get_param("queue_settings")
        # First queue is the default one
        if queue_settings_param:
            queue_settings_param_value = queue_settings_param.value

            if queue_settings_param_value:
                self.value = queue_settings_param_value.split(",")[0].strip()


# ---------------------- SettingsParams ---------------------- #
class SettingsJsonParam(SettingsParam):
    """Settings params with storage in Json."""

    def to_storage(self, storage_params):
        """
        Convert the referred sections into the json storage representation.

        In case of multiple sections, a subdictionary is created for each section under the param key, with the section
        label as key and the related section as value.
        Example of storage conversion:
        config file:
            queue_settings = queue1, queue2

        json config:
            "cluster": {
                ...
                "queue_settings": {
                    "queue1": {...},
                    "queue2": {...}
                }
            }

        In case of single section, a subdictionary is created under the section key, and the section label is set as as
        a dict item.
        Example of storage conversion:
        config file:
            dashboard_settings = dashboard1

        json config:
            "cluster": {
                ...
                "dashboard": {
                  "label": "dashboard1",
                  ...
                }
            }

        """
        if self.value:
            labels = self.referred_section_labels

            for label in labels:
                section = self.pcluster_config.get_section(self.referred_section_key, label.strip())
                section.to_storage(storage_params)

    def from_storage(self, storage_params):
        """
        Load the referred sections from storage representation.

        This method rebuilds the settings labels by iterating through all subsections of the related section;
        then each subsection is loaded from storage as well.
        """
        json_params = storage_params.json_params
        json_subdict = _get_storage_subdict(self, json_params)
        labels = None
        if json_subdict:
            if self.referred_section_definition.get("max_resources", 1) > 1:
                # Multiple sections: the dict is under <section_key>_settings
                json_subdict = json_subdict.get(self.key)
                if json_subdict:
                    labels = [label for label in json_subdict.keys()]
            else:
                # Single section: the dict is under <section_key>
                json_subdict = json_subdict.get(self.referred_section_key)
                if json_subdict:
                    labels = [json_subdict.get("label")]

            if labels:
                self.value = ",".join(labels)
                for label in labels:
                    section = self.referred_section_type(
                        self.referred_section_definition,
                        self.pcluster_config,
                        section_label=label,
                        parent_section=self.owner_section,
                    ).from_storage(storage_params)
                    self.pcluster_config.add_section(section)

        return self


# ---------------------- Sections ---------------------- #
class JsonSection(Section):
    """Class representing configuration sections which are persisted in Json."""

    def from_storage(self, storage_params):
        """Load the section from storage params."""
        for param_key, param_definition in self.definition.get("params").items():
            param_type = param_definition.get("type", Param)
            param = param_type(
                self.key, self.label, param_key, param_definition, self.pcluster_config, owner_section=self
            ).from_storage(storage_params)
            self.add_param(param)
        return self

    def to_storage(self, storage_params):
        """Write the section into storage params."""
        for param_key, _ in self.definition.get("params").items():
            param = self.get_param(param_key)
            if param:
                param.to_storage(storage_params)

    def has_metadata(self):
        """No metadata must be stored in CloudFormation for Json Sections."""
        return False

    def get_default_param_type(self):
        """Get the default Param type managed by the Section type."""
        return JsonParam

    def refresh(self):
        """Refresh the Json section."""
        self.refresh_section()
        super(JsonSection, self).refresh()

    def refresh_section(self):
        """Perform custom refresh operations."""
        pass


class QueueJsonSection(JsonSection):
    """JSon Section for queues."""

    def refresh_section(self):
        """Take values of disable_hyperthreading and enable_efa from cluster section if not specified."""
        if self.get_param_value("disable_hyperthreading") is None:
            cluster_disable_hyperthreading = self.pcluster_config.get_section("cluster").get_param_value(
                "disable_hyperthreading"
            )
            # None value at cluster level is converted to False at queue level
            self.get_param("disable_hyperthreading").value = cluster_disable_hyperthreading is True

        if self.get_param_value("enable_efa") is None:
            cluster_enable_efa = self.pcluster_config.get_section("cluster").get_param_value("enable_efa")

            # enable_efa is of string type in cluster section and of bool type in queue section.
            # None value at cluster level is converted to False at queue level
            self.get_param("enable_efa").value = cluster_enable_efa == "compute"

        compute_resource_labels = self.get_param("compute_resource_settings").referred_section_labels
        if compute_resource_labels:
            for compute_resource_label in compute_resource_labels:
                compute_resource_section = self.pcluster_config.get_section("compute_resource", compute_resource_label)
                self.refresh_compute_resource(compute_resource_section)

    def refresh_compute_resource(self, compute_resource_section):
        """
        Populate additional settings needed for the linked compute resource like vcpus, gpus etc.

        These parameters are set according to queue settings and instance type capabilities.
        """
        instance_type_param = compute_resource_section.get_param("instance_type")

        if instance_type_param.value:
            instance_type_info = utils.InstanceTypeInfo.init_from_instance_type(instance_type_param.value)

            # Set vcpus according to queue's disable_hyperthreading and instance features
            ht_disabled = self.get_param_value("disable_hyperthreading")
            default_threads_per_core = instance_type_info.default_threads_per_core()
            vcpus = (
                (instance_type_info.vcpus_count() // default_threads_per_core)
                if ht_disabled
                else instance_type_info.vcpus_count()
            )
            compute_resource_section.get_param("vcpus").value = vcpus

            # Set gpus according to instance features
            gpus = instance_type_info.gpu_count()
            compute_resource_section.get_param("gpus").value = gpus
            compute_resource_section.get_param("gpu_type").value = instance_type_info.gpu_type()

            # Set enable_efa according to queues' enable_efa and instance features
            # Instance type must support EFA
            enable_efa = self.get_param_value("enable_efa")
            compute_resource_section.get_param("enable_efa").value = (
                enable_efa and instance_type_info.is_efa_supported()
            )

            # Set disable_hyperthreading according to queues' disable_hyperthreading and instance features
            compute_resource_section.get_param("disable_hyperthreading").value = (
                ht_disabled and default_threads_per_core != 1
            )

            # On some instance types, hyperthreading must be disabled manually rather than
            # through the CpuOptions of a launch template.
            compute_resource_section.get_param(
                "disable_hyperthreading_via_cpu_options"
            ).value = compute_resource_section.get_param(
                "disable_hyperthreading"
            ).value and utils.disable_ht_via_cpu_options(
                instance_type_param.value
            )

            # Set initial_count to min_count if not manually set
            initial_count_param = compute_resource_section.get_param("initial_count")
            if initial_count_param.value is None:
                initial_count_param.value = compute_resource_section.get_param_value("min_count")

            # Set number of network interfaces
            compute_resource_section.get_param(
                "network_interfaces"
            ).value = instance_type_info.max_network_interface_count()


# ---------------------- Common functions ---------------------- #
def _get_storage_subdict(param, json_storage_params):
    """Get the JSON configuration subdictionary where the current parameter must be stored."""
    parent_section = param.owner_section
    sections_path = []
    while parent_section:
        sections_path.insert(0, parent_section)
        parent_section = parent_section.parent_section

    current_dict = json_storage_params

    for section in sections_path:
        dict_key = section.key + "_settings" if section.max_resources > 1 else section.key
        section_key_dict = current_dict.get(dict_key, None)
        if not section_key_dict:
            section_key_dict = OrderedDict({})
            # Single sections have label as attribute and no subsections
            if section.max_resources == 1:
                section_key_dict["label"] = section.label
            current_dict[dict_key] = section_key_dict
        current_dict = section_key_dict

        if section.max_resources > 1:
            # Multiple sections have one subsection per label
            section_label_dict = current_dict.get(section.label, None)
            if not section_label_dict:
                section_label_dict = OrderedDict({})
                current_dict[section.label] = section_label_dict

            current_dict = section_label_dict

    return current_dict
