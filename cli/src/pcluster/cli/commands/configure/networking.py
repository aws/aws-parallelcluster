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
import abc
import datetime
import logging
import sys
from enum import Enum

import boto3

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import get_region
from pcluster.cli.commands.configure.subnet_computation import evaluate_cidr, get_subnet_cidr
from pcluster.cli.commands.configure.utils import handle_client_exception
from pcluster.networking.vpc_factory import VpcFactory
from pcluster.utils import (
    get_cli_log_file,
    get_installed_version,
    get_stack_output_value,
    get_templates_bucket_path,
    verify_stack_status,
)

DEFAULT_AWS_REGION_NAME = "us-east-1"
LOGGER = logging.getLogger(__name__)
TIMESTAMP = "-{:%Y%m%d%H%M%S}".format(datetime.datetime.utcnow())
HEAD_NODE_SUBNET_IPS = 250

if sys.version_info >= (3, 4):
    ABC = abc.ABC
else:
    ABC = abc.ABCMeta("ABC", (), {})


class BaseNetworkConfig(ABC):
    """The abstract base configuration from which all configurations shall inherit."""

    def __init__(self, config_type, template_name, stack_name_prefix, availability_zone):
        self.config_type = config_type
        self.template_name = template_name
        self.stack_name_prefix = stack_name_prefix
        self.availability_zone = availability_zone

    def create(self, vpc_id, compute_subnet_size):
        """
        Create the configuration.

        :param vpc_id: the id of the vpc in which create the configuration
        :param compute_subnet_size: the minimum size of the compute subnet
        :return: the parameters to write in the config file
        """
        subnets_cidrs = get_vpc_subnets(vpc_id)
        vpc_cidr = _get_vpc_cidr(vpc_id)
        internet_gateway_id = _get_internet_gateway_id(vpc_id)
        return self._create(vpc_id, vpc_cidr, subnets_cidrs, internet_gateway_id, compute_subnet_size)

    @abc.abstractmethod
    def _create(self, vpc_id, vpc_cidr, subnet_cidrs, internet_gateway_id, compute_subnet_size):
        pass

    @staticmethod
    def _build_cfn_param(key, value):
        return {"ParameterKey": key, "ParameterValue": value}

    def _get_cfn_parameters(self, vpc_id, internet_gateway_id):
        return [
            BaseNetworkConfig._build_cfn_param("AvailabilityZone", self.availability_zone),
            BaseNetworkConfig._build_cfn_param("InternetGatewayId", internet_gateway_id),
            BaseNetworkConfig._build_cfn_param("VpcId", vpc_id),
        ]


class PublicNetworkConfig(BaseNetworkConfig):
    """The public configuration that creates one public subnet with head node and compute fleet."""

    def __init__(self, availability_zone=None):
        super().__init__(
            config_type="Head node and compute fleet in the same public subnet",
            template_name="public",
            stack_name_prefix="pub",
            availability_zone=availability_zone,
        )

    def get_cfn_parameters(self, vpc_id, internet_gateway_id, public_cidr):
        """Create cloudformation-compatible stack parameter given the variables."""
        parameters = self._get_cfn_parameters(vpc_id, internet_gateway_id)
        parameters.append(super()._build_cfn_param("PublicCIDR", public_cidr))
        return parameters

    def _create(self, vpc_id, vpc_cidr, subnet_cidrs, internet_gateway_id, compute_subnet_size):
        public_cidr = get_subnet_cidr(
            vpc_cidr=vpc_cidr, occupied_cidr=subnet_cidrs, min_subnet_size=compute_subnet_size + HEAD_NODE_SUBNET_IPS
        )
        _validate_cidr(public_cidr)
        parameters = self.get_cfn_parameters(vpc_id, internet_gateway_id, public_cidr)
        stack_output = _create_network_stack(self, parameters)
        return {
            "head_node_subnet_id": get_stack_output_value(stack_output, "PublicSubnetId"),
            "compute_subnet_id": get_stack_output_value(stack_output, "PublicSubnetId"),
        }


