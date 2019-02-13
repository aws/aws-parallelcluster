# Copyright 2013-2014 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
# fmt: off
from __future__ import absolute_import, print_function  # isort:skip
from future import standard_library  # isort:skip
standard_library.install_aliases()
# fmt: on

import inspect
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from builtins import object
from collections import OrderedDict

import boto3
import configparser
import pkg_resources
from botocore.exceptions import ClientError

from pcluster.config_sanity import ResourceValidator


def get_stack_template(region, aws_access_key_id, aws_secret_access_key, cluster_name):
    """
    Get stack template corresponding to the given cluster name.

    :param region: AWS Region
    :param aws_access_key_id: AWS access key
    :param aws_secret_access_key: AWS secret access key
    :param cluster_name: The cluster name to search for
    :return: the corresponding stack template
    """
    cfn = boto3.client(
        "cloudformation",
        region_name=region,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )
    stack_name = "parallelcluster-" + cluster_name

    try:
        stack = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0]
    except ClientError as e:
        print(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        sys.exit(1)

    cli_template = [p.get("ParameterValue") for p in stack.get("Parameters") if p.get("ParameterKey") == "CLITemplate"][
        0
    ]

    return cli_template


class ParallelClusterConfig(object):
    """Manage ParallelCluster Config."""

    MAX_EBS_VOLUMES = 5

    def __init__(self, args):
        self.args = args
        self.parameters = {}
        self.version = pkg_resources.get_distribution("aws-parallelcluster").version

        # Initialize configuration attribute by parsing config file
        self.__config = self.__init_config()

        # Initialize region and credentials public attributes
        self.__init_region()
        self.__init_credentials()

        # Get cluster template and define corresponding parameter
        cluster_template = self.__get_cluster_template()
        self.__cluster_section = "cluster %s" % cluster_template
        self.parameters["CLITemplate"] = cluster_template

        # Check for update, if required, according to the configuration parameter
        self.__check_for_updates()

        # Initialize sanity_check private attribute and ResourceValidator object
        self.__init_sanity_check()

        # Initialize key name public attribute and corresponding parameter
        self.__init_key_name()

        # Initialize template url public attribute
        self.__init_template_url()

        # Validate VPC configuration settings and initialize corresponding parameters
        self.__init_vpc_parameters()

        # Initialize Scheduler parameters
        self.__init_scheduler_parameters()

        # Initialize parameters related to the cluster configuration
        self.__init_cluster_parameters()

        # Initialize ExtraJson parameter
        self.__init_extra_json_parameter()

        # Initialize Tags public attribute
        self.__init_tags()

        # Initialize EBS related parameters
        self.__init_ebs_parameters()

        # Initialize EFS related parameters
        self.__init_efs_parameters()

        # Initialize RAID related parameters
        self.__init_raid_parameters()

        # Initialize scaling related parameters
        self.__init_scaling_parameters()

        # Initialize aliases public attributes
        self.__init_aliases()

        # Handle extra parameters supplied on command-line
        try:
            if self.args.extra_parameters is not None:
                self.parameters.update(dict(self.args.extra_parameters))
        except AttributeError:
            pass

    def __init_config(self):
        """
        Initialize configuration from file.

        :return: configuration object
        """
        # Determine config file name based on args or default
        if hasattr(self.args, "config_file") and self.args.config_file is not None:
            config_file = self.args.config_file
            default_config = False
        else:
            config_file = os.path.expanduser(os.path.join("~", ".parallelcluster", "config"))
            default_config = True

        if not os.path.isfile(config_file):
            if default_config:
                print("Default config %s not found" % config_file)
                print(
                    "You can copy a template from here: %s%sexamples%sconfig"
                    % (
                        os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))),
                        os.path.sep,
                        os.path.sep,
                    )
                )
                sys.exit(1)
            else:
                print("Config file %s not found" % config_file)
                sys.exit(1)

        config = configparser.ConfigParser()
        config.read(config_file)
        return config

    def _get_config_value(self, section, key, default=None):
        """
        Get configuration key value from the given section.

        :param section: Configuration file section
        :param key: Configuration parameter key
        :param default: default value to return if the option is not present in the configuration file
        :return: Configuration parameter value, or <default> if not found.
        """
        try:
            return self.__config.get(section, key)
        except configparser.NoOptionError:
            return default

    def __init_region(self):
        """
        Initialize region attribute.

        Order is 1) CLI arg 2) AWS_DEFAULT_REGION env 3) Config file 4) us-east-1
        """
        if hasattr(self.args, "region") and self.args.region:
            self.region = self.args.region
        elif os.environ.get("AWS_DEFAULT_REGION"):
            self.region = os.environ.get("AWS_DEFAULT_REGION")
        else:
            self.region = self._get_config_value("aws", "aws_region_name", "us-east-1")

    def __init_credentials(self):
        """Init credentials by checking if they have been provided in config."""
        self.aws_access_key_id = self._get_config_value("aws", "aws_access_key_id")
        self.aws_secret_access_key = self._get_config_value("aws", "aws_secret_access_key")

    def __get_cluster_template(self):
        """
        Determine which cluster template will be used and return it.

        :return: the cluster template to use
        """
        args_func = self.args.func.__name__
        if args_func in ["start", "stop", "instances"]:
            # Starting and stopping a cluster is unique in that we would want to prevent the
            # customer from inadvertently using a different template than what
            # the cluster was created with, so we do not support the -t
            # parameter. We always get the template to use from CloudFormation.
            cluster_template = get_stack_template(
                self.region, self.aws_access_key_id, self.aws_secret_access_key, self.args.cluster_name
            )
        else:
            try:
                if self.args.cluster_template is not None:
                    cluster_template = self.args.cluster_template
                else:
                    if args_func == "update":
                        cluster_template = get_stack_template(
                            self.region, self.aws_access_key_id, self.aws_secret_access_key, self.args.cluster_name
                        )
                    else:
                        cluster_template = self.__config.get("global", "cluster_template")
            except AttributeError:
                cluster_template = self.__config.get("global", "cluster_template")

        return cluster_template

    def __check_for_updates(self):
        """Check for updates, if required."""
        # verify if package updates should be checked
        try:
            update_check = self.__config.getboolean("global", "update_check")
        except configparser.NoOptionError:
            update_check = True

        if update_check is True:
            try:
                latest = json.loads(
                    urllib.request.urlopen("https://pypi.python.org/pypi/aws-parallelcluster/json").read()
                )["info"]["version"]
                if self.version < latest:
                    print("warning: There is a newer version %s of AWS ParallelCluster available." % latest)
            except Exception:
                pass

    def __init_sanity_check(self):
        """
        Check if config sanity should be run and initialize the corresponding attribute.

        The method also initializes the ResourceValidator object, to be used to validate the resources.
        """
        try:
            self.__sanity_check = self.__config.getboolean("global", "sanity_check")
            self.__resource_validator = ResourceValidator(
                self.region, self.aws_access_key_id, self.aws_secret_access_key
            )

            # Only check config on calls that mutate it
            if self.args.func.__name__ not in ["create", "update", "configure"]:
                self.__sanity_check = False

        except configparser.NoOptionError:
            self.__sanity_check = False

    def __validate_resource(self, resource_type, resource_value):
        """
        Validate the given resource, only if the sanity_check configuration parameter is set to true.

        :param resource_type: Resource type
        :param resource_value: Resource value
        """
        if self.__sanity_check:
            self.__resource_validator.validate(resource_type, resource_value)

    def __init_key_name(self):
        """Get the EC2 keypair name to be used and set the corresponding attribute and parameter, exit if not set."""
        try:
            self.key_name = self.__config.get(self.__cluster_section, "key_name")
            if not self.key_name:
                print("ERROR: key_name set in [%s] section but not defined." % self.__cluster_section)
                sys.exit(1)
            self.__validate_resource("EC2KeyPair", self.key_name)
        except configparser.NoOptionError:
            print("ERROR: Missing key_name option in [%s] section." % self.__cluster_section)
            sys.exit(1)

        self.parameters["KeyName"] = self.key_name

    def __init_template_url(self):
        """
        Determine the CloudFormation URL to be used and initialize the corresponding attribute.

        Order is 1) CLI arg 2) Config file 3) default for version + region
        """
        try:
            if self.args.template_url is not None:
                self.template_url = self.args.template_url
            else:
                try:
                    self.template_url = self.__config.get(self.__cluster_section, "template_url")
                    if not self.template_url:
                        print("ERROR: template_url set in [%s] section but not defined." % self.__cluster_section)
                        sys.exit(1)
                    self.__validate_resource("URL", self.template_url)
                except configparser.NoOptionError:
                    s3_suffix = ".cn" if self.region.startswith("cn") else ""
                    self.template_url = (
                        "https://s3.%s.amazonaws.com%s/%s-aws-parallelcluster/templates/"
                        "aws-parallelcluster-%s.cfn.json" % (self.region, s3_suffix, self.region, self.version)
                    )
        except AttributeError:
            pass

    def __init_vpc_parameters(self):
        """Initialize VPC Parameters."""
        # Determine which vpc settings section will be used
        vpc_settings = self.__config.get(self.__cluster_section, "vpc_settings")
        vpc_section = "vpc %s" % vpc_settings

        # Dictionary list of all VPC options
        vpc_options = dict(
            vpc_id=("VPCId", "VPC"),
            master_subnet_id=("MasterSubnetId", "VPCSubnet"),
            compute_subnet_cidr=("ComputeSubnetCidr", None),
            compute_subnet_id=("ComputeSubnetId", "VPCSubnet"),
            use_public_ips=("UsePublicIps", None),
            ssh_from=("AccessFrom", None),
            access_from=("AccessFrom", None),
            additional_sg=("AdditionalSG", "VPCSecurityGroup"),
            vpc_security_group_id=("VPCSecurityGroupId", "VPCSecurityGroup"),
        )
        self.__master_subnet = self.__config.get(vpc_section, "master_subnet_id")

        # Loop over all VPC options and add define to parameters, raise Exception is defined but null
        for key in vpc_options:
            try:
                __temp__ = self.__config.get(vpc_section, key)
                if not __temp__:
                    print("ERROR: %s defined but not set in [%s] section" % (key, vpc_section))
                    sys.exit(1)
                if vpc_options.get(key)[1] is not None:
                    self.__validate_resource(vpc_options.get(key)[1], __temp__)
                self.parameters[vpc_options.get(key)[0]] = __temp__
            except configparser.NoOptionError:
                pass
            except configparser.NoSectionError:
                print(
                    "ERROR: VPC section [%s] used in [%s] section is not defined"
                    % (vpc_section, self.__cluster_section)
                )
                sys.exit(1)

    def __init_scheduler_parameters(self):
        """Validate scheduler related configuration settings and initialize corresponding parameters."""
        # use sge as default scheduler
        if self.__config.has_option(self.__cluster_section, "scheduler"):
            self.parameters["Scheduler"] = self.__config.get(self.__cluster_section, "scheduler")
        else:
            self.parameters["Scheduler"] = "sge"

        # check for the scheduler since AWS Batch requires different configuration parameters
        if self.parameters["Scheduler"] == "awsbatch":
            self.__init_batch_parameters()
        else:
            self.__init_size_parameters()

    def __init_size_parameters(self):
        """Initialize size parameters."""
        # Set defaults outside the cloudformation template
        self.parameters["MinSize"] = "0"
        self.parameters["DesiredSize"] = "2"
        self.parameters["MaxSize"] = "10"

        size_parameters = OrderedDict(
            initial_queue_size=("InitialQueueSize", None),
            maintain_initial_size=("MaintainInitialSize", None),
            max_queue_size=("MaxQueueSize", None),
        )
        for key in size_parameters:
            try:
                __temp__ = self.__config.get(self.__cluster_section, key)
                if not __temp__:
                    print("ERROR: %s defined but not set in [%s] section" % (key, self.__cluster_section))
                    sys.exit(1)
                if key == "initial_queue_size":
                    self.parameters["DesiredSize"] = __temp__
                elif key == "maintain_initial_size":
                    self.parameters["MinSize"] = self.parameters.get("DesiredSize") if __temp__ == "true" else "0"
                elif key == "max_queue_size":
                    self.parameters["MaxSize"] = __temp__
            except configparser.NoOptionError:
                pass

    def __init_cluster_parameters(self):
        """Loop over all the cluster options and define parameters, raise Exception if defined but None."""
        cluster_options = dict(
            cluster_user=("ClusterUser", None),
            compute_instance_type=("ComputeInstanceType", None),
            master_instance_type=("MasterInstanceType", None),
            scheduler=("Scheduler", None),
            cluster_type=("ClusterType", None),
            ephemeral_dir=("EphemeralDir", None),
            spot_price=("SpotPrice", None),
            custom_ami=("CustomAMI", "EC2Ami"),
            pre_install=("PreInstallScript", "URL"),
            post_install=("PostInstallScript", "URL"),
            proxy_server=("ProxyServer", None),
            placement=("Placement", None),
            placement_group=("PlacementGroup", "EC2PlacementGroup"),
            encrypted_ephemeral=("EncryptedEphemeral", None),
            pre_install_args=("PreInstallArgs", None),
            post_install_args=("PostInstallArgs", None),
            s3_read_resource=("S3ReadResource", None),
            s3_read_write_resource=("S3ReadWriteResource", None),
            tenancy=("Tenancy", None),
            master_root_volume_size=("MasterRootVolumeSize", None),
            compute_root_volume_size=("ComputeRootVolumeSize", None),
            base_os=("BaseOS", None),
            ec2_iam_role=("EC2IAMRoleName", "EC2IAMRoleName"),
            extra_json=("ExtraJson", None),
            custom_chef_cookbook=("CustomChefCookbook", None),
            custom_chef_runlist=("CustomChefRunList", None),
            additional_cfn_template=("AdditionalCfnTemplate", None),
            custom_awsbatch_template_url=("CustomAWSBatchTemplateURL", None),
        )
        for key in cluster_options:
            try:
                __temp__ = self.__config.get(self.__cluster_section, key)
                if not __temp__:
                    print("ERROR: %s defined but not set in [%s] section" % (key, self.__cluster_section))
                    sys.exit(1)
                if cluster_options.get(key)[1] is not None:
                    self.__validate_resource(cluster_options.get(key)[1], __temp__)
                self.parameters[cluster_options.get(key)[0]] = __temp__
            except configparser.NoOptionError:
                pass

    def __init_extra_json_parameter(self):
        """Check for extra_json = { "cluster" : ... } configuration parameters and map to "cfncluster"."""
        extra_json = self.parameters.get("ExtraJson")
        if extra_json:
            extra_json = json.loads(extra_json)
            if "cluster" in extra_json:
                # support parallelcluster syntax by replacing the key
                extra_json["cfncluster"] = extra_json.pop("cluster")
                self.parameters["ExtraJson"] = json.dumps(extra_json)

    def __init_tags(self):
        """
        Merge tags from config with tags from command line args.

        Command line args take precedent and overwrite tags supplied in the config.
        """
        self.tags = {}
        try:
            tags = self.__config.get(self.__cluster_section, "tags")
            self.tags = json.loads(tags)
        except configparser.NoOptionError:
            pass
        try:
            if self.args.tags is not None:
                for key in self.args.tags:
                    self.tags[key] = self.args.tags[key]
        except AttributeError:
            pass

    def __init_scaling_parameters(self):  # noqa: C901 FIXME!!!
        """Initialize scaling related parameters."""
        # Determine if scaling settings are defined and set section.
        try:
            self.__scaling_settings = self.__config.get(self.__cluster_section, "scaling_settings")
            if not self.__scaling_settings:
                print("ERROR: scaling_settings defined by not set in [%s] section" % self.__cluster_section)
                sys.exit(1)
            scaling_section = "scaling %s" % self.__scaling_settings
        except configparser.NoOptionError:
            scaling_section = None

        if scaling_section:
            # Dictionary list of all scaling options
            scaling_options = dict(scaledown_idletime=("ScaleDownIdleTime", None))
            for key in scaling_options:
                try:
                    __temp__ = self.__config.get(scaling_section, key)
                    if not __temp__:
                        print("ERROR: %s defined but not set in [%s] section" % (key, scaling_section))
                        sys.exit(1)
                    if scaling_options.get(key)[1] is not None:
                        self.__validate_resource(scaling_options.get(key)[1], __temp__)
                    self.parameters[scaling_options.get(key)[0]] = __temp__
                except configparser.NoOptionError:
                    pass

    def __init_aliases(self):
        """Initialize aliases attributes according to the configuration."""
        self.aliases = {}
        alias_section = "aliases"
        if self.__config.has_section(alias_section):
            for alias in self.__config.options(alias_section):
                self.aliases[alias] = self.__config.get(alias_section, alias)

    def __check_option_absent_awsbatch(self, option):
        if self.__config.has_option(self.__cluster_section, option):
            print("ERROR: option %s cannot be used with awsbatch" % option)
            sys.exit(1)

    @staticmethod
    def __validate_awsbatch_os(baseos):
        supported_batch_oses = ["alinux"]
        if baseos not in supported_batch_oses:
            print("ERROR: awsbatch scheduler supports following OSes: %s" % supported_batch_oses)
            sys.exit(1)

    def __init_batch_parameters(self):  # noqa: C901 FIXME!!!
        """
        Initialize Batch specific parameters.

        :param config: configuration object.
        """
        self.__check_option_absent_awsbatch("initial_queue_size")
        self.__check_option_absent_awsbatch("maintain_initial_size")
        self.__check_option_absent_awsbatch("max_queue_size")
        self.__check_option_absent_awsbatch("spot_price")

        if self.__config.has_option(self.__cluster_section, "base_os"):
            self.__validate_awsbatch_os(self.__config.get(self.__cluster_section, "base_os"))

        if self.__config.has_option(self.__cluster_section, "compute_instance_type"):
            compute_instance_type = self.__config.get(self.__cluster_section, "compute_instance_type")
            self.parameters["ComputeInstanceType"] = compute_instance_type
        else:
            # use 'optimal' as default for awsbatch
            self.parameters["ComputeInstanceType"] = "optimal"

        if self.__config.has_option(self.__cluster_section, "spot_bid_percentage"):
            spot_bid_percentage = self.__config.get(self.__cluster_section, "spot_bid_percentage")
            # use spot price to indicate spot bid percentage in case of awsbatch
            self.parameters["SpotPrice"] = spot_bid_percentage

        if self.__config.has_option(self.__cluster_section, "custom_awsbatch_template_url"):
            awsbatch_custom_url = self.__config.get(self.__cluster_section, "custom_awsbatch_template_url")
            if not awsbatch_custom_url:
                print(
                    "ERROR: custom_awsbatch_template_url set in [%s] section but not defined." % self.__cluster_section
                )
                sys.exit(1)
            self.parameters["CustomAWSBatchTemplateURL"] = awsbatch_custom_url

        # Set batch default size parameters
        self.parameters["MinSize"] = "0"
        self.parameters["DesiredSize"] = "4"
        self.parameters["MaxSize"] = "20"

        # Override those parameters from config if they are available
        batch_size_parameters = dict(
            min_vcpus=("MinVCpus", None), desired_vcpus=("DesiredVCpus", None), max_vcpus=("MaxVCpus", None)
        )
        for key in batch_size_parameters:
            try:
                __temp__ = self.__config.get(self.__cluster_section, key)
                if not __temp__:
                    print("ERROR: %s defined but not set in [%s] section" % (key, self.__cluster_section))
                    sys.exit(1)
                if key == "min_vcpus":
                    self.parameters["MinSize"] = __temp__
                elif key == "desired_vcpus":
                    self.parameters["DesiredSize"] = __temp__
                elif key == "max_vcpus":
                    self.parameters["MaxSize"] = __temp__
            except configparser.NoOptionError:
                pass

        self.__validate_resource("AWSBatch_Parameters", self.parameters)

    def __init_efs_parameters(self):  # noqa: C901 FIXME!!!
        # Determine if EFS settings are defined and set section
        try:
            self.__efs_settings = self.__config.get(self.__cluster_section, "efs_settings")
            if not self.__efs_settings:
                print("ERROR: efs_settings defined but not set in [%s] section" % self.__cluster_section)
                sys.exit(1)
            self.__efs_section = "efs %s" % self.__efs_settings
        except configparser.NoOptionError:
            pass

        # Dictionary list of all EFS options
        self.__efs_options = OrderedDict(
            [
                ("shared_dir", ("EFSShared_dir", None)),
                ("efs_fs_id", ("EFSFileSystemId", "EFSFSId")),
                ("performance_mode", ("EFSPerformanceMode", "EFSPerfMode")),
                ("efs_kms_key_id", ("EFSKMSKeyId", None)),
                ("provisioned_throughput", ("EFSProvisionedThroughput", None)),
                ("encrypted", ("EFSEncryption", None)),
                ("throughput_mode", ("EFSThroughput_mode", None)),
            ]
        )
        __valid_mt = False
        __throughput_mode = None
        __provisioned_throughput = None
        try:
            if self.__efs_section:
                __temp_efs_options = []
                for key in self.__efs_options:
                    try:
                        __temp__ = self.__config.get(self.__efs_section, key)
                        if not __temp__:
                            print("ERROR: %s defined but not set in [%s] section" % (key, self.__efs_section))
                            sys.exit(1)
                        if key == "provisioned_throughput":
                            __provisioned_throughput = __temp__
                        elif key == "throughput_mode":
                            __throughput_mode = __temp__
                        # Separate sanity_check for fs_id, need to pass in fs_id and subnet_id
                        if self.__efs_options.get(key)[1] == "EFSFSId":
                            __valid_mt = self.__validate_resource("EFSFSId", (__temp__, self.__master_subnet))
                        elif self.__efs_options.get(key)[1] is not None:
                            self.__validate_resource(self.__efs_options.get(key)[1], __temp__)
                        __temp_efs_options.append(__temp__)
                    except configparser.NoOptionError:
                        __temp_efs_options.append("NONE")
                # Separate sanity_check for throughput settings,
                # need to pass in throughput_mode and provisioned_throughput
                if __provisioned_throughput is not None or __throughput_mode is not None:
                    self.__validate_resource("EFSThroughput", (__throughput_mode, __provisioned_throughput))
                if __valid_mt:
                    __temp_efs_options.append("Valid")
                else:
                    __temp_efs_options.append("NONE")
                self.parameters["EFSOptions"] = ",".join(__temp_efs_options)
        except AttributeError:
            pass

    def __init_raid_parameters(self):  # noqa: C901 FIXME!!!
        # Determine if RAID settings are defined and set section
        try:
            self.__raid_settings = self.__config.get(self.__cluster_section, "raid_settings")
            if not self.__raid_settings:
                print("ERROR: raid_settings defined by not set in [%s] section" % self.__cluster_section)
                sys.exit(1)
            self.__raid_section = "raid %s" % self.__raid_settings
        except configparser.NoOptionError:
            pass

        # Dictionary list of all RAID options
        self.__raid_options = OrderedDict(
            [
                ("shared_dir", ("RAIDShared_dir", None)),
                ("raid_type", ("RAIDType", "RAIDType")),
                ("num_of_raid_volumes", ("RAIDVolNum", "RAIDNumVol")),
                ("volume_type", ("RAIDVolType", "RAIDVolType")),
                ("volume_size", ("RAIDVolSize", None)),
                ("volume_iops", ("RAIDVolIOPS", None)),
                ("encrypted", ("RAIDEncryption", None)),
                ("ebs_kms_key_id", ("EBSKMSKeyId", None)),
            ]
        )

        try:
            if self.__raid_section:
                __temp_raid_options = []
                __raid_shared_dir = None
                __raid_vol_size = None
                __raid_iops = None
                __raid_type = None
                for key in self.__raid_options:
                    try:
                        __temp__ = self.__config.get(self.__raid_section, key)
                        if not __temp__:
                            print("ERROR: %s defined but not set in [%s] section" % (key, self.__raid_section))
                            sys.exit(1)
                        if key == "volume_size":
                            __raid_vol_size = __temp__
                        elif key == "volume_iops":
                            __raid_iops = __temp__
                        elif key == "shared_dir":
                            __raid_shared_dir = __temp__
                        elif key == "raid_type":
                            __raid_type = __temp__
                        if self.__raid_options.get(key)[1] is not None:
                            self.__validate_resource(self.__raid_options.get(key)[1], __temp__)
                        __temp_raid_options.append(__temp__)
                    except configparser.NoOptionError:
                        if key == "num_of_raid_volumes":
                            __temp_raid_options.append("2")
                        else:
                            __temp_raid_options.append("NONE")
                        pass
                if __raid_iops is not None:
                    if __raid_vol_size is not None:
                        self.__validate_resource("RAIDIOPS", (__raid_iops, __raid_vol_size))
                    # If volume_size is not specified, check IOPS against default volume size, 20GB
                    else:
                        self.__validate_resource("RAIDIOPS", (__raid_iops, 20))
                if __raid_type is None and __raid_shared_dir is not None:
                    print("ERROR: raid_type (0 or 1) is required in order to create RAID array.")
                    sys.exit(1)
                self.parameters["RAIDOptions"] = ",".join(__temp_raid_options)
        except AttributeError:
            pass

    def __ebs_determine_shared_dir(self):  # noqa: C901 FIXME!!!
        # Handle the shared_dir under EBS setting sections
        __temp_dir_list = []
        try:
            if self.__ebs_section:
                for section in self.__ebs_section:
                    try:
                        __temp_shared_dir = self.__config.get(section, "shared_dir")
                        if not __temp_shared_dir:
                            print("ERROR: shared_dir defined but not set in [%s] section" % section)
                            sys.exit(1)
                        __temp_dir_list.append(__temp_shared_dir)

                    except configparser.NoOptionError:
                        pass
                    except configparser.NoSectionError:
                        print("ERROR: [%s] section defined in ebs_settings does not exist" % section)
                        sys.exit(1)
        except AttributeError:
            pass

        # For backwards compatibility, user can still use shared_dir under [cluster] section for 1 volume,
        # but the shared_dir under [ebs] section will overwrite shared_dir under [cluster],
        # and user MUST specify a shared_dir under each [ebs] section when using > 1 volumes.
        try:
            if len(__temp_dir_list) == len(self.__ebs_section):
                self.parameters["SharedDir"] = ",".join(__temp_dir_list)
            # For backwards compatibility with just 1 volume explicitly specified through ebs_settings
            elif len(self.__ebs_section) == 1:
                try:
                    __temp_shared_dir = self.__config.get(self.__cluster_section, "shared_dir")
                    if not __temp_shared_dir:
                        print("ERROR: shared_dir defined but not set")
                        sys.exit(1)
                    self.parameters["SharedDir"] = __temp_shared_dir
                except configparser.NoOptionError:
                    pass
            else:
                print(
                    "ERROR: not enough shared directories provided.\n"
                    "When using multiple EBS Volumes, please specify a shared_dir under each [ebs] section"
                )
                sys.exit(1)
        except AttributeError:
            try:
                __temp_shared_dir = self.__config.get(self.__cluster_section, "shared_dir")
                if not __temp_shared_dir:
                    print("ERROR: shared_dir defined but not set")
                    sys.exit(1)
                self.parameters["SharedDir"] = __temp_shared_dir
            except configparser.NoOptionError:
                pass

    def __init_ebs_parameters(self):  # noqa: C901 FIXME!!!

        try:
            self.__ebs_settings = self.__config.get(self.__cluster_section, "ebs_settings")

            if not self.__ebs_settings:
                print("ERROR: ebs_settings defined by not set in [%s] section" % self.__cluster_section)
                sys.exit(1)
            # Modify list
            self.__ebs_section = self.__ebs_settings.split(",")
            if len(self.__ebs_section) > self.MAX_EBS_VOLUMES:
                print(
                    "ERROR: number of EBS volumes requested is greater than the MAX.\n"
                    "Max number of EBS volumes supported is currently %s" % self.MAX_EBS_VOLUMES
                )
                sys.exit(1)
            self.parameters["NumberOfEBSVol"] = "%s" % len(self.__ebs_section)
            for i, item in enumerate(self.__ebs_section):
                item = "ebs %s" % item.strip()
                self.__ebs_section[i] = item
        except configparser.NoOptionError:
            pass

        self.__ebs_determine_shared_dir()

        # Dictionary list of all EBS options
        self.__ebs_options = dict(
            ebs_snapshot_id=("EBSSnapshotId", "EC2Snapshot"),
            volume_type=("VolumeType", None),
            volume_size=("VolumeSize", None),
            ebs_kms_key_id=("EBSKMSKeyId", None),
            volume_iops=("VolumeIOPS", None),
            encrypted=("EBSEncryption", None),
            ebs_volume_id=("EBSVolumeId", "EC2Volume"),
        )
        # EBS options processing
        try:
            if self.__ebs_section:
                for key in self.__ebs_options:
                    __temp_parameter_list = []
                    for section in self.__ebs_section:
                        try:
                            __temp__ = self.__config.get(section, key)
                            if not __temp__:
                                print("ERROR: %s defined but not set in [%s] section" % (key, section))
                                sys.exit(1)
                            if self.__ebs_options.get(key)[1] is not None:
                                self.__validate_resource(self.__ebs_options.get(key)[1], __temp__)
                            __temp_parameter_list.append(__temp__)
                        except configparser.NoOptionError:
                            __temp_parameter_list.append("NONE")
                    # Fill the rest of the parameter with NONE
                    while len(__temp_parameter_list) < self.MAX_EBS_VOLUMES:
                        __temp_parameter_list.append("NONE")
                    self.parameters[self.__ebs_options.get(key)[0]] = ",".join(x for x in __temp_parameter_list)

        except AttributeError:
            pass
