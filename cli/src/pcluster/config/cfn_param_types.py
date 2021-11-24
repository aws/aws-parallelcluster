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

import json
from collections import OrderedDict

import yaml

from pcluster.config.iam_policy_rules import AWSBatchFullAccessInclusionRule, CloudWatchAgentServerPolicyInclusionRule
from pcluster.config.param_types import LOGGER, Param, Section, SettingsParam, StorageData, _ensure_section_existence
from pcluster.config.resource_map import ResourceMap
from pcluster.constants import PCLUSTER_ISSUES_LINK
from pcluster.utils import (
    InstanceTypeInfo,
    disable_ht_via_cpu_options,
    error,
    get_availability_zone_of_subnet,
    get_cfn_param,
    get_default_instance_type,
    get_ebs_snapshot_info,
    get_efs_mount_target_id,
    get_file_section_name,
    get_fsx_info,
    get_supported_architectures_for_instance_type,
)


# ---------------------- Params ---------------------- #
class CfnParam(Param):
    """Base class for configuration parameters using CloudFormation parameters as storage mechanism."""

    def from_storage(self, storage_params):
        """Load the param from the related storage data structure."""
        return self.from_cfn_params(storage_params.cfn_params)

    def to_storage(self, storage_params):
        """Write the param into the related storage data structure."""
        cfn_params = storage_params.cfn_params
        cfn_params.update(self.to_cfn())

    def from_cfn_params(self, cfn_params):
        """
        Initialize parameter value by parsing CFN input parameters.

        :param cfn_params: list of all the CFN parameters, used if "cfn_param_mapping" is specified in the definition
        """
        cfn_converter = self.definition.get("cfn_param_mapping", None)
        if cfn_params:
            cfn_value = get_cfn_param(cfn_params, cfn_converter) if cfn_converter else "NONE"
            self.value = self.get_value_from_string(cfn_value)

        return self

    def from_cfn_value(self, cfn_value):
        """
        Initialize parameter value by parsing from a given value coming from CFN.

        :param cfn_value: a value coming from a comma separated CFN param
        """
        self.value = self.get_value_from_string(cfn_value)

        return self

    def to_cfn(self):
        """Convert param to CFN representation, if "cfn_param_mapping" attribute is present in the Param definition."""
        cfn_params = {}
        cfn_converter = self.definition.get("cfn_param_mapping", None)

        if cfn_converter:
            cfn_value = self.get_cfn_value()
            cfn_params[cfn_converter] = str(cfn_value)

        return cfn_params

    def get_cfn_value(self):
        """
        Convert parameter value into CFN value.

        Used when the parameter must go into a comma separated CFN parameter.
        """
        return str(self.value if self.value is not None else self.definition.get("default", "NONE"))


class CommaSeparatedCfnParam(CfnParam):
    """Class to manage comma separated parameters. E.g. additional_iam_policies."""

    def from_file(self, config_parser):
        """
        Initialize parameter value from config_parser.

        :param config_parser: the configparser object from which get the parameter
        """
        section_name = get_file_section_name(self.section_key, self.section_label)
        if config_parser.has_option(section_name, self.key):
            config_value = config_parser.get(section_name, self.key)
            self.value = list(map(lambda x: x.strip(), config_value.split(",")))
            self._check_allowed_values()

        return self

    def get_string_value(self):
        """Convert internal representation into string."""
        return str(",".join(self.value)) if self.value else ""

    def get_value_from_string(self, string_value):
        """Return internal representation starting from string/CFN value."""
        param_value = self.get_default_value()

        if string_value and string_value != "NONE":
            param_value = list(map(lambda x: x.strip(), string_value.split(",")))

        return param_value

    def get_cfn_value(self):
        """
        Convert parameter value into CFN value.

        Used when the parameter must go into a comma separated CFN parameter.
        """
        return str(",".join(self.value) if self.value else self.definition.get("default", "NONE"))

    def get_default_value(self):
        """Get default value from the Param definition if there, empty list otherwise."""
        return self.definition.get("default", [])


class FloatCfnParam(CfnParam):
    """Class to manage float configuration parameters."""

    def from_file(self, config_parser):
        """
        Initialize parameter value from config_parser.

        :param config_parser: the configparser object from which get the parameter
        """
        section_name = get_file_section_name(self.section_key, self.section_label)
        if config_parser.has_option(section_name, self.key):
            try:
                self.value = config_parser.getfloat(section_name, self.key)
                self._check_allowed_values()
            except ValueError:
                self.pcluster_config.error("Configuration parameter '{0}' must be a Float".format(self.key))

        return self

    def get_value_from_string(self, string_value):
        """Return internal representation starting from CFN/user-input value."""
        param_value = self.get_default_value()

        try:
            if string_value is not None:
                string_value = str(string_value).strip()
                if string_value != "NONE":
                    param_value = float(string_value)
        except ValueError:
            self.pcluster_config.warn(
                "Unable to convert the value '{0}' to a Float. "
                "Using default value for parameter '{1}'".format(string_value, self.key)
            )

        return param_value


class BoolCfnParam(CfnParam):
    """Class to manage boolean configuration parameters."""

    def from_file(self, config_parser):
        """
        Initialize parameter value from config_parser.

        :param config_parser: the configparser object from which get the parameter
        """
        section_name = get_file_section_name(self.section_key, self.section_label)
        if config_parser.has_option(section_name, self.key):
            try:
                self.value = config_parser.getboolean(section_name, self.key)
                self._check_allowed_values()
            except ValueError:
                self.pcluster_config.error("Configuration parameter '{0}' must be a Boolean".format(self.key))

        return self

    def get_value_from_string(self, string_value):
        """Return internal representation starting from CFN/user-input value."""
        param_value = self.get_default_value()

        if string_value is not None:
            string_value = str(string_value).strip()
            if string_value != "NONE":
                param_value = string_value == "true"

        return param_value

    def get_string_value(self):
        """Convert internal representation into string."""
        return "NONE" if self.value is None else str(bool(self.value)).lower()

    def get_cfn_value(self):
        """
        Convert parameter value into CFN value.

        Used when the parameter must go into a comma separated CFN parameter.
        """
        return self.get_string_value()


