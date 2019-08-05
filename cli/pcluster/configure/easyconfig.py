# Copyright 2013-2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the 'License'). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the 'LICENSE.txt' file accompanying this file. This file is distributed on an 'AS IS' BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import absolute_import, print_function
from future import standard_library

import errno
import logging
import os
import stat

import configparser

from pcluster import cfnconfig
from pcluster.configure.networking import (
    NetworkConfiguration,
    PublicPrivateNetworkConfig,
    automate_subnet_creation,
    automate_vpc_with_subnet_creation,
    ec2_conn,
)
from pcluster.configure.utils import get_regions, get_resource_tag, handle_client_exception, prompt, prompt_iterable
from pcluster.utils import get_supported_os, get_supported_schedulers

standard_library.install_aliases()


LOGGER = logging.getLogger(__name__)
DEFAULT_VALUES = {
    "aws_region_name": "us-east-1",
    "cluster_template": "default",
    "scheduler": "sge",
    "os": "alinux",
    "max_size": "10",
    "master_instance_type": "t2.micro",
    "compute_instance_type": "t2.micro",
    "min_size": "0",
}
VPC_PARAMETERS_TO_REMOVE = "vpc-id", "master_subnet_id", "compute_subnet_id", "use_public_ips", "compute_subnet_cidr"


@handle_client_exception
def _get_keys(aws_region_name):
    """Return a list of keys."""
    conn = ec2_conn(aws_region_name)
    keypairs = conn.describe_key_pairs()
    key_options = []
    for key in keypairs.get("KeyPairs"):
        key_name = key.get("KeyName")
        key_options.append(key_name)

    if not key_options:
        print(
            "No KeyPair found in region {0}, please create one following the guide: "
            "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html".format(aws_region_name)
        )

    return key_options


def _extract_subnet_size(cidr):
    return 2 ** (32 - int(cidr.split("/")[1]))


@handle_client_exception
def _get_vpcs_and_subnets(aws_region_name):
    """
    Return a dictionary containing a list of vpc in the given region and the associated VPCs.

    Example:

    {"vpc_list": list(tuple(vpc-id, name, number of subnets)) ,
    "vpc_to_subnet" : {"vpc-id1": list(tuple(subnet-id1, name)), "vpc-id2": list(tuple(subnet-id1, name))}}
    :param aws_region_name: the region name
    """
    conn = ec2_conn(aws_region_name)
    vpcs = conn.describe_vpcs()
    vpc_options = []
    vpc_subnets = {}

    for vpc in vpcs.get("Vpcs"):
        vpc_id = vpc.get("VpcId")
        subnets = _get_subnets(conn, vpc_id)
        vpc_name = get_resource_tag(vpc, tag_name="Name")
        vpc_subnets[vpc_id] = subnets
        subnets_count = "{0} subnets inside".format(len(subnets))
        if vpc_name:
            vpc_options.append((vpc_id, vpc_name, subnets_count))
        else:
            vpc_options.append((vpc_id, subnets_count))

    return {"vpc_list": vpc_options, "vpc_subnets": vpc_subnets}


def _get_subnets(conn, vpc_id):
    subnet_options = []
    subnet_list = conn.describe_subnets(Filters=[{"Name": "vpcId", "Values": [vpc_id]}]).get("Subnets")
    for subnet in subnet_list:
        subnet_id = subnet.get("SubnetId")
        subnet_size_description = "Subnet size: {0}".format(_extract_subnet_size(subnet.get("CidrBlock")))
        name = get_resource_tag(subnet, tag_name="Name")
        if name:
            subnet_options.append((subnet_id, name, subnet_size_description))
        else:
            subnet_options.append((subnet_id, subnet_size_description))
    return subnet_options


@handle_client_exception
def _list_instances():  # Specifying the region does not make any difference
    """Return a list of all the supported instance at the moment by aws, independent by the region."""
    return ec2_conn(DEFAULT_VALUES["aws_region_name"]).meta.service_model.shape_for("InstanceType").enum


