# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import os

import boto3
import pytest
from assertpy import assert_that
from cfn_stacks_factory import CfnStack, CfnStacksFactory
from utils import generate_stack_name


@pytest.fixture()
@pytest.mark.usefixtures("setup_sts_credentials")
def networking_stack_factory(request):
    """Define a fixture to manage the creation and destruction of CloudFormation stacks."""
    factory = CfnStacksFactory(request.config.getoption("credential"))

    def _create_network(region, template_path, parameters):
        file_content = extract_template(template_path)
        stack = CfnStack(
            name=generate_stack_name("integ-tests-networking", request.config.getoption("stackname_suffix")),
            region=region,
            template=file_content,
            parameters=parameters,
        )
        factory.create_stack(stack)
        return stack

    def extract_template(template_path):
        with open(template_path) as cfn_file:
            file_content = cfn_file.read()
        return file_content

    yield _create_network
    factory.delete_all_stacks()


@pytest.mark.regions(["eu-central-1", "us-gov-east-1", "cn-northwest-1"])
def test_public_network_topology(region, vpc_stack, networking_stack_factory, random_az_selector):
    ec2_client = boto3.client("ec2", region_name=region)
    vpc_id = vpc_stack.cfn_outputs["VpcId"]
    public_subnet_cidr = "192.168.3.0/24"
    availability_zone = random_az_selector(region, default_value="")
    internet_gateway_id = vpc_stack.cfn_resources["InternetGateway"]

    parameters = _get_cfn_parameters(
        availability_zone, internet_gateway_id=internet_gateway_id, vpc_id=vpc_id, public_cidr=public_subnet_cidr
    )
    path = os.path.join("..", "..", "cloudformation", "networking", "public.cfn.json")
    stack = networking_stack_factory(region, path, parameters)

    public_subnet_id = stack.cfn_outputs["PublicSubnetId"]
    _assert_subnet_cidr(ec2_client, public_subnet_id, expected_subnet_cidr=public_subnet_cidr)
    _assert_internet_gateway_id(ec2_client, vpc_id, expected_internet_gateway_id=internet_gateway_id)
    _assert_internet_gateway_in_subnet_route(ec2_client, public_subnet_id, internet_gateway_id)
    _assert_subnet_property(
        region, public_subnet_id, expected_autoassign_ip_value=False, expected_availability_zone=availability_zone
    )


@pytest.mark.regions(["eu-central-1", "us-gov-east-1", "cn-northwest-1"])
def test_public_private_network_topology(region, vpc_stack, networking_stack_factory, random_az_selector):
    ec2_client = boto3.client("ec2", region_name=region)
    vpc_id = vpc_stack.cfn_outputs["VpcId"]
    public_subnet_cidr = "192.168.5.0/24"
    private_subnet_cidr = "192.168.4.0/24"
    availability_zone = random_az_selector(region, default_value="")
    internet_gateway_id = vpc_stack.cfn_resources["InternetGateway"]

    parameters = _get_cfn_parameters(
        availability_zone,
        internet_gateway_id=internet_gateway_id,
        vpc_id=vpc_id,
        public_cidr=public_subnet_cidr,
        private_cidr=private_subnet_cidr,
    )
    path = os.path.join("..", "..", "cloudformation", "networking", "public-private.cfn.json")
    stack = networking_stack_factory(region, path, parameters)

    public_subnet_id = stack.cfn_outputs["PublicSubnetId"]
    private_subnet_id = stack.cfn_outputs["PrivateSubnetId"]
    _assert_subnet_cidr(ec2_client, public_subnet_id, expected_subnet_cidr=public_subnet_cidr)
    _assert_subnet_cidr(ec2_client, private_subnet_id, expected_subnet_cidr=private_subnet_cidr)
    _assert_internet_gateway_id(ec2_client, vpc_id, expected_internet_gateway_id=internet_gateway_id)
    _assert_internet_gateway_in_subnet_route(ec2_client, public_subnet_id, internet_gateway_id)
    _assert_subnet_property(
        region, public_subnet_id, expected_autoassign_ip_value=True, expected_availability_zone=availability_zone
    )
    _assert_subnet_property(
        region, private_subnet_id, expected_autoassign_ip_value=False, expected_availability_zone=availability_zone
    )
    _assert_nat_in_subnet(ec2_client, public_subnet_id)
    _assert_nat_in_subnet_route(ec2_client, private_subnet_id)


