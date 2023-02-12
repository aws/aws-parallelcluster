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
from assertpy import assert_that
from cfn_stacks_factory import CfnStacksFactory, CfnVpcStack
from framework.credential_providers import aws_credential_provider
from framework.fixture_utils import xdist_session_fixture
from framework.tests_configuration.config_utils import get_all_regions
from network_template_builder import Gateways, NetworkTemplateBuilder, SubnetConfig, VPCConfig
from retrying import retry
from utils import generate_stack_name, to_pascal_from_kebab_case

from tests.common.utils import retrieve_latest_ami

DEFAULT_AVAILABILITY_ZONE = {
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


# Split the VPC address space into 32 subnets of 2046 (/21) addresses
# to ensure that each subnets has enough IP addresses to support enough tests parallelism.
# The first 10 are used for public subnets
# The second 10 are used for private subnets
# The remaining 12 are left for custom subnets
CIDR_FOR_PUBLIC_SUBNETS = [
    "192.168.0.0/21",
    "192.168.8.0/21",
    "192.168.16.0/21",
    "192.168.24.0/21",
    "192.168.32.0/21",
    "192.168.40.0/21",
    "192.168.48.0/21",
    "192.168.56.0/21",
    "192.168.64.0/21",
    "192.168.72.0/21",
]
CIDR_FOR_PRIVATE_SUBNETS = [
    "192.168.80.0/21",
    "192.168.88.0/21",
    "192.168.96.0/21",
    "192.168.104.0/21",
    "192.168.112.0/21",
    "192.168.120.0/21",
    "192.168.128.0/21",
    "192.168.136.0/21",
    "192.168.144.0/21",
    "192.168.152.0/21",
]
CIDR_FOR_CUSTOM_SUBNETS = [
    "192.168.160.0/21",
    "192.168.168.0/21",
    "192.168.176.0/21",
    "192.168.184.0/21",
    "192.168.192.0/21",
    "192.168.200.0/21",
    "192.168.208.0/21",
    "192.168.216.0/21",
    "192.168.224.0/21",
    "192.168.232.0/21",
    "192.168.240.0/21",
    "192.168.248.0/21",
]


def subnet_name(visibility="Public", az_id=None, flavor=None):
    az_id_pascal_case = "" if az_id is None else f"{to_pascal_from_kebab_case(az_id)}"
    flavor_string = "" if flavor is None else f"{flavor}"
    return f"{az_id_pascal_case}{visibility}{flavor_string}"


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
def _create_vpc_stack(request, template, region, default_az, az_ids, cfn_stacks_factory):
    if request.config.getoption("vpc_stack"):
        logging.info("Using stack {0} in region {1}".format(request.config.getoption("vpc_stack"), region))
        stack = CfnVpcStack(
            name=request.config.getoption("vpc_stack"),
            region=region,
            template=template.to_json(),
            default_az_id=default_az,
            az_ids=az_ids,
        )
    else:
        stack = CfnVpcStack(
            name=generate_stack_name("integ-tests-vpc", request.config.getoption("stackname_suffix")),
            region=region,
            template=template.to_json(),
            default_az_id=default_az,
            az_ids=az_ids,
        )
        cfn_stacks_factory.create_stack(stack)
    return stack


@pytest.fixture(scope="function")
def random_az_selector(request):
    """Select random AZs for a given region."""

    def _get_random_availability_zones(region, num_azs=1, default_value=None):
        """Return num_azs random AZs (in the form of AZ names, e.g. 'us-east-1a') for the given region."""
        az_ids = DEFAULT_AVAILABILITY_ZONE.get(region, [])
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
    credential = request.config.getoption("credential")

    vpc_stacks_dict = {}
    for region in regions:
        # TODO Region can be AZ ID, in this case convert it to Region
        az_id_to_az_name_map = get_az_id_to_az_name_map(region, credential)
        az_ids = list(az_id_to_az_name_map)  # cannot be a dict_keys
        az_names = [az_id_to_az_name_map.get(az_id) for az_id in az_id_to_az_name_map]
        default_az_id = random.choice(DEFAULT_AVAILABILITY_ZONE.get(region))
        default_az_name = az_id_to_az_name_map.get(default_az_id)

        subnets = []
        assert_that(len(az_names)).is_greater_than(1)

        for index, az_id in enumerate(az_ids):
            az_name = az_id_to_az_name_map.get(az_id)
            # Subnets visual representation:
            # http://www.davidc.net/sites/default/subnets/subnets.html?network=192.168.0.0&mask=16&division=7.70
            subnets.append(
                SubnetConfig(
                    name=subnet_name(visibility="Public", az_id=az_id),
                    cidr=CIDR_FOR_PUBLIC_SUBNETS[index],
                    map_public_ip_on_launch=True,
                    has_nat_gateway=True,
                    availability_zone=az_name,
                    default_gateway=Gateways.INTERNET_GATEWAY,
                )
            )
            subnets.append(
                SubnetConfig(
                    name=subnet_name(visibility="Private", az_id=az_id),
                    cidr=CIDR_FOR_PRIVATE_SUBNETS[index],
                    map_public_ip_on_launch=False,
                    has_nat_gateway=False,
                    availability_zone=az_name,
                    default_gateway=Gateways.NAT_GATEWAY,
                )
            )
            if index == 0:
                # Creating private_subnet_different_cidr in a different AZ for test_efs
                # TODO isolate this logic and create a compute subnet in different AZ than head node in test_efs
                subnets.append(
                    SubnetConfig(
                        name=subnet_name(visibility="Private", flavor="AdditionalCidr"),
                        cidr=CIDR_FOR_CUSTOM_SUBNETS[index],
                        map_public_ip_on_launch=False,
                        has_nat_gateway=False,
                        availability_zone=az_names[index + 1],
                        default_gateway=Gateways.NAT_GATEWAY,
                    )
                )
                subnets.append(
                    SubnetConfig(
                        name=subnet_name(visibility="Private", flavor="NoInternet"),
                        cidr=CIDR_FOR_CUSTOM_SUBNETS[index + 1],
                        map_public_ip_on_launch=False,
                        has_nat_gateway=False,
                        availability_zone=az_name,
                        default_gateway=Gateways.NONE,
                    )
                )

        vpc_config = VPCConfig(
            cidr="192.168.0.0/17",
            additional_cidr_blocks=["192.168.128.0/17"],
            subnets=subnets,
        )

        with aws_credential_provider(region, credential):
            bastion_image_id = retrieve_latest_ami(region, "alinux2")
        template = NetworkTemplateBuilder(
            vpc_configuration=vpc_config,
            default_availability_zone=default_az_name,
            create_bastion_instance=True,
            bastion_key_name=key_name,
            bastion_image_id=bastion_image_id,
            region=region,
        ).build()
        vpc_stacks_dict[region] = _create_vpc_stack(
            request, template, region, default_az_id, az_ids, cfn_stacks_factory
        )

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

    def _create_stack(request, template, region, default_az_id, az_ids, stack_factory):
        # TODO: be able to reuse an existing VPC endpoint stack
        stack = CfnVpcStack(
            name=generate_stack_name("integ-tests-vpc-endpoints", request.config.getoption("stackname_suffix")),
            region=region,
            template=template.to_json(),
            default_az_id=default_az_id,
            az_ids=az_ids,
        )
        stack_factory.create_stack(stack)
        return stack

    # tests with VPC endpoints are not using multi-AZ
    az_id_to_az_name_map = get_az_id_to_az_name_map(region, credential)
    default_az_id = random.choice(DEFAULT_AVAILABILITY_ZONE.get(region))
    default_az_name = az_id_to_az_name_map.get(default_az_id)

    bastion_subnet = SubnetConfig(
        name=subnet_name(visibility="Public", az_id=default_az_id),
        cidr=CIDR_FOR_PUBLIC_SUBNETS[0],
        map_public_ip_on_launch=True,
        has_nat_gateway=True,
        availability_zone=default_az_name,
        default_gateway=Gateways.INTERNET_GATEWAY,
    )

    no_internet_subnet = SubnetConfig(
        name=subnet_name(visibility="Private", flavor="NoInternet"),
        cidr=CIDR_FOR_PRIVATE_SUBNETS[0],
        map_public_ip_on_launch=False,
        has_nat_gateway=False,
        availability_zone=default_az_name,
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
        default_availability_zone=default_az_name,
        create_vpc_endpoints=True,
        bastion_key_name=key_name,
        bastion_image_id=bastion_image_id,
        region=region,
    ).build()

    yield _create_stack(request, template, region, default_az_id, [default_az_id], stack_factory)

    if not request.config.getoption("no_delete"):
        stack_factory.delete_all_stacks()
    else:
        logging.warning("Skipping deletion of CFN VPC endpoints stack because --no-delete option is set")
