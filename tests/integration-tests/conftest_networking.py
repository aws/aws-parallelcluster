# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

# This file has a special meaning for pytest. See https://docs.pytest.org/en/2.7.3/plugins.html for
# additional details.

import logging
import random

import boto3
import pytest
from cfn_stacks_factory import CfnStack, CfnStacksFactory
from framework.credential_providers import aws_credential_provider
from framework.fixture_utils import xdist_session_fixture
from framework.tests_configuration.config_utils import get_all_regions
from network_template_builder import Gateways, NetworkTemplateBuilder, SubnetConfig, VPCConfig
from retrying import retry
from utils import generate_stack_name

from tests.common.utils import retrieve_latest_ami

AVAILABILITY_ZONE_OVERRIDES = {
    # c5.xlarge is not supported in use1-az3
    # FSx Lustre file system creation is currently not supported for use1-az3
    # p4d.24xlarge targeted ODCR is only available on use1-az6
    "us-east-1": ["use1-az6"],
    # some instance type is only supported in use2-az2
    "us-east-2": ["use2-az2"],
    # trn available on usw2-az4
    "us-west-2": ["usw2-az4"],
    # c5.xlarge is not supported in apse2-az3
    "ap-southeast-2": ["apse2-az1", "apse2-az2"],
    # FSx for Luster is not supported in apne1-az1
    "ap-northeast-1": ["apne1-az4", "apne1-az2"],
    # c4.xlarge is not supported in apne2-az2
    "ap-northeast-2": ["apne2-az1", "apne2-az3"],
    # c5.xlarge is not supported in apse1-az3
    "ap-southeast-1": ["apse1-az2", "apse1-az1"],
    # c4.xlarge is not supported in aps1-az2
    "ap-south-1": ["aps1-az1", "aps1-az3"],
    # NAT Gateway not available in sae1-az2 , c5n.18xlarge is not supported in sae1-az3
    "sa-east-1": ["sae1-az1"],
    # m6g.xlarge instances not available in euw1-az3
    "eu-west-1": ["euw1-az1", "euw1-az2"],
    # io2 EBS volumes not available in cac1-az4
    "ca-central-1": ["cac1-az1", "cac1-az2"],
    # instance can only be launch in placement group in eun1-az2
    "eu-north-1": ["eun1-az2"],
    # g3.8xlarge is not supported in euc1-az1
    "eu-central-1": ["euc1-az2", "euc1-az3"],
    # FSx not available in cnn1-az4
    "cn-north-1": ["cnn1-az1", "cnn1-az2"],
}

# Implements NamingConvention for Subnets
# See: https://quip-amazon.com/xLgkAjTFgb7L/
# Decision-Doc-Test-Runner-MultiAZ-requirements-and-improvements#temp:C:ZbZc1ead4e609ac455e821b5a7dc
#
# Default subnets (for retro-compatibilities and test-based overrides) will be named
#  - Public
#  - Private
#
# Unique zonal subnets will be named
#  - Az1Public ....
#  - Az1Private ...
#
# Custom subnets are allowed in either format
# Az1PublicNoInternet
# PrivateSpecialCidr
#
# Note: postfix SubnetId should be added somewhere else
def subnet_name(visibility="Public", az_num=None, special=None):
    az_id = "" if az_num is None else f"Az{az_num}"
    special_tag = "" if special is None else f"{special}"
    return f"{az_id}{visibility}{special_tag}"

def get_availability_zones(region, credential):
    """
    Return a list of availability zones for the given region.

    Note that this function is called by the vpc_stacks fixture. Because vcp_stacks is session-scoped,
    it cannot utilize setup_sts_credentials, which is required in opt-in regions in order to call
    describe_availability_zones.
    """
    az_list = []
    with aws_credential_provider(region, credential):
        client = boto3.client("ec2", region_name=region)
        response_az = client.describe_availability_zones(
            Filters=[
                {"Name": "region-name", "Values": [str(region)]},
                {"Name": "zone-type", "Values": ["availability-zone"]},
            ]
        )
        for az in response_az.get("AvailabilityZones"):
            az_list.append(az.get("ZoneName"))
    return az_list


def get_az_id_to_az_name_map(region, credential):
    """Return a dict mapping AZ IDs (e.g, 'use1-az2') to AZ names (e.g., 'us-east-1c')."""
    # credentials are managed manually rather than via setup_sts_credentials because this function
    # is called by a session-scoped fixture, which cannot make use of a class-scoped fixture.
    with aws_credential_provider(region, credential):
        ec2_client = boto3.client("ec2", region_name=region)
        return {
            entry.get("ZoneId"): entry.get("ZoneName")
            for entry in ec2_client.describe_availability_zones().get("AvailabilityZones")
        }


