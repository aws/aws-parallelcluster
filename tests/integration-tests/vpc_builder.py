# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from enum import Enum, auto
from typing import List, NamedTuple

from troposphere import Equals, GetAtt, If, Not, Output, Parameter, Ref, Sub, Tags, Template
from troposphere.ec2 import (
    EIP,
    VPC,
    InternetGateway,
    NatGateway,
    Route,
    RouteTable,
    Subnet,
    SubnetRouteTableAssociation,
    VPCGatewayAttachment,
)


class Gateways(Enum):
    """Define gateways to use for default traffic in a subnet."""

    INTERNET_GATEWAY = auto()
    NAT_GATEWAY = auto()
    PROXY = auto()


class SubnetConfig(NamedTuple):
    """Configuration of a VPC Subnet"""

    name: str = "PublicSubnet"
    cidr: object = None
    map_public_ip_on_launch: bool = True
    has_nat_gateway: bool = True
    default_gateway: Gateways = Gateways.INTERNET_GATEWAY

    def tags(self):
        """Get the tags for the subnet"""
        return Tags(Name=Sub("${AWS::StackName}" + self.name + "Subnet"), Stack=Ref("AWS::StackId"))


class VPCConfig(NamedTuple):
    """Configuration of a VPC"""

    name: str = "vpc"
    cidr: str = "10.0.0.0/16"
    enable_dns_support: bool = True
    enable_dns_hostnames: bool = True
    has_internet_gateway: bool = True
    subnets: List[SubnetConfig] = [SubnetConfig()]
    tags: Tags = Tags(Name=Ref("AWS::StackName"), Stack=Ref("AWS::StackId"))