def configure(args):
    # Determine config file name based on args or default
    config_file = (
        args.config_file if args.config_file else os.path.expanduser(os.path.join("~", ".parallelcluster", "config"))
    )

    config = configparser.ConfigParser()
    # Check if configuration file exists
    if os.path.isfile(config_file):
        config.read(config_file)

    cluster_template = DEFAULT_VALUES["cluster_template"]
    cluster_label = "cluster " + cluster_template
    vpc_label = "vpc " + cluster_template

    # Use built in boto regions as an available option
    aws_region_name = prompt_iterable("AWS Region ID", get_regions())

    scheduler = prompt_iterable(
        "Scheduler",
        get_supported_schedulers(),
        default_value=_get_config_parameter(
            config, section=cluster_label, parameter_name="scheduler", default_value=DEFAULT_VALUES["scheduler"]
        ),
    )

    scheduler_handler = SchedulerHandler(config, cluster_label, scheduler)

    scheduler_handler.prompt_os()
    scheduler_handler.prompt_cluster_size()

    master_instance_type = prompt(
        "Master instance type",
        lambda x: x in _list_instances(),
        default_value=_get_config_parameter(
            config,
            section=cluster_label,
            parameter_name="master_instance_type",
            default_value=DEFAULT_VALUES["master_instance_type"],
        ),
    )

    scheduler_handler.prompt_compute_instance_type()

    key_name = prompt_iterable("EC2 Key Pair Name", _get_keys(aws_region_name))
    automate_vpc = prompt("Automate VPC creation? (y/n)", lambda x: x == "y" or x == "n", default_value="n") == "y"

    vpc_parameters = _create_vpc_parameters(
        vpc_label, aws_region_name, scheduler, scheduler_handler.max_cluster_size, automate_vpc_creation=automate_vpc
    )
    global_parameters = {
        "name": "global",
        "cluster_template": cluster_template,
        "update_check": "true",
        "sanity_check": "true",
    }
    aws_parameters = {"name": "aws", "aws_region_name": aws_region_name}
    cluster_parameters = {
        "name": cluster_label,
        "key_name": key_name,
        "vpc_settings": cluster_template,
        "scheduler": scheduler,
        "master_instance_type": master_instance_type,
    }
    cluster_parameters.update(scheduler_handler.get_scheduler_parameters())

    aliases_parameters = {"name": "aliases", "ssh": "ssh {CFN_USER}@{MASTER_IP} {ARGS}"}
    sections = [aws_parameters, cluster_parameters, vpc_parameters, global_parameters, aliases_parameters]

    # We remove parameters that may still be present from the past configuration but can conflict with the current.
    _remove_parameter_from_past_configuration(cluster_label, config, scheduler_handler.get_parameters_to_remove())
    _remove_parameter_from_past_configuration(vpc_label, config, VPC_PARAMETERS_TO_REMOVE)

    _write_config(config, sections)
    _check_destination_directory(config_file)

    # Write configuration to disk
    with open(config_file, "w") as cf:
        config.write(cf)
    os.chmod(config_file, stat.S_IRUSR | stat.S_IWUSR)

    args.config_file = config_file
    args.cluster_template = cluster_template
    if _is_config_valid(args):
        print("The configuration is valid")


def _check_destination_directory(config_file):
    # ensure that the directory for the config file exists (because
    # ~/.parallelcluster is likely not to exist on first usage)
    try:
        os.makedirs(os.path.dirname(config_file))
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise  # can safely ignore EEXISTS for this purpose...


def _write_config(config, sections):
    for section in sections:
        try:
            config.add_section(section["name"])
        except configparser.DuplicateSectionError:
            pass
        for key, value in section.items():
            # Only update configuration if not set
            if value is not None and key != "name":
                config.set(section["name"], key, value)


def _remove_parameter_from_past_configuration(section, config, parameters_to_remove):
    if config.has_section(section):
        for par in parameters_to_remove:
            config.remove_option(section, par)


def _create_vpc_parameters(vpc_label, aws_region_name, scheduler, min_subnet_size, automate_vpc_creation=True):
    vpc_parameters = {"name": vpc_label}
    min_subnet_size = int(min_subnet_size)
    if automate_vpc_creation:
        vpc_parameters.update(
            automate_vpc_with_subnet_creation(
                aws_region_name, _choose_network_configuration(scheduler), min_subnet_size
            )
        )
    else:
        vpc_and_subnets = _get_vpcs_and_subnets(aws_region_name)
        vpc_list = vpc_and_subnets["vpc_list"]
        if not vpc_list:
            print("There are no VPC for the given region. Starting automatic creation of VPC and subnets...")
            vpc_parameters.update(
                automate_vpc_with_subnet_creation(
                    aws_region_name, _choose_network_configuration(scheduler), min_subnet_size
                )
            )
        else:
            vpc_id = prompt_iterable("VPC ID", vpc_list)
            vpc_parameters["vpc_id"] = vpc_id
            subnet_list = vpc_and_subnets["vpc_subnets"][vpc_id]
            if not subnet_list or (
                prompt("Automate Subnet creation? (y/n)", lambda x: x == "y" or x == "n", default_value="y") == "y"
            ):
                vpc_parameters.update(
                    automate_subnet_creation(
                        aws_region_name, vpc_id, _choose_network_configuration(scheduler), min_subnet_size
                    )
                )
            else:
                vpc_parameters.update(_ask_for_subnets(subnet_list))
    return vpc_parameters


