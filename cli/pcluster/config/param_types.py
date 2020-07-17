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
from future.moves.collections import OrderedDict

import json
import logging
import re
import sys

from configparser import NoSectionError

import yaml
from pcluster.config.iam_policy_rules import AWSBatchFullAccessInclusionRule, CloudWatchAgentServerPolicyInclusionRule
from pcluster.config.resource_map import ResourceMap
from pcluster.config.update_policy import UpdatePolicy
from pcluster.constants import DEFAULT_ARCHITECTURE, PCLUSTER_ISSUES_LINK
from pcluster.utils import (
    error,
    get_avail_zone,
    get_cfn_param,
    get_efs_mount_target_id,
    get_instance_vcpus,
    get_supported_architectures_for_instance_type,
)

LOGGER = logging.getLogger(__name__)

# ---------------------- standard Parameters ---------------------- #
# The following classes represent the Param of the standard types
# like String, Int, Float, Bool and Json
# and how to convert them from/to CFN/file.


class Param(object):
    """Class to manage simple string configuration parameters."""

    def __init__(self, section_key, section_label, param_key, param_definition, pcluster_config):
        self.section_key = section_key
        self.section_label = section_label
        self.key = param_key
        self.definition = param_definition
        self.pcluster_config = pcluster_config

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

    def from_file(self, config_parser):
        """
        Initialize parameter value from config_parser.

        :param config_parser: the configparser object from which get the parameter
        """
        section_name = get_file_section_name(self.section_key, self.section_label)
        if config_parser.has_option(section_name, self.key):
            self.value = config_parser.get(section_name, self.key)
            self._check_allowed_values()

        return self

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

    def to_cfn(self):
        """Convert param to CFN representation, if "cfn_param_mapping" attribute is present in the Param definition."""
        cfn_params = {}
        cfn_converter = self.definition.get("cfn_param_mapping", None)

        if cfn_converter:
            cfn_value = self.get_cfn_value()
            cfn_params[cfn_converter] = str(cfn_value)

        return cfn_params

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

    def get_cfn_value(self):
        """
        Convert parameter value into CFN value.

        Used when the parameter must go into a comma separated CFN parameter.
        """
        return str(self.value if self.value is not None else self.definition.get("default", "NONE"))

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


class CommaSeparatedParam(Param):
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
        return str(",".join(self.value))

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


class FloatParam(Param):
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


class BoolParam(Param):
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


class IntParam(Param):
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


class JsonParam(Param):
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
            # Do not convert empty string and use format and yaml.load in place of json.loads
            # for Python 2.7 compatibility because it returns unicode chars
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


# ---------------------- custom Parameters ---------------------- #
# The following classes represent "custom" parameters
# that require some custom action during CFN/file conversion


class ExtraJsonParam(JsonParam):
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

    def to_file(self, config_parser, write_defaults=False):
        """Set parameter in the config_parser in the right section.

        The extra_json configuration parameter can contain both "cfncluster" or "cluster" keys but
        we are writing "cluster" in the file to suggest the users the recommended syntax.
        """
        if self.value and "cfncluster" in self.value:
            self.value["cluster"] = self.value.pop("cfncluster")
        super(ExtraJsonParam, self).to_file(config_parser)


class SharedDirParam(Param):
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
            config_parser.set(section_name, self.key, self.value)
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
                super(SharedDirParam, self).from_cfn_params(cfn_params)

        return self


class SpotPriceParam(FloatParam):
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


class SpotBidPercentageParam(IntParam):
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


class QueueSizeParam(IntParam):
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


class MaintainInitialSizeParam(BoolParam):
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


class AdditionalIamPoliciesParam(CommaSeparatedParam):
    """
    Class to manage the additional_iam_policies configuration parameters.

    We need this class for 2 reasons:
    * When the scheduler is awsbatch, we need to add/remove the AWSBatchFullAccess policy
      during CFN conversion.
    * When CloudWatch logging is enabled, we need to add/remove the CloudWatchAgentServerPolicy
      during CFN conversion.
    """

    policy_inclusion_rules = [CloudWatchAgentServerPolicyInclusionRule, AWSBatchFullAccessInclusionRule]

    def __init__(self, section_key, section_label, param_key, param_definition, pcluster_config):
        super(AdditionalIamPoliciesParam, self).__init__(
            section_key, section_label, param_key, param_definition, pcluster_config
        )

    def get_string_value(self):
        """Convert internal representation into string. Conditionally enabled policies are not written."""
        non_conditional_iam_policies = self._non_conditional_iam_policies()
        return str(",".join(non_conditional_iam_policies)) if non_conditional_iam_policies else None

    def refresh(self):
        """Refresh the additional IAM policies by adding conditional policies, if needed."""
        additional_policies = set(self.value)
        for rule in AdditionalIamPoliciesParam.policy_inclusion_rules:
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


