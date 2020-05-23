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

import logging
import os

import boto3

from pcluster.config.pcluster_config import PclusterConfig
from pcluster.configure.networking import (
    NetworkConfiguration,
    PublicPrivateNetworkConfig,
    automate_subnet_creation,
    automate_vpc_with_subnet_creation,
)
from pcluster.configure.utils import get_regions, get_resource_tag, handle_client_exception, prompt, prompt_iterable
from pcluster.utils import (
    error,
    get_region,
    get_supported_compute_instance_types,
    get_supported_instance_types,
    get_supported_os_for_scheduler,
    get_supported_schedulers,
)

LOGGER = logging.getLogger(__name__)


@handle_client_exception
def _get_keys():
    """Return a list of keys."""
    keypairs = boto3.client("ec2").describe_key_pairs()
    key_options = []
    for key in keypairs.get("KeyPairs"):
        key_name = key.get("KeyName")
        key_options.append(key_name)

    if not key_options:
        print(
            "No KeyPair found in region {0}, please create one following the guide: "
            "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html".format(get_region())
        )

    return key_options


def _extract_subnet_size(cidr):
    return 2 ** (32 - int(cidr.split("/")[1]))


@handle_client_exception
def _get_vpcs_and_subnets():
    """
    Return a dictionary containing a list of vpc in the given region and the associated VPCs.

    Example:
    {"vpc_list": list(tuple(vpc-id, name, number of subnets)) ,
    "vpc_to_subnet" : {"vpc-id1": list(tuple(subnet-id1, name)), "vpc-id2": list(tuple(subnet-id1, name))}}
    """
    ec2_client = boto3.client("ec2")
    vpcs = ec2_client.describe_vpcs()
    vpc_options = []
    vpc_subnets = {}

    for vpc in vpcs.get("Vpcs"):
        vpc_id = vpc.get("VpcId")
        subnets = _get_subnets(ec2_client, vpc_id)
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


def configure(args):
    # Check for invalid path (eg. a directory)
    if args.config_file and os.path.exists(args.config_file) and not os.path.isfile(args.config_file):
        error("Invalid configuration file path: {0}".format(args.config_file))

    pcluster_config = PclusterConfig(config_file=args.config_file, fail_on_error=False)

    if os.path.exists(pcluster_config.config_file):
        msg = "WARNING: Configuration file {0} will be overwritten."
    else:
        msg = "INFO: Configuration file {0} will be written."
    print(msg.format(pcluster_config.config_file))
    print("Press CTRL-C to interrupt the procedure.\n\n")

    cluster_section = pcluster_config.get_section("cluster")

    global_config = pcluster_config.get_section("global")
    cluster_label = global_config.get_param_value("cluster_template")

    vpc_section = pcluster_config.get_section("vpc")
    vpc_label = vpc_section.label

    # Use built in boto regions as an available option
    available_regions = get_regions()
    default_region = pcluster_config.get_section("aws").get_param_value("aws_region_name")
    aws_region_name = prompt_iterable(
        "AWS Region ID",
        available_regions,
        default_value=default_region if default_region in available_regions else None,
    )
    # Set provided region into os environment for suggestions and validations from here on
    os.environ["AWS_DEFAULT_REGION"] = aws_region_name

    # Get the key name from the current region, if any
    available_keys = _get_keys()
    default_key = cluster_section.get_param_value("key_name")
    key_name = prompt_iterable(
        "EC2 Key Pair Name", available_keys, default_value=default_key if default_key in available_keys else None
    )

    scheduler = prompt_iterable(
        "Scheduler", get_supported_schedulers(), default_value=cluster_section.get_param_value("scheduler")
    )
    scheduler_handler = SchedulerHandler(cluster_section, scheduler)

    scheduler_handler.prompt_os()
    scheduler_handler.prompt_cluster_size()

    master_instance_type = prompt(
        "Master instance type",
        lambda x: x in get_supported_instance_types(),
        default_value=cluster_section.get_param_value("master_instance_type"),
    )

    scheduler_handler.prompt_compute_instance_type()

    automate_vpc = prompt("Automate VPC creation? (y/n)", lambda x: x in ("y", "n"), default_value="n") == "y"

    vpc_parameters = _create_vpc_parameters(
        vpc_section, scheduler, scheduler_handler.max_cluster_size, automate_vpc_creation=automate_vpc
    )
    cluster_parameters = {"key_name": key_name, "scheduler": scheduler, "master_instance_type": master_instance_type}
    cluster_parameters.update(scheduler_handler.get_scheduler_parameters())

    # Remove parameters from the past configuration that can conflict with the user's choices.
    _reset_config_params(cluster_section, scheduler_handler.get_parameters_to_reset())
    _reset_config_params(vpc_section, ("compute_subnet_id", "use_public_ips", "compute_subnet_cidr"))

    # Update configuration values according to user's choices
    pcluster_config.region = aws_region_name

    cluster_section.label = cluster_label
    for param_key, param_value in cluster_parameters.items():
        param = cluster_section.get_param(param_key)
        param.value = param.get_value_from_string(param_value)

    vpc_section.label = vpc_label
    for param_key, param_value in vpc_parameters.items():
        param = vpc_section.get_param(param_key)
        param.value = param.get_value_from_string(param_value)

    # Update config file by overriding changed settings
    pcluster_config.to_file()
    print("Configuration file written to {0}".format(pcluster_config.config_file))
    print(
        "You can edit your configuration file or simply run 'pcluster create -c {0} cluster-name' "
        "to create your cluster".format(pcluster_config.config_file)
    )


