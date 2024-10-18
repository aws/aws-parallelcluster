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

import copy
import logging
import random
import re

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

AVAILABLE_AVAILABILITY_ZONE = {
    # c5.xlarge is not supported in use1-az3
    "us-east-1": ["use1-az1", "use1-az2", "use1-az4", "use1-az6", "use1-az5"],
    # c5.xlarge is not supported in apse2-az3
    "ap-southeast-2": ["apse2-az1", "apse2-az2"],
    # FSx for Luster is not supported in apne1-az1
    "ap-northeast-1": ["apne1-az4", "apne1-az2"],
    # c5.xlarge is not supported in apse1-az3
    "ap-southeast-1": ["apse1-az2", "apse1-az1"],
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
    # Should only consider supported AZs
    "us-isob-east-1": ["usibe1-az2", "usibe1-az3"],
}

# used to map a ZoneId to the corresponding region
# Nice-To-Have: a python script that creates this mapping by invoking aws describe-regions / subnets
# and then read it from a file
ZONE_ID_MAPPING = {
    "af-south-1": "^afs1-az[0-9]",
    "ap-east-1": "^ape1-az[0-9]",
    "ap-northeast-1": "^apne1-az[0-9]",
    "ap-northeast-2": "^apne2-az[0-9]",
    "ap-northeast-3": "^apne3-az[0-9]",
    "ap-south-1": "^aps1-az[0-9]",
    "ap-southeast-1": "^apse1-az[0-9]",
    "ap-southeast-2": "^apse2-az[0-9]",
    "ca-central-1": "^cac1-az[0-9]",
    "cn-north-1": "^cnn1-az[0-9]",
    "cn-northwest-1": "^cnnw1-az[0-9]",
    "eu-central-1": "^euc1-az[0-9]",
    "eu-north-1": "^eun1-az[0-9]",
    "eu-west-1": "^euw1-az[0-9]",
    "eu-west-2": "^euw2-az[0-9]",
    "eu-west-3": "^euw3-az[0-9]",
    "eu-south-1": "^eus1-az[0-9]",
    "me-south-1": "^mes1-az[0-9]",
    "sa-east-1": "^sae1-az[0-9]",
    "us-east-1": "^use1-az[0-9]",
    "us-east-2": "^use2-az[0-9]",
    "us-west-1": "^usw1-az[0-9]",
    "us-west-2": "^usw2-az[0-9]",
    "us-gov-east-1": "^usge1-az[0-9]",
    "us-gov-west-1": "^usgw1-az[0-9]",
}


# Split the VPC address space into 16 subnets of 4,096 (/20) addresses
# to ensure that each subnets has enough IP addresses to support enough tests parallelism and scaling tests.
# The first 6 are used for public subnets
# The second 6 are used for private subnets
# The remaining 4 are left for custom subnets
CIDR_FOR_PUBLIC_SUBNETS = [
    "192.168.0.0/20",
    "192.168.16.0/20",
    "192.168.32.0/20",
    "192.168.48.0/20",
    "192.168.64.0/20",
    "192.168.80.0/20",
]
CIDR_FOR_PRIVATE_SUBNETS = [
    "192.168.96.0/20",
    "192.168.112.0/20",
    "192.168.128.0/20",
    "192.168.144.0/20",
    "192.168.160.0/20",
    "192.168.176.0/20",
]
CIDR_FOR_PRIVATE_SUBNETS_SCALING = [
    "192.168.64.0/20",
    "192.168.80.0/20",
    "192.168.96.0/20",
    "192.168.112.0/20",
]
CIDR_FOR_CUSTOM_SUBNETS = [
    "192.168.192.0/20",
    "192.168.208.0/20",
    "192.168.224.0/20",
    "192.168.240.0/20",
]


@pytest.fixture(autouse=True)
def az_id():
    """Removes the need to declare the fixture in all tests even if not needed."""
    pass


def unmarshal_az_override(az_override):
    for region, regex in ZONE_ID_MAPPING.items():
        pattern = re.compile(regex)
        if pattern.match(az_override.lower()):
            return region
        elif region == az_override.lower():
            return az_override

    # If no mapping was found return the input parameter assuming the region value set by the user is correct.
    # This will fail while trying to make an AZ override for a region without a proper mapping.
    # In this case add the mapping to the list above before attempting the override.
    return az_override


