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

from pcluster.utils import get_supported_os, get_supported_schedulers

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


def prompt(message, default_value=None, hidden=False, options=None, check_validity=False):
    if hidden and default_value is not None:
        user_prompt = message + " [*******" + default_value[-4:] + "]: "
    else:
        user_prompt = message + " ["
        if default_value is not None:
            user_prompt = user_prompt + default_value + "]: "
        else:
            user_prompt = user_prompt + "]: "

    if isinstance(options, (list, tuple)):
        print("Acceptable Values for %s: " % message)
        for o in options:
            print("    %s" % o)

    var = input(user_prompt).strip()

    if var == "":
        return default_value
    else:
        if check_validity and options is not None and var not in options:
            print("ERROR: The value (%s) is not valid " % var)
            print("Please select one of the Acceptable Values listed above.")
            sys.exit(1)
        else:
            return var


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


@handle_client_exception
def list_keys(aws_region_name):
    conn = ec2_conn(aws_region_name)
    keypairs = conn.describe_key_pairs()
    keynames = []
    for key in keypairs.get("KeyPairs"):
        keynames.append(key.get("KeyName"))

    if not keynames:
        print("ERROR: No Key Pairs found in region " + aws_region_name)
        print("Please create an EC2 Key Pair before continuing")
        sys.exit(1)

    return keynames


@handle_client_exception
def list_vpcs(aws_region_name):
    conn = ec2_conn(aws_region_name)
    vpcs = conn.describe_vpcs()
    vpcids = []
    for vpc in vpcs.get("Vpcs"):
        vpcids.append(vpc.get("VpcId"))

    if not vpcids:
        print("ERROR: No VPCs found in region " + aws_region_name)
        print("Please create a VPC before continuing")
        sys.exit(1)

    return vpcids


@handle_client_exception
def list_subnets(aws_region_name, vpc_id):
    conn = ec2_conn(aws_region_name)
    subnets = conn.describe_subnets(Filters=[{"Name": "vpcId", "Values": [vpc_id]}])
    subnetids = []
    for subnet in subnets.get("Subnets"):
        subnetids.append(subnet.get("SubnetId"))

    if not subnetids:
        print("ERROR: No Subnets found in region " + aws_region_name)
        print("Please create a VPC Subnet before continuing")
        sys.exit(1)

    return subnetids


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
        check_validity=True,
    )

    scheduler = prompt(
        "Scheduler",
        get_config_parameter(
            config, section=cluster_label, parameter_name="scheduler", default_value=DEFAULT_VALUES["scheduler"]
        ),
        options=get_supported_schedulers(),
        check_validity=True,
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
            check_validity=True,
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

    keys = list_keys(aws_region_name)
    key_name = prompt(
        "Key Name",
        get_config_parameter(config, section=cluster_label, parameter_name="key_name", default_value=keys[0]),
        options=keys,
        check_validity=True,
    )

    vpc_id = prompt(
        "VPC ID",
        get_config_parameter(config, section=vpc_label, parameter_name="vpc_id", default_value=None),
        options=list_vpcs(aws_region_name),
        check_validity=True,
    )

    master_subnet_id = prompt(
        "Master Subnet ID",
        get_config_parameter(config, section=vpc_label, parameter_name="master_subnet_id", default_value=None),
        options=list_subnets(aws_region_name, vpc_id),
        check_validity=True,
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
