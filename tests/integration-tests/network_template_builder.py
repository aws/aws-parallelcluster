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

from assertpy import assert_that
from troposphere import Equals, GetAtt, If, Not, Output, Parameter, Ref, Tags, Template, ec2
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
    VPCEndpoint,
    VPCGatewayAttachment,
)
from troposphere.iam import InstanceProfile, Role
from utils import get_arn_partition

TAGS_PREFIX = "ParallelCluster"
BASTION_INSTANCE_TYPE = "t3.large"


class Gateways(Enum):
    """Define gateways to use for default traffic in a subnet."""

    INTERNET_GATEWAY = auto()
    NAT_GATEWAY = auto()
    PROXY = auto()
    NONE = auto()


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


class VPCEndpointConfig(NamedTuple):
    """Configuration for a VPC Endpoint."""

    class EndpointType(Enum):
        """Type of VPC Endpoint."""

        GATEWAY = "Gateway"
        INTERFACE = "Interface"

        def __str__(self):
            return self.value

    name: str = None
    service_name: str = None
    type: EndpointType = EndpointType.INTERFACE
    enable_private_dns: bool = True


class NetworkTemplateBuilder:
    """Build troposphere CFN templates for VPC creation."""

    def __init__(
        self,
        vpc_configuration: VPCConfig,
        existing_vpc: bool = False,
        default_availability_zone: str = None,
        description="Network build by NetworkTemplateBuilder",
        create_vpc_endpoints: bool = False,
        create_bastion_instance: bool = False,
        bastion_key_name: str = None,
        bastion_image_id: str = None,
        region: str = None,
    ):
        self.__template = Template()
        self.__template.set_version("2010-09-09")
        self.__template.set_description(description)
        self.__default_availability_zone = self.__get_default_availability_zone(default_availability_zone)
        self.__vpc_config = vpc_configuration
        self.__vpc, self.__additional_vpc_cidr_blocks = self.__get_vpc(existing_vpc)
        self.__existing_vpc = existing_vpc
        self.__vpc_subnets = vpc_configuration.subnets
        self.__gateway_id = self.__get_gateway_id()
        self.__create_ig = self.__template.add_condition("CreateInternetGateway", Equals(self.__gateway_id, ""))
        self.__existing_ig = self.__template.add_condition(  # can't negate above condition with Not()
            "ExistingInternetGateway", Not(Equals(self.__gateway_id, ""))
        )
        self.__region = region
        self.__create_vpc_endpoints = create_vpc_endpoints
        self.__create_bastion_instance = create_bastion_instance
        self.__bastion_key_name = bastion_key_name
        self.__bastion_image_id = bastion_image_id

    def __get_vpc(self, existing_vpc):
        if existing_vpc:
            return self.__add_parameter(name="VpcId", description="The vpc id", expected_input_type="String"), []
        else:
            return self.__build_vpc()

    def __get_default_availability_zone(self, availability_zone):
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
        nat_gateway_per_az_map = {}
        subnets = []
        subnet_refs = []
        bastion_subnet_ref = None
        no_internet_subnet_ref = None
        for subnet_config in self.__vpc_subnets:
            subnet = self.__build_subnet(subnet_config, self.__vpc, self.__additional_vpc_cidr_blocks)
            subnets.append(subnet)
            subnet_refs.append(Ref(subnet))
            if subnet_config.has_nat_gateway and nat_gateway_per_az_map.get(subnet_config.availability_zone) is None:
                nat_gateway_per_az_map[subnet_config.availability_zone] = self.__build_nat_gateway(
                    subnet_config, subnet
                )
            if subnet_config.default_gateway == Gateways.INTERNET_GATEWAY:
                bastion_subnet_ref = Ref(subnet)
            if subnet_config.default_gateway == Gateways.NONE:
                no_internet_subnet_ref = Ref(subnet)

        route_tables_refs = []
        for subnet_config, subnet in zip(self.__vpc_subnets, subnets):
            route_tables_refs.append(
                Ref(
                    self.__build_route_table(
                        subnet_config, subnet, self.__vpc, internet_gateway, nat_gateway_per_az_map
                    )
                )
            )

        if self.__create_vpc_endpoints:
            assert_that(no_internet_subnet_ref).is_not_none()
            self.__build_vpc_endpoints(no_internet_subnet_ref, route_tables_refs)

        if self.__create_bastion_instance or self.__create_vpc_endpoints:
            assert_that(bastion_subnet_ref).is_not_none()
            assert_that(self.__bastion_key_name).is_not_none()
            assert_that(self.__bastion_image_id).is_not_none()
            assert_that(self.__region).is_not_none()
            self.__build_bastion_instance(bastion_subnet_ref)

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
        self.__template.add_output(
            Output(
                "DefaultVpcSecurityGroupId",
                Value=GetAtt(vpc, "DefaultSecurityGroup"),
                Description="The Vpc default security group ID",
            )
        )

        additional_vpc_cidr_blocks = []
        for idx, cidr_block in enumerate(self.__vpc_config.additional_cidr_blocks):
            additional_vpc_cidr_blocks.append(
                self.__template.add_resource(
                    VPCCidrBlock(f"AdditionalVPCCidrBlock{idx}", CidrBlock=cidr_block, VpcId=Ref(vpc))
                )
            )

        return vpc, additional_vpc_cidr_blocks

    def __build_vpc_endpoints(self, subnet_id, route_table_ids):
        region = self.__region
        assert_that(region).is_not_none()
        prefix = "cn." if region.startswith("cn-") else ""

        vpc_endpoints = [
            VPCEndpointConfig(
                name="LogsEndpoint",
                service_name=f"com.amazonaws.{region}.logs",
                type=VPCEndpointConfig.EndpointType.INTERFACE,
                enable_private_dns=True,
            ),
            VPCEndpointConfig(
                name="CFNEndpoint",
                service_name=prefix + f"com.amazonaws.{region}.cloudformation",
                type=VPCEndpointConfig.EndpointType.INTERFACE,
                enable_private_dns=True,
            ),
            VPCEndpointConfig(
                name="EC2Endpoint",
                service_name=prefix + f"com.amazonaws.{region}.ec2",
                type=VPCEndpointConfig.EndpointType.INTERFACE,
                enable_private_dns=True,
            ),
            VPCEndpointConfig(
                name="SecretsManager",
                service_name=f"com.amazonaws.{region}.secretsmanager",
                type=VPCEndpointConfig.EndpointType.INTERFACE,
                enable_private_dns=True,
            ),
            VPCEndpointConfig(
                name="SystemsManagerEndpoint",
                service_name=f"com.amazonaws.{region}.ssm",
                type=VPCEndpointConfig.EndpointType.INTERFACE,
                enable_private_dns=True,
            ),
            VPCEndpointConfig(
                name="SystemsManagerMessagesEndpoint",
                service_name=f"com.amazonaws.{region}.ssmmessages",
                type=VPCEndpointConfig.EndpointType.INTERFACE,
                enable_private_dns=True,
            ),
            VPCEndpointConfig(
                name="EC2MessagesEndpoint",
                service_name=f"com.amazonaws.{region}.ec2messages",
                type=VPCEndpointConfig.EndpointType.INTERFACE,
                enable_private_dns=True,
            ),
            VPCEndpointConfig(
                name="S3Endpoint",
                service_name=f"com.amazonaws.{region}.s3",
                type=VPCEndpointConfig.EndpointType.GATEWAY,
                enable_private_dns=False,
            ),
            VPCEndpointConfig(
                name="DynamoEndpoint",
                service_name=f"com.amazonaws.{region}.dynamodb",
                type=VPCEndpointConfig.EndpointType.GATEWAY,
                enable_private_dns=False,
            ),
        ]

        for vpc_endpoint in vpc_endpoints:
            vpc_endpoint_kwargs = {
                "ServiceName": vpc_endpoint.service_name,
                "PrivateDnsEnabled": vpc_endpoint.enable_private_dns,
                "VpcEndpointType": str(vpc_endpoint.type),
                "VpcId": Ref(self.__vpc),
            }
            if vpc_endpoint.type == VPCEndpointConfig.EndpointType.INTERFACE:
                vpc_endpoint_kwargs["SubnetIds"] = [subnet_id]
            if vpc_endpoint.type == VPCEndpointConfig.EndpointType.GATEWAY:
                vpc_endpoint_kwargs["RouteTableIds"] = route_table_ids

            self.__template.add_resource(
                VPCEndpoint(
                    vpc_endpoint.name,
                    **vpc_endpoint_kwargs,
                )
            )

    def __bastion_instance_profile(self):
        instance_role = Role(
            "BastionNetworkingRole",
            ManagedPolicyArns=[f"arn:{get_arn_partition(self.__region)}:iam::aws:policy/AmazonSSMManagedInstanceCore"],
            AssumeRolePolicyDocument={
                "Version": "2012-10-17",
                "Statement": [
                    {"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}
                ],
            },
        )
        self.__template.add_resource(instance_role)
        instance_profile = InstanceProfile(
            "BastionInstanceProfile",
            Roles=[Ref(instance_role)],
        )
        self.__template.add_resource(instance_profile)
        return instance_profile

    def __build_bastion_instance(self, bastion_subnet_id):
        bastion_sg = ec2.SecurityGroup(
            "NetworkingTestBastionSG",
            GroupDescription="SecurityGroup for Bastion",
            SecurityGroupIngress=[
                ec2.SecurityGroupRule(
                    IpProtocol="tcp",
                    FromPort="22",
                    ToPort="22",
                    CidrIp="0.0.0.0/0",
                ),
            ],
            VpcId=Ref(self.__vpc),
        )
        instance_profile = self.__bastion_instance_profile()
        launch_template = ec2.LaunchTemplate(
            "NetworkingBastionLaunchTemplate",
            LaunchTemplateData=ec2.LaunchTemplateData(
                MetadataOptions=ec2.MetadataOptions(
                    HttpTokens="required",
                    HttpEndpoint="enabled",
                ),
                IamInstanceProfile=ec2.IamInstanceProfile(
                    Arn=GetAtt(instance_profile, "Arn"),
                ),
            ),
        )
        self.__template.add_resource(launch_template)
        instance = ec2.Instance(
            "NetworkingBastionInstance",
            InstanceType=BASTION_INSTANCE_TYPE,
            ImageId=self.__bastion_image_id,
            KeyName=self.__bastion_key_name,
            SecurityGroupIds=[Ref(bastion_sg)],
            LaunchTemplate=ec2.LaunchTemplateSpecification(
                LaunchTemplateId=Ref(launch_template), Version=GetAtt(launch_template, "LatestVersionNumber")
            ),
            SubnetId=bastion_subnet_id,
        )
        self.__template.add_resource(bastion_sg)
        self.__template.add_resource(instance)

        self.__template.add_output(
            Output("BastionIP", Value=GetAtt(instance, "PublicIp"), Description="The Bastion Public IP")
        )
        self.__template.add_output(Output("BastionUser", Value="ec2-user", Description="The Bastion User"))

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
            AvailabilityZone=subnet_config.availability_zone or self.__default_availability_zone,
            DependsOn=additional_vpc_cidr_blocks,
        )
        self.__template.add_resource(subnet)
        self.__template.add_output(Output(subnet_config.name + "SubnetId", Value=Ref(subnet)))
        return subnet

    def __build_nat_gateway(self, subnet_config: SubnetConfig, subnet_ref: Subnet):
        # The following depends_on ensures that EIP is not left over if VPC or InternetGateway creation fails.
        depends_on = []
        if self.__create_ig:
            depends_on.append("InternetGateway")
        if not self.__existing_vpc:
            depends_on.append(self.__vpc_config.name)
        nat_eip = self.__template.add_resource(EIP("NatEIP" + subnet_config.name, Domain="vpc", DependsOn=depends_on))
        return self.__template.add_resource(
            NatGateway(
                "NatGateway" + subnet_config.name,
                AllocationId=GetAtt(nat_eip, "AllocationId"),
                SubnetId=Ref(subnet_ref),
            )
        )

    def __build_route_table(
        self, subnet_config: SubnetConfig, subnet_ref: Subnet, vpc: VPC, internet_gateway, nat_gateway_per_az_map: dict
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
                    NatGatewayId=Ref(nat_gateway_per_az_map.get(subnet_config.availability_zone)),
                )
            )

        return route_table

    def __add_parameter(self, name, description, expected_input_type):
        return self.__template.add_parameter(Parameter(name, Description=description, Type=expected_input_type))
