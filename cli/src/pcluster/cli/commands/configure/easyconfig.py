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
import errno
import logging
import os
import re
import stat
import sys
from collections import OrderedDict

import boto3
import yaml

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import get_region
from pcluster.cli.commands.configure.networking import (
    NetworkConfiguration,
    PublicPrivateNetworkConfig,
    automate_subnet_creation,
    automate_vpc_with_subnet_creation,
)
from pcluster.cli.commands.configure.utils import (
    get_regions,
    get_resource_tag,
    handle_client_exception,
    instance_type_supports_efa,
    placement_group_exists,
    prompt,
    prompt_iterable,
)
from pcluster.constants import (
    DEFAULT_MAX_COUNT,
    DEFAULT_MIN_COUNT,
    MAX_NUMBER_OF_COMPUTE_RESOURCES,
    MAX_NUMBER_OF_QUEUES,
    SUPPORTED_SCHEDULERS,
)
from pcluster.utils import error, get_supported_os_for_scheduler
from pcluster.validators.cluster_validators import NameValidator

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


def configure(args):  # noqa: C901

    config_file_path = args.config
    # Check for invalid path (eg. a directory)
    if os.path.exists(config_file_path):
        error(f"A file/folder exists at {config_file_path}. Please specify a different file path")

    print(f"INFO: Configuration file {config_file_path} will be written.")
    print("Press CTRL-C to interrupt the procedure.\n\n")

    if not args.region:
        # Use built in boto regions as an available option
        available_regions = get_regions()
        aws_region_name = prompt_iterable(
            "AWS Region ID", available_regions, default_value=boto3.session.Session().region_name
        )
        # Set provided region into os environment for suggestions and validations from here on
        os.environ["AWS_DEFAULT_REGION"] = aws_region_name
    else:
        os.environ["AWS_DEFAULT_REGION"] = args.region

    # Get the key name from the current region, if any
    available_keys = _get_keys()
    key_name = prompt_iterable("EC2 Key Pair Name", available_keys)

    scheduler = prompt_iterable("Scheduler", SUPPORTED_SCHEDULERS)

    if scheduler == "awsbatch":
        base_os = "alinux2"
    else:
        base_os = prompt_iterable("Operating System", get_supported_os_for_scheduler(scheduler))

    default_instance_type = AWSApi.instance().ec2.get_default_instance_type()
    head_node_instance_type = prompt(
        "Head node instance type",
        lambda x: x in AWSApi.instance().ec2.list_instance_types()
        and (  # pcluster doesn't support CentOS7 with ARM
            base_os != "centos7"
            or AWSApi.instance().ec2.get_instance_type_info(x).supported_architecture()[0] == "x86_64"
        ),
        default_value=default_instance_type,
    )
    if scheduler == "awsbatch":
        number_of_queues = 1
        size_name = "vCPU"
    else:
        number_of_queues = int(
            prompt(
                "Number of queues",
                lambda x: str(x).isdigit() and int(x) >= 1 and int(x) <= MAX_NUMBER_OF_QUEUES,
                default_value=1,
            )
        )
        size_name = "instance count"

    queues = []
    queue_names = []
    compute_instance_types = []
    cluster_size = 0  # Sum of maximum count through all the compute resources
    for queue_index in range(number_of_queues):
        while True:
            queue_name = prompt(
                f"Name of queue {queue_index+1}",
                validator=lambda x: len(NameValidator().execute(x)) == 0,
                default_value=f"queue{queue_index+1}",
            )
            if queue_name not in queue_names:
                break
            print(
                f"Error: The name {queue_name} cannot be used for multiple queues. Please insert a different queue "
                "name."
            )

        if scheduler == "awsbatch":
            number_of_compute_resources = 1
        else:
            number_of_compute_resources = int(
                prompt(
                    f"Number of compute resources for {queue_name}",
                    validator=lambda x: str(x).isdigit() and int(x) >= 1 and int(x) <= MAX_NUMBER_OF_COMPUTE_RESOURCES,
                    default_value=1,
                )
            )
        compute_resources = []
        efa_enabled_in_queue = False
        for compute_resource_index in range(number_of_compute_resources):
            efa_enabled_in_compute_resource = False
            efa_supported_by_instance_type = False
            if scheduler != "awsbatch":
                while True:
                    compute_instance_type = prompt(
                        f"Compute instance type for compute resource {compute_resource_index+1} in {queue_name}",
                        validator=lambda x: x in AWSApi.instance().ec2.list_instance_types(),
                        default_value=default_instance_type,
                    )
                    if compute_instance_type not in [
                        instances["InstanceType"]
                        for compute_resource in compute_resources
                        for instances in compute_resource["Instances"]
                    ]:
                        break
                    print(
                        f"Error: Instance type {compute_instance_type} cannot be specified for multiple compute "
                        "resources in the same queue. Please insert a different instance type."
                    )
                compute_resource_name = re.sub(r"[^A-Za-z0-9]", "", compute_instance_type)

                efa_supported_by_instance_type = instance_type_supports_efa(compute_instance_type)
                if efa_supported_by_instance_type:
                    efa_enabled_in_compute_resource = _prompt_for_efa(compute_instance_type)
                    if efa_enabled_in_compute_resource:
                        efa_enabled_in_queue = True
            min_cluster_size = DEFAULT_MIN_COUNT
            max_cluster_size = int(
                prompt(
                    "Maximum {0}".format(size_name),
                    validator=lambda x, ms=min_cluster_size: str(x).isdigit() and int(x) >= ms,  # pylint: disable=W0640
                    default_value=DEFAULT_MAX_COUNT,
                )
            )
            if scheduler == "awsbatch":
                compute_resources.append(
                    {
                        "Name": "optimal",
                        "InstanceTypes": ["optimal"],
                        "MinvCpus": min_cluster_size,
                        "DesiredvCpus": min_cluster_size,
                        "MaxvCpus": max_cluster_size,
                    }
                )
            else:
                compute_resource = {
                    "Name": compute_resource_name,
                    "Instances": [{"InstanceType": compute_instance_type}],
                    "MinCount": min_cluster_size,
                    "MaxCount": max_cluster_size,
                }
                if efa_supported_by_instance_type:
                    compute_resource["Efa"] = {"Enabled": efa_enabled_in_compute_resource}

                compute_resources.append(compute_resource)
                compute_instance_types.append(compute_instance_type)

            queue_names.append(queue_name)
            cluster_size += max_cluster_size  # Fixme: is it the right calculation for awsbatch?

        queue = {
            "Name": queue_name,
            "ComputeResources": compute_resources,
        }
        if efa_enabled_in_queue:
            placement_group = {"Enabled": True}
            placement_group_name = _prompt_for_placement_group()
            if placement_group_name:
                placement_group["Id"] = placement_group_name

            networking = queue.get("Networking", {})
            networking["PlacementGroup"] = placement_group
            queue["Networking"] = networking

        queues.append(queue)

    vpc_parameters = _create_vpc_parameters(scheduler, head_node_instance_type, compute_instance_types, cluster_size)

    # Here is the end of prompt. Code below assembles config and write to file
    for queue in queues:
        networking = queue.get("Networking", {})
        networking["SubnetIds"] = [vpc_parameters["compute_subnet_id"]]
        queue["Networking"] = networking

    head_node_config = {
        "InstanceType": head_node_instance_type,
        "Networking": {"SubnetId": vpc_parameters["head_node_subnet_id"]},
        "Ssh": {"KeyName": key_name},
    }
    if scheduler == "awsbatch":
        scheduler_prefix = "AwsBatch"
        head_node_config["Imds"] = {"Secured": False}
    else:
        scheduler_prefix = scheduler.capitalize()

    result = {
        "Region": os.environ.get("AWS_DEFAULT_REGION"),
        "Image": {"Os": base_os},
        "HeadNode": head_node_config,
        "Scheduling": {"Scheduler": scheduler, f"{scheduler_prefix}Queues": queues},
    }

    _write_configuration_file(config_file_path, result)
    print(
        "You can edit your configuration file or simply run 'pcluster create-cluster --cluster-configuration "
        f"{config_file_path} --cluster-name cluster-name --region {get_region()}' to create your cluster."
    )


