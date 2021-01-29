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
from enum import Enum
from typing import NamedTuple

import boto3
import pytest
from assertpy import assert_that
from cfn_stacks_factory import CfnStack
from troposphere import Template
from troposphere.ec2 import VPCEndpoint
from utils import generate_stack_name, get_compute_nodes_instance_ids

from tests.common.utils import get_default_vpc_security_group, get_route_tables


@pytest.mark.dimensions("us-west-2", "c5.xlarge", "alinux2", "slurm")
@pytest.mark.dimensions("eu-west-2", "c5.xlarge", "centos7", "sge")
@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_cluster_in_private_subnet(region, pcluster_config_reader, clusters_factory):
    # This test just creates a cluster in the private subnet and just checks that no failures occur
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    assert_that(cluster).is_not_none()

    assert_that(len(get_compute_nodes_instance_ids(cluster.cfn_name, region))).is_equal_to(1)


@pytest.mark.usefixtures("enable_vpc_endpoints")
@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_cluster_in_no_internet_subnet(
    region, pcluster_config_reader, clusters_factory, vpc_stack, s3_bucket_factory, test_datadir
):
    # This test just creates a cluster in a subnet with no internet and checks that no failures occur

    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "pre_install.sh"), "scripts/pre_install.sh")

    vpc_default_security_group_id = get_default_vpc_security_group(vpc_stack.cfn_outputs["VpcId"], region)
    cluster_config = pcluster_config_reader(
        vpc_default_security_group_id=vpc_default_security_group_id, bucket_name=bucket_name
    )
    cluster = clusters_factory(cluster_config)
    assert_that(cluster).is_not_none()

    assert_that(len(get_compute_nodes_instance_ids(cluster.cfn_name, region))).is_equal_to(1)

    # Todo: add test for job submission. This will require a proxy node to connect to the head node of the cluster.


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


@pytest.fixture()
def enable_vpc_endpoints(vpc_stack, region, cfn_stacks_factory, request):
    if not hasattr(enable_vpc_endpoints, "created_stacks"):
        enable_vpc_endpoints.created_stacks = set()

    if region in enable_vpc_endpoints.created_stacks:
        return

    vpc_endpoints = [
        VPCEndpointConfig(
            name="LogsEndpoint",
            service_name=f"com.amazonaws.{region}.logs",
            type=VPCEndpointConfig.EndpointType.INTERFACE,
            enable_private_dns=True,
        ),
        VPCEndpointConfig(
            name="ASGEndpoint",
            service_name=f"com.amazonaws.{region}.autoscaling",
            type=VPCEndpointConfig.EndpointType.INTERFACE,
            enable_private_dns=True,
        ),
        VPCEndpointConfig(
            name="SQSEndpoint",
            service_name=f"com.amazonaws.{region}.sqs",
            type=VPCEndpointConfig.EndpointType.INTERFACE,
            enable_private_dns=True,
        ),
        VPCEndpointConfig(
            name="CFNEndpoint",
            service_name=f"com.amazonaws.{region}.cloudformation",
            type=VPCEndpointConfig.EndpointType.INTERFACE,
            enable_private_dns=True,
        ),
        VPCEndpointConfig(
            name="EC2Endpoint",
            service_name=f"com.amazonaws.{region}.ec2",
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
    vpc_id = vpc_stack.cfn_outputs["VpcId"]
    subnet_id = vpc_stack.cfn_outputs["NoInternetSubnetId"]
    route_table_ids = get_route_tables(subnet_id, region)
    troposphere_template = Template()
    for vpc_endpoint in vpc_endpoints:
        vpc_endpoint_kwargs = {
            "ServiceName": vpc_endpoint.service_name,
            "PrivateDnsEnabled": vpc_endpoint.enable_private_dns,
            "VpcEndpointType": str(vpc_endpoint.type),
            "VpcId": vpc_id,
        }
        if vpc_endpoint.type == VPCEndpointConfig.EndpointType.INTERFACE:
            vpc_endpoint_kwargs["SubnetIds"] = [subnet_id]
        elif vpc_endpoint.type == VPCEndpointConfig.EndpointType.GATEWAY:
            vpc_endpoint_kwargs["RouteTableIds"] = route_table_ids
        troposphere_template.add_resource(
            VPCEndpoint(
                vpc_endpoint.name,
                **vpc_endpoint_kwargs,
            )
        )
    vpc_endpoints_stack = CfnStack(
        name=generate_stack_name("integ-tests-vpc-endpoints", request.config.getoption("stackname_suffix")),
        region=region,
        template=troposphere_template.to_json(),
    )

    cfn_stacks_factory.create_stack(vpc_endpoints_stack)
    enable_vpc_endpoints.created_stacks.add(region)
    # cfn_stacks_factory takes care of stack deletion on tests teardown
