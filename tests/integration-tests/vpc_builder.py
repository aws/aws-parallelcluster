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

from troposphere import GetAtt, Output, Ref, Sub, Tags, Template
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
    cidr: str = "10.0.0.0/24"
    map_public_ip_on_launch: bool = True
    has_nat_gateway: bool = True
    default_gateway: Gateways = Gateways.INTERNET_GATEWAY

    def tags(self):
        """Get the tags for the subnet"""
        return Tags(Name=Sub("${AWS::StackName}-" + self.name + "_subnet"), Stack=Ref("AWS::StackId"))


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

    def __init__(self, vpc_config, description="VPC built by VPCBuilder"):
        self.__template = Template()
        self.__template.set_version("2010-09-09")
        self.__template.set_description(description)
        self.__vpc_config = vpc_config

    def build(self):
        """Build the template."""
        self.__build_template()
        return self.__template

    def __build_template(self):
        vpc = self.__build_vpc()
        internet_gateway = self.__build_internet_gateway(vpc)
        nat_gateway = None
        subnet_refs = []
        for subnet in self.__vpc_config.subnets:
            subnet_ref = self.__build_subnet(subnet, vpc)
            subnet_refs.append(subnet_ref)
            if subnet.has_nat_gateway:
                nat_gateway = self.__build_nat_gateway(subnet, subnet_ref)

        for subnet, subnet_ref in zip(self.__vpc_config.subnets, subnet_refs):
            self.__build_route_table(subnet, subnet_ref, vpc, internet_gateway, nat_gateway)

    def __build_vpc(self):
        vpc_config = self.__vpc_config
        vpc = self.__template.add_resource(
            VPC(
                vpc_config.name,
                CidrBlock=vpc_config.cidr,
                EnableDnsSupport=vpc_config.enable_dns_support,
                EnableDnsHostnames=vpc_config.enable_dns_hostnames,
                Tags=vpc_config.tags,
            )
        )
        self.__template.add_output(Output("VpcId", Value=Ref(vpc), Description="VPC Id"))
        return vpc

    def __build_internet_gateway(self, vpc: VPC):
        internet_gateway = self.__template.add_resource(
            InternetGateway("InternetGateway", Tags=Tags(Name=Ref("AWS::StackName"), Stack=Ref("AWS::StackId")))
        )
        self.__template.add_resource(
            VPCGatewayAttachment("VPCGatewayAttachment", VpcId=Ref(vpc), InternetGatewayId=Ref(internet_gateway))
        )
        return internet_gateway

    def __build_subnet(self, subnet_config: SubnetConfig, vpc: VPC):
        subnet = self.__template.add_resource(
            Subnet(
                subnet_config.name,
                CidrBlock=subnet_config.cidr,
                VpcId=Ref(vpc),
                MapPublicIpOnLaunch=subnet_config.map_public_ip_on_launch,
                Tags=subnet_config.tags(),
            )
        )
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
        self,
        subnet_config: SubnetConfig,
        subnet_ref: Subnet,
        vpc: VPC,
        internet_gateway: InternetGateway,
        nat_gateway: NatGateway,
    ):
        route_table = self.__template.add_resource(
            RouteTable(
                "RouteTable" + subnet_config.name,
                VpcId=Ref(vpc),
                Tags=Tags(Name=Sub("${AWS::StackName}_route_table_" + subnet_config.name), Stack=Ref("AWS::StackId")),
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
                    "DefaultRoute" + subnet_config.name,
                    RouteTableId=Ref(route_table),
                    DestinationCidrBlock="0.0.0.0/0",
                    GatewayId=Ref(internet_gateway),
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