# If stack creation fails it'll retry once more. This is done to mitigate failures due to resources
# not available in randomly picked AZs.
@retry(
    stop_max_attempt_number=2,
    wait_fixed=5000,
    retry_on_exception=lambda exception: not isinstance(exception, KeyboardInterrupt),
)
def _create_vpc_stack(request, template, region, cfn_stacks_factory):
    if request.config.getoption("vpc_stack"):
        logging.info("Using stack {0} in region {1}".format(request.config.getoption("vpc_stack"), region))
        stack = CfnStack(name=request.config.getoption("vpc_stack"), region=region, template=template.to_json())
    else:
        stack = CfnStack(
            name=generate_stack_name("integ-tests-vpc", request.config.getoption("stackname_suffix")),
            region=region,
            template=template.to_json(),
        )
        cfn_stacks_factory.create_stack(stack)
    return stack


@pytest.fixture(scope="function")
def random_az_selector(request):
    """Select random AZs for a given region."""

    def _get_random_availability_zones(region, num_azs=1, default_value=None):
        """Return num_azs random AZs (in the form of AZ names, e.g. 'us-east-1a') for the given region."""
        az_ids = AVAILABILITY_ZONE_OVERRIDES.get(region, [])
        if az_ids:
            az_id_to_az_name_map = get_az_id_to_az_name_map(region, request.config.getoption("credential"))
            sample = random.sample([az_id_to_az_name_map.get(az_id, default_value) for az_id in az_ids], k=num_azs)
        else:
            sample = [default_value] * num_azs
        return sample[0] if num_azs == 1 else sample

    return _get_random_availability_zones


@pytest.fixture(scope="class")
def vpc_stack(vpc_stacks_shared, region):
    return vpc_stacks_shared.get(region)


@xdist_session_fixture(autouse=True)
def vpc_stacks_shared(cfn_stacks_factory, request, key_name):
    """
    Create VPC used by integ tests in all configured regions, shared among session.
    One VPC per region will be created.
    :return: a dictionary of VPC stacks with region as key
    """

    regions = request.config.getoption("regions") or get_all_regions(request.config.getoption("tests_config"))
    vpc_stacks_dict = {}

    for region in regions:
        # Creating private_subnet_different_cidr in a different AZ for test_efs
        # To-do: isolate this logic and create a compute subnet in different AZ than head node in test_efs

        # if region has a non-empty list in AVAILABILITY_ZONE_OVERRIDES, select a subset of those AZs
        credential = request.config.getoption("credential")
        az_ids_for_region = AVAILABILITY_ZONE_OVERRIDES.get(region, [])
        if az_ids_for_region:
            az_id_to_az_name = get_az_id_to_az_name_map(region, credential)
            az_names = [az_id_to_az_name.get(az_id) for az_id in az_ids_for_region]
            # if only one AZ can be used for the given region, use it multiple times
            if len(az_names) == 1:
                availability_zones = az_names * 3
            if len(az_names) == 2:
                # ensures that az[0] and az[1] are always different if two az are available for use
                availability_zones = az_names + random.sample(az_names, k=1)
        # otherwise, select a subset of all AZs in the region
        else:
            az_list = get_availability_zones(region, credential)
            # if number of available zones is smaller than 3, list is expanded to 3 and filled with [None, ...]
            if len(az_list) < 3:
                diff = 3 - len(az_list)
                availability_zones = az_list + [None] * diff
            else:
                availability_zones = random.sample(az_list, k=3)

        # Subnets visual representation:
        # http://www.davidc.net/sites/default/subnets/subnets.html?network=192.168.0.0&mask=16&division=7.70
        public_subnet = SubnetConfig(
            name=subnet_name(visibility="Public"),
            cidr="192.168.32.0/20",  # 4096 IPs
            map_public_ip_on_launch=True,
            has_nat_gateway=True,
            availability_zone=availability_zones[0],
            default_gateway=Gateways.INTERNET_GATEWAY,
        )
        private_subnet = SubnetConfig(
            name=subnet_name(visibility="Private"),
            cidr="192.168.64.0/20",  # 4096 IPs
            map_public_ip_on_launch=False,
            has_nat_gateway=False,
            availability_zone=availability_zones[0],
            default_gateway=Gateways.NAT_GATEWAY,
        )
        private_subnet_different_cidr = SubnetConfig(
            name=subnet_name(visibility="Private", special="AdditionalCidr"),
            cidr="192.168.96.0/20",  # 4096 IPs
            map_public_ip_on_launch=False,
            has_nat_gateway=False,
            availability_zone=availability_zones[1],
            default_gateway=Gateways.NAT_GATEWAY,
        )
        no_internet_subnet = SubnetConfig(
            name=subnet_name(visibility="Private", special="NoInternet"),
            cidr="192.168.16.0/20",  # 4096 IPs
            map_public_ip_on_launch=False,
            has_nat_gateway=False,
            availability_zone=availability_zones[0],
            default_gateway=Gateways.NONE,
        )
        public_subnet_az2 = SubnetConfig(
            name=subnet_name(visibility="Public", az_num=2),
            cidr="192.168.128.0/20",  # 4096 IPs
            map_public_ip_on_launch=True,
            has_nat_gateway=True,
            availability_zone=availability_zones[1],
            default_gateway=Gateways.INTERNET_GATEWAY,
        )
        private_subnet_az2 = SubnetConfig(
            name=subnet_name(visibility="Private", az_num=2),
            cidr="192.168.160.0/20",  # 4096 IPs
            map_public_ip_on_launch=False,
            has_nat_gateway=False,
            availability_zone=availability_zones[1],
            default_gateway=Gateways.NAT_GATEWAY,
        )
        public_subnet_az3 = SubnetConfig(
            name=subnet_name(visibility="Public", az_num=3),
            cidr="192.168.192.0/20",  # 4096 IPs
            map_public_ip_on_launch=True,
            has_nat_gateway=True,
            availability_zone=availability_zones[2],
            default_gateway=Gateways.INTERNET_GATEWAY,
        )
        private_subnet_az3 = SubnetConfig(
            name=subnet_name(visibility="Private", az_num=3),
            cidr="192.168.224.0/20",  # 4096 IPs
            map_public_ip_on_launch=False,
            has_nat_gateway=False,
            availability_zone=availability_zones[2],
            default_gateway=Gateways.NAT_GATEWAY,
        )
        vpc_config = VPCConfig(
            cidr="192.168.0.0/17",
            additional_cidr_blocks=["192.168.128.0/17"],
            subnets=[
                public_subnet,
                private_subnet,
                private_subnet_different_cidr,
                no_internet_subnet,
                public_subnet_az2,
                private_subnet_az2,
                public_subnet_az3,
                private_subnet_az3,
            ],
        )

        with aws_credential_provider(region, credential):
            bastion_image_id = retrieve_latest_ami(region, "alinux2")
        template = NetworkTemplateBuilder(
            vpc_configuration=vpc_config,
            default_availability_zone=availability_zones[0],
            create_bastion_instance=True,
            bastion_key_name=key_name,
            bastion_image_id=bastion_image_id,
            region=region,
        ).build()
        vpc_stacks_dict[region] = _create_vpc_stack(request, template, region, cfn_stacks_factory)

    return vpc_stacks_dict


