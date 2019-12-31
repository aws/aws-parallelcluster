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

import errno
import inspect
import logging
import os
import stat
import sys

import boto3
import configparser
from botocore.exceptions import ClientError

from pcluster.config.iam_policy_rules import AWSBatchFullAccessInclusionRule, CloudWatchAgentServerPolicyInclusionRule
from pcluster.config.mappings import ALIASES, AWS, CLUSTER, GLOBAL
from pcluster.utils import get_instance_vcpus, get_latest_alinux_ami_id, get_stack, get_stack_name, warn

LOGGER = logging.getLogger(__name__)


class PclusterConfig(object):
    """
    Class to manage the configuration of a cluster created (or to create) with ParallelCluster.

    This class contains a dictionary of sections associated to the given cluster
    """

    policy_inclusion_rules = [CloudWatchAgentServerPolicyInclusionRule, AWSBatchFullAccessInclusionRule]

    def __init__(
        self,
        config_file=None,
        cluster_label=None,  # args.cluster_template
        fail_on_file_absence=False,
        fail_on_error=None,
        cluster_name=None,
    ):
        """
        Initialize object, from file, from a CFN Stack or from the internal mapping.

        NOTE: The class tries to parse the config file (the default one, if not specified) to get AWS credentials

        # "From file" initialization parameters:
        :param config_file: if specified the initialization of the sections will start from the file
        :param cluster_label: the label associated to a [cluster ...] section in the file
        :param fail_on_file_absence: initialization will fail if the specified file or a default one doesn't exist
        :param fail_on_error: tells if initialization must fail in presence of errors. If not set, the behaviour will
        depend on sanity_check parameter in conf file
        # "From Stack" initialization parameters:
        :param cluster_name: the cluster name associated to a running Stack,
        if specified the initialization will start from the running Stack
        """
        self.__stale = False
        self.fail_on_error = fail_on_error
        self.__sections = OrderedDict({})

        # always parse the configuration file if there, to get AWS section
        self._init_config_parser(config_file, fail_on_file_absence)
        # init AWS section
        self.__init_section_from_file(AWS, self.config_parser)
        self.__init_region()
        self.__init_aws_credentials()

        # init pcluster_config object, from cfn or from config_file
        if cluster_name:
            self.__init_sections_from_cfn(cluster_name)
        else:
            self.__init_sections_from_file(cluster_label, self.config_parser, fail_on_file_absence)
            self.__update_conditional_policies()

    def _init_config_parser(self, config_file, fail_on_config_file_absence=True):
        """
        Parse the config file and initialize config_file and config_parser attributes.

        :param config_file: The config file to parse
        :param fail_on_config_file_absence: set to true to raise SystemExit if config file doesn't exist
        """
        if config_file:
            self.config_file = config_file
            default_config = False
        elif "AWS_PCLUSTER_CONFIG_FILE" in os.environ:
            self.config_file = os.environ["AWS_PCLUSTER_CONFIG_FILE"]
            default_config = False
        else:
            config_file = os.path.expanduser(os.path.join("~", ".parallelcluster", "config"))
            default_config = True

        self.config_file = str(
            config_file if config_file else os.path.expanduser(os.path.join("~", ".parallelcluster", "config"))
        )

        if not os.path.isfile(self.config_file):
            if fail_on_config_file_absence:
                error_message = "Configuration file {0} not found."
                if default_config:
                    error_message += (
                        "\nYou can copy a template from {1}{2}examples{2}config "
                        "or execute the 'pcluster configure' command".format(
                            self.config_file,
                            os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))),
                            os.path.sep,
                        )
                    )
                self.error(error_message)
            else:
                LOGGER.debug("Specified configuration file %s doesn't exist.", self.config_file)
        else:
            LOGGER.debug("Parsing configuration file %s", self.config_file)
        self.config_parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
        try:
            self.config_parser.read(self.config_file)
        except configparser.ParsingError as e:
            LOGGER.debug("Error parsing configuration file {0}.\n{1}".format(self.config_file, str(e)))

    def get_sections(self, section_key):
        """
        Get the Section(s) identified by the given key.

        Example of output:
        {
            "ebs" : {
                "ebs1": Section, "ebs2": Section
            }
        }

        :param section_key: the identifier of the section type
        :return a dictionary containing the section
        """
        self.__refresh()
        return self.__sections.get(section_key, {})

    def get_section(self, section_key, section_label=None):
        """
        Get the Section identified by the given key and label.

        Example of output:
        {
            "ebs1": Section
        }

        :param section_key: the identifier of the section type
        :param section_label: the label of the section, returns the first section if empty.
        """
        if section_label:
            section = self.get_sections(section_key).get(section_label, None)
        else:
            sections = self.get_sections(section_key)
            section = next(iter(sections.values()), None) if sections else None
        return section

    def add_section(self, section):
        """
        Add a section to the PclusterConfig object.

        The internal sections structure is a dictionary:
        {
            "ebs" :{"ebs1": Section, "ebs2": Section},
            "vpc" :{"default": Section}
        }

        :param section, a Section object
        """
        if section.key not in self.__sections:
            self.__sections[section.key] = {}

        section_label = section.label if section.label else section.definition.get("default_label", "default")
        self.__sections[section.key][section_label] = section

    def remove_section(self, section_key, section_label):
        """
        Remove a section from the PclusterConfig object, if there.

        :param section_key: the identifier of the section type
        :param section_label: the label of the section to delete.
        """
        if section_key in self.__sections:
            self.__sections[section_key].pop(section_label, None)

    def __init_aws_credentials(self):
        """Set credentials in the environment to be available for all the boto3 calls."""
        # Init credentials by checking if they have been provided in config
        try:
            aws_section = self.get_section("aws")
            aws_access_key_id = aws_section.get_param_value("aws_access_key_id")
            if aws_access_key_id:
                os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key_id

            aws_secret_access_key = aws_section.get_param_value("aws_secret_access_key")
            if aws_secret_access_key:
                os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_access_key
        except AttributeError:
            # If there is no [aws] section in the config file,
            # we rely on the AWS CLI configuration or already set env variable
            pass

    @property
    def region(self):
        """Get the region. The value is stored inside the aws_region_name of the aws section."""
        return self.get_section("aws").get_param_value("aws_region_name")

    @region.setter
    def region(self, region):
        """Set the region. The value is stored inside the aws_region_name of the aws section."""
        self.get_section("aws").get_param("aws_region_name").value = region

    def __init_region(self):
        """
        Evaluate region to use and set in the environment to be available for all the boto3 calls.

        Order is 1) AWS_DEFAULT_REGION env 2) Config file 3) default from mapping
        """
        if os.environ.get("AWS_DEFAULT_REGION"):
            self.region = os.environ.get("AWS_DEFAULT_REGION")
        else:
            os.environ["AWS_DEFAULT_REGION"] = self.region

    @property
    def fail_on_error(self):
        """Get fail_on_error property value. Will fall back to sanity_check parameter if not explicitly set."""
        if self._fail_on_error is None:
            self._fail_on_error = (
                self.get_section("global").get_param_value("sanity_check")
                if self.get_section("global")
                else GLOBAL.get("params").get("sanity_check").get("default")
            )
        return self._fail_on_error

    @fail_on_error.setter
    def fail_on_error(self, fail_on_error):
        """Set fail_on_error property value."""
        self._fail_on_error = fail_on_error

    def to_file(self):
        """Convert the internal representation of the cluster to the relative file sections."""
        for section_key in ["aws", "global", "aliases"]:
            self.get_section(section_key).to_file(self.config_parser, write_defaults=True)

        self.get_section("cluster").to_file(self.config_parser)

        # ensure that the directory for the config file exists
        if not os.path.isfile(self.config_file):
            try:
                config_folder = os.path.dirname(self.config_file) or "."
                os.makedirs(config_folder)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise  # can safely ignore EEXISTS for this purpose...

            # Fix permissions
            with open(self.config_file, "a"):
                os.chmod(self.config_file, stat.S_IRUSR | stat.S_IWUSR)

        # Write configuration to disk
        with open(self.config_file, "w") as conf_file_stream:
            self.config_parser.write(conf_file_stream)

    def to_cfn(self):
        """
        Convert the internal representation of the cluster to a list of CFN parameters.

        :return: a dict containing the cfn parameters associated with the cluster configuration
        """
        return self.get_section("cluster").to_cfn()

    def __init_sections_from_file(self, cluster_label=None, config_parser=None, fail_on_absence=False):
        """
        Initialize all the Sections object and add them to the internal structure by parsing configuration file.

        :param cluster_label: the label of the section (if there)
        :param config_parser: the config parser object to parse
        :param fail_on_absence: if true, the initialization will fail if one section doesn't exist in the file
        """
        for section_definition in [ALIASES, GLOBAL]:
            self.__init_section_from_file(section_definition, config_parser)

        # get cluster by cluster_label
        if not cluster_label:
            cluster_label = (
                self.get_section("global").get_param_value("cluster_template") if self.get_section("global") else None
            )
        self.__init_section_from_file(
            CLUSTER, config_parser, section_label=cluster_label, fail_on_absence=fail_on_absence
        )

    def __init_section_from_file(self, section_definition, config_parser, section_label=None, fail_on_absence=False):
        """
        Initialize the Section object and add it to the internal structure.

        :param section_definition: the definition of the section to initialize
        :param config_parser: the config parser object to parse
        :param section_label: the label of the section (if there)
        :param fail_on_absence: if true, the initialization will fail if the section doesn't exist in the file
        """
        section_type = section_definition.get("type")
        section = section_type(section_definition=section_definition, pcluster_config=self, section_label=section_label)
        self.add_section(section)
        try:
            section.from_file(config_parser, fail_on_absence)
        except configparser.NoSectionError as e:
            self.error("Section '[{0}]' not found in the config file.".format(e.section))

    def __refresh(self):
        """When the object is marked as stale, reload the sections structure."""
        if self.__stale:
            new_sections = OrderedDict({})
            for key, sections in self.__sections.items():
                new_sections_map = {}
                new_sections[key] = new_sections_map
                for _, section in sections.items():
                    new_sections_map[section.label] = section
            self.__sections = new_sections

    def refresh(self):
        """
        Mark the object as stale.

        When the object is marked as stale, the next call to one of its public methods will trigger a refresh operation.
        """
        self.__stale = True

    def __update_conditional_policies(self):
        cluster_section = self.get_section("cluster")
        additional_policies = cluster_section.get_param_value("additional_iam_policies")
        for rule in PclusterConfig.policy_inclusion_rules:
            if rule.policy_is_required(self) and rule.get_policy() not in additional_policies:
                additional_policies.append(rule.get_policy())
        cluster_section.get_param("additional_iam_policies").value = sorted(set(additional_policies))

    def non_conditional_iam_policies(self, iam_policies):
        """Given a list of IAM policies return a new list containing only the non conditional ones."""
        policies = sorted(set(iam_policies))  # List is cloned to avoid modifying self value
        for rule in self.policy_inclusion_rules:
            if rule.get_policy() in policies and rule.policy_is_required(self):
                policies.remove(rule.get_policy())
        return policies

    def __init_sections_from_cfn(self, cluster_name):
        try:
            stack = get_stack(get_stack_name(cluster_name))

            section_type = CLUSTER.get("type")
            section = section_type(section_definition=CLUSTER, pcluster_config=self).from_cfn_params(
                cfn_params=stack.get("Parameters", [])
            )
            self.add_section(section)
        except ClientError as e:
            self.error(
                "Unable to retrieve the configuration of the cluster '{0}'.\n{1}".format(
                    cluster_name, e.response.get("Error").get("Message")
                )
            )

    def validate(self):
        """Validate the configuration."""
        for _, sections in self.__sections.items():
            for _, section in sections.items():
                section.validate()

        # check AWS account limits
        self.__check_account_capacity()

    def get_master_availability_zone(self):
        """Get the Availability zone of the Master Subnet."""
        return self.get_section("vpc").get_param_value("master_availability_zone")

    def get_compute_availability_zone(self):
        """Get the Availability zone of the Compute Subnet."""
        return self.get_section("vpc").get_param_value("compute_availability_zone")

    def __check_account_capacity(self):  # noqa: C901
        """Try to launch the requested number of instances to verify Account limits."""
        cluster_section = self.get_section("cluster")
        vpc_section = self.get_section("vpc")

        if (
            not cluster_section
            or cluster_section.get_param_value("scheduler") == "awsbatch"
            or cluster_section.get_param_value("cluster_type") == "spot"
            or not vpc_section
        ):
            return

        master_instance_type = cluster_section.get_param_value("master_instance_type")
        compute_instance_type = cluster_section.get_param_value("compute_instance_type")
        # get max size
        if cluster_section.get_param_value("scheduler") == "awsbatch":
            max_vcpus = cluster_section.get_param_value("max_vcpus")
            vcpus = get_instance_vcpus(self.region, compute_instance_type)
            max_size = -(-max_vcpus // vcpus)
        else:
            max_size = cluster_section.get_param_value("max_queue_size")
        if max_size < 0:
            warn("Unable to check AWS account capacity. Skipping limits validation")
            return

        # Check for insufficient Account capacity
        compute_subnet = vpc_section.get_param_value("compute_subnet_id")
        master_subnet = vpc_section.get_param_value("master_subnet_id")
        if not compute_subnet:
            compute_subnet = master_subnet

        # Initialize CpuOptions
        disable_hyperthreading = cluster_section.get_param_value("disable_hyperthreading")
        master_vcpus = get_instance_vcpus(self.region, master_instance_type)
        compute_vcpus = get_instance_vcpus(self.region, compute_instance_type)
        master_cpu_options = {"CoreCount": master_vcpus // 2, "ThreadsPerCore": 1} if disable_hyperthreading else {}
        compute_cpu_options = {"CoreCount": compute_vcpus // 2, "ThreadsPerCore": 1} if disable_hyperthreading else {}

        # Initialize Placement Group Logic
        placement_group = cluster_section.get_param_value("placement_group")
        placement = cluster_section.get_param_value("placement")
        master_placement_group = (
            {"GroupName": placement_group}
            if placement_group not in [None, "NONE", "DYNAMIC"] and placement == "cluster"
            else {}
        )
        compute_placement_group = (
            {"GroupName": placement_group} if placement_group not in [None, "NONE", "DYNAMIC"] else {}
        )

        # Test Master Instance Configuration
        self.__ec2_run_instance(
            max_size,
            InstanceType=master_instance_type,
            MinCount=1,
            MaxCount=1,
            ImageId=get_latest_alinux_ami_id(),
            SubnetId=master_subnet,
            CpuOptions=master_cpu_options,
            Placement=master_placement_group,
            DryRun=True,
        )

        # Test Compute Instances Configuration
        self.__ec2_run_instance(
            max_size,
            InstanceType=compute_instance_type,
            MinCount=max_size,
            MaxCount=max_size,
            ImageId=get_latest_alinux_ami_id(),
            SubnetId=compute_subnet,
            CpuOptions=compute_cpu_options,
            Placement=compute_placement_group,
            DryRun=True,
        )

    def __ec2_run_instance(self, max_size, **kwargs):
        """Wrap ec2 run_instance call. Useful since a successful run_instance call signals 'DryRunOperation'."""
        try:
            boto3.client("ec2").run_instances(**kwargs)
        except ClientError as e:
            code = e.response.get("Error").get("Code")
            message = e.response.get("Error").get("Message")
            if code == "DryRunOperation":
                pass
            elif code == "UnsupportedOperation":
                if "does not support specifying CpuOptions" in message:
                    self.error(message.replace("CpuOptions", "disable_hyperthreading"))
                self.error(message)
            elif code == "InstanceLimitExceeded":
                self.error(
                    "The configured max size parameter {0} exceeds the AWS Account limit "
                    "in the {1} region.\n{2}".format(max_size, self.region, message)
                )
            elif code == "InsufficientInstanceCapacity":
                self.error(
                    "The configured max size parameter {0} exceeds the On-Demand capacity on AWS.\n{1}".format(
                        max_size, message
                    )
                )
            elif code == "InsufficientFreeAddressesInSubnet":
                self.error(
                    "The configured max size parameter {0} exceeds the number of free private IP addresses "
                    "available in the Compute subnet.\n{1}".format(max_size, message)
                )
            elif code == "InvalidParameterCombination":
                self.error(message)
            else:
                self.error(
                    "Unable to check AWS Account limits. Please double check your cluster configuration.\n%s" % message
                )

    def error(self, message):
        """Print an error message and Raise SystemExit exception to the stderr if fail_on_error is true."""
        if self.fail_on_error:
            sys.exit("ERROR: {0}".format(message))
        else:
            print("ERROR: {0}".format(message))

    def warn(self, message):
        """Print a warning message."""
        print("WARNING: {0}".format(message))

    @staticmethod
    def init_aws(config_file=None):
        """
        Initialize AWS env settings from pcluster config file.

        Useful when the only thing needed is to set AWS env variables, without really loading and checking the
        configuration settings.
        :param config_file: pcluster config file - None to use default
        """
        PclusterConfig(config_file=config_file, fail_on_error=False, fail_on_file_absence=False)