class IntCfnParam(CfnParam):
    """Class to manage integer configuration parameters."""

    def from_file(self, config_parser):
        """
        Initialize param_value from config_parser.

        :param config_parser: the configparser object from which get the parameter
        """
        section_name = get_file_section_name(self.section_key, self.section_label)
        if config_parser.has_option(section_name, self.key):
            try:
                self.value = config_parser.getint(section_name, self.key)
                self._check_allowed_values()
            except ValueError:
                self.pcluster_config.error("Configuration parameter '{0}' must be an Integer".format(self.key))

        return self

    def get_value_from_string(self, string_value):
        """Return internal representation starting from CFN/user-input value."""
        param_value = self.get_default_value()
        try:
            if string_value is not None:
                string_value = str(string_value).strip()
                if string_value != "NONE":
                    param_value = int(string_value)
        except ValueError:
            self.pcluster_config.warn(
                "Unable to convert the value '{0}' to an Integer. "
                "Using default value for parameter '{1}'".format(string_value, self.key)
            )

        return param_value


class JsonCfnParam(CfnParam):
    """Class to manage json configuration parameters."""

    def from_file(self, config_parser):
        """
        Initialize parameter value from config_parser.

        :param config_parser: the configparser object from which get the parameter
        """
        section_name = get_file_section_name(self.section_key, self.section_label)
        if config_parser.has_option(section_name, self.key):
            config_value = config_parser.get(section_name, self.key)
            self.value = self.get_value_from_string(config_value)
            self._check_allowed_values()

        return self

    def get_value_from_string(self, string_value):
        """Return internal representation starting from CFN/user-input value."""
        param_value = self.get_default_value()
        try:
            if string_value:
                string_value = str(string_value).strip()
                if string_value != "NONE":
                    param_value = yaml.safe_load(string_value)
        except Exception as e:
            self.pcluster_config.error("Error parsing JSON parameter '{0}'. {1}".format(self.key, e))

        return param_value

    def get_default_value(self):
        """Get default value from the Param definition, if there, {} otherwise."""
        return self.definition.get("default", {})

    def get_string_value(self):
        """
        Convert the internal representation into JSON.

        The keys in the Json are sorted alphabetically to produce a predictable and easy to test output.
        """
        return json.dumps(self.value, sort_keys=True)

    def get_cfn_value(self):
        """Convert parameter value into CFN value."""
        return self.get_string_value()


class ExtraJsonCfnParam(JsonCfnParam):
    """Class to manage extra_json configuration parameters."""

    def get_cfn_value(self):
        """
        Convert parameter value into CFN value.

        The extra_json configuration parameter can contain both "cfncluster" or "cluster" keys but cookbook
        recipes require "cfncluster" as key.
        """
        if self.value and "cluster" in self.value:
            self.value["cfncluster"] = self.value.pop("cluster")
        return self.get_string_value()

    def refresh(self):
        """
        Refresh the extra_jason.

        The extra_json configuration parameter can contain both "cfncluster" or "cluster" keys but
        we are using "cluster" in CLI to suggest the users the recommended syntax.
        """
        if self.value and "cfncluster" in self.value:
            self.value["cluster"] = self.value.pop("cfncluster")


class SharedDirCfnParam(CfnParam):
    """
    Class to manage the shared_dir configuration parameter.

    We need this class since the same CFN input parameter "SharedDir" is populated
    from the "shared" parameter of the cluster section (e.g. SharedDir = /shared)
    and the "shared" parameter of the ebs sections (e.g. SharedDir = /shared1,/shared2,NONE,NONE,NONE).
    """

    def to_cfn(self):
        """Convert parameter to CFN representation."""
        cfn_params = {}
        # if not using ebs_settings or
        # if only using 1 volume without specifying shared_dir in EBS section
        # use the shared_dir parameter in cluster section
        ebs_labels = self.pcluster_config.get_section("cluster").get_param_value("ebs_settings")
        if not ebs_labels or (
            len(ebs_labels.split(",")) == 1
            and not self.pcluster_config.get_section("ebs", ebs_labels).get_param_value("shared_dir")
        ):
            cfn_params[self.definition.get("cfn_param_mapping")] = self.get_cfn_value()
        # else: there are shared_dir specified in EBS sections
        # let the EBSSettings populate the SharedDir CFN parameter.
        return cfn_params

    def to_file(self, config_parser, write_defaults=False):
        """Set parameter in the config_parser only if the PclusterConfig object does not contains ebs sections."""
        # if not contains ebs_settings --> single SharedDir
        section_name = get_file_section_name(self.section_key, self.section_label)
        if not self.pcluster_config.get_section("ebs") and (write_defaults or self.value != self.get_default_value()):
            _ensure_section_existence(config_parser, section_name)
            config_parser.set(section_name, self.key, self.get_string_value())
        # else: there are ebs volumes, let the EBSSettings parse the SharedDir CFN parameter.

    def from_cfn_params(self, cfn_params):
        """
        Initialize param value by parsing CFN input only if the scheduler is a traditional one.

        When the SharedDir doesn't contain commas, it has been created from a single EBS volume
        specified through the shared_dir configuration parameter,
        if it contains commas, we need to create at least one ebs section.
        """
        if cfn_params:
            num_of_ebs = int(get_cfn_param(cfn_params, "NumberOfEBSVol"))
            if num_of_ebs == 1 and "," not in get_cfn_param(cfn_params, "SharedDir"):
                super(SharedDirCfnParam, self).from_cfn_params(cfn_params)

        return self


class SpotPriceCfnParam(FloatCfnParam):
    """
    Class to manage the spot_price configuration parameter.

    We need this class since the same CFN input parameter "SpotPrice" is populated
    from the "spot_bid_percentage" parameter when the scheduler is awsbatch and
    from "spot_price" when the scheduler is a traditional one.
    """

    def from_cfn_params(self, cfn_params):
        """Initialize param value by parsing CFN input only if the scheduler is a traditional one."""
        cfn_converter = self.definition.get("cfn_param_mapping", None)
        if cfn_converter and cfn_params:
            if get_cfn_param(cfn_params, "Scheduler") != "awsbatch":
                self.value = float(get_cfn_param(cfn_params, cfn_converter))

        return self

    def get_cfn_value(self):
        """
        Convert parameter value into CFN value.

        Insignificant trailing zeros removed to correctly match CloudFormation conditions using "0" as test value
        """
        return str("{0:g}".format(self.value) if self.value is not None else self.definition.get("default", "NONE"))

    def to_cfn(self):
        """Convert parameter to CFN representation."""
        cfn_params = {}

        cluster_config = self.pcluster_config.get_section(self.section_key)
        if cluster_config.get_param_value("scheduler") != "awsbatch":
            cfn_params[self.definition.get("cfn_param_mapping")] = self.get_cfn_value()

        return cfn_params


