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
from future import standard_library  # isort:skip

standard_library.install_aliases()
# fmt: on

import copy
import errno
import functools
import logging
import os
import stat
import sys
import tempfile
from builtins import input

import boto3
import configparser
from botocore.exceptions import BotoCoreError, ClientError

from pcluster.utils import NumberedList, get_supported_os, get_supported_schedulers

from . import cfnconfig

logger = logging.getLogger("pcluster.pcluster")
unsupported_regions = ["ap-northeast-3"]
DEFAULT_VALUES = {
    "cluster_template": "default",
    "aws_region_name": "us-east-1",
    "scheduler": "sge",
    "os": "alinux",
    "max_queue_size": "10",
    "master_instance_type": "t2.micro",
    "compute_instance_type": "t2.micro",
    "vpc_name": "public",
    "initial_size": "1",
}
FORCED_BATCH_VALUES = {"os": "alinux", "compute_instance_type": "optimal"}


def handle_client_exception(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (BotoCoreError, ClientError) as e:
            print("Failed with error: %s" % e)
            print("Hint: please check your AWS credentials.")
            print("Run `aws configure` or set the credentials as environment variables.")
            sys.exit(1)

    return wrapper


def prompt(message, default_value=None, options=None):
    """
    Prompt the user a message and return the acquired value.

    Example:

    prompt("vpc", "vpc-id1", [("vpc-id1", "nome-1"), ("vpc-id2", "nome-2")])

    result:
    __________________
    Acceptable value for vpc:
    1) vpc-id1 | sasso
    2) vpc-id2 | cavolo

    vpc[vpc-id1] = xxx
    __________________

    :param message: the message to show to the user
    :param default_value: the value to return if user does not input anything
    :param options: a list of items (can also be list of list or tuple of tuple) containing the options
    to show to the user.
    Only the first element of the tuple, if you pass a tuple will be considered as acceptable.
    The user can then choose one of the option or write something that is not in them.
    :raise ValueError if options is not a list of tuple
    :return: the id of the option selected by the user.
    """
    user_prompt = "{0} [{1}]: ".format(message, default_value or "")
    if options:
        if not (isinstance(options, (tuple, list))):
            # Should never been thrown, DEBUGGING
            raise ValueError("options is not a list nor a tuple")
        if not (isinstance(options[0], (tuple, list))):
            # Convert a list to a list of tuple
            options = [(item,) for item in options]
        print("Acceptable Values for %s: " % message)
        allowed_values = set([item[0] for item in options])
        numbered_items = NumberedList(options)
        for key, value in numbered_items.get().items():
            print("{0}. {1}".format(key, " | ".join(value)))

        result = get_correct_answer(allowed_values, default_value, message, numbered_items, user_prompt)
    else:
        user_input = input(user_prompt).strip()
        result = user_input or default_value
    return result


def get_correct_answer(allowed_values, default_value, message, numbered_items, user_prompt):
    user_input = input(user_prompt).strip()
    if user_input == "":
        result = default_value
    else:
        # We give the user the possibility to try again if wrong
        while True:
            result = numbered_items.get_item_by_index(int(user_input))[0] if user_input.isdigit() else user_input
            if result in allowed_values:
                break
            else:
                print("WARNING: {0} is not an acceptable value for {1}".format(user_input, message))
                if input("Press q if you want to exit, or any other character to try again: ").strip() == "q":
                    print("Aborted by the user")
                    sys.exit(1)
            user_input = input(user_prompt).strip()
    return result


@handle_client_exception
def get_regions():
    ec2 = boto3.client("ec2")
    regions = ec2.describe_regions().get("Regions")
    return [region.get("RegionName") for region in regions if region.get("RegionName") not in unsupported_regions]


def _evaluate_aws_region(aws_region_name):
    if aws_region_name:
        region = aws_region_name
    elif os.environ.get("AWS_DEFAULT_REGION"):
        region = os.environ.get("AWS_DEFAULT_REGION")
    else:
        region = DEFAULT_VALUES["aws_region_name"]
    return region


@handle_client_exception
def ec2_conn(aws_region_name):
    region = _evaluate_aws_region(aws_region_name)
    ec2 = boto3.client("ec2", region_name=region)
    return ec2


def extract_tag_from_resource(resource, tag_name):
    tags = resource.get("Tags", [])
    return next((item.get("Value") for item in tags if item.get("Key") == tag_name), None)


def _list_resource(resource, aws_region_name, resource_name, resource_id_name):
    resource_options = []
    for key in resource.get(resource_name):
        keyid = key.get(resource_id_name)
        name = extract_tag_from_resource(key, tag_name="Name")
        resource_options.append((keyid, name)) if name else resource_options.append((keyid,))

    if not resource_options:
        print("ERROR: No {0} found in region  {1}".format(resource_name, aws_region_name))
        print("Please create a {0} before continuing".format(resource_name[:-1]))
        sys.exit(1)
    return resource_options


@handle_client_exception
def _list_keys(aws_region_name):
    """Return a list of keys as a list of tuple of type (key-name,)."""
    conn = ec2_conn(aws_region_name)
    keypairs = conn.describe_key_pairs()
    return _list_resource(keypairs, aws_region_name, "KeyPairs", "KeyName")


@handle_client_exception
def _list_vpcs(aws_region_name):
    """Return a list of vpcs as a list of tuple of type (vpc-id, vpc-name (if present))."""
    conn = ec2_conn(aws_region_name)
    vpcs = conn.describe_vpcs()
    return _list_resource(vpcs, aws_region_name, "Vpcs", "VpcId")


@handle_client_exception
def _list_subnets(aws_region_name, vpc_id):
    """Return a list of subnet as a list of tuple of type (subnet-id, subnet-name (if present))."""
    conn = ec2_conn(aws_region_name)
    subnets = conn.describe_subnets(Filters=[{"Name": "vpcId", "Values": [vpc_id]}])
    return _list_resource(subnets, aws_region_name, "Subnets", "SubnetId")


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
    cluster_template = prompt(
        "Cluster configuration label",
        get_config_parameter(
            config,
            section="global",
            parameter_name="cluster_template",
            default_value=DEFAULT_VALUES["cluster_template"],
        ),
    )
    cluster_label = "cluster " + cluster_template

    # Use built in boto regions as an available option
    aws_region_name = prompt(
        "AWS Region ID",
        get_config_parameter(
            config, section="aws", parameter_name="aws_region_name", default_value=DEFAULT_VALUES["aws_region_name"]
        ),
        options=get_regions(),
    )

    scheduler = prompt(
        "Scheduler",
        get_config_parameter(
            config, section=cluster_label, parameter_name="scheduler", default_value=DEFAULT_VALUES["scheduler"]
        ),
        options=get_supported_schedulers(),
    )
    scheduler_info = scheduler_handler(scheduler)
    is_aws_batch = scheduler == "awsbatch"

    if is_aws_batch:
        operating_system = FORCED_BATCH_VALUES["os"]
    else:
        operating_system = prompt(
            "Operating System",
            get_config_parameter(
                config, section=cluster_label, parameter_name="base_os", default_value=DEFAULT_VALUES["os"]
            ),
            options=get_supported_os(scheduler),
        )

    max_queue_size = prompt(
        "Max Queue Size",
        get_config_parameter(config, cluster_label, scheduler_info["max_size"], DEFAULT_VALUES["max_queue_size"]),
    )

    master_instance_type = prompt(
        "Master instance type",
        get_config_parameter(
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
            message="Compute instance type", default_value=DEFAULT_VALUES["compute_instance_type"]
        )

    vpc_name = prompt(
        "VPC configuration label",
        get_config_parameter(
            config, section=cluster_label, parameter_name="vpc_settings", default_value=DEFAULT_VALUES["vpc_name"]
        ),
    )
    vpc_label = "vpc " + vpc_name

    keys = _list_keys(aws_region_name)
    default_key = keys[0]
    default_key_id = default_key[0]
    key_name = prompt("Key Name", default_key_id, options=keys)

    vpcs = _list_vpcs(aws_region_name)
    default_vpc = vpcs[0]
    default_vpc_id = default_vpc[0]
    vpc_id = prompt("VPC ID", default_vpc_id, options=vpcs)

    subnets = _list_subnets(aws_region_name, vpc_id)
    default_subnet = subnets[0]
    default_subnet_id = default_subnet[0]
    master_subnet_id = prompt("Master Subnet ID", default_subnet_id, options=subnets)

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
        "vpc_settings": vpc_name,
        "scheduler": scheduler,
        "base_os": operating_system,
        "compute_instance_type": compute_instance_type,
        "master_instance_type": master_instance_type,
        scheduler_info["max_size"]: max_queue_size,
        scheduler_info["initial_size"]: DEFAULT_VALUES["initial_size"],
    }
    aliases_parameters = {"__name__": "aliases", "ssh": "ssh {CFN_USER}@{MASTER_IP} {ARGS}"}
    vpc_parameters = {"__name__": vpc_label, "vpc_id": vpc_id, "master_subnet_id": master_subnet_id}
    sections = [aws_parameters, cluster_parameters, vpc_parameters, global_parameters, aliases_parameters]

    # We first remove unnecessary parameters from the past configurations
    if config.has_section(cluster_label):
        for par in scheduler_info["parameters_to_remove"]:
            config.remove_option(cluster_label, par)

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

    if not _is_config_valid(args, config):
        sys.exit(1)

    # If we are here, than the file it's correct and we can override it.
    # Write configuration to disk
    open(config_file, "a").close()
    os.chmod(config_file, stat.S_IRUSR | stat.S_IWUSR)
    with open(config_file, "w") as cf:
        config.write(cf)


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
        scheduler_info["initial_size"] = "desired_vcpus"
    else:
        scheduler_info["parameters_to_remove"] = "max_vcpus", "desired_vcpus", "min_vcpus", "compute_instance_type"
        scheduler_info["max_size"] = "max_queue_size"
        scheduler_info["initial_size"] = "initial_queue_size"
    return scheduler_info