class VPCTemplateBuilder:
    """Build troposphere CFN templates for VPC creation."""

    def __init__(
        self,
        vpc_configuration: VPCConfig,
        existing_vpc: bool = False,
        availability_zone: str = None,
        description="Network build by NetworkTemplateBuilder",
    ):
        self.__template = Template()
        self.__template.set_version("2010-09-09")
        self.__template.set_description(description)
        if availability_zone:
            self.__availability_zone = availability_zone
        else:
            self.__availability_zone = Ref(
                self.__add_parameter(
                    name="AvailabilityZone",
                    description="(Optional) The zone in which you want to create your subnet(s)",
                    expected_input_type="String",
                )
            )

        if existing_vpc:
            self.__vpc = self.__add_parameter(name="VpcId", description="The vpc id", expected_input_type="String")
            self.__vpc_subnets = vpc_configuration.subnets

        else:
            self.__vpc = self.__build_vpc(vpc_configuration)
            self.__vpc_subnets = vpc_configuration.subnets

        self.__gateway_id = Ref(
            self.__add_parameter(
                name="InternetGatewayId",
                description="(Optional) The id of the gateway (will be created if not specified)",
                expected_input_type="String",
            )
        )
        self.__create_ig = self.__template.add_condition("CreateInternetGateway", Equals(self.__gateway_id, ""))
        self.__existing_ig = self.__template.add_condition(  # can't negate above condition with Not()
            "ExistingInternetGateway", Not(Equals(self.__gateway_id, ""))
        )

    def build(self):
        """Build the template."""
        self.__build_template()
        return self.__template

    def __build_template(self):
        internet_gateway = self.__build_internet_gateway(self.__vpc)
        nat_gateway = None
        subnet_refs = []
        for subnet in self.__vpc_subnets:
            subnet_ref = self.__build_subnet(subnet, self.__vpc)
            subnet_refs.append(subnet_ref)
            if subnet.has_nat_gateway:
                nat_gateway = self.__build_nat_gateway(subnet, subnet_ref)

        for subnet, subnet_ref in zip(self.__vpc_subnets, subnet_refs):
            self.__build_route_table(subnet, subnet_ref, self.__vpc, internet_gateway, nat_gateway)

    def __build_vpc(self, vpc_config_new):
        vpc = self.__template.add_resource(
            VPC(
                vpc_config_new.name,
                CidrBlock=vpc_config_new.cidr,
                EnableDnsSupport=vpc_config_new.enable_dns_support,
                EnableDnsHostnames=vpc_config_new.enable_dns_hostnames,
                Tags=vpc_config_new.tags,
            )
        )
        self.__template.add_output(Output("VpcId", Value=Ref(vpc), Description="The Vpc Id"))
        return vpc

    def __build_internet_gateway(self, vpc: VPC):
        internet_gateway = self.__template.add_resource(
            InternetGateway(
                "InternetGateway",
                Tags=Tags(Name=Ref("AWS::StackName"), Stack=Ref("AWS::StackId")),
                Condition=self.__create_ig,
            )
        )
        self.__template.add_resource(
            VPCGatewayAttachment(
                "VPCGatewayAttachment",
                VpcId=Ref(vpc),
                InternetGatewayId=Ref(internet_gateway),
                Condition=self.__create_ig,
            )
        )
        return If(self.__create_ig, Ref(internet_gateway), self.__gateway_id)

    def __build_subnet(self, subnet_config: SubnetConfig, vpc: VPC):
        if not subnet_config.cidr:
            cidr = Ref(
                self.__add_parameter(
                    name=f"{subnet_config.name}CIDR",
                    description=f"The CIDR of the {subnet_config.name}",
                    expected_input_type="String",
                )
            )
        else:
            cidr = subnet_config.cidr

        subnet = Subnet(
            subnet_config.name,
            CidrBlock=cidr,
            VpcId=Ref(vpc),
            MapPublicIpOnLaunch=subnet_config.map_public_ip_on_launch,
            Tags=subnet_config.tags(),
            AvailabilityZone=self.__availability_zone,
        )
        self.__template.add_resource(subnet)
        self.__template.add_output(Output(subnet_config.name + "Id", Value=Ref(subnet)))
        return subnet

    def __build_nat_gateway(self, subnet_config: SubnetConfig, subnet_ref: Subnet):
        nat_eip = self.__template.add_resource(EIP("NatEIP" + subnet_config.name, Domain="vpc"))
        return self.__template.add_resource(
            NatGateway(
                "NatGateway" + subnet_config.name,
                AllocationId=GetAtt(nat_eip, "AllocationId"),
                SubnetId=Ref(subnet_ref),
            )
        )

    def __build_route_table(
        self, subnet_config: SubnetConfig, subnet_ref: Subnet, vpc: VPC, internet_gateway, nat_gateway: NatGateway
    ):
        route_table = self.__template.add_resource(
            RouteTable(
                "RouteTable" + subnet_config.name,
                VpcId=Ref(vpc),
                Tags=Tags(Name=Sub("${AWS::StackName}RouteTable" + subnet_config.name), Stack=Ref("AWS::StackId")),
            )
        )
        self.__template.add_resource(
            SubnetRouteTableAssociation(
                "RouteAssociation" + subnet_config.name, SubnetId=Ref(subnet_ref), RouteTableId=Ref(route_table)
            )
        )
        if subnet_config.default_gateway == Gateways.INTERNET_GATEWAY:
            self.__template.add_resource(
                Route(
                    "DefaultRouteDependsOn" + subnet_config.name,
                    RouteTableId=Ref(route_table),
                    DestinationCidrBlock="0.0.0.0/0",
                    GatewayId=internet_gateway,
                    DependsOn="VPCGatewayAttachment",
                    Condition=self.__create_ig,
                )
            )
            self.__template.add_resource(
                Route(
                    "DefaultRouteNoDependsOn" + subnet_config.name,
                    RouteTableId=Ref(route_table),
                    DestinationCidrBlock="0.0.0.0/0",
                    GatewayId=internet_gateway,
                    Condition=self.__existing_ig,  # cant use Not()
                )
            )
        elif subnet_config.default_gateway == Gateways.NAT_GATEWAY:
            self.__template.add_resource(
                Route(
                    "NatRoute" + subnet_config.name,
                    RouteTableId=Ref(route_table),
                    DestinationCidrBlock="0.0.0.0/0",
                    NatGatewayId=Ref(nat_gateway),
                )
            )

    def __add_parameter(self, name, description, expected_input_type):
        return self.__template.add_parameter(Parameter(name, Description=description, Type=expected_input_type))