class SpotBidPercentageCfnParam(IntCfnParam):
    """
    Class to manage the spot_bid_percentage configuration parameter.

    We need this class since the same CFN input parameter "SpotPrice" is populated
    from the "spot_bid_percentage" parameter when the scheduler is awsbatch and
    from "spot_price" when the scheduler is a traditional one.
    """

    def from_cfn_params(self, cfn_params):
        """Initialize param value by parsing CFN input only if the scheduler is awsbatch."""
        cfn_converter = self.definition.get("cfn_param_mapping", None)
        if cfn_converter and cfn_params:
            if get_cfn_param(cfn_params, "Scheduler") == "awsbatch":
                # we have the same CFN input parameters for both spot_price and spot_bid_percentage
                # so the CFN input could be a float
                self.value = int(float(get_cfn_param(cfn_params, cfn_converter)))

        return self

    def to_cfn(self):
        """Convert parameter to CFN representation."""
        cfn_params = {}

        cluster_config = self.pcluster_config.get_section(self.section_key)
        if cluster_config.get_param_value("scheduler") == "awsbatch":
            cfn_params[self.definition.get("cfn_param_mapping")] = self.get_cfn_value()

        return cfn_params


class QueueSizeCfnParam(IntCfnParam):
    """
    Class to manage both the *_queue_size and *_vcpus configuration parameters.

    We need this class since the same CFN input parameter "*Size" is populated
    from the "*_vcpus" parameter when the scheduler is awsbatch and
    from "*_queue_size" when the scheduler is a traditional one.
    """

    def from_cfn_params(self, cfn_params):
        """Initialize param value by parsing the right CFN input according to the scheduler."""
        cfn_converter = self.definition.get("cfn_param_mapping", None)
        if cfn_converter and cfn_params:
            cfn_value = get_cfn_param(cfn_params, cfn_converter) if cfn_converter else "NONE"

            is_traditional_scheduler_param = get_cfn_param(cfn_params, "Scheduler") != "awsbatch" and (
                self.key == "initial_queue_size" or self.key == "max_queue_size"
            )
            is_awsbatch_param = get_cfn_param(cfn_params, "Scheduler") == "awsbatch" and (
                self.key == "desired_vcpus" or self.key == "max_vcpus" or self.key == "min_vcpus"
            )

            # initialize the value from cfn according to the scheduler
            if is_traditional_scheduler_param or is_awsbatch_param:
                self.value = self.get_value_from_string(cfn_value)

        return self

    def to_cfn(self):
        """Convert parameter to CFN representation."""
        cfn_params = {}

        cluster_config = self.pcluster_config.get_section(self.section_key)
        if (
            # traditional scheduler parameters
            cluster_config.get_param_value("scheduler") != "awsbatch"
            and (self.key == "initial_queue_size" or self.key == "max_queue_size")
        ) or (
            # awsbatch scheduler parameters
            cluster_config.get_param_value("scheduler") == "awsbatch"
            and (self.key == "desired_vcpus" or self.key == "max_vcpus" or self.key == "min_vcpus")
        ):
            cfn_value = cluster_config.get_param_value(self.key)
            cfn_params[self.definition.get("cfn_param_mapping")] = str(cfn_value)

        return cfn_params


class MaintainInitialSizeCfnParam(BoolCfnParam):
    """
    Class to manage the maintain_initial_size configuration parameters.

    We need this class since the same CFN input parameter "MinSize" is populated
    from the "min_vcpus" parameter when the scheduler is awsbatch and
    merging info from "initial_queue_size" and "maintain_initial_size" when the scheduler is a traditional one.
    """

    def from_cfn_params(self, cfn_params):
        """Initialize param value by parsing the right CFN input."""
        cfn_converter = self.definition.get("cfn_param_mapping", None)
        if cfn_converter and cfn_params:
            # initialize the value from cfn only if the scheduler is a traditional one
            if get_cfn_param(cfn_params, "Scheduler") != "awsbatch":
                # MinSize param > 0 means that maintain_initial_size was set to true at cluster creation
                min_size_cfn_value = get_cfn_param(cfn_params, cfn_converter) if cfn_converter else "0"
                min_size_value = int(min_size_cfn_value) if min_size_cfn_value != "NONE" else 0
                self.value = min_size_value > 0

        return self

    def to_cfn(self):
        """Convert parameter to CFN representation."""
        cfn_params = {}

        cluster_config = self.pcluster_config.get_section(self.section_key)
        if cluster_config.get_param_value("scheduler") != "awsbatch":
            cfn_value = cluster_config.get_param_value("maintain_initial_size")
            min_size_value = cluster_config.get_param_value("initial_queue_size") if cfn_value else "0"
            cfn_params.update({self.definition.get("cfn_param_mapping"): str(min_size_value)})

        return cfn_params


class AdditionalIamPoliciesCfnParam(CommaSeparatedCfnParam):
    """
    Class to manage the additional_iam_policies configuration parameters.

    We need this class for 2 reasons:
    * When the scheduler is awsbatch, we need to add/remove the AWSBatchFullAccess policy
      during CFN conversion.
    * When CloudWatch logging is enabled, we need to add/remove the CloudWatchAgentServerPolicy
      during CFN conversion.
    """

    policy_inclusion_rules = [CloudWatchAgentServerPolicyInclusionRule, AWSBatchFullAccessInclusionRule]

    def __init__(self, section_key, section_label, param_key, param_definition, pcluster_config, owner_section=None):
        super(AdditionalIamPoliciesCfnParam, self).__init__(
            section_key, section_label, param_key, param_definition, pcluster_config, owner_section
        )

    def get_string_value(self):
        """Convert internal representation into string. Conditionally enabled policies are not written."""
        non_conditional_iam_policies = self._non_conditional_iam_policies()
        return str(",".join(non_conditional_iam_policies)) if non_conditional_iam_policies else None

    def refresh(self):
        """Refresh the additional IAM policies by adding conditional policies, if needed."""
        additional_policies = set(self.value)
        for rule in AdditionalIamPoliciesCfnParam.policy_inclusion_rules:
            if rule.policy_is_required(self.pcluster_config) and rule.get_policy() not in additional_policies:
                additional_policies.add(rule.get_policy())
        self.value = sorted(additional_policies)

    def _non_conditional_iam_policies(self):
        """Given a list of IAM policies return a new list containing only the non conditional ones."""
        policies = set(self.value)  # List is cloned to avoid modifying self value
        for rule in self.policy_inclusion_rules:
            if rule.policy_is_required(self.pcluster_config):
                policies.discard(rule.get_policy())
        return sorted(policies)


