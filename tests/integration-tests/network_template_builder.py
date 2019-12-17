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

from troposphere import Equals, GetAtt, If, Not, Output, Parameter, Ref, Tags, Template
from troposphere.ec2 import (
    EIP,
    VPC,
    InternetGateway,
    NatGateway,
    Route,
    RouteTable,
    Subnet,
    SubnetRouteTableAssociation,
    VPCCidrBlock,
    VPCGatewayAttachment,
)

TAGS_PREFIX = "ParallelCluster"


class Gateways(Enum):
    """Define gateways to use for default traffic in a subnet."""

    INTERNET_GATEWAY = auto()
    NAT_GATEWAY = auto()
    PROXY = auto()


class SubnetConfig(NamedTuple):
    """Configuration of a VPC Subnet"""

    name: str = "Public"
    cidr: object = None
    map_public_ip_on_launch: bool = True
    has_nat_gateway: bool = True
    availability_zone: str = None
    default_gateway: Gateways = Gateways.INTERNET_GATEWAY

    def tags(self):
        """Get the tags for the subnet"""
        return Tags(Name=TAGS_PREFIX + self.name + "Subnet", Stack=Ref("AWS::StackId"))


class VPCConfig(NamedTuple):
    """Configuration of a VPC"""

    name: str = "vpc"
    cidr: str = "10.0.0.0/16"
    additional_cidr_blocks: List[str] = []
    enable_dns_support: bool = True
    enable_dns_hostnames: bool = True
    has_internet_gateway: bool = True
    subnets: List[SubnetConfig] = [SubnetConfig()]
    tags: Tags = Tags(Name=Ref("AWS::StackName"), Stack=Ref("AWS::StackId"))


class NetworkTemplateBuilder:
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
        self.__availability_zone = self.__get_availability_zone(availability_zone)
        self.__vpc_config = vpc_configuration
        self.__vpc, self.__additional_vpc_cidr_blocks = self.__get_vpc(existing_vpc)
        self.__vpc_subnets = vpc_configuration.subnets
        self.__gateway_id = self.__get_gateway_id()
        self.__create_ig = self.__template.add_condition("CreateInternetGateway", Equals(self.__gateway_id, ""))
        self.__existing_ig = self.__template.add_condition(  # can't negate above condition with Not()
            "ExistingInternetGateway", Not(Equals(self.__gateway_id, ""))
        )

    def __get_vpc(self, existing_vpc):
        if existing_vpc:
            return self.__add_parameter(name="VpcId", description="The vpc id", expected_input_type="String"), []
        else:
            return self.__build_vpc()

    def __get_availability_zone(self, availability_zone):
        if availability_zone:
            return availability_zone
        else:
            return Ref(
                self.__template.add_parameter(
                    Parameter(
                        "AvailabilityZone",
                        Description="(Optional) The zone in which you want to create your subnet(s)",
                        Type="String",
                        Default="",
                    )
                )
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
            subnet_ref = self.__build_subnet(subnet, self.__vpc, self.__additional_vpc_cidr_blocks)
            subnet_refs.append(subnet_ref)
            if subnet.has_nat_gateway:
                nat_gateway = self.__build_nat_gateway(subnet, subnet_ref)

        for subnet, subnet_ref in zip(self.__vpc_subnets, subnet_refs):
            self.__build_route_table(subnet, subnet_ref, self.__vpc, internet_gateway, nat_gateway)

    def __build_vpc(self):
        vpc = self.__template.add_resource(
            VPC(
                self.__vpc_config.name,
                CidrBlock=self.__vpc_config.cidr,
                EnableDnsSupport=self.__vpc_config.enable_dns_support,
                EnableDnsHostnames=self.__vpc_config.enable_dns_hostnames,
                Tags=self.__vpc_config.tags,
            )
        )
        self.__template.add_output(Output("VpcId", Value=Ref(vpc), Description="The Vpc Id"))

        additional_vpc_cidr_blocks = []
        for idx, cidr_block in enumerate(self.__vpc_config.additional_cidr_blocks):
            additional_vpc_cidr_blocks.append(
                self.__template.add_resource(
                    VPCCidrBlock(f"AdditionalVPCCidrBlock{idx}", CidrBlock=cidr_block, VpcId=Ref(vpc))
                )
            )

        return vpc, additional_vpc_cidr_blocks

    def __build_internet_gateway(self, vpc: VPC):
        internet_gateway = self.__template.add_resource(
            InternetGateway(
                "InternetGateway",
                Tags=Tags(Name=TAGS_PREFIX + "IG", Stack=Ref("AWS::StackId")),
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
        return Ref(internet_gateway)

    def __get_gateway_id(self):
        return Ref(
            self.__template.add_parameter(
                Parameter(
                    "InternetGatewayId",
                    Description="(Optional) The id of the gateway (will be created if not specified)",
                    Type="String",
                    Default="",
                )
            )
        )

    def __build_subnet(self, subnet_config: SubnetConfig, vpc: VPC, additional_vpc_cidr_blocks: VPCCidrBlock):
        if not subnet_config.cidr:
            cidr = Ref(
                self.__template.add_parameter(
                    Parameter(
                        f"{subnet_config.name}CIDR",
                        Description=f"The CIDR of the {subnet_config.name}",
                        Type="String",
                        AllowedPattern=r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/(1[6-9]|2[0-9]|3[0-2])$",
                    )
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
            AvailabilityZone=subnet_config.availability_zone or self.__availability_zone,
            DependsOn=additional_vpc_cidr_blocks,
        )
        self.__template.add_resource(subnet)
        self.__template.add_output(Output(subnet_config.name + "SubnetId", Value=Ref(subnet)))
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
        internet_gateway = If(self.__create_ig, internet_gateway, self.__gateway_id)
        route_table = self.__template.add_resource(
            RouteTable(
                "RouteTable" + subnet_config.name,
                VpcId=Ref(vpc),
                Tags=Tags(Name=TAGS_PREFIX + "RouteTable" + subnet_config.name, Stack=Ref("AWS::StackId")),
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