def _get_cfn_parameters(availability_zone, internet_gateway_id, public_cidr, vpc_id, private_cidr=None):
    """Create cloudformation-compatible stack parameter given the variables."""
    parameters = [
        {"ParameterKey": "AvailabilityZone", "ParameterValue": availability_zone},
        {"ParameterKey": "InternetGatewayId", "ParameterValue": internet_gateway_id},
        {"ParameterKey": "PublicCIDR", "ParameterValue": public_cidr},
        {"ParameterKey": "VpcId", "ParameterValue": vpc_id},
    ]
    if private_cidr:
        parameters.append({"ParameterKey": "PrivateCIDR", "ParameterValue": private_cidr})
    return parameters


def _assert_internet_gateway_in_subnet_route(ec2_client, subnet_id, expected_internet_gateway_id):
    """
    Check that the given internet_gateway is associated with the route of the subnet.

    :param ec2_client: the boto3 client to which make requests
    :param subnet_id: the subnet associated with the route we want to verify
    :param expected_internet_gateway_id: the gateway we expect to find in the route
    """
    response = ec2_client.describe_route_tables(Filters=[{"Name": "association.subnet-id", "Values": [subnet_id]}])
    routes = response["RouteTables"][0]["Routes"]
    internet_gateway_route = next(route for route in routes if route["DestinationCidrBlock"] == "0.0.0.0/0")
    assert_that(internet_gateway_route).contains("GatewayId")
    assert_that(internet_gateway_route["GatewayId"]).is_equal_to(expected_internet_gateway_id)


def _assert_subnet_cidr(ec2_client, subnet_id, expected_subnet_cidr):
    """Check that the given subnet has the same subnet cidr."""
    response = ec2_client.describe_subnets(Filters=[{"Name": "subnet-id", "Values": [subnet_id]}])
    subnet_cidr = response["Subnets"][0]["CidrBlock"]
    assert_that(subnet_cidr).is_equal_to(expected_subnet_cidr)


def _assert_internet_gateway_id(ec2_client, vpc_id, expected_internet_gateway_id):
    """Check that the vpc contains the given internet gateway."""
    if expected_internet_gateway_id:
        response = ec2_client.describe_internet_gateways(Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}])
        internet_gateway_id = response["InternetGateways"][0]["InternetGatewayId"]
        assert_that(internet_gateway_id).is_equal_to(expected_internet_gateway_id)


def _assert_subnet_property(region, subnet_id, expected_autoassign_ip_value, expected_availability_zone=""):
    """Check that the subnet has the given property."""
    subnet = boto3.resource("ec2", region_name=region).Subnet(subnet_id)
    assert_that(subnet.map_public_ip_on_launch).is_equal_to(expected_autoassign_ip_value)
    if expected_availability_zone:
        assert_that(subnet.availability_zone).is_equal_to(expected_availability_zone)


def _assert_nat_in_subnet(ec2_client, subnet_id):
    """Check that there is a nat in the given subnet."""
    response = ec2_client.describe_nat_gateways(Filters=[{"Name": "subnet-id", "Values": [subnet_id]}])
    assert_that(len(response["NatGateways"])).is_greater_than(0)


def _assert_nat_in_subnet_route(ec2_client, subnet_id):
    """Check that the route of the given subnet contains a Nat Gateway."""
    response = ec2_client.describe_route_tables(Filters=[{"Name": "association.subnet-id", "Values": [subnet_id]}])
    routes = response["RouteTables"][0]["Routes"]
    assert_that(next(route for route in routes if route["DestinationCidrBlock"] == "0.0.0.0/0")).contains(
        "NatGatewayId"
    )