class AvailabilityZoneParam(Param):
    """
    Base class to manage availability_zone internal attribute.

    This parameter is not exposed as configuration parameter in the file but it exists as CFN parameter
    and it is used for master_availability_zone and compute_availability_zone.
    """

    def _init_az(self, config_parser, subnet_parameter):
        section_name = get_file_section_name(self.section_key, self.section_label)
        if config_parser.has_option(section_name, subnet_parameter):
            subnet_id = config_parser.get(section_name, subnet_parameter)
            self.value = get_avail_zone(subnet_id)
            self._check_allowed_values()

    def to_file(self, config_parser, write_defaults=False):
        """Do nothing, because master_availability_zone it is an internal parameter, not exposed in the config file."""
        pass


class MasterAvailabilityZoneParam(AvailabilityZoneParam):
    """
    Class to manage master_availability_zone internal attribute.

    This parameter is not exposed as configuration parameter in the file but it exists as CFN parameter
    and it is used during EFS conversion and validation.
    """

    def from_file(self, config_parser):
        """Initialize the Availability zone of the cluster by checking the Master Subnet."""
        self._init_az(config_parser, "master_subnet_id")

        return self

    def from_cfn_params(self, cfn_params):
        """Initialize the Availability zone by checking the Compute Subnet from cfn."""
        master_subnet_id = get_cfn_param(cfn_params, "MasterSubnetId")
        self.value = get_avail_zone(master_subnet_id)
        return self


class ComputeAvailabilityZoneParam(AvailabilityZoneParam):
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
        self.value = get_avail_zone(compute_subnet_id)
        return self


class DisableHyperThreadingParam(BoolParam):
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
                if cores and cores != "NONE":
                    cores = int(cores.split(",")[0])
                    self.value = cores > 0
        except (ValueError, IndexError):
            self.pcluster_config.warn("Unable to parse Cfn Parameter Cores = {0}".format(cfn_params))

        return self

    def to_cfn(self):
        """
        Define the Cores CFN parameter as a tuple (cores_master,cores_compute) if disable_hyperthreading = true.

        :return: string (cores_master,cores_compute)
        """
        cfn_params = {self.definition.get("cfn_param_mapping"): "-1,-1"}

        cluster_config = self.pcluster_config.get_section(self.section_key)
        if cluster_config.get_param_value("disable_hyperthreading"):
            master_instance_type = cluster_config.get_param_value("master_instance_type")
            compute_instance_type = cluster_config.get_param_value("compute_instance_type")

            master_cores = get_instance_vcpus(self.pcluster_config.region, master_instance_type) // 2
            compute_cores = get_instance_vcpus(self.pcluster_config.region, compute_instance_type) // 2

            if master_cores < 0 or compute_cores < 0:
                self.pcluster_config.error(
                    "For disable_hyperthreading, unable to get number of vcpus for {0} instance. "
                    "Please open an issue {1}".format(
                        master_instance_type if master_cores < 0 else compute_instance_type, PCLUSTER_ISSUES_LINK
                    )
                )
            cfn_params.update({self.definition.get("cfn_param_mapping"): "{0},{1}".format(master_cores, compute_cores)})

        return cfn_params


class ClusterConfigMetadataParam(JsonParam):
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
        super(JsonParam, self).from_cfn_params(cfn_params)
        self.__section_resources = ResourceMap(self.value.get("sections"))
        return self

    def __store_section_labels(self, section_key):
        """Store all the section labels corresponding to the provided section key into the internal ResourceMap."""
        section = self.pcluster_config.get_section(section_key)
        if section:
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
        return self.__section_resources.resources(section_key)