class PublicPrivateNetworkConfig(BaseNetworkConfig):
    """The public private config that creates one public subnet for head node and one private subnet for compute."""

    def __init__(self, availability_zone=""):
        super().__init__(
            config_type="Head node in a public subnet and compute fleet in a private subnet",
            template_name="public-private",
            stack_name_prefix="pubpriv",
            availability_zone=availability_zone,
        )

    def get_cfn_parameters(self, vpc_id, internet_gateway_id, public_cidr, private_cidr):
        """Create cloudformation-compatible stack parameter given the variables."""
        parameters = self._get_cfn_parameters(vpc_id, internet_gateway_id)
        parameters.append(super()._build_cfn_param("PublicCIDR", public_cidr))
        parameters.append(super()._build_cfn_param("PrivateCIDR", private_cidr))
        return parameters

    def _create(self, vpc_id, vpc_cidr, subnet_cidrs, internet_gateway_id, compute_subnet_size):  # noqa D102
        public_cidr = evaluate_cidr(vpc_cidr=vpc_cidr, occupied_cidrs=subnet_cidrs, target_size=HEAD_NODE_SUBNET_IPS)
        _validate_cidr(public_cidr)
        subnet_cidrs.append(public_cidr)
        private_cidr = get_subnet_cidr(
            vpc_cidr=vpc_cidr, occupied_cidr=subnet_cidrs, min_subnet_size=compute_subnet_size
        )
        _validate_cidr(private_cidr)
        parameters = self.get_cfn_parameters(vpc_id, internet_gateway_id, public_cidr, private_cidr)
        stack_output = _create_network_stack(self, parameters)
        return {
            "head_node_subnet_id": get_stack_output_value(stack_output, "PublicSubnetId"),
            "compute_subnet_id": get_stack_output_value(stack_output, "PrivateSubnetId"),
        }


class NetworkConfiguration(Enum):
    """Contain all possible network configuration."""

    PUBLIC_PRIVATE = PublicPrivateNetworkConfig()
    PUBLIC = PublicNetworkConfig()


def _create_network_stack(configuration, parameters):
    print("Creating CloudFormation stack...\nDo not leave the terminal until the process has finished.")
    stack_name = "parallelclusternetworking-{0}{1}".format(configuration.stack_name_prefix, TIMESTAMP)
    try:
        cfn_client = boto3.client("cloudformation")
        template_url = "{0}networking/{1}-{2}.cfn.json".format(
            get_templates_bucket_path(), configuration.template_name, get_installed_version()
        )
        LOGGER.info("Template URL: %s", template_url)
        stack = cfn_client.create_stack(
            StackName=stack_name, TemplateURL=template_url, Parameters=parameters, Capabilities=["CAPABILITY_IAM"]
        )
        print(f"Stack Name: {stack_name} (id: {stack.get('StackId')})")
        if not verify_stack_status(
            stack_name, waiting_states=["CREATE_IN_PROGRESS"], successful_states=["CREATE_COMPLETE"]
        ):
            print("Could not create the network configuration.")
            sys.exit(0)
        print("\nThe stack has been created.")
        return AWSApi.instance().cfn.describe_stack(stack_name).get("Outputs")
    except KeyboardInterrupt:
        print(
            "\nUnable to update the configuration file with the selected network configuration. "
            f"Please manually check the status of the CloudFormation stack: {stack_name}"
        )
        sys.exit(0)
    except Exception as e:  # Any exception is a problem
        print(
            f"\nAn exception occurred while creating the CloudFormation stack: {stack_name}. "
            f"For details please check log file: {get_cli_log_file()}"
        )
        LOGGER.critical(e)
        sys.exit(1)


def _validate_cidr(cidr):
    if not cidr:
        print("Unable to create subnet. Please check the number of available IPs in the VPC")
        sys.exit(1)


@handle_client_exception
def get_vpc_subnets(vpc_id):
    """Return a list of the subnets cidr contained in the vpc."""
    subnets = boto3.client("ec2").describe_subnets(Filters=[{"Name": "vpcId", "Values": [vpc_id]}])["Subnets"]
    return [subnet["CidrBlock"] for subnet in subnets]


@handle_client_exception
def _get_vpc_cidr(vpc_id):
    return boto3.client("ec2").describe_vpcs(VpcIds=[vpc_id])["Vpcs"][0]["CidrBlock"]


@handle_client_exception
def _get_internet_gateway_id(vpc_id):
    response = boto3.client("ec2").describe_internet_gateways(
        Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
    )
    return response["InternetGateways"][0]["InternetGatewayId"] if response["InternetGateways"] else ""


def automate_vpc_with_subnet_creation(network_configuration, compute_subnet_size):
    print("Beginning VPC creation. Please do not leave the terminal until the creation is finalized")
    vpc_creator = VpcFactory(get_region())
    vpc_id = vpc_creator.create()
    vpc_creator.setup(vpc_id, name="ParallelClusterVPC" + TIMESTAMP)
    if not vpc_creator.check(vpc_id):
        logging.critical("Something went wrong in VPC creation. Please delete it and start the process again")
        sys.exit(1)

    vpc_parameters = {"vpc_id": vpc_id}
    vpc_parameters.update(automate_subnet_creation(vpc_id, network_configuration, compute_subnet_size))
    return vpc_parameters


@handle_client_exception
def automate_subnet_creation(vpc_id, network_configuration, compute_subnet_size):
    _validate_vpc(vpc_id)
    return network_configuration.create(vpc_id, compute_subnet_size)


def _validate_vpc(vpc_id):
    # This function should be further expandend once we decide to allow the user to use his vpcs. For example, we should
    # also check for the presence of a NAT gateway
    if not VpcFactory(get_region()).check(vpc_id):
        logging.error("WARNING: The VPC does not have the correct parameters set.")
