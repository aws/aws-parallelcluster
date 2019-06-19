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
# fmt: off
from __future__ import absolute_import, print_function  # isort:skip


import copy
import errno
import logging
import os
import stat
import tempfile

import boto3
import configparser

from pcluster import cfnconfig
from pcluster.easyconfig.easyconfig_networking import (
    _choose_network_configuration,
    automate_creation_of_subnet,
    automate_creation_of_vpc_and_subnet,
    ec2_conn,
    handle_client_exception,
)
from pcluster.easyconfig.easyconfig_utils import _prompt_a_list, _prompt_a_list_of_tuple, prompt
from pcluster.utils import get_subnet_cidr, get_supported_os, get_supported_schedulers

from future import standard_library  # isort:skip


standard_library.install_aliases()
# fmt: on


LOGGER = logging.getLogger("pcluster.pcluster")
unsupported_regions = ["ap-northeast-3"]
DEFAULT_VALUES = {
    "aws_region_name": "us-east-1",
    "cluster_template": "default",
    "scheduler": "sge",
    "os": "alinux",
    "max_queue_size": "10",
    "master_instance_type": "t2.micro",
    "compute_instance_type": "t2.micro",
    "vpc_name": "public",
    "min_size": "0",
}
FORCED_BATCH_VALUES = {"os": "alinux", "compute_instance_type": "optimal"}
VPC_PARAMETERS_TO_REMOVE = "vpc-id", "master_subnet_id", "compute_subnet_id", "use_public_ips", "compute_subnet_cidr"


@handle_client_exception
def get_regions():
    ec2 = boto3.client("ec2")
    regions = ec2.describe_regions().get("Regions")
    return [region.get("RegionName") for region in regions if region.get("RegionName") not in unsupported_regions]


def extract_tag_from_resource(resource, tag_name):
    tags = resource.get("Tags", [])
    return next((item.get("Value") for item in tags if item.get("Key") == tag_name), None)


@handle_client_exception
def _list_keys(aws_region_name):
    """Return a list of keys."""
    conn = ec2_conn(aws_region_name)
    keypairs = conn.describe_key_pairs()
    key_options = []
    for resource in keypairs.get("KeyPairs"):
        keyid = resource.get("KeyName")
        key_options.append(keyid)

    if not key_options:
        print(
            "No KeyPair found in region {0}, please create one following the guide: "
            "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html".format(aws_region_name)
        )

    return key_options


def extract_subnet_size(cidr):
    return 2 ** (32 - int(cidr.split("/")[1]))


@handle_client_exception
def _list_vpcs_and_subnets(aws_region_name):
    """
    Return a dictionary containg a list of vpc in the given region and the associated vpcs.

    Example:

    {"vpc_list": list(tuple(vpc-id, name, number of subnets)) ,
    "vpc_to_subnet" : {"vpc-id1": list(tuple(subnet-id1, name)), "vpc-id2": list(tuple(subnet-id1, name))}}
    :param aws_region_name: the region name
    """
    conn = ec2_conn(aws_region_name)
    vpcs = conn.describe_vpcs()
    vpc_options = []
    vpc_to_subnets = {}
    for vpc in vpcs.get("Vpcs"):
        vpc_id = vpc.get("VpcId")
        subnet_options = []
        subnet_list = conn.describe_subnets(Filters=[{"Name": "vpcId", "Values": [vpc_id]}]).get("Subnets")
        for subnet in subnet_list:
            subnet_id = subnet.get("SubnetId")
            subnet_size_string = "Subnet size: {0}".format(extract_subnet_size(subnet.get("CidrBlock")))
            name = extract_tag_from_resource(subnet, tag_name="Name")
            if name:
                subnet_options.append((subnet_id, name, subnet_size_string))
            else:
                subnet_options.append((subnet_id, subnet_size_string))
        name = extract_tag_from_resource(vpc, tag_name="Name")
        vpc_to_subnets[vpc_id] = subnet_options
        subnets_number = "{0} subnets inside".format(len(subnet_list))
        vpc_options.append((vpc_id, name, subnets_number)) if name else vpc_options.append((vpc_id, subnets_number))

    return {"vpc_list": vpc_options, "vpc_to_subnets": vpc_to_subnets}


@handle_client_exception
def _list_instances():  # Specifying the region does not make any difference
    """Return a list of all the supported instance at the moment by aws, independent by the region."""
    return ec2_conn(DEFAULT_VALUES["aws_region_name"]).meta.service_model.shape_for("InstanceType").enum