class ArchitectureParam(Param):
    """
    Class to manage the architecture configuration parameter.

    We need this class in order to compute the derived value given the cluster section's configuration.
    """

    def from_file(self, config_parser):
        """
        Ensure this parameter is not present in the config file.

        This parameter is meant to be derived from other parameters, and should not be specified in the config.
        :param config_parser: the configparser object from which get the parameter
        """
        section_name = get_file_section_name(self.section_key, self.section_label)
        if config_parser.has_option(section_name, self.key):
            self.pcluster_config.error(
                "The parameter '{0}' is a derived parameter and should not be specified in the config".format(self.key)
            )

        return self

    @staticmethod
    def get_master_instance_type_architecture(cluster_section):
        """Compute cluster's 'Architecture' CFN parameter based on its master server instance type."""
        if not cluster_section:
            return DEFAULT_ARCHITECTURE

        master_inst_type = cluster_section.get_param_value("master_instance_type")
        if not master_inst_type:
            error("Cannot infer architecture without master instance type")
        master_inst_supported_architectures = get_supported_architectures_for_instance_type(master_inst_type)

        if not master_inst_supported_architectures:
            error("Unable to get architectures supported by instance type {0}.".format(master_inst_type))
        # If the instance type supports multiple architectures, choose the first one.
        # TODO: this is currently not an issue because none of the instance types we support more than one of the
        #       architectures we support. If this were ever to change (e.g., we start supporting i386) then we would
        #       probably need to choose based on the subset of the architecutres supported by both the master and
        #       compute instance types.
        return master_inst_supported_architectures[0]

    def get_default_value(self):
        """
        Get default value from the Param definition.

        The default value is only allowed to be a function, which is passed a cluster section object.
        """
        section = self.pcluster_config.get_section(self.section_key, self.section_label)
        return self.get_master_instance_type_architecture(section)


# ---------------------- SettingsParam ---------------------- #


class SettingsParam(Param):
    """Class to manage *_settings parameter on which the value is a single value (e.g. vpc_settings = default)."""

    def __init__(self, section_key, section_label, param_key, param_definition, pcluster_config):
        """Extend Param by adding info regarding the section referred by the settings."""
        self.referred_section_definition = param_definition.get("referred_section")
        self.referred_section_key = self.referred_section_definition.get("key")
        self.referred_section_type = self.referred_section_definition.get("type")
        super(SettingsParam, self).__init__(section_key, section_label, param_key, param_definition, pcluster_config)

    def from_file(self, config_parser):
        """
        Initialize parameter value from config_parser.

        :param config_parser: the configparser object from which get the parameter
        """
        section_name = get_file_section_name(self.section_key, self.section_label)
        if config_parser.has_option(section_name, self.key):
            self.value = config_parser.get(section_name, self.key)
            if self.value:
                if "," in self.value:
                    self.pcluster_config.error(
                        "The value of '{0}' parameter is invalid. "
                        "It can only contains a single {1} section label.".format(self.key, self.referred_section_key)
                    )
                else:
                    # Calls the "from_file" of the Section
                    section = self.referred_section_type(
                        self.referred_section_definition, self.pcluster_config, section_label=self.value
                    ).from_file(config_parser, fail_on_absence=True)
                    self._replace_default_section(section)

        return self

    def from_cfn_params(self, cfn_params):
        """Initialize section configuration parameters referred by the settings value by parsing CFN parameters."""
        self.value = self.definition.get("default", None)
        section_labels = self.get_labels_by_cfn_order()
        label = section_labels[0] if section_labels else None

        # Section if rebuilt only if section label is found in cluster metadata
        if label:
            if cfn_params:
                section = self.referred_section_type(
                    self.referred_section_definition, self.pcluster_config, section_label=label
                ).from_cfn_params(cfn_params)
                self._replace_default_section(section)

        return self

    def _from_definition(self):
        self.value = self.definition.get("default", None)
        if self.value:
            # the SettingsParam has a default value, it means that it is required to initialize
            # the related section with default values (e.g. vpc, scaling).
            LOGGER.debug("Initializing default Section '[%s %s]'", self.key, self.value)
            # Use the label defined in the SettingsParam definition
            if "," in self.value:
                self.pcluster_config.error(
                    "The default value of '{0}' parameter is invalid. "
                    "It can only contains a single {1} section label.".format(self.key, self.referred_section_key)
                )
            else:
                # initialize related section with default values
                section = self.referred_section_type(
                    self.referred_section_definition, self.pcluster_config, section_label=self.value
                )
                self.pcluster_config.add_section(section)

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
                    config_parser.set(section_name, self.key, self.value)

            # create section
            section.to_file(config_parser)

    def to_cfn(self):
        """Convert the referred section to CFN representation."""
        cfn_params = {}
        section = self.pcluster_config.get_section(self.referred_section_key, self.value)
        if not section:
            # Crate a default section to populate with default values (e.g. NONE)
            section = self.referred_section_type(self.referred_section_definition, self.pcluster_config)

        cfn_params.update(section.to_cfn())

        return cfn_params

    def refresh(self):
        """Update SettingsParam value to make it match actual sections in config."""
        sections_labels = [
            section.label for _, section in self.pcluster_config.get_sections(self.referred_section_key).items()
        ]

        self.value = ",".join(sorted(sections_labels)) if sections_labels else None

    def get_labels_by_cfn_order(self, expected_num_labels=0, include_none_values=True):
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