class AvailabilityZoneCfnParam(CfnParam):
    """
    Base class to manage availability_zone internal attribute.

    This parameter is not exposed as configuration parameter in the file but it exists as CFN parameter
    and it is used for master_availability_zone and compute_availability_zone.
    """

    def _init_az(self, config_parser, subnet_parameter):
        section_name = get_file_section_name(self.section_key, self.section_label)
        if config_parser.has_option(section_name, subnet_parameter):
            subnet_id = config_parser.get(section_name, subnet_parameter)
            self.value = get_availability_zone_of_subnet(subnet_id)
            self._check_allowed_values()

    def to_file(self, config_parser, write_defaults=False):
        """Do nothing, because master_availability_zone it is an internal parameter, not exposed in the config file."""
        pass


class HeadNodeAvailabilityZoneCfnParam(AvailabilityZoneCfnParam):
    """
    Class to manage master_availability_zone internal attribute.

    This parameter is not exposed as configuration parameter in the file but it exists as CFN parameter
    and it is used during EFS conversion and validation.
    """

    def from_file(self, config_parser):
        """Initialize the Availability zone of the cluster by checking the head node Subnet."""
        self._init_az(config_parser, "master_subnet_id")

        return self

    def from_cfn_params(self, cfn_params):
        """Initialize the Availability zone by checking the head node subnet from cfn."""
        head_node_subnet_id = get_cfn_param(cfn_params, "MasterSubnetId")
        self.value = get_availability_zone_of_subnet(head_node_subnet_id)
        return self


class ComputeAvailabilityZoneCfnParam(AvailabilityZoneCfnParam):
    """
    Class to manage compute_availability_zone internal attribute.

    This parameter is not exposed as configuration parameter in the file but it exists as CFN parameter
    and it is used during EFS conversion and validation.
    """

    def from_file(self, config_parser):
        """Initialize the Availability zone of the cluster by checking the Compute Subnet."""
        self._init_az(config_parser, "compute_subnet_id")

        return self

    def from_cfn_params(self, cfn_params):
        """Initialize the Availability zone by checking the Compute Subnet from cfn."""
        compute_subnet_id = get_cfn_param(cfn_params, "ComputeSubnetId")
        self.value = get_availability_zone_of_subnet(compute_subnet_id)
        return self


class DisableHyperThreadingCfnParam(BoolCfnParam):
    """
    Class to manage the disable_hyperthreading configuration parameter.

    We need this class in order to convert the boolean disable_hyperthreading = [true/false] into Cores.
    """

    def from_cfn_params(self, cfn_params):
        """Initialize param value by parsing the right CFN input."""
        try:
            cfn_converter = self.definition.get("cfn_param_mapping", None)
            if cfn_converter and cfn_params:
                cores = get_cfn_param(cfn_params, cfn_converter)
                if cores and not cores.startswith("NONE,NONE"):
                    cores = int(cores.split(",")[0])
                    self.value = cores > 0
        except (ValueError, IndexError):
            self.pcluster_config.warn("Unable to parse Cfn Parameter Cores = {0}".format(cfn_params))

        return self

    @staticmethod
    def _get_cfn_params_for_instance_type(instance_type):
        """
        Return a pair describing whether or not to disable HT for the instance_type and how to do so.

        The first item in the pair is an integer representing a core count for the instance type when
        HT is disabled (or "NONE" if it shouldn't be disabled). The second item is a boolean expressing
        if HT should be disabled via CPU Options for the given instance type.
        """
        instance_type_info = InstanceTypeInfo.init_from_instance_type(instance_type)
        default_threads_per_core = instance_type_info.default_threads_per_core()
        if default_threads_per_core == 1:
            # no action is required to disable hyperthreading
            cores = "NONE"
        else:
            cores = instance_type_info.vcpus_count() // default_threads_per_core

        return cores, disable_ht_via_cpu_options(instance_type)

    def to_cfn(self):
        """
        Define the Cores CFN parameter if disable_hyperthreading = true.

        :return: string (head_node_cores,compute_cores,head_node_supports_cpu_options,compute_supports_cpu_options)
        """
        cfn_params = {self.definition.get("cfn_param_mapping"): "NONE,NONE,NONE,NONE"}
        cluster_config = self.pcluster_config.get_section(self.section_key)
        if self.value:
            head_node_instance_type = cluster_config.get_param_value("master_instance_type")
            head_node_cores, disable_head_node_ht_via_cpu_options = self._get_cfn_params_for_instance_type(
                head_node_instance_type
            )

            if (
                self.pcluster_config.cluster_model.name == "SIT"
                and cluster_config.get_param_value("scheduler") != "awsbatch"
            ):
                # compute_instance_type parameter is valid only in SIT clusters
                compute_instance_type = cluster_config.get_param_value("compute_instance_type")
                compute_cores, disable_compute_ht_via_cpu_options = self._get_cfn_params_for_instance_type(
                    compute_instance_type
                )
            else:
                compute_instance_type = None
                compute_cores = 0
                disable_compute_ht_via_cpu_options = False

            for node_label, cores, instance_type in [
                ("master", head_node_cores, head_node_instance_type),
                ("compute", compute_cores, compute_instance_type),
            ]:
                if isinstance(cores, int) and cores < 0:
                    self.pcluster_config.error(
                        "For disable_hyperthreading, unable to get number of vcpus for {0} instance type {1}. "
                        "Please open an issue {2}".format(node_label, instance_type, PCLUSTER_ISSUES_LINK)
                    )
            cfn_params.update(
                {
                    self.definition.get("cfn_param_mapping"): "{0},{1},{2},{3}".format(
                        head_node_cores,
                        compute_cores,
                        str(disable_head_node_ht_via_cpu_options).lower(),
                        str(disable_compute_ht_via_cpu_options).lower(),
                    )
                }
            )

        return cfn_params