def _write_configuration_file(config_file_path, content):
    if not os.path.isfile(config_file_path):
        try:
            config_folder = os.path.dirname(config_file_path) or "."
            os.makedirs(config_folder)
        except OSError as e:
            if e.errno != errno.EEXIST:  # Can safely ignore EEXISTS for this purpose
                print(f"Error: Encountered exception when writing configuration file. {e}")
                sys.exit(1)

        # Fix permissions
        with open(config_file_path, "a", encoding="utf-8"):
            os.chmod(config_file_path, stat.S_IRUSR | stat.S_IWUSR)

    # Write configuration to disk
    with open(config_file_path, "w", encoding="utf-8") as config_file:
        yaml.dump(content, config_file, sort_keys=False)
    print(f"Configuration file written to {config_file_path}")


def _create_vpc_parameters(scheduler, head_node_instance_type, compute_instance_types, cluster_size):
    vpc_parameters = {}
    min_subnet_size = int(cluster_size)
    vpc_and_subnets = _get_vpcs_and_subnets()
    vpc_list = vpc_and_subnets["vpc_list"]
    if not vpc_list:
        print("There are no VPC for the given region. Starting automatic creation of VPC and subnets...")
    if not vpc_list or prompt("Automate VPC creation? (y/n)", lambda x: x in ("y", "n"), default_value="n") == "y":
        vpc_parameters.update(
            automate_vpc_with_subnet_creation(
                _choose_network_configuration(scheduler, head_node_instance_type, compute_instance_types),
                min_subnet_size,
            )
        )
    else:
        vpc_id = prompt_iterable("VPC ID", vpc_list)
        vpc_parameters["vpc_id"] = vpc_id
        subnet_list = vpc_and_subnets["vpc_subnets"][vpc_id]
        qualified_head_node_subnets = _filter_subnets_offering_instance_types(subnet_list, [head_node_instance_type])
        if scheduler != "awsbatch":
            qualified_compute_subnets = _filter_subnets_offering_instance_types(subnet_list, compute_instance_types)
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
                automate_subnet_creation(
                    vpc_id,
                    _choose_network_configuration(scheduler, head_node_instance_type, compute_instance_types),
                    min_subnet_size,
                )
            )
        else:
            vpc_parameters.update(_ask_for_subnets(subnet_list, qualified_head_node_subnets, qualified_compute_subnets))
    return vpc_parameters


