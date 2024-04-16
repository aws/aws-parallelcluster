import logging
import random
import string

import pytest
from cfn_stacks_factory import CfnStack, CfnStacksFactory, CfnVpcStack
from conftest_networking import (
    CIDR_FOR_CUSTOM_SUBNETS,
    CIDR_FOR_PRIVATE_SUBNETS,
    CIDR_FOR_PUBLIC_SUBNETS,
    get_az_setup_for_region,
    subnet_name,
)
from network_template_builder import Gateways, NetworkTemplateBuilder, SubnetConfig, VPCConfig
from utils import generate_stack_name


@pytest.fixture(scope="class")
def vpc_stack_for_database(region, request):
    """
    Create a VPC stack to be used for testing database stack template.
    :return: a VPC stack
    """

    logging.info("Creating VPC stack for database")
    credential = request.config.getoption("credential")
    stack_factory = CfnStacksFactory(request.config.getoption("credential"))

    def _create_stack(request, template, region, default_az_id, az_ids, stack_factory):
        stack = CfnVpcStack(
            name=generate_stack_name("integ-tests-vpc-database", request.config.getoption("stackname_suffix")),
            region=region,
            template=template.to_json(),
            default_az_id=default_az_id,
            az_ids=az_ids,
        )
        stack_factory.create_stack(stack)
        return stack

    # tests with database are not using multi-AZ
    default_az_id, default_az_name, _ = get_az_setup_for_region(region, credential)

    public_subnet = SubnetConfig(
        name=subnet_name(visibility="Public", az_id=default_az_id),
        cidr=CIDR_FOR_PUBLIC_SUBNETS[0],
        map_public_ip_on_launch=True,
        has_nat_gateway=True,
        availability_zone=default_az_name,
        default_gateway=Gateways.INTERNET_GATEWAY,
    )
    private_subnet = SubnetConfig(
        name=subnet_name(visibility="Private", az_id=default_az_id),
        cidr=CIDR_FOR_PRIVATE_SUBNETS[0],
        map_public_ip_on_launch=False,
        has_nat_gateway=False,
        availability_zone=default_az_name,
        default_gateway=Gateways.NAT_GATEWAY,
    )
    vpc_config = VPCConfig(
        cidr="192.168.0.0/17",
        additional_cidr_blocks=["192.168.128.0/17"],
        subnets=[
            public_subnet,
            private_subnet,
        ],
    )

    template = NetworkTemplateBuilder(
        vpc_configuration=vpc_config,
        default_availability_zone=default_az_name,
    ).build()

    yield _create_stack(request, template, region, default_az_id, [default_az_id], stack_factory)

    if not request.config.getoption("no_delete"):
        stack_factory.delete_all_stacks()
    else:
        logging.warning("Skipping deletion of CFN VPC database stack because --no-delete option is set")


def _create_database_stack(stack_factory, request, region, vpc_stack_for_database):
    logging.info("Creating stack for database")
    database_stack_name = generate_stack_name("integ-tests-slurm-db", request.config.getoption("stackname_suffix"))

    database_stack_template_path = "../../cloudformation/database/serverless-database.yaml"
    logging.info("Creating stack %s", database_stack_name)

    admin_password = "".join(
        [
            *random.choices(string.ascii_uppercase, k=6),
            *random.choices("!$%^()_+", k=4),
            *random.choices(string.digits, k=4),
            *random.choices(string.ascii_lowercase, k=6),
        ]
    )

    cluster_name = "".join(["slurm-accounting-", *random.choices(string.ascii_lowercase + string.digits, k=6)])

    with open(database_stack_template_path) as database_template:
        stack_parameters = [
            {"ParameterKey": "ClusterName", "ParameterValue": cluster_name},
            {"ParameterKey": "Vpc", "ParameterValue": vpc_stack_for_database.cfn_outputs["VpcId"]},
            {"ParameterKey": "AdminPasswordSecretString", "ParameterValue": admin_password},
            {"ParameterKey": "Subnet1CidrBlock", "ParameterValue": CIDR_FOR_CUSTOM_SUBNETS[-1]},
            {"ParameterKey": "Subnet2CidrBlock", "ParameterValue": CIDR_FOR_CUSTOM_SUBNETS[-2]},
        ]
        database_stack = CfnStack(
            name=database_stack_name,
            region=region,
            template=database_template.read(),
            parameters=stack_parameters,
            capabilities=["CAPABILITY_AUTO_EXPAND"],
        )
    stack_factory.create_stack(database_stack)
    logging.info("Creation of stack %s complete", database_stack_name)

    return database_stack


@pytest.fixture(scope="class")
def database(request, vpc_stack_for_database, region):
    stack_factory = CfnStacksFactory(request.config.getoption("credential"))

    logging.info("Setting up database fixture")
    existing_database_stack_name = request.config.getoption("slurm_database_stack_name")

    if existing_database_stack_name:
        logging.info("Using pre-existing database stack named %s", existing_database_stack_name)
        database_stack = CfnStack(name=existing_database_stack_name, region=region, template=None)
    else:
        logging.info("Creating default database stack")
        database_stack = _create_database_stack(stack_factory, request, region, vpc_stack_for_database)

        logging.info("Using database stack %s", database_stack.name)

    yield database_stack

    stack_name = database_stack.name
    if request.config.getoption("no_delete"):
        logging.info(
            "Not deleting database stack %s in region %s because --no-delete option was specified",
            stack_name,
            region,
        )
    else:
        logging.info(
            "Deleting database stack %s in region %s",
            stack_name,
            region,
        )
        stack_factory.delete_stack(stack_name, region)


@pytest.fixture(scope="function")
def test_resources_dir(datadir):
    return datadir / "resources"