@pytest.fixture(scope="class")
def vpc_stack_with_endpoints(region, request, key_name):
    """
    Create a VPC stack with VPC endpoints.
    Since VPC endpoints modify DNS at VPC level, all the subnets in that VPC will be affected.
    :return: a VPC stack
    """

    logging.info("Creating VPC stack with endpoints")
    credential = request.config.getoption("credential")
    stack_factory = CfnStacksFactory(request.config.getoption("credential"))

    def _create_stack(request, template, region, stack_factory):
        # TODO: be able to reuse an existing VPC endpoint stack
        stack = CfnStack(
            name=generate_stack_name("integ-tests-vpc-endpoints", request.config.getoption("stackname_suffix")),
            region=region,
            template=template.to_json(),
        )
        stack_factory.create_stack(stack)
        return stack

    # tests with VPC endpoints are not using multi-AZ
    availability_zone = get_availability_zones(region, credential)[0]

    bastion_subnet = SubnetConfig(
        name="Bastion",
        cidr="192.168.32.0/20",
        map_public_ip_on_launch=True,
        has_nat_gateway=True,
        availability_zone=availability_zone,
        default_gateway=Gateways.INTERNET_GATEWAY,
    )

    no_internet_subnet = SubnetConfig(
        name="NoInternet",
        cidr="192.168.16.0/20",  # 4096 IPs
        map_public_ip_on_launch=False,
        has_nat_gateway=False,
        availability_zone=availability_zone,
        default_gateway=Gateways.NONE,
    )

    vpc_config = VPCConfig(
        cidr="192.168.0.0/17",
        additional_cidr_blocks=["192.168.128.0/17"],
        subnets=[
            bastion_subnet,
            no_internet_subnet,
        ],
    )

    with aws_credential_provider(region, credential):
        bastion_image_id = retrieve_latest_ami(region, "alinux2")

    template = NetworkTemplateBuilder(
        vpc_configuration=vpc_config,
        default_availability_zone=availability_zone,
        create_vpc_endpoints=True,
        bastion_key_name=key_name,
        bastion_image_id=bastion_image_id,
        region=region,
    ).build()

    yield _create_stack(request, template, region, stack_factory)

    if not request.config.getoption("no_delete"):
        stack_factory.delete_all_stacks()
    else:
        logging.warning("Skipping deletion of CFN VPC endpoints stack because --no-delete option is set")