class ClusterConfigMetadataCfnParam(JsonCfnParam):
    """
    Class to manage configuration metadata.

    Uses an internal ResourceMap to manage section labels in order to ensure proper correspondence between the section
    labels and their corresponding CloudFormation resources.
    """

    def _from_definition(self):
        self.value = self.get_default_value()
        self.__section_resources = ResourceMap(self.value.get("sections"))

    def from_cfn_params(self, cfn_params):
        """Initialize parameter by parsing CFN parameters."""
        super(JsonCfnParam, self).from_cfn_params(cfn_params)
        self.__section_resources = ResourceMap(self.value.get("sections"))
        return self

    def __store_section_labels(self, section_key):
        """Store all the section labels corresponding to the provided section key into the internal ResourceMap."""
        section = self.pcluster_config.get_section(section_key)
        if section and section.has_metadata():
            labels = [section.label for section in self.pcluster_config.get_sections(section.key).values()]

            if not self.__section_resources.resources(section.key):
                # Allocating more resources than allowed is fine here. Integrity check is performed by validation.
                self.__section_resources.alloc(section.key, max(section.max_resources, len(labels)))

            self.__section_resources.store(section.key, labels)

    def get_cfn_value(self):
        """Get value to store in CloudFormation."""
        return self.get_string_value()

    def get_default_value(self):
        """Get default value from the Param definition."""
        return self.definition.get("default", {"sections": {}})

    def refresh(self):
        """
        Refresh the configuration metadata.

        The operation is done by storing all section labels of the parent PClusterConfig instance into the internal
        ResourceMap and then setting them back into the "sections" key of the parameter's Json value.
        This allows the original order of the labels to be maintained when the configuration has been loaded from cfn.
        """
        for section_key in self.pcluster_config.get_section_keys():
            self.__store_section_labels(section_key)
        self.value["sections"] = self.__section_resources.resources()

    def get_section_resources(self, section_key):
        """Get the resources linked to a specific section key in the configuration metadata."""
        return self.__section_resources.resources(section_key)

    def create_section_resources(self, section_key, num_labels, max_resources):
        """
        Create automatic section resource labels for the provided section key.

        :param section_key The section key
        :param num_labels The number of labels to create
        :param max_resources The max number of resources to allocate for this section key
        """
        self.__section_resources.alloc(section_key, max_resources)
        section_labels = ["{0}{1}".format(section_key, str(index + 1)) for index in range(num_labels)]
        self.__section_resources.store(section_key, section_labels)
        LOGGER.debug("Automatic labels generated: {0}".format(str(section_labels)))
        # Refresh param value
        self.__resources_to_value()
        return self.__section_resources.resources(section_key)

    def __resources_to_value(self):
        """Sync data from internal resources structure to param value."""
        self.value["sections"] = self.__section_resources.resources()


class BaseOSCfnParam(CfnParam):
    """
    Class to manage the base_os configuration parameter.

    We need this class in order to initialize the private architecture param.
    """

    @staticmethod
    def get_instance_type_architecture(instance_type):
        """Compute cluster's 'Architecture' CFN parameter based on its head node instance type."""
        if not instance_type:
            error("Cannot infer architecture without head node instance type")
        head_node_supported_architectures = get_supported_architectures_for_instance_type(instance_type)

        if not head_node_supported_architectures:
            error("Unable to get architectures supported by instance type {0}.".format(instance_type))
        # If the instance type supports multiple architectures, choose the first one.
        # TODO: this is currently not an issue because none of the instance types we support more than one of the
        #       architectures we support. If this were ever to change (e.g., we start supporting i386) then we would
        #       probably need to choose based on the subset of the architecutres supported by both the head node and
        #       compute instance types.
        return head_node_supported_architectures[0]

    def refresh(self):
        """Initialize the private architecture param."""
        if self.value:
            head_node_instance_type = self.owner_section.get_param_value("master_instance_type")
            architecture = self.get_instance_type_architecture(head_node_instance_type)
            self.owner_section.get_param("architecture").value = architecture


class ArgsCfnParam(CfnParam):
    """
    Class to manage the pre/post_install_args configuration parameter.

    We need this class in order to escape the args to json param.
    """

    def from_cfn_params(self, cfn_params):
        """
        Initialize parameter value by parsing CFN input parameters.

        :param cfn_params: list of all the CFN parameters, used if "cfn_param_mapping" is specified in the definition
        """
        cfn_converter = self.definition.get("cfn_param_mapping", None)
        if cfn_params:
            cfn_value = get_cfn_param(cfn_params, cfn_converter) if cfn_converter else "NONE"
            self.value = self.get_value_from_string(json.loads('"' + cfn_value + '"'))

        return self

    def to_cfn(self):
        """Convert param to CFN representation, if "cfn_param_mapping" attribute is present in the Param definition."""
        cfn_params = {}
        cfn_converter = self.definition.get("cfn_param_mapping", None)

        if cfn_converter:
            cfn_value = self.get_cfn_value()
            # use index to trim the redundant quotes, for example, config file "R wget" -> cfn_value = '"R wget"'
            # after json escape, cfn_value = '"/"R wget/""' -> we need '/"R wget/"' for pre/post install args
            cfn_params[cfn_converter] = json.dumps(cfn_value)[1:-1]

        return cfn_params


class ComputeInstanceTypeCfnParam(CfnParam):
    """
    Class to manage the compute instance type parameter.

    We need this class in order to set the default instance type from a boto3 call.
    """

    def refresh(self):
        """Get default value from a boto3 call for free tier instance type."""
        if not self.value:
            scheduler = self.pcluster_config.get_section("cluster").get_param_value("scheduler")
            if scheduler:
                self.value = "optimal" if scheduler == "awsbatch" else get_default_instance_type()


class HeadNodeInstanceTypeCfnParam(CfnParam):
    """
    Class to manage the head node instance type parameter.

    We need this class in order to set the default instance type from a boto3 call.
    """

    def refresh(self):
        """Get default value from a boto3 call for free tier instance type."""
        if not self.value:
            self.value = get_default_instance_type()