def unmarshal_az_params(argvalues, argnames):
    """
    Given the list of tuple parameters defining the configured test dimensions, when an az-override is specified
    it replaces the az with the corresponding region, and fill the az field with the proper value.

    E.g.
    argvalues = [('r1az-id1', 'inst1', 'os1', 's', ''), ('r1-az-id1', 'inst1', 'os2', 's', ''),
                 ('r1az-id2', 'inst1', 'os1', 's', ''), ('r1-az-id2', 'inst1', 'os2', 's', ''),
                 ('region2', 'inst1', 'os1', 's', ''), ('region2', 'inst1', 'os2', 's', '')]

    Produces the following output:
    argvalues = [('region1', 'inst1', 'os1', 's', 'az-id1'), ('region1', 'inst1', 'os2', 's', 'az-id1'),
                 ('region1', 'inst1', 'os1', 's', 'az-id2'), ('region1', 'inst1', 'os2', 's', 'az-id2'),
                 ('region2', 'inst1', 'os1', 's', ''), ('region2', 'inst1', 'os2', 's', '')]
    """

    unmarshalled_params = []
    for tuple in argvalues:
        param_set = list(tuple)
        region = unmarshal_az_override(param_set[0])
        if region != param_set[0]:  # found an override
            param_set.append(param_set[0])  # set AZ as last value
            param_set[0] = region  # override first value with unmarshalled region
        else:
            # we could set here the default_az if there is no override, but we aren't doing so because
            # these values are set at each test execution and we want to keep the default_az consistent
            # across tests and retries of the same test
            param_set.append(None)  # set AZ to none

        unmarshalled_params.append((*param_set,))

    return unmarshalled_params, argnames + ["az_id"]


def subnet_name(visibility="Public", az_id=None, flavor=None):
    az_id_pascal_case = "" if az_id is None else f"{to_pascal_from_kebab_case(az_id)}"
    flavor_string = "" if flavor is None else f"{flavor}"
    return f"{az_id_pascal_case}{visibility}{flavor_string}"


def describe_availability_zones(region, credential):
    """
    Return the response of boto3 describe_availability_zones.

    Note that this function is called by the vpc_stacks fixture. Because vcp_stacks is session-scoped,
    it cannot utilize setup_sts_credentials, which is required in opt-in regions in order to call
    describe_availability_zones.
    """
    with aws_credential_provider(region, credential):
        client = boto3.client("ec2", region_name=region)
        return client.describe_availability_zones(
            Filters=[
                {"Name": "region-name", "Values": [str(region)]},
                {"Name": "zone-type", "Values": ["availability-zone"]},
            ]
        ).get("AvailabilityZones")


def get_availability_zones(region, credential):
    """Return a list of availability zones for the given region."""
    return [az.get("ZoneName") for az in describe_availability_zones(region, credential)]


def get_az_setup_for_region(region: str, credential: list):
    """Return a default AZ ID and its name, the list of all AZ IDs and names."""
    az_id_to_az_name_map = get_az_id_to_az_name_map(region, credential)
    if "us-isob-east-1" in region:
        # Removing One of the Az's from Isolated regions
        az_id_to_az_name_map.pop("usibe1-az1", "")
    az_ids = list(az_id_to_az_name_map)  # cannot be a dict_keys
    default_az_id = random.choice(AVAILABLE_AVAILABILITY_ZONE.get(region, az_ids))
    default_az_name = az_id_to_az_name_map.get(default_az_id)

    return default_az_id, default_az_name, az_id_to_az_name_map


def get_az_id_to_az_name_map(region, credential):
    """Return a dict mapping AZ IDs (e.g, 'use1-az2') to AZ names (e.g., 'us-east-1c')."""
    return {entry.get("ZoneId"): entry.get("ZoneName") for entry in describe_availability_zones(region, credential)}


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
        az_ids = AVAILABLE_AVAILABILITY_ZONE.get(region, [])
        if az_ids:
            az_id_to_az_name_map = get_az_id_to_az_name_map(region, request.config.getoption("credential"))
            sample = random.sample([az_id_to_az_name_map.get(az_id, default_value) for az_id in az_ids], k=num_azs)
        else:
            sample = [default_value] * num_azs
        return sample[0] if num_azs == 1 else sample

    return _get_random_availability_zones


@pytest.fixture(scope="class")
def vpc_stack(vpc_stacks_shared, region, az_id):
    # Create a local copy fo the shared vpcs to avoid
    # undesired effects on other tests.
    local_vpc_stack = copy.deepcopy(vpc_stacks_shared.get(region))
    local_vpc_stack.set_az_override(az_id)
    return local_vpc_stack


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
        # region may contain an az_id if an override was specified
        # here we ensure that we are using the region
        region = unmarshal_az_override(region)
        default_az_id, default_az_name, az_id_name_dict = get_az_setup_for_region(region, credential)

        subnets = []
        assert_that(len(az_id_name_dict)).is_greater_than(1)
        for index, (az_id, az_name) in enumerate(az_id_name_dict.items()):
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
                # Subnet with no Internet and no VPC Endpoints used to test bootstrap failure
                subnets.append(
                    SubnetConfig(
                        name=subnet_name(visibility="Private", flavor="Isolated"),
                        cidr=CIDR_FOR_CUSTOM_SUBNETS[index],
                        map_public_ip_on_launch=False,
                        has_nat_gateway=False,
                        availability_zone=default_az_name,
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
            request, template, region, default_az_id, list(az_id_name_dict), cfn_stacks_factory
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
    default_az_id, default_az_name, _ = get_az_setup_for_region(region, credential)

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
