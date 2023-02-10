import logging
import random
import string
from collections import defaultdict

import pytest
from cfn_stacks_factory import CfnStack, CfnStacksFactory
from conftest_networking import get_availability_zones
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

    def _create_stack(request, template, region, stack_factory):
        stack = CfnStack(
            name=generate_stack_name("integ-tests-vpc-database", request.config.getoption("stackname_suffix")),
            region=region,
            template=template.to_json(),
        )
        stack_factory.create_stack(stack)
        return stack

    availability_zone = get_availability_zones(region, credential)[0]
    public_subnet = SubnetConfig(
        name="Public",
        cidr="192.168.32.0/20",  # 4096 IPs
        map_public_ip_on_launch=True,
        has_nat_gateway=True,
        availability_zone=availability_zone,
        default_gateway=Gateways.INTERNET_GATEWAY,
    )
    private_subnet = SubnetConfig(
        name="Private",
        cidr="192.168.64.0/20",  # 4096 IPs
        map_public_ip_on_launch=False,
        has_nat_gateway=False,
        availability_zone=availability_zone,
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
        default_availability_zone=availability_zone,
    ).build()

    yield _create_stack(request, template, region, stack_factory)

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
            {"ParameterKey": "Subnet1CidrBlock", "ParameterValue": "192.168.8.0/23"},
            {"ParameterKey": "Subnet2CidrBlock", "ParameterValue": "192.168.4.0/23"},
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
def database_factory(request, vpc_stack_for_database):
    created_database_stacks = defaultdict(dict)
    stack_factory = CfnStacksFactory(request.config.getoption("credential"))

    logging.info("Setting up database_factory fixture")

    def _database_factory(
        existing_database_stack_name,
        test_resources_dir,
        region,
    ):
        if existing_database_stack_name:
            logging.info("Using pre-existing database stack named %s", existing_database_stack_name)
            return existing_database_stack_name

        if not created_database_stacks.get(region, {}).get("default"):
            logging.info("Creating default database stack")
            database_stack = _create_database_stack(stack_factory, request, region, vpc_stack_for_database)
            created_database_stacks[region]["default"] = database_stack.name

        logging.info("Using database stack %s", created_database_stacks.get(region, {}).get("default"))
        return created_database_stacks.get(region, {}).get("default")

    yield _database_factory

    for region, stack_dict in created_database_stacks.items():
        stack_name = stack_dict["default"]
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