class EBSSettingsParam(SettingsParam):
    """
    Class to manage ebs_settings parameter.

    We require a specific class for EBS settings because multiple parameters from multiple sections
    are merged together to create CFN parameters.
    Furthermore, as opposed to SettingsParam, the value can be a comma separated value (e.g. ebs_settings = ebs1,ebs2).
    """

    def from_file(self, config_parser):
        """
        Initialize parameter value from configuration file.

        :param config_parser: the configparser object from which get the parameter
        """
        section_name = get_file_section_name(self.section_key, self.section_label)
        if config_parser.has_option(section_name, self.key):
            self.value = config_parser.get(section_name, self.key)
            if self.value:
                for section_label in self.value.split(","):
                    section = self.referred_section_type(
                        self.referred_section_definition, self.pcluster_config, section_label=section_label.strip()
                    ).from_file(config_parser=config_parser, fail_on_absence=True)
                    self.pcluster_config.add_section(section)

        return self

    def from_cfn_params(self, cfn_params):
        """Init ebs section only if there are more than one ebs (the default one)."""
        labels = []
        if cfn_params:
            # FIXME: remove NumberOfEBSVol Parameter and use EBS section params to manage EBS Volumes in cfn template
            # fix ebs substack - this code can be reused for back compatibility
            num_of_ebs = int(get_cfn_param(cfn_params, "NumberOfEBSVol"))
            if num_of_ebs >= 1 and "," in get_cfn_param(cfn_params, "SharedDir"):
                # When the SharedDir doesn't contain commas, it has been created from a single EBS volume
                # specified through the shared_dir configuration parameter only
                # If SharedDir contains comma, we need to create at least one ebs section
                labels = self.get_labels_by_cfn_order(expected_num_labels=num_of_ebs, include_none_values=False)
                for index in range(len(labels)):
                    # create empty section
                    referred_section_type = self.referred_section_definition.get("type", Section)
                    referred_section = referred_section_type(
                        self.referred_section_definition, self.pcluster_config, labels[index]
                    )

                    for param_key, param_definition in self.referred_section_definition.get("params").items():
                        cfn_converter = param_definition.get("cfn_param_mapping", None)
                        if cfn_converter:

                            param_type = param_definition.get("type", Param)
                            cfn_value = get_cfn_param(cfn_params, cfn_converter).split(",")[index]
                            param = param_type(
                                self.section_key, self.section_label, param_key, param_definition, self.pcluster_config
                            ).from_cfn_value(cfn_value)
                            referred_section.add_param(param)

                    self.pcluster_config.add_section(referred_section)

        self.value = ",".join(labels) if labels else None

        return self

    def to_file(self, config_parser, write_defaults=False):
        """Convert the param value into a list of sections in the config_parser and initialize them."""
        sections = {}
        if self.value:
            for section_label in self.value.split(","):
                sections.update(self.pcluster_config.get_section(self.referred_section_key, section_label.strip()))

        if sections:
            section_name = get_file_section_name(self.section_key, self.section_label)
            # add "*_settings = *" to the parent section
            _ensure_section_existence(config_parser, section_name)
            config_parser.add_section(section_name)

            # create sections
            for _, section in sections:
                section.to_file(config_parser)

    def to_cfn(self):
        """Convert a list of sections to multiple CFN params."""
        sections = OrderedDict({})

        # Section labels are retrieved from configuration metadata rather than directly from the ebs_settings param
        # to respect the original order of Cfn resources
        section_labels = self.get_labels_by_cfn_order()

        for section_label in [section_label for section_label in section_labels if section_label is not None]:
            section = self.pcluster_config.get_section(self.referred_section_key, section_label.strip())
            sections[section_label] = section

        cfn_params = {}
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
                        param_type = param_definition.get("type", Param)
                        param = param_type(
                            self.referred_section_key, "default", param_key, param_definition, self.pcluster_config
                        )
                    cfn_value_list.append(param.to_cfn().get(cfn_converter))

                cfn_value = ",".join(cfn_value_list)
                cfn_params[cfn_converter] = cfn_value

        # We always have at least one EBS volume
        # FIXME: remove NumberOfEBSVol Parameter and use EBS section params to manage EBS Volumes in cfn template
        cfn_params["NumberOfEBSVol"] = str(max(number_of_ebs_sections, 1))

        return cfn_params