def _filter_subnets_offering_instance_types(subnet_list, instance_types):
    qualified_azs = _get_common_supported_az_for_multi_instance_types(instance_types)
    return [subnet_entry for subnet_entry in subnet_list if subnet_entry["availability_zone"] in qualified_azs]


def _ask_for_subnets(subnet_list, qualified_head_node_subnets, qualified_compute_subnets):
    head_node_subnet_id = _prompt_for_subnet(subnet_list, qualified_head_node_subnets, "head node subnet ID")
    compute_subnet_id = _prompt_for_subnet(
        subnet_list, qualified_compute_subnets, "compute subnet ID", default_subnet=head_node_subnet_id
    )

    vpc_parameters = {"head_node_subnet_id": head_node_subnet_id, "compute_subnet_id": compute_subnet_id}

    return vpc_parameters


def _choose_network_configuration(scheduler, head_node_instance_type, compute_instance_types):
    if scheduler == "awsbatch":
        return PublicPrivateNetworkConfig()
    azs_for_head_node_type = AWSApi.instance().ec2.get_supported_az_for_instance_type(head_node_instance_type)
    azs_for_compute_types = _get_common_supported_az_for_multi_instance_types(compute_instance_types)
    common_availability_zones = set(azs_for_head_node_type) & set(azs_for_compute_types)

    if not common_availability_zones:
        # Automate subnet creation only allows subnets to reside in a single az.
        # But user can bypass it by using manual subnets creation during configure or modify the config file directly.
        print(
            "Error: There is no single availability zone offering head node and compute in current region.\n"
            f"To create your cluster, make sure you have a subnet for head node in {azs_for_head_node_type}, "
            f"and a subnet for compute nodes in {azs_for_compute_types}. "
            "Then run pcluster configure again and avoid using Automate VPC/Subnet creation."
        )
        print("Exiting...")
        sys.exit(1)
    common_availability_zones_list = list(common_availability_zones)
    common_availability_zones_list.sort()
    availability_zone = prompt_iterable("Availability Zone", options=common_availability_zones_list)
    target_type = prompt_iterable(
        "Network Configuration",
        options=[configuration.value.config_type for configuration in NetworkConfiguration],
        default_value=PublicPrivateNetworkConfig().config_type,
    )
    network_configuration = next(
        configuration.value for configuration in NetworkConfiguration if configuration.value.config_type == target_type
    )
    network_configuration.availability_zone = availability_zone
    return network_configuration


def _prompt_for_subnet(all_subnets, qualified_subnets, message, default_subnet=None):
    total_omitted_subnets = len(all_subnets) - len(qualified_subnets)
    if total_omitted_subnets > 0:
        print(
            f"Note: {total_omitted_subnets} subnet(s) is/are not listed, "
            "because the instance type is not in their availability zone(s)"
        )
    return prompt_iterable(message, qualified_subnets, default_value=default_subnet)


def _prompt_for_efa(instance_type):
    print(
        "The EC2 instance selected supports enhanced networking capabilities using Elastic Fabric Adapter (EFA). "
        "EFA enables you to run applications requiring high levels of inter-node communications at scale on AWS at no "
        "additional charge (https://docs.aws.amazon.com/parallelcluster/latest/ug/efa-v3.html)."
    )
    enable_efa = prompt(f"Enable EFA on {instance_type} (y/n)", validator=lambda x: x in ("y", "n"), default_value="y")
    return enable_efa == "y"


def _prompt_for_placement_group():
    print(
        "Enabling EFA requires compute instances to be placed within a Placement Group. Please specify an existing "
        "Placement Group name or leave it blank for ParallelCluster to create one."
    )

    return prompt("Placement Group name", validator=lambda x: x == "" or placement_group_exists(x), default_value="")


# Availability zone utilities
def _get_common_supported_az_for_multi_instance_types(instance_types):
    supported_az = AWSApi.instance().ec2.get_supported_az_for_instance_types(instance_types)
    common_az = None
    for az_list in supported_az.values():
        if common_az is None:
            common_az = set(az_list)
        else:
            common_az = common_az & set(az_list)
    return common_az
