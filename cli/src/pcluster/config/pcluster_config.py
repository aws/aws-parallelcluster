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
import errno
import json
import logging
import os
import stat
import sys
from collections import OrderedDict

import boto3
import configparser
from botocore.exceptions import ClientError

from pcluster.cluster_model import ClusterModel, get_cluster_model, infer_cluster_model
from pcluster.config.cfn_param_types import ClusterCfnSection
from pcluster.config.mappings import ALIASES, AWS, GLOBAL
from pcluster.config.param_types import StorageData
from pcluster.utils import (
    InstanceTypeInfo,
    get_cfn_param,
    get_file_section_name,
    get_installed_version,
    get_stack,
    get_stack_name,
    get_stack_version,
    is_hit_enabled_cluster,
)

LOGGER = logging.getLogger(__name__)


def default_config_file_path():
    """Return the default path for the ParallelCluster configuration file."""
    return os.path.expanduser(os.path.join("~", ".parallelcluster", "config"))


class PclusterConfig(object):
    """
    Class to manage the configuration of a cluster created (or to create) with ParallelCluster.

    This class contains a dictionary of sections associated to the given cluster
    """

    def __init__(
        self,
        config_file=None,
        cluster_label=None,  # args.cluster_template
        fail_on_file_absence=False,
        fail_on_error=None,
        cluster_name=None,
        auto_refresh=True,
        enforce_version=True,
        skip_load_json_config=False,
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
        :param auto_refresh: if set, refresh() method will be called every time something changes in the structure of
        the configuration, like a section being added, removed or renamed.
        :param enforce_version: when True enforces the CLI version to be of the same version as the cluster the user
        is interacting with.
        """
        self.__autorefresh = False  # Initialization in progress
        self.fail_on_error = fail_on_error
        self.cfn_stack = None
        self.__sections = OrderedDict({})
        self.__enforce_version = enforce_version
        self.__skip_load_json_config = skip_load_json_config

        # always parse the configuration file if there, to get AWS section
        self._init_config_parser(config_file, fail_on_file_absence)
        # init AWS section
        self.__init_section_from_file(AWS, self.config_parser)
        self.__init_region()
        self.__init_aws_credentials()

        # init pcluster_config object, from cfn or from config_file
        if cluster_name:
            self.cluster_name = cluster_name
            self.__init_sections_from_cfn(cluster_name)
        else:
            self.__init_sections_from_file(cluster_label, self.config_parser, fail_on_file_absence)

        # Load instance types data if available
        self.__init_additional_instance_types_data()

        self.__autorefresh = auto_refresh  # Initialization completed

        # Refresh sections and parameters
        self._config_updated()

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
            self.config_file = default_config_file_path()
            default_config = True

        self.config_file = str(self.config_file)

        if not os.path.isfile(self.config_file):
            if fail_on_config_file_absence:
                error_message = "Configuration file {0} not found.".format(self.config_file)
                if default_config:
                    error_message += (
                        "\nYou can execute the 'pcluster configure' command "
                        "or see https://docs.aws.amazon.com/parallelcluster/latest/ug/configuration.html"
                    )
                self.error(error_message)
            else:
                LOGGER.debug("Specified configuration file %s doesn't exist.", self.config_file)
        else:
            LOGGER.debug("Parsing configuration file %s", self.config_file)
        self.config_parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
        try:
            self.config_parser.read(self.config_file)
        except (configparser.ParsingError, configparser.DuplicateOptionError) as e:
            self.error("Error parsing configuration file {0}.\n{1}".format(self.config_file, str(e)))

    @staticmethod
    def get_global_section_keys():
        """Return the keys associated to the global sections, not related to the cluster one."""
        return ["aws", "aliases", "global"]

    def get_section_keys(self, include_global_sections=False, excluded_keys=None):
        """Return the section keys."""
        excluded_keys = excluded_keys or []
        if not include_global_sections:
            excluded_keys += self.get_global_section_keys()

        section_keys = [section_key for section_key in self.__sections.keys() if section_key not in excluded_keys]
        return section_keys

    def _get_file_section_names(self):
        """Return the names of the sections as represented in the configuration file."""
        file_section_names = []
        for section_key, sections in self.__sections.items():
            for _, section in sections.items():
                file_section_names.append(get_file_section_name(section_key, section.label))

        return file_section_names

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
            self.__sections[section.key] = OrderedDict({})

        section_label = section.label if section.label else section.definition.get("default_label", "default")
        self.__sections[section.key][section_label] = section
        self._config_updated()

    def remove_section(self, section_key, section_label=None):
        """
        Remove a section from the PclusterConfig object, if there.

        :param section_key: the identifier of the section type
        :param section_label: the label of the section to delete.
        """
        if section_key in self.__sections:
            sections = self.__sections[section_key]

            if section_label:
                # If section label is specified, remove it directly
                sections.pop(section_label)
            else:
                # If no label is specified, check that no more than one section exists with the provided key
                if len(sections) > 1:
                    raise Exception("More than one section with key {0}".format(section_key))
                else:
                    self.__sections.pop(section_key)
        self._config_updated()

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
    def cluster_model(self):
        """Get the cluster model used in the configuration."""
        cluster_model = ClusterModel.SIT
        cluster_section = self.get_section("cluster")
        if cluster_section:
            cluster_model = get_cluster_model(cluster_section.definition.get("cluster_model"))
        return cluster_model

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

        Order is 1) AWS_DEFAULT_REGION env 2) Config file 3) default from aws config file
        """
        if os.environ.get("AWS_DEFAULT_REGION"):
            self.region = os.environ.get("AWS_DEFAULT_REGION")
        elif self.region:
            os.environ["AWS_DEFAULT_REGION"] = self.region
        else:
            self.error(
                "You must specify a region"
                "\nRun `aws configure`, or add the `-r <REGION_NAME>` arg to the command you are trying to"
                " run, or set the `AWS_DEFAULT_REGION` environment variable."
            )

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

    def to_file(self, print_stdout=False, exclude_unrelated_sections=False):
        """Convert the internal representation of the cluster to the relative file sections."""
        if exclude_unrelated_sections:
            # Remove sections not strictly related to the cluster from the config_parser.
            cluster_related_sections = self._get_file_section_names()
            for section_name in self.config_parser.sections():
                if section_name not in cluster_related_sections:
                    self.config_parser.remove_section(section_name)

        for section_key in self.get_global_section_keys():
            self.get_section(section_key).to_file(self.config_parser, write_defaults=True)

        self.get_section("cluster").to_file(self.config_parser)

        if print_stdout:
            # print log file to stdout instead of writing the file
            self.config_parser.write(sys.stdout)
            sys.stdout.flush()
        else:
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
        return self.to_storage().cfn_params

    def to_storage(self):
        """
        Get a data structure with all the information needed to persist the configuration.

        The internal representation of the cluster is converted into a data structure containing the information to be
        stored into all the storage mechanisms used by the CLI (currently CloudFormation parameters and Json).

        :return: a dict containing the cfn parameters and the json dict associated with the cluster configuration
        """
        return self.get_section("cluster").to_storage()

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

        # Infer cluster model and load cluster section accordingly
        cluster_model = infer_cluster_model(config_parser=config_parser, cluster_label=cluster_label)

        self.__init_section_from_file(
            cluster_model.get_cluster_section_definition(),
            config_parser,
            section_label=cluster_label,
            fail_on_absence=fail_on_absence,
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

    @property
    def auto_refresh(self):
        """Return the configuration autorefresh."""
        return self.__autorefresh

    @auto_refresh.setter
    def auto_refresh(self, refresh_enabled):
        """Enable or disable the configuration autorefresh."""
        self.__autorefresh = refresh_enabled

    def _config_updated(self):
        """
        Notify the PclusterConfig instance that the configuration structure has changed.

        The purpose of this method is to allow internal configuration objects such as Param, Section etc to notify the
        parent PclusterConfig when something structural has changed. The configuration will be reloaded based on whether
        or not the autofresh function is enabled.
        """
        if self.__autorefresh:
            self.refresh()

    def refresh(self):
        """
        Reload the sections structure and refresh all configuration sections and parameters.

        This method must be called if structural configuration changes have been applied, like updating a section
        label, adding or removing a section etc.
        """
        # Rebuild the new sections structure
        new_sections = OrderedDict({})
        for key, sections in self.__sections.items():
            new_sections_map = OrderedDict({})
            for _, section in sections.items():
                new_sections_map[section.label] = section
            new_sections[key] = new_sections_map
        self.__sections = new_sections

        # Refresh all sections
        for _, sections in self.__sections.items():
            for _, section in sections.items():
                section.refresh()

    def __init_sections_from_cfn(self, cluster_name):
        try:
            self.cfn_stack = get_stack(get_stack_name(cluster_name))
            if self.__enforce_version and get_stack_version(self.cfn_stack) != get_installed_version():
                self.error(
                    "The cluster {0} was created with a different version of ParallelCluster: {1}. "
                    "Installed version is {2}. This operation may only be performed using the same ParallelCluster "
                    "version used to create the cluster.".format(
                        cluster_name, get_stack_version(self.cfn_stack), get_installed_version()
                    )
                )

            cfn_params = self.cfn_stack.get("Parameters")
            json_params = self.__load_json_config(self.cfn_stack) if not self.__skip_load_json_config else None
            cfn_tags = self.cfn_stack.get("Tags")

            # Infer cluster model and load cluster section accordingly
            cluster_model = infer_cluster_model(cfn_stack=self.cfn_stack)
            section = ClusterCfnSection(
                section_definition=cluster_model.get_cluster_section_definition(), pcluster_config=self
            )

            self.add_section(section)

            section.from_storage(StorageData(cfn_params, json_params, cfn_tags))

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

        # test provided configuration
        self.__test_configuration()

    def get_head_node_availability_zone(self):
        """Get the Availability zone of the Head Node Subnet."""
        return self.get_section("vpc").get_param_value("master_availability_zone")

    def get_compute_availability_zone(self):
        """Get the Availability zone of the Compute Subnet."""
        return self.get_section("vpc").get_param_value("compute_availability_zone")

    def __load_json_config(self, cfn_stack):
        """Retrieve Json configuration params from the S3 bucket linked from the cfn params."""
        json_config = None
        if is_hit_enabled_cluster(cfn_stack):
            s3_bucket_name = get_cfn_param(cfn_stack.get("Parameters"), "ResourcesS3Bucket")
            artifact_directory = get_cfn_param(cfn_stack.get("Parameters"), "ArtifactS3RootDirectory")
            if not s3_bucket_name or s3_bucket_name == "NONE":
                self.error("Unable to retrieve configuration: ResourceS3Bucket not available.")
            if not artifact_directory or artifact_directory == "NONE":
                self.error("Unable to retrieve configuration: ArtifactS3RootDirectory not available.")

            json_config = self.__retrieve_cluster_config(s3_bucket_name, artifact_directory)

        return json_config

    def __retrieve_cluster_config(self, bucket, artifact_directory):
        table = boto3.resource("dynamodb").Table(get_stack_name(self.cluster_name))
        config_version = None  # Use latest if not found
        try:
            config_version_item = table.get_item(ConsistentRead=True, Key={"Id": "CLUSTER_CONFIG"})
            if config_version_item or "Item" in config_version_item:
                config_version = config_version_item["Item"].get("Version")
        except Exception as e:
            self.error("Failed when retrieving cluster config version from DynamoDB with error {0}".format(e))

        try:
            config_version_args = {"VersionId": config_version} if config_version else {}
            s3_object = boto3.resource("s3").Object(
                bucket, "{prefix}/configs/cluster-config.json".format(prefix=artifact_directory)
            )
            json_str = s3_object.get(**config_version_args)["Body"].read().decode("utf-8")
            return json.loads(json_str, object_pairs_hook=OrderedDict)
        except Exception as e:
            self.error(
                "Unable to load configuration from bucket '{bucket}/{prefix}'.\n{error}".format(
                    bucket=bucket, prefix=artifact_directory, error=e
                )
            )

    def __test_configuration(self):  # noqa: C901
        """
        Perform global tests to verify that the wanted cluster configuration can be deployed in the user's account.

        Check operations may involve dryrun tests and/or other AWS calls and depend on the current cluster model.
        """
        LOGGER.debug("Testing configuration parameters...")
        self.cluster_model.test_configuration(self)
        LOGGER.debug("Configuration parameters tested correctly.")

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
        PclusterConfig(config_file=config_file, fail_on_error=False, fail_on_file_absence=False, auto_refresh=False)

    def update(self, pcluster_config):
        """
        Update the entire configuration structure taking the data from the provided pcluster_config instance.

        This operation allows the configuration metadata to be correctly updated before being sent back to
        CloudFormation.

        :param pcluster_config: The new configuration containing the updated settings.
        """
        # When the configuration is updated, all parameters are replaced except config metadata
        # which is needed to keep the right linking between sections and CloudFormation resources
        config_metadata_param = self.get_section("cluster").get_param("cluster_config_metadata")
        self.__sections = pcluster_config.__sections
        self.get_section("cluster").set_param("cluster_config_metadata", config_metadata_param)

    def __init_additional_instance_types_data(self):
        """Store additional instance type information coming from instance_types_data parameter."""
        InstanceTypeInfo.load_additional_instance_types_data(
            self.get_section("cluster").get_param_value("instance_types_data")
        )
