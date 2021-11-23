# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import abc
import sys
from abc import abstractmethod

import boto3
from botocore.exceptions import ClientError

from pcluster.utils import (
    Cache,
    get_availability_zone_of_subnet,
    get_installed_version,
    get_supported_az_for_one_instance_type,
    is_hit_enabled_cluster,
)

if sys.version_info >= (3, 4):
    ABC = abc.ABC
else:
    ABC = abc.ABCMeta("ABC", (), {})


class ClusterModel(ABC):
    """
    Describes the model of the cluster produced by a configuration.

    The currently supported cluster models are:
    - SIT: Single Instance Type - One single queue and one instance type per queue
    - HIT: Heterogeneous Instance Types - Multiple queues and multiple instance types per queue
    """

    def __init__(self, name):
        self.name = name

    @abstractmethod
    def get_cluster_section_definition(self):
        """Get the cluster section definition used by the cluster model."""
        pass

    @abstractmethod
    def test_configuration(self, pcluster_config):
        """Do dryrun tests for the configuration."""
        pass

    @abstractmethod
    def get_start_command(self, pcluster_config):
        """Get the start command for the model."""
        pass

    @abstractmethod
    def get_stop_command(self, pcluster_config):
        """Get the stop command for the model."""
        pass

    def _ec2_run_instance(self, pcluster_config, **kwargs):  # noqa: C901 FIXME!!!
        """Wrap ec2 run_instance call. Useful since a successful run_instance call signals 'DryRunOperation'."""
        try:
            boto3.client("ec2").run_instances(**kwargs)
        except ClientError as e:
            code = e.response.get("Error").get("Code")
            message = e.response.get("Error").get("Message")
            subnet_id = kwargs["NetworkInterfaces"][0]["SubnetId"]
            if code == "DryRunOperation":
                pass
            elif code == "UnsupportedOperation":
                if "does not support specifying CpuOptions" in message:
                    pcluster_config.error(message.replace("CpuOptions", "disable_hyperthreading"))
                pcluster_config.error(message)
            elif code == "InstanceLimitExceeded":
                pcluster_config.error(
                    "You've reached the limit on the number of instances you can run concurrently "
                    "for the configured instance type.\n{0}".format(message)
                )
            elif code == "InsufficientInstanceCapacity":
                pcluster_config.error("There is not enough capacity to fulfill your request.\n{0}".format(message))
            elif code == "InsufficientFreeAddressesInSubnet":
                pcluster_config.error(
                    "The specified subnet does not contain enough free private IP addresses "
                    "to fulfill your request.\n{0}".format(message)
                )
            elif code == "InvalidParameterCombination":
                if "associatePublicIPAddress" in message:
                    # Instances with multiple Network Interfaces cannot currently take public IPs.
                    # This check is meant to warn users about this problem until services are fixed.
                    pcluster_config.warn(
                        "The instance type '{0}' cannot take public IPs. "
                        "Please make sure that the subnet with id '{1}' has the proper routing configuration to allow "
                        "private IPs reaching the Internet (e.g. a NAT Gateway and a valid route table).".format(
                            kwargs["InstanceType"], subnet_id
                        )
                    )
            elif code == "Unsupported" and get_availability_zone_of_subnet(
                subnet_id
            ) not in get_supported_az_for_one_instance_type(kwargs["InstanceType"]):
                # If an availability zone without desired instance type is selected, error code is "Unsupported"
                # Therefore, we need to write our own code to tell the specific problem
                current_az = get_availability_zone_of_subnet(subnet_id)
                qualified_az = get_supported_az_for_one_instance_type(kwargs["InstanceType"])
                pcluster_config.error(
                    "Your requested instance type ({0}) is not supported in the Availability Zone ({1}) of "
                    "your requested subnet ({2}). Please retry your request by choosing a subnet in "
                    "{3}. ".format(kwargs["InstanceType"], current_az, subnet_id, qualified_az)
                )
            else:
                pcluster_config.error(
                    "Unable to validate configuration parameters for instance type '{0}'. "
                    "Please double check your cluster configuration.\n{1}".format(kwargs["InstanceType"], message)
                )

    @Cache.cached
    def _get_official_image_id(self, os, architecture):
        """Return the id of the current official image, for the provided os-architecture combination."""
        ami_id = None
        try:
            image_prefix = self._get_official_image_name_prefix(os, architecture)
            # Look for public ParallelCluster AMI in released version
            ami_id = self._get_image_id(image_prefix, "amazon", True)
            if not ami_id:
                # Look for dev account owner during development
                ami_id = self._get_image_id(image_prefix, "self", False)
        except ClientError as e:
            raise Exception(
                "Unable to retrieve official image id for base_os='{0}' and architecture='{1}': {2}".format(
                    os, architecture, e.response.get("Error").get("Message")
                )
            )
        if not ami_id:
            raise Exception(
                "No official image id found for base_os='{0}' and architecture='{1}'".format(os, architecture)
            )

        return ami_id

    def _get_image_id(self, image_prefix, owner, public=False):
        """Search for the ami with the specified prefix from the given account and returns the id if found."""
        filters = [
            {
                "Name": "name",
                "Values": ["{0}*".format(image_prefix)],
            }
        ]
        if public:
            filters.append({"Name": "is-public", "Values": ["true"]})

        images = boto3.client("ec2").describe_images(Filters=filters, Owners=[owner]).get("Images")
        return images[0].get("ImageId") if images else None

    def _get_official_image_name_prefix(self, os, architecture):
        """Return the prefix of the current official image, for the provided os-architecture combination."""
        suffixes = {
            "alinux2": "amzn2-hvm",
            "centos7": "centos7-hvm",
            "ubuntu1804": "ubuntu-1804-lts-hvm",
            "ubuntu2004": "ubuntu-2004-lts-hvm",
        }
        return "aws-parallelcluster-{version}-{suffix}-{arch}".format(
            version=get_installed_version(), suffix=suffixes[os], arch=architecture
        )

    def _get_cluster_ami_id(self, pcluster_config):
        """Get the image id of the cluster."""
        cluster_ami = None
        os = pcluster_config.get_section("cluster").get_param_value("base_os")
        architecture = pcluster_config.get_section("cluster").get_param_value("architecture")
        custom_ami = pcluster_config.get_section("cluster").get_param_value("custom_ami")
        try:
            cluster_ami = custom_ami if custom_ami else self._get_official_image_id(os, architecture)
        except Exception as e:
            pcluster_config.error("Error when resolving cluster ami id: {0}".format(e))

        return cluster_ami

    def public_ips_in_compute_subnet(self, pcluster_config, network_interfaces_count):
        """Tell if public IPs will be used in compute subnet."""
        vpc_section = pcluster_config.get_section("vpc")
        head_node_subnet_id = vpc_section.get_param_value("master_subnet_id")
        compute_subnet_id = vpc_section.get_param_value("compute_subnet_id")
        use_public_ips = vpc_section.get_param_value("use_public_ips") and (
            # For single NIC instances we check only if subnet is the same of head node
            (not compute_subnet_id or compute_subnet_id == head_node_subnet_id)
            # For multiple NICs instances we check also if subnet is different
            # to warn users about the current lack of support for public IPs
            or (network_interfaces_count > 1)
        )

        return use_public_ips

    def build_launch_network_interfaces(
        self, network_interfaces_count, use_efa, security_group_ids, subnet, use_public_ips
    ):
        """Build the needed NetworkInterfaces to launch an instance."""
        network_interfaces = []
        for device_index in range(network_interfaces_count):
            network_interfaces.append(
                {
                    "DeviceIndex": device_index,
                    "NetworkCardIndex": device_index,
                    "InterfaceType": "efa" if use_efa else "interface",
                    "Groups": security_group_ids,
                    "SubnetId": subnet,
                }
            )

        # If instance types has multiple Network Interfaces we also check for
        if network_interfaces_count > 1 and use_public_ips:
            network_interfaces[0]["AssociatePublicIpAddress"] = True
        return network_interfaces

    @staticmethod
    def _generate_tag_specifications_for_dry_run(pcluster_config):
        """Generate list of tags to pass to dry run of RunInstances performed during configuration validation."""
        tags = pcluster_config.get_section("cluster").get_param_value("tags")
        if tags:
            tag_specifications = [
                {
                    "ResourceType": "instance",
                    "Tags": [{"Key": key, "Value": value} for key, value in tags.items()],
                }
            ]
        else:
            tag_specifications = []
        return tag_specifications