def _ask_for_subnets(subnet_list):
    master_subnet_id = prompt_iterable("Master Subnet ID", subnet_list)
    compute_subnet_id = prompt_iterable("Compute Subnet ID", subnet_list, default_value=master_subnet_id)
    vpc_parameters = {"master_subnet_id": master_subnet_id}

    if master_subnet_id != compute_subnet_id:
        vpc_parameters["compute_subnet_id"] = compute_subnet_id

    return vpc_parameters


def _is_config_valid(args):
    """
    Validate the configuration of the pcluster configure.

    :param args: the arguments passed with the command line
    :return True if the configuration is valid, false otherwise
    """
    is_valid = True
    try:
        cfnconfig.ParallelClusterConfig(args)
    except SystemExit:
        is_valid = False
    return is_valid


def _get_config_parameter(config, section, parameter_name, default_value):
    """
    Get the parameter if present in the configuration otherwise returns default value.

    :param config the configuration parser
    :param section the name of the section
    :param parameter_name: the name of the parameter
    :param default_value: the default to propose the user
    :return:
    """
    return config.get(section, parameter_name) if config.has_option(section, parameter_name) else default_value


def _choose_network_configuration(scheduler):
    if scheduler == "awsbatch":
        return PublicPrivateNetworkConfig()
    target_type = prompt_iterable(
        "Network Configuration",
        options=[configuration.value.config_type for configuration in NetworkConfiguration],
        default_value=PublicPrivateNetworkConfig().config_type,
    )

    return next(
        configuration.value for configuration in NetworkConfiguration if configuration.value.config_type == target_type
    )


class SchedulerHandler:
    """Handle question scheduler related."""

    def __init__(self, config, cluster_label, scheduler):
        self.scheduler = scheduler
        self.config = config
        self.cluster_label = cluster_label

        self.is_aws_batch = self.scheduler == "awsbatch"

        self.instance_size_name = "vcpus" if self.is_aws_batch else "instances"
        self.max_size_name = "max_vcpus" if self.is_aws_batch else "max_queue_size"
        self.min_size_name = "min_vcpus" if self.is_aws_batch else "initial_queue_size"

        self.base_os = "alinux"
        self.compute_instance_type = "optimal"
        self.max_cluster_size = DEFAULT_VALUES["max_size"]
        self.min_cluster_size = DEFAULT_VALUES["min_size"]

    def prompt_os(self):
        """Ask for os, if necessary."""
        if not self.is_aws_batch:
            self.base_os = prompt_iterable(
                "Operating System",
                get_supported_os(self.scheduler),
                default_value=_get_config_parameter(
                    self.config,
                    section=self.cluster_label,
                    parameter_name="base_os",
                    default_value=DEFAULT_VALUES["os"],
                ),
            )

    def prompt_compute_instance_type(self):
        """Ask for compute_instance_type, if necessary."""
        if not self.is_aws_batch:
            self.compute_instance_type = prompt(
                "Compute instance type",
                lambda x: x in _list_instances(),
                default_value=DEFAULT_VALUES["compute_instance_type"],
            )

    def prompt_cluster_size(self):
        """Ask for max and min instances / vcpus."""
        self.min_cluster_size = prompt(
            "Minimum cluster size ({0})".format(self.instance_size_name),
            validator=lambda x: x.isdigit(),
            default_value=_get_config_parameter(
                self.config, self.cluster_label, self.min_size_name, DEFAULT_VALUES["min_size"]
            ),
        )

        self.max_cluster_size = prompt(
            "Maximum cluster size ({0})".format(self.instance_size_name),
            validator=lambda x: x.isdigit() and int(x) >= int(self.min_cluster_size),
            default_value=_get_config_parameter(
                self.config, self.cluster_label, self.max_size_name, DEFAULT_VALUES["max_size"]
            ),
        )

    def get_scheduler_parameters(self):
        """Return a dict containing the scheduler dependent parameters."""
        scheduler_parameters = {
            "base_os": self.base_os,
            "compute_instance_type": self.compute_instance_type,
            self.max_size_name: self.max_cluster_size,
            self.min_size_name: self.min_cluster_size,
        }
        if self.is_aws_batch:
            scheduler_parameters["desired_vcpus"] = self.min_cluster_size
        else:
            scheduler_parameters["maintain_initial_size"] = "true"
        return scheduler_parameters

    def get_parameters_to_remove(self):
        """Return a list of parameter that needs to be removed from the configuration."""
        if self.is_aws_batch:
            return "max_queue_size", "initial_queue_size", "maintain_initial_size", "compute_instance_type"
        else:
            return "max_vcpus", "desired_vcpus", "min_vcpus", "compute_instance_type"