def configure(args):  # noqa: C901 FIXME!!!
    # Determine config file name based on args or default
    config_file = (
        args.config_file if args.config_file else os.path.expanduser(os.path.join("~", ".parallelcluster", "config"))
    )

    config = configparser.ConfigParser()
    # Check if configuration file exists
    if os.path.isfile(config_file):
        config.read(config_file)

    # Prompt for required values, using existing as defaults
    cluster_template = DEFAULT_VALUES["cluster_template"]
    cluster_label = "cluster " + cluster_template
    vpc_label = "vpc " + cluster_template

    # Use built in boto regions as an available option
    aws_region_name = _prompt_a_list(
        "AWS Region ID",
        get_regions(),
        default_value=get_config_parameter(
            config, section="aws", parameter_name="aws_region_name", default_value=DEFAULT_VALUES["aws_region_name"]
        ),
    )

    scheduler = _prompt_a_list(
        "Scheduler",
        get_supported_schedulers(),
        default_value=get_config_parameter(
            config, section=cluster_label, parameter_name="scheduler", default_value=DEFAULT_VALUES["scheduler"]
        ),
    )
    scheduler_info = scheduler_handler(scheduler)
    is_aws_batch = scheduler == "awsbatch"

    if is_aws_batch:
        operating_system = FORCED_BATCH_VALUES["os"]
    else:
        operating_system = _prompt_a_list(
            "Operating System",
            get_supported_os(scheduler),
            default_value=get_config_parameter(
                config, section=cluster_label, parameter_name="base_os", default_value=DEFAULT_VALUES["os"]
            ),
        )

    min_queue_size = prompt(
        "Minimum cluster size ({0})".format(scheduler_info["instance_size_name"]),
        validator=lambda x: x.isdigit(),
        default_value=get_config_parameter(
            config, cluster_label, scheduler_info["min_size"], DEFAULT_VALUES["min_size"]
        ),
    )

    max_queue_size = prompt(
        "Maximum cluster size ({0})".format(scheduler_info["instance_size_name"]),
        validator=lambda x: x.isdigit() and int(x) >= int(min_queue_size),
        default_value=get_config_parameter(
            config, cluster_label, scheduler_info["max_size"], DEFAULT_VALUES["max_queue_size"]
        ),
    )

    master_instance_type = prompt(
        "Master instance type",
        lambda x: x in _list_instances(),
        default_value=get_config_parameter(
            config,
            section=cluster_label,
            parameter_name="master_instance_type",
            default_value=DEFAULT_VALUES["master_instance_type"],
        ),
    )

    if is_aws_batch:
        compute_instance_type = FORCED_BATCH_VALUES["compute_instance_type"]
    else:
        compute_instance_type = prompt(
            "Compute instance type",
            lambda x: x in _list_instances(),
            default_value=DEFAULT_VALUES["compute_instance_type"],
        )

    key_name = _prompt_a_list("EC2 Key Pair Name", _list_keys(aws_region_name))
    automate_vpc = prompt("Automate VPC creation? (y/n)", lambda x: x == "y" or x == "n", default_value="n") == "y"

    vpc_parameters = _create_vpc_parameters(
        vpc_label, aws_region_name, scheduler, max_queue_size, automatized_vpc=automate_vpc
    )
    global_parameters = {
        "__name__": "global",
        "cluster_template": cluster_template,
        "update_check": "true",
        "sanity_check": "true",
    }
    aws_parameters = {"__name__": "aws", "aws_region_name": aws_region_name}
    cluster_parameters = {
        "__name__": cluster_label,
        "key_name": key_name,
        "vpc_settings": cluster_template,
        "scheduler": scheduler,
        "base_os": operating_system,
        "compute_instance_type": compute_instance_type,
        "master_instance_type": master_instance_type,
        scheduler_info["max_size"]: max_queue_size,
        scheduler_info["min_size"]: min_queue_size,
    }
    if scheduler_info["value_for_initial_size"] == "min_size":
        cluster_parameters[scheduler_info["initial_size_parameter_name"]] = min_queue_size
    else:
        cluster_parameters[scheduler_info["initial_size_parameter_name"]] = scheduler_info["value_for_initial_size"]

    aliases_parameters = {"__name__": "aliases", "ssh": "ssh {CFN_USER}@{MASTER_IP} {ARGS}"}
    sections = [aws_parameters, cluster_parameters, vpc_parameters, global_parameters, aliases_parameters]

    # We first remove unnecessary parameters from the past configurations
    _remove_parameter_from_past_configuration(cluster_label, config, scheduler_info["parameters_to_remove"])
    _remove_parameter_from_past_configuration(vpc_label, config, VPC_PARAMETERS_TO_REMOVE)

    # Loop through the configuration sections we care about
    for section in sections:
        try:
            config.add_section(section["__name__"])
        except configparser.DuplicateSectionError:
            pass
        for key, value in section.items():
            # Only update configuration if not set
            if value is not None and key != "__name__":
                config.set(section["__name__"], key, value)

    # ensure that the directory for the config file exists (because
    # ~/.parallelcluster is likely not to exist on first usage)
    try:
        os.makedirs(os.path.dirname(config_file))
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise  # can safely ignore EEXISTS for this purpose...

    # Write configuration to disk
    open(config_file, "a").close()
    os.chmod(config_file, stat.S_IRUSR | stat.S_IWUSR)
    with open(config_file, "w") as cf:
        config.write(cf)

    if _is_config_valid(args, config):
        print("The configuration is valid")