def infer_cluster_model(config_parser=None, cluster_label=None, cfn_stack=None):
    """
    Infer the cluster model from the provided configuration.

    The configuration can be provided as coming from CloudFormation (CfnParams) or from config_file, with cluster label
    and a config_parser instance.
    """
    return (
        _infer_cluster_model_from_cfn(cfn_stack)
        if cfn_stack
        else _infer_cluster_model_from_file(config_parser, cluster_label)
    )


def _infer_cluster_model_from_file(config_parser, cluster_label):
    """
    Infer the cluster model from the configuration file.

    SIT style config files are supported also with Slurm, so check is performed on queue_settings.
    """
    return (
        ClusterModel.HIT
        if config_parser.has_option("cluster {0}".format(cluster_label), "queue_settings")
        else ClusterModel.SIT
    )


def _infer_cluster_model_from_cfn(cfn_stack):
    """
    Infer the cluster model from cfn params.

    Only HIT model is allowed to be stored if scheduler is Slurm, so checking the scheduler is enough to determine the
    cluster model.
    """
    return ClusterModel.HIT if is_hit_enabled_cluster(cfn_stack) else ClusterModel.SIT


def get_cluster_model(name):
    """Get the cluster model by name."""
    # Simple binary check; no additional cluster models are expected in the next future.
    return ClusterModel.HIT if ClusterModel.HIT.name == name else ClusterModel.SIT


def load_cluster_models():
    """Load supported cluster models."""
    from pcluster.models.hit.hit_cluster_model import HITClusterModel
    from pcluster.models.sit.sit_cluster_model import SITClusterModel

    ClusterModel.HIT = HITClusterModel()
    ClusterModel.SIT = SITClusterModel()


load_cluster_models()