def _reset_config_params(section, parameters_to_remove):
    for param_key in parameters_to_remove:
        param = section.get_param(param_key)
        param.value = param.get_default_value()


def _create_vpc_parameters(vpc_section, scheduler, min_subnet_size, automate_vpc_creation=True):
    vpc_parameters = {}
    min_subnet_size = int(min_subnet_size)
    if automate_vpc_creation:
        vpc_parameters.update(
            automate_vpc_with_subnet_creation(_choose_network_configuration(scheduler), min_subnet_size)
        )
    else:
        vpc_and_subnets = _get_vpcs_and_subnets()
        vpc_list = vpc_and_subnets["vpc_list"]
        if not vpc_list:
            print("There are no VPC for the given region. Starting automatic creation of VPC and subnets...")
            vpc_parameters.update(
                automate_vpc_with_subnet_creation(_choose_network_configuration(scheduler), min_subnet_size)
            )
        else:
            default_vpc = vpc_section.get_param_value("vpc_id")
            vpc_id = prompt_iterable(
                "VPC ID",
                vpc_list,
                default_value=default_vpc if default_vpc in [vpc_entry[0] for vpc_entry in vpc_list] else None,
            )
            vpc_parameters["vpc_id"] = vpc_id
            subnet_list = vpc_and_subnets["vpc_subnets"][vpc_id]
            if not subnet_list or (
                prompt("Automate Subnet creation? (y/n)", lambda x: x in ("y", "n"), default_value="y") == "y"
            ):
                vpc_parameters.update(
                    automate_subnet_creation(vpc_id, _choose_network_configuration(scheduler), min_subnet_size)
                )
            else:
                vpc_parameters.update(_ask_for_subnets(subnet_list, vpc_section))
    return vpc_parameters


def _ask_for_subnets(subnet_list, vpc_section):
    available_subnets = [subnet_entry[0] for subnet_entry in subnet_list]
    default_master_subnet = vpc_section.get_param_value("master_subnet_id")
    master_subnet_id = prompt_iterable(
        "Master Subnet ID",
        subnet_list,
        default_value=default_master_subnet if default_master_subnet in available_subnets else None,
    )

    default_compute_subnet = vpc_section.get_param_value("compute_subnet_id")
    compute_subnet_id = prompt_iterable(
        "Compute Subnet ID",
        subnet_list,
        default_value=(default_compute_subnet if default_compute_subnet in available_subnets else None)
        or master_subnet_id,
    )
    vpc_parameters = {"master_subnet_id": master_subnet_id}

    if master_subnet_id != compute_subnet_id:
        vpc_parameters["compute_subnet_id"] = compute_subnet_id

    return vpc_parameters


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

    def __init__(self, cluster_section, scheduler):
        self.scheduler = scheduler
        self.cluster_section = cluster_section

        self.is_aws_batch = self.scheduler == "awsbatch"

        if self.is_aws_batch:
            self.instance_size_name = "vcpus"
            self.max_size_name = "max_vcpus"
            self.min_size_name = "min_vcpus"
            self.base_os = "alinux2"
            self.compute_instance_type = "optimal"
        else:
            self.instance_size_name = "instances"
            self.max_size_name = "max_queue_size"
            self.min_size_name = "initial_queue_size"
            self.base_os = cluster_section.get_param("base_os").get_default_value()
            self.compute_instance_type = cluster_section.get_param("compute_instance_type").get_default_value()

        self.max_cluster_size = cluster_section.get_param(self.max_size_name).get_default_value()
        self.min_cluster_size = cluster_section.get_param(self.min_size_name).get_default_value()

    def prompt_os(self):
        """Ask for os, if necessary."""
        if not self.is_aws_batch:
            self.base_os = prompt_iterable(
                "Operating System",
                get_supported_os_for_scheduler(self.scheduler),
                default_value=self.cluster_section.get_param_value("base_os"),
            )

    def prompt_compute_instance_type(self):
        """Ask for compute_instance_type, if necessary."""
        if not self.is_aws_batch:
            self.compute_instance_type = prompt(
                "Compute instance type",
                lambda x: x in get_supported_compute_instance_types(self.scheduler),
                default_value=self.cluster_section.get_param_value("compute_instance_type"),
            )

    def prompt_cluster_size(self):
        """Ask for max and min instances / vcpus."""
        self.min_cluster_size = prompt(
            "Minimum cluster size ({0})".format(self.instance_size_name),
            validator=lambda x: str(x).isdigit(),
            default_value=self.cluster_section.get_param_value(self.min_size_name),
        )

        self.max_cluster_size = prompt(
            "Maximum cluster size ({0})".format(self.instance_size_name),
            validator=lambda x: str(x).isdigit() and int(x) >= int(self.min_cluster_size),
            default_value=self.cluster_section.get_param_value(self.max_size_name),
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
        elif int(self.min_cluster_size) > 0:
            scheduler_parameters["maintain_initial_size"] = "true"
        return scheduler_parameters

    def get_parameters_to_reset(self):
        """Return a list of parameter that needs to be reset from the configuration."""
        if self.is_aws_batch:
            return "max_queue_size", "initial_queue_size", "maintain_initial_size", "compute_instance_type"
        else:
            return "max_vcpus", "desired_vcpus", "min_vcpus", "compute_instance_type"