def _remove_parameter_from_past_configuration(section, config, parameters_to_remove):
    if config.has_section(section):
        for par in parameters_to_remove:
            config.remove_option(section, par)


def _create_vpc_parameters(vpc_label, aws_region_name, scheduler, max_queue_size, automatized_vpc=True):
    vpc_parameters = {"__name__": vpc_label}
    max_queue_size = int(max_queue_size)
    if automatized_vpc:
        vpc_parameters.update(
            automate_creation_of_vpc_and_subnet(
                aws_region_name,
                _choose_network_configuration(scheduler),
                max_queue_size,
            )
        )
    else:
        vpc_and_subnets = _list_vpcs_and_subnets(aws_region_name)
        vpc_list = vpc_and_subnets["vpc_list"]
        if not vpc_list:
            print("There are no VPC for the given region. Starting automatic creation of vpc and subnets...")
            vpc_parameters.update(
                automate_creation_of_vpc_and_subnet(
                    aws_region_name, _choose_network_configuration(scheduler), max_queue_size
                )
            )
        else:
            vpc_id = _prompt_a_list_of_tuple("VPC ID", vpc_list)
            vpc_parameters["vpc_id"] = vpc_id
            subnet_list = vpc_and_subnets["vpc_to_subnets"][vpc_id]
            if not subnet_list or (
                prompt("Automate Subnet creation? (y/n)", lambda x: x == "y" or x == "n", default_value="y") == "y"
            ):
                vpc_parameters.update(
                    automate_creation_of_subnet(
                        aws_region_name, vpc_id, _choose_network_configuration(scheduler), max_queue_size
                    )
                )
            else:
                vpc_parameters.update(_ask_for_subnets(subnet_list))
    return vpc_parameters


def _ask_for_subnets(subnet_list):
    master_subnet_id = _prompt_a_list_of_tuple("Master Subnet ID", subnet_list)
    compute_subnet_id = _prompt_a_list_of_tuple("Compute Subnet ID", subnet_list, default_value=master_subnet_id)
    vpc_parameters = {"master_subnet_id": master_subnet_id}

    if master_subnet_id != compute_subnet_id:
        vpc_parameters["compute_subnet_id"] = compute_subnet_id

    return vpc_parameters


def _is_config_valid(args, config):
    """
    Validate the configuration of the pcluster configure.

    :param args: the arguments passed with the command line
    :param config: the configParser
    :return True if the configuration is valid, false otherwise
    """
    # We create a temp_file_path to validate before overriding the original config
    temp_file_path = os.path.join(tempfile.gettempdir(), "temp_config")
    temp_args = copy.copy(args)  # Defensive copy is needed because we change config_file

    temp_args.config_file = temp_file_path
    with open(temp_file_path, "w+") as cf:
        config.write(cf)
    # Verify the configuration
    is_valid = True
    try:
        cfnconfig.ParallelClusterConfig(temp_args)
    except SystemExit:
        is_valid = False
    finally:
        os.remove(temp_file_path)
        return is_valid


def get_config_parameter(config, section, parameter_name, default_value):
    """
    Get the parameter if present in the configuration otherwise returns default value.

    :param config the configuration parser
    :param section the name of the section
    :param parameter_name: the name of the parameter
    :param default_value: the default to propose the user
    :return:
    """
    return config.get(section, parameter_name) if config.has_option(section, parameter_name) else default_value


def scheduler_handler(scheduler):
    """
    Return a dictionary containing information based on the scheduler.

    :param scheduler the target scheduler
    :return: a dictionary with containing the information
    """
    scheduler_info = {}
    if scheduler == "awsbatch":
        scheduler_info["parameters_to_remove"] = (
            "max_queue_size",
            "initial_queue_size",
            "maintain_initial_size",
            "compute_instance_type",
        )
        scheduler_info["max_size"] = "max_vcpus"
        scheduler_info["min_size"] = "min_vcpus"
        scheduler_info["initial_size_parameter_name"] = "desired_vcpus"
        scheduler_info["value_for_initial_size"] = "min_size"
        scheduler_info["instance_size_name"] = "vcpus"
    else:
        scheduler_info["parameters_to_remove"] = ("max_vcpus", "desired_vcpus", "min_vcpus", "compute_instance_type")
        scheduler_info["max_size"] = "max_queue_size"
        scheduler_info["min_size"] = "initial_queue_size"
        scheduler_info["initial_size_parameter_name"] = "maintain_initial_size"
        scheduler_info["value_for_initial_size"] = "true"
        scheduler_info["instance_size_name"] = "instances"
    return scheduler_info
