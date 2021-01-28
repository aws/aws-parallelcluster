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
import sys
from collections import OrderedDict

import boto3

from pcluster.cluster_model import ClusterModel
from pcluster.config.hit_converter import HitConverter
from pcluster.config.pcluster_config import PclusterConfig
from pcluster.config.validators import HEAD_NODE_UNSUPPORTED_INSTANCE_TYPES, HEAD_NODE_UNSUPPORTED_MESSAGE
from pcluster.configure.networking import (
    NetworkConfiguration,
    PublicPrivateNetworkConfig,
    automate_subnet_creation,
    automate_vpc_with_subnet_creation,
)
from pcluster.configure.utils import get_regions, get_resource_tag, handle_client_exception, prompt, prompt_iterable
from pcluster.utils import (
    error,
    get_default_instance_type,
    get_region,
    get_supported_az_for_multi_instance_types,
    get_supported_az_for_one_instance_type,
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
    {"vpc_list": list({"id":vpc-id, "name":name, "number_of_subnets": 6}) ,
    "vpc_to_subnet" :
                   {"vpc-id1": list({"id":subnet-id, "name":name, "size":subnet-size, "availability_zone": subnet-az}),
                    "vpc-id2": list({"id":subnet-id, "name":name, "size":subnet-size, "availability_zone": subnet-az})}}
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
        vpc_options.append(OrderedDict([("id", vpc_id), ("name", vpc_name), ("number_of_subnets", len(subnets))]))

    return {"vpc_list": vpc_options, "vpc_subnets": vpc_subnets}


def _get_subnets(conn, vpc_id):
    subnet_options = []
    subnet_list = conn.describe_subnets(Filters=[{"Name": "vpcId", "Values": [vpc_id]}]).get("Subnets")
    for subnet in subnet_list:
        subnet_options.append(
            OrderedDict(
                [
                    ("id", subnet.get("SubnetId")),
                    ("name", get_resource_tag(subnet, tag_name="Name")),
                    ("size", _extract_subnet_size(subnet.get("CidrBlock"))),
                    ("availability_zone", subnet.get("AvailabilityZone")),
                ]
            )
        )
    return subnet_options


def configure(args):
    # Check for invalid path (eg. a directory)
    if args.config_file and os.path.exists(args.config_file) and not os.path.isfile(args.config_file):
        error("Invalid configuration file path: {0}".format(args.config_file))

    pcluster_config = PclusterConfig(config_file=args.config_file, fail_on_error=False, auto_refresh=False)

    # FIXME: Overriding HIT config files is currently not supported.
    if pcluster_config.cluster_model == ClusterModel.HIT:
        error(
            "Configuration in file {0} cannot be overwritten. Please specify a different file path".format(
                pcluster_config.config_file
            )
        )

    if os.path.exists(pcluster_config.config_file):
        msg = "WARNING: Configuration file {0} will be overwritten."
    else:
        msg = "INFO: Configuration file {0} will be written."
    print(msg.format(pcluster_config.config_file))
    print("Press CTRL-C to interrupt the procedure.\n\n")

    if not args.region:
        # Use built in boto regions as an available option
        available_regions = get_regions()
        default_region = pcluster_config.get_section("aws").get_param_value("aws_region_name")
        aws_region_name = prompt_iterable("AWS Region ID", available_regions, default_value=default_region)
        # Set provided region into os environment for suggestions and validations from here on
        os.environ["AWS_DEFAULT_REGION"] = aws_region_name
    else:
        aws_region_name = args.region

    cluster_section = pcluster_config.get_section("cluster")

    global_config = pcluster_config.get_section("global")
    cluster_label = global_config.get_param_value("cluster_template")

    vpc_section = pcluster_config.get_section("vpc")
    vpc_label = vpc_section.label

    # Get the key name from the current region, if any
    available_keys = _get_keys()
    default_key = cluster_section.get_param_value("key_name")
    key_name = prompt_iterable("EC2 Key Pair Name", available_keys, default_value=default_key)

    scheduler = prompt_iterable(
        "Scheduler", get_supported_schedulers(), default_value=cluster_section.get_param_value("scheduler")
    )
    cluster_config = ClusterConfigureHelper(cluster_section, scheduler)
    cluster_config.prompt_os()
    cluster_config.prompt_cluster_size()
    cluster_config.prompt_instance_types()

    vpc_parameters = _create_vpc_parameters(vpc_section, cluster_config)
    # Here is the end of prompt. Code below assembles config and write to file

    cluster_parameters = {"key_name": key_name, "scheduler": scheduler}
    cluster_parameters.update(cluster_config.get_scheduler_parameters())

    # Remove parameters from the past configuration that can conflict with the user's choices.
    _reset_config_params(cluster_section, cluster_config.get_parameters_to_reset())
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

    # Update internal params according to provided parameters and enable auto-refresh before eventual hit conversion
    pcluster_config.refresh()
    pcluster_config.auto_refresh = True

    # Convert file if needed
    HitConverter(pcluster_config).convert(prepare_to_file=True)

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


def _create_vpc_parameters(vpc_section, cluster_config):
    vpc_parameters = {}
    min_subnet_size = int(cluster_config.max_cluster_size)
    automate_vpc_creation = prompt("Automate VPC creation? (y/n)", lambda x: x in ("y", "n"), default_value="n") == "y"
    if automate_vpc_creation:
        vpc_parameters.update(
            automate_vpc_with_subnet_creation(_choose_network_configuration(cluster_config), min_subnet_size)
        )
    else:
        vpc_and_subnets = _get_vpcs_and_subnets()
        vpc_list = vpc_and_subnets["vpc_list"]
        if not vpc_list:
            print("There are no VPC for the given region. Starting automatic creation of VPC and subnets...")
            vpc_parameters.update(
                automate_vpc_with_subnet_creation(_choose_network_configuration(cluster_config), min_subnet_size)
            )
        else:
            default_vpc = vpc_section.get_param_value("vpc_id")
            vpc_id = prompt_iterable("VPC ID", vpc_list, default_value=default_vpc)
            vpc_parameters["vpc_id"] = vpc_id
            subnet_list = vpc_and_subnets["vpc_subnets"][vpc_id]
            qualified_head_node_subnets = _filter_subnets_offering_instance_type(
                subnet_list, cluster_config.head_node_instance_type
            )
            if cluster_config.scheduler != "awsbatch":
                qualified_compute_subnets = _filter_subnets_offering_instance_type(
                    subnet_list, cluster_config.compute_instance_type
                )
            else:
                # Special case of awsbatch, where compute instance type is not specified
                qualified_compute_subnets = subnet_list
            if (
                not qualified_head_node_subnets
                or not qualified_compute_subnets
                or (prompt("Automate Subnet creation? (y/n)", lambda x: x in ("y", "n"), default_value="y") == "y")
            ):
                # Start auto subnets creation in the absence of qualified subnets.
                # Otherwise, user selects between manual and automate subnets creation
                if not qualified_head_node_subnets or not qualified_compute_subnets:
                    print("There are no qualified subnets. Starting automatic creation of subnets...")
                vpc_parameters.update(
                    automate_subnet_creation(vpc_id, _choose_network_configuration(cluster_config), min_subnet_size)
                )
            else:
                vpc_parameters.update(
                    _ask_for_subnets(subnet_list, vpc_section, qualified_head_node_subnets, qualified_compute_subnets)
                )
    return vpc_parameters


def _filter_subnets_offering_instance_type(subnet_list, instance_type):
    qualified_azs = get_supported_az_for_one_instance_type(instance_type)
    return [subnet_entry for subnet_entry in subnet_list if subnet_entry["availability_zone"] in qualified_azs]


def _ask_for_subnets(subnet_list, vpc_section, qualified_head_node_subnets, qualified_compute_subnets):
    head_node_subnet_id = _prompt_for_subnet(
        vpc_section.get_param_value("master_subnet_id"), subnet_list, qualified_head_node_subnets, "head node Subnet ID"
    )
    compute_subnet_id = _prompt_for_subnet(
        vpc_section.get_param_value("compute_subnet_id") or head_node_subnet_id,
        subnet_list,
        qualified_compute_subnets,
        "compute Subnet ID",
    )

    vpc_parameters = {"master_subnet_id": head_node_subnet_id}

    if head_node_subnet_id != compute_subnet_id:
        vpc_parameters["compute_subnet_id"] = compute_subnet_id

    return vpc_parameters


def _choose_network_configuration(cluster_config):
    if cluster_config.scheduler == "awsbatch":
        return PublicPrivateNetworkConfig()
    azs_for_head_node_type = get_supported_az_for_one_instance_type(cluster_config.head_node_instance_type)
    azs_for_compute_type = get_supported_az_for_one_instance_type(cluster_config.compute_instance_type)
    common_availability_zones = set(azs_for_head_node_type) & set(azs_for_compute_type)

    if not common_availability_zones:
        # Automate subnet creation only allows subnets to reside in a single az.
        # But user can bypass it by using manual subnets creation during configure or modify the config file directly.
        print(
            "Error: There is no single availability zone offering head node and compute in current region.\n"
            "To create your cluster, make sure you have a subnet for head node in {0}"
            ", and a subnet for compute nodes in {1}. Then run pcluster configure again"
            "and avoid using Automate VPC/Subnet creation.".format(azs_for_head_node_type, azs_for_compute_type)
        )
        print("Exiting...")
        sys.exit(1)
    target_type = prompt_iterable(
        "Network Configuration",
        options=[configuration.value.config_type for configuration in NetworkConfiguration],
        default_value=PublicPrivateNetworkConfig().config_type,
    )

    network_configuration = next(
        configuration.value for configuration in NetworkConfiguration if configuration.value.config_type == target_type
    )
    network_configuration.availability_zones = common_availability_zones
    return network_configuration


def _prompt_for_subnet(default_subnet, all_subnets, qualified_subnets, message):
    total_omitted_subnets = len(all_subnets) - len(qualified_subnets)
    if total_omitted_subnets > 0:
        print(
            "Note:  {0} subnet(s) is/are not listed, "
            "because the instance type is not in their availability zone(s)".format(total_omitted_subnets)
        )
    return prompt_iterable(message, qualified_subnets, default_value=default_subnet)


def _is_instance_type_supported_for_head_node(instance_type):
    if instance_type in HEAD_NODE_UNSUPPORTED_INSTANCE_TYPES:
        print(HEAD_NODE_UNSUPPORTED_MESSAGE.format(instance_type))
        return False
    return True


class ClusterConfigureHelper:
    """Handle prompts for cluster section."""

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

    def prompt_instance_types(self):
        """Ask for head_node_instance_type and compute_instance_type (if necessary)."""
        default_head_node_instance_type = self.cluster_section.get_param_value("master_instance_type")
        if not default_head_node_instance_type:
            default_head_node_instance_type = get_default_instance_type()
        self.head_node_instance_type = prompt(
            "Head node instance type",
            lambda x: _is_instance_type_supported_for_head_node(x) and x in get_supported_instance_types(),
            default_value=default_head_node_instance_type,
        )
        if not self.is_aws_batch:
            default_compute_instance_type = self.cluster_section.get_param_value("compute_instance_type")
            if not default_compute_instance_type:
                default_compute_instance_type = get_default_instance_type()
            self.compute_instance_type = prompt(
                "Compute instance type",
                lambda x: x in get_supported_compute_instance_types(self.scheduler),
                default_value=default_compute_instance_type,
            )
        # Cache availability zones offering the selected instance type(s) for later use
        self.cache_qualified_az()

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
            "master_instance_type": self.head_node_instance_type,
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

    def cache_qualified_az(self):
        """
        Call API once for both head node and compute instance type.

        Cache is done inside get get_supported_az_for_instance_types.
        """
        if not self.is_aws_batch:
            get_supported_az_for_multi_instance_types([self.head_node_instance_type, self.compute_instance_type])