# ---------------------- custom Section ---------------------- #
# The following classes represent the Section(s) and how to convert them from/to CFN/file.


class Section(object):
    """Class to manage a generic section (e.g vpc, scaling, aws, etc)."""

    def __init__(self, section_definition, pcluster_config, section_label=None):
        self.definition = section_definition
        self.key = section_definition.get("key")
        self._label = section_label or self.definition.get("default_label", "")
        # All sections have only 1 resource by default, which means they refer to a single Cfn resource or set
        # of resources
        self.max_resources = int(section_definition.get("max_resources", "1"))
        self.pcluster_config = pcluster_config

        # initialize section parameters with default values
        self.params = {}
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

        if config_parser.has_section(section_name):
            for param_key, param_definition in params_definitions.items():
                param_type = param_definition.get("type", Param)

                param = param_type(
                    self.key, self.label, param_key, param_definition, pcluster_config=self.pcluster_config
                ).from_file(config_parser)
                self.add_param(param)

            not_valid_keys = [key for key, value in config_parser.items(section_name) if key not in params_definitions]
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

    def from_cfn_params(self, cfn_params):
        """Initialize section configuration parameters by parsing CFN parameters."""
        cfn_converter = self.definition.get("cfn_param_mapping", None)
        if cfn_converter:
            # It is a section converted to a single CFN parameter
            cfn_values = get_cfn_param(cfn_params, cfn_converter).split(",")

            cfn_param_index = 0
            for param_key, param_definition in self.definition.get("params").items():
                try:
                    cfn_value = cfn_values[cfn_param_index]
                except IndexError:
                    # This happen if the expected comma separated CFN param doesn't exist in the Stack,
                    # so it is set to a single NONE value
                    cfn_value = "NONE"

                param_type = param_definition.get("type", Param)
                param = param_type(
                    self.key, self.label, param_key, param_definition, self.pcluster_config
                ).from_cfn_value(cfn_value)

                self.add_param(param)
                cfn_param_index += 1
        else:
            for param_key, param_definition in self.definition.get("params").items():
                param_type = param_definition.get("type", Param)
                param = param_type(
                    self.key, self.label, param_key, param_definition, self.pcluster_config
                ).from_cfn_params(cfn_params)
                self.add_param(param)

        return self

    def _from_definition(self):
        """Initialize parameters with default values."""
        for param_key, param_definition in self.definition.get("params").items():
            param_type = param_definition.get("type", Param)
            param = param_type(self.key, self.label, param_key, param_definition, self.pcluster_config)
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
                param_type = param_definition.get("type", Param)

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
            param = self.get_param(param_key)
            if not param:
                # generate a default param
                param_type = param_definition.get("type", Param)
                param = param_type(self.key, self.label, param_key, param_definition, self.pcluster_config)

            if write_defaults or param.value != param_definition.get("default", None):
                # add section in the config file only if at least one parameter value is different by the default
                _ensure_section_existence(config_parser, section_name)

            param.to_file(config_parser, write_defaults)

    def to_cfn(self):
        """
        Convert section to CFN representation.

        The section is converted to a single CFN parameter if "cfn_param_mapping" is present in the Section definition,
        otherwise each parameter of the section will be converted to the respective CFN parameter.
        """
        cfn_params = {}
        cfn_converter = self.definition.get("cfn_param_mapping", None)
        if cfn_converter:
            # it is a section converted to a single CFN parameter
            cfn_items = []
            for param_key, param_definition in self.definition.get("params").items():
                param = self.get_param(param_key)
                if param:
                    cfn_items.append(param.get_cfn_value())
                else:
                    param_type = param_definition.get("type", Param)
                    param = param_type(self.key, self.label, param_key, param_definition, self.pcluster_config)
                    cfn_items.append(param.get_cfn_value())

            if cfn_items[0] == "NONE":
                # empty dict or first item is NONE --> set all values to NONE
                cfn_items = ["NONE"] * len(self.definition.get("params"))

            cfn_params[cfn_converter] = ",".join(cfn_items)
        else:
            # get value from config object
            for param_key, param_definition in self.definition.get("params").items():
                param = self.get_param(param_key)
                if param:
                    cfn_params.update(param.to_cfn())
                else:
                    # set CFN value from a default param
                    param_type = param_definition.get("type", Param)
                    param = param_type(self.key, self.label, param_key, param_definition, self.pcluster_config)
                    cfn_params.update(param.to_cfn())

        return cfn_params

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


