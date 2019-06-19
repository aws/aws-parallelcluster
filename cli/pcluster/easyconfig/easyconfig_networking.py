from future.backports import datetime

import functools
import logging
import os
import sys
import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from pcluster.easyconfig.easyconfig_utils import _prompt_a_list
from pcluster.networking.vpc_factory import VpcFactory
from pcluster.utils import decide_cidr, get_subnet_cidr

DEFAULT_AWS_REGION_NAME = "us-east-1"
LOGGER = logging.getLogger("pcluster.pcluster")
TIMESTAMP = "-{:%Y%m%d%H%M%S}".format(datetime.datetime.utcnow())
PUBLIC_PRIVATE_CONFIG_NAME = "public-private-with-nat"
PUBLIC_CONFIG_NAME = "public-only"
NUMBER_OF_IP_MASTER_SUBNET = 250


def handle_client_exception(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (BotoCoreError, ClientError) as e:
            LOGGER.error("Failed with error: %s" % e)
            LOGGER.error("Hint: please check your AWS credentials.")
            LOGGER.error("Run `aws configure` or set the credentials as environment variables.")
            sys.exit(1)

    return wrapper


class NetworkConfigurer:
    """Create a NetworkConfigurer item that will be used by _create_network_configuration."""

    def __init__(
        self, aws_region_name, availability_zone, vpc_id, public_cidr="", internet_gateway_id="", private_cidr=""
    ):
        self.aws_region_name = aws_region_name
        self.availability_zone = availability_zone
        self.vpc_id = vpc_id
        self.public_cidr = public_cidr
        self.internet_gateway_id = internet_gateway_id
        self.private_cidr = private_cidr

    def create_stack_parameters(self, also_private_cidr=False):
        """Create cloudformation-compatible stack parameter given the variables."""
        parameters = [
            {"ParameterKey": "AvailabilityZone", "ParameterValue": self.availability_zone},
            {"ParameterKey": "InternetGatewayId", "ParameterValue": self.internet_gateway_id},
            {"ParameterKey": "PublicCIDR", "ParameterValue": self.public_cidr},
            {"ParameterKey": "VpcId", "ParameterValue": self.vpc_id},
        ]
        if also_private_cidr:
            parameters.append({"ParameterKey": "PrivateCIDR", "ParameterValue": self.private_cidr})
        return parameters


def _evaluate_aws_region(aws_region_name):
    if aws_region_name:
        region = aws_region_name
    elif os.environ.get("AWS_DEFAULT_REGION"):
        region = os.environ.get("AWS_DEFAULT_REGION")
    else:
        region = DEFAULT_AWS_REGION_NAME
    return region


@handle_client_exception
def ec2_conn(aws_region_name):
    region = _evaluate_aws_region(aws_region_name)
    ec2 = boto3.client("ec2", region_name=region)
    return ec2


def automate_creation_of_vpc_and_subnet(aws_region_name, network_configuration, number_of_ip_for_compute):
    print("Beginning creation of vpc. Please do not leave the terminal until the process has finish")
    vpc_creator = VpcFactory(aws_region_name)
    vpc_id = vpc_creator.create()
    vpc_creator.setup(vpc_id, name="ParallelClusterVPC" + TIMESTAMP)
    if not vpc_creator.check(vpc_id):
        logging.critical("ERROR:Something went wrong in vpc creation. Please delete it and start the process again")
        sys.exit(1)

    vpc_parameters = {"vpc_id": vpc_id}
    vpc_parameters.update(
        automate_creation_of_subnet(aws_region_name, vpc_id, network_configuration, number_of_ip_for_compute)
    )
    return vpc_parameters


@handle_client_exception
def automate_creation_of_subnet(aws_region_name, vpc_id, network_configuration, number_of_ip_for_compute):
    _check_the_vpc(aws_region_name, vpc_id)
    ec2_client = ec2_conn(aws_region_name)
    vpc_cidr = ec2_client.describe_vpcs(VpcIds=[vpc_id])["Vpcs"][0]["CidrBlock"]
    internet_gateway_response = ec2_client.describe_internet_gateways(
        Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
    )
    internet_gateway_id = (
        internet_gateway_response["InternetGateways"][0]["InternetGatewayId"]
        if internet_gateway_response["InternetGateways"]
        else ""
    )

    configurer = NetworkConfigurer(
        aws_region_name, _get_availability_zone(aws_region_name), vpc_id, internet_gateway_id=internet_gateway_id
    )

    possible_network_configuration = {
        PUBLIC_PRIVATE_CONFIG_NAME: _create_public_private_with_nat_configuration,
        PUBLIC_CONFIG_NAME: _create_public_configuration,
    }
    return possible_network_configuration[network_configuration](
        configurer, vpc_cidr, _get_subnets_in_vpc(aws_region_name, vpc_id), number_of_ip_for_compute
    )


def _create_public_configuration(configurer, vpc_cidr, subnet_cidrs, number_of_ip_for_compute):
    configurer.public_cidr = get_subnet_cidr(
        vpc_cidr=vpc_cidr,
        occupied_cidr=subnet_cidrs,
        max_queue_size=number_of_ip_for_compute + NUMBER_OF_IP_MASTER_SUBNET,
    )
    _check_cidr(configurer.public_cidr)
    template_name = "public.cfn.json"
    stack_output = _create_network_configuration(template_name, configurer, also_private_cidr=False)
    return {"master_subnet_id": stack_output[0]["OutputValue"], "use_public_ips": "true"}


def _create_public_private_with_nat_configuration(configurer, vpc_cidr, subnet_cidrs, number_of_ip_for_compute):
    configurer.public_cidr = decide_cidr(
        vpc_cidr=vpc_cidr, occupied_cidr=subnet_cidrs, target_size=NUMBER_OF_IP_MASTER_SUBNET
    )
    _check_cidr(configurer.public_cidr)
    subnet_cidrs.append(configurer.public_cidr)
    configurer.private_cidr = get_subnet_cidr(
        vpc_cidr=vpc_cidr, occupied_cidr=subnet_cidrs, max_queue_size=number_of_ip_for_compute
    )
    _check_cidr(configurer.private_cidr)
    template_name = "public-private.cfn.json"
    stack_output = _create_network_configuration(template_name, configurer, also_private_cidr=True)
    #  stack output size is 2
    public_index = 0 if (stack_output[0]["OutputKey"] == "PublicSubnetId") else 1
    private_index = (public_index + 1) % 2
    return {
        "master_subnet_id": stack_output[public_index]["OutputValue"],
        "compute_subnet_id": stack_output[private_index]["OutputValue"],
        "use_public_ips": "false",
    }


# very similar to pcluster.py line 104 and after
def _create_network_configuration(template_name, configurer, also_private_cidr):
    LOGGER.info("Creating stack for the network configuration...")
    LOGGER.info("Do not leave the terminal until the process has finished")
    cfn = boto3.client("cloudformation", region_name=configurer.aws_region_name)
    capabilities = ["CAPABILITY_IAM"]
    try:
        stack_name = "parallelclusternetworking-" + ("pubpriv" if also_private_cidr else "pub") + TIMESTAMP
        stack = cfn.create_stack(
            StackName=stack_name,
            TemplateURL="https://network-configuration-bucket.s3-eu-west-1.amazonaws.com/{0}".format(template_name),
            Parameters=configurer.create_stack_parameters(also_private_cidr=also_private_cidr),
            Capabilities=capabilities,
        )
        LOGGER.debug("StackId: %s", stack.get("StackId"))
        LOGGER.info("Stack Name: {0}".format(stack_name))
        status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get("StackStatus")
        resource_status = ""
        while status == "CREATE_IN_PROGRESS":
            status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get("StackStatus")
            events = cfn.describe_stack_events(StackName=stack_name).get("StackEvents")[0]
            resource_status = (
                "Status: %s - %s" % (events.get("LogicalResourceId"), events.get("ResourceStatus"))
            ).ljust(80)
            sys.stdout.write("\r%s" % resource_status)
            sys.stdout.flush()
            time.sleep(5)
        # print the last status update in the logs
        if resource_status != "":
            LOGGER.debug(resource_status)

        if status != "CREATE_COMPLETE":
            LOGGER.critical("\nCluster creation failed.  Failed events:")
            events = cfn.describe_stack_events(StackName=stack_name).get("StackEvents")
            for event in events:
                if event.get("ResourceStatus") == "CREATE_FAILED":
                    LOGGER.info(
                        "  - %s %s %s",
                        event.get("ResourceType"),
                        event.get("LogicalResourceId"),
                        event.get("ResourceStatusReason"),
                    )
            LOGGER.error("Could not create the network configuration")
            sys.exit(0)
        print()
        LOGGER.info("The stack has been created")
        return cfn.describe_stacks(StackName=stack_name).get("Stacks")[0]["Outputs"]
    except KeyboardInterrupt as e:
        print()
        LOGGER.info("Could not write up the configuration.")
        LOGGER.info("Please check manually the created resources and stacks")
    except Exception as e:  # Any exception is a problem
        print()
        LOGGER.error(
            "An exception as occured. Please restart the configuration and check manually the created resource"
        )
        LOGGER.critical(e)
        sys.exit(1)


@handle_client_exception
def _get_availability_zone(aws_region_name):
    # FIXME to update
    return ""


def _choose_network_configuration(scheduler):
    if scheduler == "awsbatch":
        return PUBLIC_PRIVATE_CONFIG_NAME
    options = (
        "Master in a public subnet and compute fleet in a private subnet",
        "Master and compute fleet in the same public subnet",
    )
    to_network_identifiers = {options[0]: PUBLIC_PRIVATE_CONFIG_NAME, options[1]: PUBLIC_CONFIG_NAME}

    return to_network_identifiers[_prompt_a_list("Network Configuration", options, default_value=options[0])]


@handle_client_exception
def _get_subnets_in_vpc(aws_region_name, vpc_id):
    """Return a list of the subnets cidr contained in the vpc."""
    conn = ec2_conn(aws_region_name)
    subnets = conn.describe_subnets(Filters=[{"Name": "vpcId", "Values": [vpc_id]}])["Subnets"]
    return [subnet["CidrBlock"] for subnet in subnets]


def _check_the_vpc(aws_region_name, vpc_id):
    # This function should be further expandend once we decide to allow the user to use his vpcs. For example, we should
    # also check for the presence of a NAT gateway
    if not VpcFactory(aws_region_name).check(vpc_id):
        logging.error("WARNING: The vpc does not have the correct parameters set.")


def _check_cidr(cidr):
    if not cidr:
        LOGGER.error(
            "Could not create the subnet needed for the network configuration. Check that the vpc has enough"
            "space for the new subnet"
        )
        sys.exit(1)