class TagsParam(JsonCfnParam):
    """
    Class to manage the tags json configuration parameter.

    Tags are stored in CFN as a separate field instead of inside parameters in CFN.
    Therefore, we need to overwrite the from_storage function
    """

    def from_storage(self, storage_params):
        """Load the param from the related storage data structure."""
        return self.from_cfn_tag(storage_params.cfn_tags)

    def from_cfn_tag(self, cfn_tags):
        """Initialize custom tags."""
        if cfn_tags:
            for tag in cfn_tags:
                key = tag.get("Key")
                if key == "Version":
                    # Skip default "Version" tag
                    continue
                self.value[key] = tag.get("Value")
        return self


# ---------------------- SettingsParams ---------------------- #
class SettingsCfnParam(SettingsParam):
    """Class to manage *_settings parameter on which the value is a single value (e.g. vpc_settings = default)."""

    def from_storage(self, storage_params):
        """Initialize section configuration parameters referred by the settings value by parsing CFN parameters."""
        self.value = self.get_default_value()
        section_labels = self.get_metadata_labels()
        label = section_labels[0] if section_labels else None

        # Section if rebuilt only if section label is found in cluster metadata
        if label:
            if storage_params:
                section = self.referred_section_type(
                    self.referred_section_definition, self.pcluster_config, section_label=label
                ).from_storage(storage_params)
                self._replace_default_section(section)

        return self

    def to_storage(self, storage_params):
        """Convert the referred section to CFN representation."""
        section_labels = self.get_metadata_labels()

        if self.referred_section_definition.get("max_resources", 1) > 1:
            # Multiple section
            for section_label in [section_label for section_label in section_labels if section_label is not None]:
                section = self.pcluster_config.get_section(self.referred_section_key, section_label.strip())
                section.to_storage(storage_params)
        else:
            # Single section
            section = self.pcluster_config.get_section(self.referred_section_key, self.value)
            if not section:
                # Create a default section to populate with default values (e.g. NONE)
                section = self.referred_section_type(self.referred_section_definition, self.pcluster_config)

            section.to_storage(storage_params)

    def get_metadata_labels(self, expected_num_labels=0, include_none_values=True):
        """
        Return the sections labels of this Settings param respecting their order in the cluster config metadata.

        If the config metadata has been restored from CloudFormation, for instance in the context of a pcluster update
        operation, this method ensures that the labels already stored in metadata will maintain their positions, so that
        their correspondence with the existing CloudFormation resources is respected.
        Important: calling this method is safe from all stages of configuration loading / writing  because the
        CloudFormationMetadata parameter is the first to be loaded.

        :param expected_num_labels: number of expected labels
        :param include_none_values: Include None values in the result
        :returns: The labels list as stored in config metadata
        """
        metadata = self.pcluster_config.get_section("cluster").get_param("cluster_config_metadata")
        section_labels = metadata.get_section_resources(self.referred_section_key)
        if not section_labels:
            section_labels = self.value.split(",") if self.value else None

        # Automatic section labels creation if no metadata information is found.
        # This condition is expected in two cases:
        #   1) when loading sections from cfn which where not present in the original config file (these sections will
        #      contain all default parameter values)
        #   2) in unit tests that build the configuration on the fly
        if not section_labels:
            max_resources = int(self.referred_section_definition.get("max_resources", "1"))
            section_labels = metadata.create_section_resources(
                self.referred_section_key, expected_num_labels, max_resources
            )

        if not include_none_values:
            section_labels = [label for label in section_labels if label is not None]

        return section_labels


class EBSSettingsCfnParam(SettingsCfnParam):
    """
    Class to manage ebs_settings parameter.

    We require a specific class for EBS settings because multiple parameters from multiple sections
    are merged together to create CFN parameters.
    Furthermore, as opposed to SettingsParam, the value can be a comma separated value (e.g. ebs_settings = ebs1,ebs2).
    """

    def from_storage(self, storage_params):
        """Init ebs section only if there are more than one ebs (the default one)."""
        labels = []
        if storage_params.cfn_params:
            cfn_params = storage_params.cfn_params
            # FIXME: remove NumberOfEBSVol Parameter and use EBS section params to manage EBS Volumes in cfn template
            # fix ebs substack - this code can be reused for back compatibility
            num_of_ebs = int(get_cfn_param(cfn_params, "NumberOfEBSVol"))
            if num_of_ebs >= 1 and "ebs" in get_cfn_param(cfn_params, "ClusterConfigMetadata"):
                # If "ebs" is in "ClusterConfigMetadata", there are at least one ebs section configured
                labels = self.get_metadata_labels(expected_num_labels=num_of_ebs, include_none_values=False)
                for index in range(len(labels)):
                    # create empty section
                    referred_section_type = self.referred_section_definition.get("type", CfnSection)
                    referred_section = referred_section_type(
                        self.referred_section_definition, self.pcluster_config, labels[index]
                    )

                    for param_key, param_definition in self.referred_section_definition.get("params").items():
                        cfn_converter = param_definition.get("cfn_param_mapping", None)
                        if cfn_converter:

                            param_type = param_definition.get("type", CfnParam)
                            cfn_value = get_cfn_param(cfn_params, cfn_converter).split(",")[index]
                            param = param_type(
                                referred_section.key,
                                referred_section.label,
                                param_key,
                                param_definition,
                                self.pcluster_config,
                            ).from_cfn_value(
                                None
                                if param_key == "shared_dir" and "," not in get_cfn_param(cfn_params, "SharedDir")
                                else cfn_value
                            )
                            # When the SharedDir doesn't contain commas, it has been created from a single EBS volume
                            # specified through the shared_dir configuration parameter in the cluster section
                            # If SharedDir contains comma, we need to create at least one ebs section
                            referred_section.add_param(param)

                    self.pcluster_config.add_section(referred_section)

        self.value = ",".join(labels) if labels else None

        return self

    def to_file(self, config_parser, write_defaults=False):
        """Convert the param value into a list of sections in the config_parser and initialize them."""
        sections = []
        if self.value:
            for section_label in self.value.split(","):
                sections.append(self.pcluster_config.get_section(self.referred_section_key, section_label.strip()))

        if sections:
            section_name = get_file_section_name(self.section_key, self.section_label)
            # add "*_settings = *" to the parent section
            _ensure_section_existence(config_parser, section_name)
            config_parser.set(section_name, self.key, self.get_string_value())

            # create sections
            for section in sections:
                section.to_file(config_parser)

    def to_storage(self, storage_params):
        """Convert a list of sections to multiple CFN params."""
        sections = OrderedDict({})

        # Section labels are retrieved from configuration metadata rather than directly from the ebs_settings param
        # to respect the original order of Cfn resources
        section_labels = self.get_metadata_labels()

        for section_label in [section_label for section_label in section_labels if section_label is not None]:
            section = self.pcluster_config.get_section(self.referred_section_key, section_label.strip())
            sections[section_label] = section

        cfn_params = storage_params.cfn_params
        number_of_ebs_sections = len(sections)
        for param_key, param_definition in self.referred_section_definition.get("params").items():
            if param_key == "shared_dir":
                # The same CFN parameter is used for both single and multiple EBS cases
                # if there are no EBS volumes, or if user does not specify shared_dir when using 1 EBS volume
                # let the SharedDirParam populate the "SharedDir" CFN parameter.
                if number_of_ebs_sections == 0 or (
                    number_of_ebs_sections == 1 and not next(iter(sections.values())).get_param_value("shared_dir")
                ):
                    continue

            cfn_converter = param_definition.get("cfn_param_mapping", None)
            if cfn_converter:

                cfn_value_list = []
                for section_label in section_labels:
                    if section_label:
                        section = sections[section_label]
                        param = section.get_param(param_key)
                    else:
                        # Create a default param
                        param_type = param_definition.get("type", CfnParam)
                        param = param_type(
                            self.referred_section_key, "default", param_key, param_definition, self.pcluster_config
                        )
                    cfn_value_list.append(param.to_cfn().get(cfn_converter))

                cfn_value = ",".join(cfn_value_list)
                cfn_params[cfn_converter] = cfn_value

        # We always have at least one EBS volume
        # FIXME: remove NumberOfEBSVol Parameter and use EBS section params to manage EBS Volumes in cfn template
        cfn_params["NumberOfEBSVol"] = str(max(number_of_ebs_sections, 1))


