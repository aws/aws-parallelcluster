import logging
import random
import string
from collections import defaultdict

import pytest
from cfn_stacks_factory import CfnStack
from utils import generate_stack_name


def _create_database_stack(cfn_stacks_factory, request, region, vpc_stack):
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
            {"ParameterKey": "Vpc", "ParameterValue": vpc_stack.cfn_outputs["VpcId"]},
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
    cfn_stacks_factory.create_stack(database_stack)
    logging.info("Creation of stack %s complete", database_stack_name)

    return database_stack


@pytest.fixture(scope="package")
def database_factory(request, cfn_stacks_factory, vpc_stacks):
    created_database_stacks = defaultdict(dict)

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
            database_stack = _create_database_stack(cfn_stacks_factory, request, region, vpc_stacks[region])
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
            cfn_stacks_factory.delete_stack(stack_name, region)


@pytest.fixture(scope="function")
def test_resources_dir(datadir):
    return datadir / "resources"
