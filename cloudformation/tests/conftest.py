"""Additional pytest configuration."""
import os
import random
import string

import boto3
import pytest

PUBPRIV_TEMPLATE = "../networking/public-private.cfn.json"


def pytest_addoption(parser):
    """Add the pytest parameter options with defaults from environment."""
    for arg in ["bucket", "private_subnet_id", "public_subnet_id", "service_token"]:
        parser.addoption(f"--{arg}", action="store", default=os.environ.get(arg.upper(), ""))


def random_str():
    """Generate a random string."""
    alnum = string.ascii_uppercase + string.ascii_lowercase + string.digits
    start = random.choice(string.ascii_uppercase + string.ascii_lowercase)
    return start + "".join(random.choice(alnum) for _ in range(8))


def cfn_stack_generator(path, name, parameters=None, capabilities=None):
    """Create a stack, wait for completion and yield it."""
    cfn = boto3.client("cloudformation")
    with open(path, encoding="utf-8") as templ:
        template = templ.read()

    parameters = parameters or {}

    # Create networking using CloudFormation, block on completion
    cfn.create_stack(
        StackName=name,
        TemplateBody=template,
        Capabilities=capabilities or ["CAPABILITY_IAM"],
        Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in parameters.items()],
    )
    cfn.get_waiter("stack_create_complete").wait(StackName=name)

    try:
        outputs = cfn.describe_stacks(StackName=name)["Stacks"][0]["Outputs"]
        yield {o["OutputKey"]: o["OutputValue"] for o in outputs}

        # Delete the stack through CFN and wait for delete to complete
        cfn.delete_stack(StackName=name)
        cfn.get_waiter("stack_delete_complete").wait(StackName=name)
    except Exception as exc:
        cfn.delete_stack(StackName=name)
        raise exc


def pytest_collection_modifyitems(items, config):
    """Augment the tests to add unmarked marker to tests that aren't marked."""
    for item in items:
        if not any(item.iter_markers()):
            item.add_marker("unmarked")


@pytest.fixture(name="random_stack_name")
def random_stack_name_fixture():
    """Provide a short random id that can be used in a aack name."""
    return random_str()


@pytest.fixture(scope="session")
def service_token(pytestconfig):
    """Bucket returned from pytest arguments for retrieving artifacts."""
    return pytestconfig.getoption("service_token")


@pytest.fixture(scope="session", name="bucket")
def bucket_fixture(pytestconfig):
    """Bucket returned from pytest arguments for retrieving artifacts."""
    return pytestconfig.getoption("bucket")


@pytest.fixture(scope="session", name="private_subnet_id")
def private_subnet_id_fixture(pytestconfig):
    """public_subnet_id returned from pytest arguments for HeadNode."""
    return pytestconfig.getoption("private_subnet_id")


@pytest.fixture(scope="session", name="public_subnet_id")
def public_subnet_id_fixture(pytestconfig):
    """private_subnet_id returned from pytest argumenets for Compute Nodes."""
    return pytestconfig.getoption("public_subnet_id")


@pytest.fixture(scope="session", name="cfn")
def cfn_fixture():
    """Create a CloudFormation Boto3 client."""
    client = boto3.client("cloudformation")
    return client


@pytest.fixture(scope="module", name="default_vpc")
def default_vpc_fixture(private_subnet_id, public_subnet_id):
    """Create our default VPC networking and return the stack name."""
    if private_subnet_id != "" and public_subnet_id != "":
        yield {"PublicSubnetId": public_subnet_id, "PrivateSubnetId": private_subnet_id}
        return

    ec2 = boto3.client("ec2")
    azs = ec2.describe_availability_zones()["AvailabilityZones"]
    stack_name = random_str()
    parameters = {"AvailabilityZone": azs[0]["ZoneName"]}

    yield from cfn_stack_generator(PUBPRIV_TEMPLATE, stack_name, parameters)