class NetworkInterfacesCountCfnParam(CommaSeparatedCfnParam):
    """
    Class to manage NetworkInterfacesCount Cfn param.

    The internal value is a list of two items, which respectively indicate the number of network interfaces to activate
    on head node and compute nodes.
    """

    def refresh(self):
        """Compute the number of network interfaces for head node and compute nodes."""
        cluster_section = self.pcluster_config.get_section("cluster")
        scheduler = cluster_section.get_param_value("scheduler")
        compute_instance_type = (
            cluster_section.get_param_value("compute_instance_type")
            if self.pcluster_config.cluster_model.name == "SIT" and scheduler != "awsbatch"
            else None
        )
        self.value = [
            str(
                InstanceTypeInfo.init_from_instance_type(
                    cluster_section.get_param_value("master_instance_type")
                ).max_network_interface_count()
            ),
            str(InstanceTypeInfo.init_from_instance_type(compute_instance_type).max_network_interface_count())
            if compute_instance_type
            else "1",
        ]


# ---------------------- Sections ---------------------- #
class CfnSection(Section):
    """Class to manage configuration sections with storage persistence in CloudFormation."""

    def from_storage(self, storage_params):
        """Initialize section configuration parameters by parsing CFN parameters."""
        cfn_converter = self.definition.get("cfn_param_mapping", None)
        if cfn_converter:
            # It is a section converted to a single CFN parameter
            cfn_values = get_cfn_param(storage_params.cfn_params, cfn_converter).split(",")

            cfn_param_index = 0
            for param_key, param_definition in self.definition.get("params").items():
                try:
                    cfn_value = cfn_values[cfn_param_index]
                except IndexError:
                    # This happen if the expected comma separated CFN param doesn't exist in the Stack,
                    # so it is set to a single NONE value
                    cfn_value = "NONE"

                param_type = param_definition.get("type", CfnParam)
                param = param_type(
                    self.key, self.label, param_key, param_definition, self.pcluster_config, owner_section=self
                ).from_cfn_value(cfn_value)

                self.add_param(param)
                cfn_param_index += 1
        else:
            for param_key, param_definition in self.definition.get("params").items():
                param_type = param_definition.get("type", CfnParam)
                param = param_type(
                    self.key, self.label, param_key, param_definition, self.pcluster_config, owner_section=self
                ).from_storage(storage_params)
                self.add_param(param)

        return self

    def to_storage(self, storage_params=None):
        """
        Convert section to CFN representation.

        The section is converted to a single CFN parameter if "cfn_param_mapping" is present in the Section definition,
        otherwise each parameter of the section will be converted to the respective CFN parameter.
        """
        if not storage_params:
            storage_params = StorageData({}, {})

        cfn_converter = self.definition.get("cfn_param_mapping", None)
        if cfn_converter:
            # it is a section converted to a single CFN parameter
            cfn_items = []
            for param_key, param_definition in self.definition.get("params").items():
                param = self.get_param(param_key)
                if param:
                    cfn_items.append(param.get_cfn_value())
                else:
                    param_type = param_definition.get("type", CfnParam)
                    param = param_type(self.key, self.label, param_key, param_definition, self.pcluster_config)
                    cfn_items.append(param.get_cfn_value())

            if cfn_items[0] == "NONE":
                # empty dict or first item is NONE --> set all values to NONE
                cfn_items = ["NONE"] * len(self.definition.get("params"))

            storage_params.cfn_params[cfn_converter] = ",".join(cfn_items)
        else:
            # get value from config object
            for param_key, param_definition in self.definition.get("params").items():
                param = self.get_param(param_key)
                if param:
                    param.to_storage(storage_params)
                else:
                    # set CFN value from a default param
                    param_type = param_definition.get("type", Param)
                    param = param_type(self.key, self.label, param_key, param_definition, self.pcluster_config)
                    param.to_storage(storage_params)

        return storage_params

    def get_default_param_type(self):
        """Get the default Param type managed by the Section type."""
        return CfnParam


