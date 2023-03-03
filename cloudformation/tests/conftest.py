"""Additional pytest configuration."""
import random
import string

import boto3
import pytest


def pytest_collection_modifyitems(items, config):
    """Augment the tests to add unmarked marker to tests that aren't marked."""
    for item in items:
        if not any(item.iter_markers()):
            item.add_marker("unmarked")


@pytest.fixture(name="random_stack_name")
def random_stack_name_fixture():
    """Provide a short random id that can be used in a aack name."""
    alnum = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "".join(random.choice(alnum) for _ in range(8))


@pytest.fixture(scope="session", name="cfn")
def cfn_fixture():
    """Create a CloudFormation Boto3 client."""
    client = boto3.client("cloudformation")
    return client
