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
from botocore.exceptions import BotoCoreError, ClientError

from . import cfnconfig

logger = logging.getLogger("pcluster.pcluster")
unsupported_regions = ["ap-northeast-3", "cn-north-1", "cn-northwest-1"]


def handle_client_exception(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (BotoCoreError, ClientError) as e:
            print("Failed with error: %s" % e)
            print("Hint: please check your AWS credentials.")
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

    if isinstance(options, list):
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


def ec2_conn(aws_access_key_id, aws_secret_access_key, aws_region_name):
    if aws_region_name:
        region = aws_region_name
    elif os.environ.get("AWS_DEFAULT_REGION"):
        region = os.environ.get("AWS_DEFAULT_REGION")
    else:
        region = "us-east-1"

    ec2 = boto3.client(
        "ec2", region_name=region, aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key
    )
    return ec2


@handle_client_exception
def list_keys(aws_access_key_id, aws_secret_access_key, aws_region_name):
    conn = ec2_conn(aws_access_key_id, aws_secret_access_key, aws_region_name)
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
def list_vpcs(aws_access_key_id, aws_secret_access_key, aws_region_name):
    conn = ec2_conn(aws_access_key_id, aws_secret_access_key, aws_region_name)
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
def list_subnets(aws_access_key_id, aws_secret_access_key, aws_region_name, vpc_id):
    conn = ec2_conn(aws_access_key_id, aws_secret_access_key, aws_region_name)
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

    # Prompt for required values, using existing as defaults
    cluster_template = prompt(
        "Cluster Template",
        config.get("global", "cluster_template") if config.has_option("global", "cluster_template") else "default",
    )
    aws_access_key_id = prompt(
        "AWS Access Key ID",
        config.get("aws", "aws_access_key_id") if config.has_option("aws", "aws_access_key_id") else None,
        True,
    )
    aws_secret_access_key = prompt(
        "AWS Secret Access Key ID",
        config.get("aws", "aws_secret_access_key") if config.has_option("aws", "aws_secret_access_key") else None,
        True,
    )
    if not aws_access_key_id or not aws_secret_access_key:
        print(
            "You chose not to configure aws credentials in parallelcluster config file.\n"
            "Please make sure you export a valid AWS_PROFILE or you have them exported in "
            "the AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables."
        )

    # Use built in boto regions as an available option
    aws_region_name = prompt(
        "AWS Region ID",
        config.get("aws", "aws_region_name") if config.has_option("aws", "aws_region_name") else None,
        options=get_regions(),
        check_validity=True,
    )
    vpcname = prompt(
        "VPC Name",
        config.get("cluster " + cluster_template, "vpc_settings")
        if config.has_option("cluster " + cluster_template, "vpc_settings")
        else "public",
    )

    # Query EC2 for available keys as options
    key_name = prompt(
        "Key Name",
        config.get("cluster " + cluster_template, "key_name")
        if config.has_option("cluster " + cluster_template, "key_name")
        else None,
        options=list_keys(aws_access_key_id, aws_secret_access_key, aws_region_name),
        check_validity=True,
    )
    vpc_id = prompt(
        "VPC ID",
        config.get("vpc " + vpcname, "vpc_id") if config.has_option("vpc " + vpcname, "vpc_id") else None,
        options=list_vpcs(aws_access_key_id, aws_secret_access_key, aws_region_name),
        check_validity=True,
    )
    master_subnet_id = prompt(
        "Master Subnet ID",
        config.get("vpc " + vpcname, "master_subnet_id")
        if config.has_option("vpc " + vpcname, "master_subnet_id")
        else None,
        options=list_subnets(aws_access_key_id, aws_secret_access_key, aws_region_name, vpc_id),
        check_validity=True,
    )

    # Dictionary of values we want to set
    s_global = {
        "__name__": "global",
        "cluster_template": cluster_template,
        "update_check": "true",
        "sanity_check": "true",
    }
    s_aws = {
        "__name__": "aws",
        "aws_access_key_id": aws_access_key_id,
        "aws_secret_access_key": aws_secret_access_key,
        "aws_region_name": aws_region_name,
    }
    s_aliases = {"__name__": "aliases", "ssh": "ssh {CFN_USER}@{MASTER_IP} {ARGS}"}
    s_cluster = {"__name__": "cluster " + cluster_template, "key_name": key_name, "vpc_settings": vpcname}
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
            if value is not None and key is not "__name__":
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

    # Verify the configuration
    cfnconfig.ParallelClusterConfig(args)