class EFSSection(Section):
    """
    Class to manage [efs ...] section.

    We need to define this class because during the CFN conversion it is required to perform custom actions.
    """

    def to_cfn(self):
        """
        Convert section to CFN representation.

        In addition to the conversion of the parameter contained in the section definition,
        it also add a final value in the CFN param that identifies if exists or not
        a valid Mount Target for the given EFS FS Id.
        """
        cfn_params = {}
        cfn_converter = self.definition.get("cfn_param_mapping", None)

        cfn_items = []
        for param_key, param_definition in self.definition.get("params").items():
            param = self.get_param(param_key)
            if param:
                cfn_items.append(param.get_cfn_value())
            else:
                param_type = param_definition.get("type", Param)
                param = param_type(self.key, self.label, param_key, param_definition, self.pcluster_config)
                cfn_items.append(param.get_cfn_value())

        if cfn_items[0] == "NONE":
            master_mt_valid = False
            compute_mt_valid = False
            master_avail_zone = "fake_az1"
            compute_avail_zone = "fake_az2"
            # empty dict or first item is NONE --> set all values to NONE
            cfn_items = ["NONE"] * len(self.definition.get("params"))
        else:
            # add another CFN param that will identify if create or not a Mount Target for the given EFS FS Id
            master_avail_zone = self.pcluster_config.get_master_availability_zone()
            master_mount_target_id = get_efs_mount_target_id(
                efs_fs_id=self.get_param_value("efs_fs_id"), avail_zone=master_avail_zone
            )
            compute_avail_zone = self.pcluster_config.get_compute_availability_zone()
            compute_mount_target_id = get_efs_mount_target_id(
                efs_fs_id=self.get_param_value("efs_fs_id"), avail_zone=compute_avail_zone
            )
            master_mt_valid = bool(master_mount_target_id)
            compute_mt_valid = bool(compute_mount_target_id)

        cfn_items.append("Valid" if master_mt_valid else "NONE")
        # Do not create additional compute mount target if compute and master subnet in the same AZ
        cfn_items.append("Valid" if compute_mt_valid or (master_avail_zone == compute_avail_zone) else "NONE")
        cfn_params[cfn_converter] = ",".join(cfn_items)

        return cfn_params


class ClusterSection(Section):
    """
    Class to manage [cluster ...] section.

    We need to define this class because during the CFN conversion it is required to manage another CFN param
    that identifies the label in the template.
    """

    def from_cfn_params(self, cfn_params):
        """Initialize section configuration parameters by parsing CFN parameters."""
        if cfn_params:
            super(ClusterSection, self).from_cfn_params(cfn_params)

        # Update section label from metadata
        section_metadata = self.get_param_value("cluster_config_metadata").get("sections").get("cluster")
        self.label = section_metadata[0] if section_metadata else "default"

        return self

    def to_cfn(self):
        """Convert section to CFN representation."""
        cfn_params = super(ClusterSection, self).to_cfn()
        return cfn_params


def get_file_section_name(section_key, section_label=None):
    return section_key + (" {0}".format(section_label) if section_label else "")


def _ensure_section_existence(config_parser, section_name):
    """Add a section to the config_parser if not present."""
    if not config_parser.has_section(section_name):
        config_parser.add_section(section_name)