class EFSCfnSection(CfnSection):
    """
    Class to manage [efs ...] section.

    We need to define this class because during the CFN conversion it is required to perform custom actions.
    """

    def to_storage(self, storage_params=None):
        """
        Convert section to CFN representation.

        In addition to the conversion of the parameter contained in the section definition,
        it also add a final value in the CFN param that identifies if exists or not
        a valid Mount Target for the given EFS FS Id.
        """
        if not storage_params:
            storage_params = StorageData({}, {})
        cfn_params = storage_params.cfn_params
        cfn_converter = self.definition.get("cfn_param_mapping", None)

        cfn_items = []
        for param_key, param_definition in self.definition.get("params").items():
            param = self.get_param(param_key)
            if param:
                cfn_items.append(param.get_cfn_value())
            else:
                param_type = param_definition.get("type", CfnParam)
                param = param_type(self.key, self.label, param_key, param_definition, self.pcluster_config)
                cfn_items.append(param.get_cfn_value())

        if cfn_items[0] == "NONE":
            head_node_mt_valid = False
            compute_mt_valid = False
            head_node_avail_zone = "fake_az1"
            compute_avail_zone = "fake_az2"
            # empty dict or first item is NONE --> set all values to NONE
            cfn_items = ["NONE"] * len(self.definition.get("params"))
        else:
            # add another CFN param that will identify if create or not a Mount Target for the given EFS FS Id
            head_node_avail_zone = self.pcluster_config.get_head_node_availability_zone()
            head_node_mount_target_id = get_efs_mount_target_id(
                efs_fs_id=self.get_param_value("efs_fs_id"), avail_zone=head_node_avail_zone
            )
            compute_avail_zone = self.pcluster_config.get_compute_availability_zone()
            compute_mount_target_id = get_efs_mount_target_id(
                efs_fs_id=self.get_param_value("efs_fs_id"), avail_zone=compute_avail_zone
            )
            head_node_mt_valid = bool(head_node_mount_target_id)
            compute_mt_valid = bool(compute_mount_target_id)

        cfn_items.append("Valid" if head_node_mt_valid else "NONE")
        # Do not create additional compute mount target if compute and head node subnet in the same AZ
        cfn_items.append("Valid" if compute_mt_valid or (head_node_avail_zone == compute_avail_zone) else "NONE")
        cfn_params[cfn_converter] = ",".join(cfn_items)

        return storage_params


class ClusterCfnSection(CfnSection):
    """
    Class to manage [cluster ...] section.

    We need to define this class because during the CFN conversion it is required to manage another CFN param
    that identifies the label in the template.
    """

    def from_storage(self, storage_params):
        """Initialize section configuration parameters by parsing CFN parameters."""
        if storage_params:
            super(ClusterCfnSection, self).from_storage(storage_params)

        # Update section label from metadata
        section_metadata = self.get_param_value("cluster_config_metadata").get("sections").get("cluster")
        self.label = section_metadata[0] if section_metadata else "default"

        return self

    def to_storage(self, storage_params=None):
        """Convert section to CFN representation."""
        if not storage_params:
            storage_params = StorageData({}, {})

        super(ClusterCfnSection, self).to_storage(storage_params)
        return storage_params


class VolumeSizeParam(IntCfnParam):
    """Class to manage ebs volume_size parameter."""

    def refresh(self):
        """
        We need this method to check whether the user have an input on ebs volume_size.

        If the volume_size is not specified by an user, we will create an EBS volume with default volume size. The
        default volume size would be 20 if it is not created from a specified snapshot, otherwise it will be equal to
        the size of the specified EBS snapshot.
        """
        section = self.pcluster_config.get_section(self.section_key, self.section_label)
        if section and section.get_param_value("volume_size") is None:
            if section.get_param_value("ebs_snapshot_id"):
                ebs_snapshot_id = section.get_param_value("ebs_snapshot_id")
                default_volume_size = get_ebs_snapshot_info(ebs_snapshot_id).get("VolumeSize")
            else:
                default_volume_size = 500 if section.get_param_value("volume_type") in ["st1", "sc1"] else 20
            self.value = default_volume_size


class VolumeIopsParam(IntCfnParam):
    """Class to manage ebs volume_iops parameter in the EBS section."""

    EBS_VOLUME_TYPE_IOPS_DEFAULT = {
        "io1": 100,
        "io2": 100,
        "gp3": 3000,
    }

    def refresh(self):
        """
        We need this method to set different default value for ebs IOPS for different volume.

        Check whether the user have an input on ebs volume_iops when specify volume type to be "gp3".
        For "gp3", the default iops is 3000. For other volumes, the default iops are 100. If the volume_iops is not
        specified by an user, we will create an EBS volume with default volume
        iops.
        """
        section = self.pcluster_config.get_section(self.section_key, self.section_label)

        if section and section.get_param_value("volume_iops") is None:
            volume_type = section.get_param_value("volume_type")
            if volume_type in VolumeIopsParam.EBS_VOLUME_TYPE_IOPS_DEFAULT:
                default_iops = VolumeIopsParam.EBS_VOLUME_TYPE_IOPS_DEFAULT.get(volume_type)
                self.value = default_iops


class FSxMountNameParam(CfnParam):
    """Class to manage FSx MountName."""

    def refresh(self):
        """Retrieve the MountName for existing filesystem and pass to cookbook for mounting."""
        section = self.pcluster_config.get_section(self.section_key, self.section_label)
        if section:
            fs_id = section.get_param_value("fsx_fs_id")
            if fs_id and fs_id != "NONE":
                file_system = get_fsx_info(fs_id)
                self.value = file_system.get("LustreConfiguration").get("MountName")


class FSxDNSNameParam(CfnParam):
    """Class to manage FSx DNSName."""

    def refresh(self):
        """
        Retrieve the DNSName for existing filesystem and pass to cookbook for mounting.

        This is needed because some old filesystems in China have .com instead of .com.cn domain.
        For newer filesystems the DNS name can be generated: <fsx-id>.fsx.<region>.amazonaws.<partition-domain>
        """
        section = self.pcluster_config.get_section(self.section_key, self.section_label)
        if section:
            fs_id = section.get_param_value("fsx_fs_id")
            if fs_id and fs_id != "NONE":
                file_system = get_fsx_info(fs_id)
                self.value = file_system.get("DNSName")
