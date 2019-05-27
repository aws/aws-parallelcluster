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

import errno
import functools
import logging
import os
import stat
import sys
from builtins import input

import boto3
import configparser
import tempfile
from botocore.exceptions import BotoCoreError, ClientError

from . import cfnconfig
from pcluster.utils import get_supported_schedulers
from pcluster.utils import get_supported_os

logger = logging.getLogger("pcluster.pcluster")
unsupported_regions = ["ap-northeast-3"]
default_region = "us-east-1"


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


def prompt(prompt, default_value=None, hidden=False, options=None, check_validity=False):
    if hidden and default_value is not None:
        user_prompt = prompt + " [*******" + default_value[-4:] + "]: "
    else:
        user_prompt = prompt + " ["
        if default_value is not None:
            user_prompt = user_prompt + default_value + "]: "
        else:
            user_prompt = user_prompt + "]: "

    if isinstance(options, (list,tuple)):
        print("Acceptable Values for %s: " % prompt)
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


@handle_client_exception
def ec2_get_region(aws_region_name):
    if aws_region_name:
        region = aws_region_name
    elif os.environ.get("AWS_DEFAULT_REGION"):
        region = os.environ.get("AWS_DEFAULT_REGION")
    else:
        region = default_region
    return region


@handle_client_exception
def ec2_conn(aws_region_name):
    region = ec2_get_region(aws_region_name)
    ec2 = boto3.client("ec2", region_name=region)
    return ec2


@handle_client_exception
def list_keys(aws_region_name):
    aws_region_name = ec2_get_region(aws_region_name)  # we get the default if not present
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
    if args.config_file is not None:
        config_file = args.config_file
    else:
        config_file = os.path.expanduser(os.path.join("~", ".parallelcluster", "config"))

    config = configparser.ConfigParser()
    # Check if configuration file exists
    if os.path.isfile(config_file):
        config.read(config_file)

    s_cluster = {}

    # Prompt for required values, using existing as defaults
    cluster_template = prompt(
        "Cluster template",
        get_parameter(config, "global", "cluster_template", "default"),
    )
    s_cluster["__name__"] = "cluster " + cluster_template

    # Use built in boto regions as an available option
    aws_region_name = prompt(
        "AWS Region ID",
        get_parameter(config, "aws", "aws_region_name", default_region),
        options=get_regions(),
        check_validity=True,
    )

    scheduler = prompt(
        "Scheduler",
        get_parameter(config, "cluster " + cluster_template, "scheduler", "sge"),
        options=get_supported_schedulers(),
        check_validity=True,
    )
    s_cluster["scheduler"] = scheduler

    if _is_aws_batch(scheduler):
        s_cluster.update(aws_batch_handler(config, cluster_template))
    else:
        s_cluster.update(general_scheduler_handler(config, cluster_template))

    vpcname = prompt(
        "VPC Name",
        get_parameter(config, "cluster " + cluster_template, "vpc_settings", "public"),
    )
    s_cluster["vpc_settings"] = vpcname

    keys = list_keys(aws_region_name)
    # Query EC2 for available keys as options
    key_name = prompt(
        "Key Name",
        get_parameter(config, "cluster " + cluster_template, "key_name", keys[0]),
        options=keys,
        check_validity=True,
    )
    s_cluster["key_name"] = key_name

    vpc_id = prompt(
        "VPC ID",
        get_parameter(config, "vpc " + vpcname, "vpc_id", None),
        options=list_vpcs(aws_region_name),
        check_validity=True,
    )

    master_subnet_id = prompt(
        "Master Subnet ID",
        get_parameter(config, "vpc " + vpcname, "master_subnet_id", None),
        options=list_subnets(aws_region_name, vpc_id),
        check_validity=True,
    )

    # Dictionary of values we want to set
    s_global = {
        "__name__": "global",
        "cluster_template": cluster_template,
        "update_check": "true",
        "sanity_check": "true",
    }
    s_aws = {"__name__": "aws", "aws_region_name": aws_region_name}
    s_aliases = {"__name__": "aliases", "ssh": "ssh {CFN_USER}@{MASTER_IP} {ARGS}"}
    s_vpc = {"__name__": "vpc " + vpcname, "vpc_id": vpc_id, "master_subnet_id": master_subnet_id}

    sections = [s_aws, s_cluster, s_vpc, s_global, s_aliases]

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
    # We create a temp_file to validate before overriding the original config
    path = os.path.join(tempfile.gettempdir(), "temp_config")
    temp_file = path
    temp_args = args
    temp_args.config_file = path
    open(temp_file, "a").close()
    os.chmod(temp_file, stat.S_IRUSR | stat.S_IWUSR)
    with open(temp_file, "w") as cf:
        config.write(cf)
    # Verify the configuration
    is_file_ok = True
    try:
        cfnconfig.ParallelClusterConfig(temp_args)
    except SystemExit as e:
        is_file_ok = False
    finally:
        os.remove(path)
        if is_file_ok:
            return True
        return False


def get_parameter(config, section, parameter_name, default_value):
    """
    Prompt the user to ask question without validation
    :param config the configuration parser
    :param section the name of the section
    :param parameter_name: the name of the parameter
    :param default_value: the default string to ask the user
    :return:
    """
    return config.get(section, parameter_name) if config.has_option(section, parameter_name) else default_value


def general_scheduler_handler(config, cluster_template):
    """
    Return a dictionary containing the values asked to the user for a generic scheduler non aws_batch
    :param config the configuration parser
    :param cluster_template the name of the cluster
    :return: a dictionary with the updated values
    """
    scheduler_dict = {}

    # We first remove unnecessary parameters from the past configurations
    batch_parameters = "max_vcpus", "desired_vcpus", "min_vcpus"
    for par in batch_parameters:
        config.remove_option("cluster " + cluster_template, par)

    operating_system = prompt(
        "Operating System",
        get_parameter(config, "cluster " + cluster_template, "base_os", "alinux"),
        options=get_supported_os(),
        check_validity=True,
    )
    scheduler_dict["base_os"] = operating_system

    max_queue_size = prompt(
        "Max Queue Size",
        get_parameter(config, "cluster " + cluster_template, "max_queue_size", "10")
    )

    scheduler_dict["max_queue_size"] = max_queue_size
    scheduler_dict["initial_queue_size"] = "1"
    return scheduler_dict


def aws_batch_handler(config, cluster_template):
    """
    Return a dictionary containing the values asked to the user for aws_batch
    :param config the configuration parser
    :param cluster_template the name of the cluster
    :return: a dictionary with the updated values
    """
    batch_dict = {"base_os": "alinux", "desired_vcpus": "1"}

    # We first remove unnecessary parameters from the past configurations
    non_batch_parameters = "max_queue_size", "initial_queue_size", "maintain_initial_size"
    for par in non_batch_parameters:
        config.remove_option("cluster " + cluster_template, par)
    # Ask the users for max_vcpus
    max_vcpus = prompt(
        "Max Queue Size",
        get_parameter(config, "cluster " + cluster_template, "max_vcpus", "10")
    )

    batch_dict["max_vcpus"] = max_vcpus
    return batch_dict


def _is_aws_batch(scheduler):
    """
    Return true if the scheduler is awsbatch
    :param scheduler: the scheduler to check
    :return: true if the scheduler is awsbatch
    """
    if scheduler == "awsbatch":
        return True
    return False
