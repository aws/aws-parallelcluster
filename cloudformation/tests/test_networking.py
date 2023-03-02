"""Test the CloudFormation Template for networking."""

import boto3
import pytest
from assertpy import assert_that

PUBPRIV_TEMPLATE = "../networking/public-private.cfn.json"
PUBLIC_TEMPLATE = "../networking/public.cfn.json"


def _stack_output(cfn, stack_name, output_key):
    """Retrieve the output value for output_key from stack_name."""
    outputs = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    return next(filter(lambda x: x["OutputKey"] == output_key, outputs)).get("OutputValue")


# pylint: disable=too-many-arguments
def _create_vpc(cfn, stack_name, template_file, public_cidr, private_cidr=None, vpc_id=None, igw_id=None):
    """Create a networking configuration using the template,  wait for it to start and yield it."""
    ec2 = boto3.client("ec2")
    azs = ec2.describe_availability_zones()["AvailabilityZones"]
    availability_zone = azs[0]["ZoneName"]
    parameters = {
        "AvailabilityZone": availability_zone,
        "PublicCIDR": public_cidr,
        **({"PrivateCIDR": private_cidr} if private_cidr else {}),
        **({"VpcId": vpc_id} if vpc_id else {}),
        **({"InternetGatewayId": igw_id} if igw_id else {}),
    }

    with open(template_file, encoding="utf-8") as templ:
        template = templ.read()

    # Create networking using CloudFormation, block on completion
    cfn.create_stack(
        StackName=stack_name,
        TemplateBody=template,
        Capabilities=["CAPABILITY_IAM"],
        Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in parameters.items()],
    )
    cfn.get_waiter("stack_create_complete").wait(StackName=stack_name)

    try:
        yield stack_name

        # Delete the stack through CFN and wait for delete to complete
        cfn.delete_stack(StackName=stack_name)
        cfn.get_waiter("stack_delete_complete").wait(StackName=stack_name)
    except Exception as exc:
        cfn.delete_stack(StackName=stack_name)
        raise exc


@pytest.fixture(name="pubpriv")
def pubpriv_fixture(cfn, random_stack_name):
    """Create a networking configuration using the template,  wait for it to start and yield it."""
    stack_name = f"pc-net-{random_stack_name}"
    yield from _create_vpc(cfn, stack_name, PUBPRIV_TEMPLATE, "10.0.0.0/28", "10.0.0.16/28")


@pytest.fixture(name="public")
def public_fixture(cfn, random_stack_name):
    """Create a networking configuration using the template,  wait for it to start and yield it."""
    stack_name = f"pc-net-{random_stack_name}"
    yield from _create_vpc(cfn, stack_name, PUBLIC_TEMPLATE, "10.0.0.0/28")


@pytest.mark.local
def test_pubpriv_vpc_created(cfn, pubpriv):
    """Validate that a VPC is created by default."""
    assert_that(_stack_output(cfn, pubpriv, "VpcId")).is_not_none()


@pytest.mark.local
def test_public_vpc_created(cfn, public):
    """Validate that a VPC is created by default."""
    assert_that(_stack_output(cfn, public, "VpcId")).is_not_none()


@pytest.mark.local
def test_pubpriv_existing_vpc(cfn, pubpriv):
    """Validate that we can provide a VPC and IGW to create networking in Public / Private networking."""
    vpc_id = _stack_output(cfn, pubpriv, "VpcId")
    igw_id = _stack_output(cfn, pubpriv, "InternetGatewayId")

    # Create a new stack using existing VPC / IGW
    stack_name = f"{pubpriv}-2"
    vpc_gen = _create_vpc(cfn, stack_name, PUBPRIV_TEMPLATE, "10.0.0.48/28", "10.0.0.32/28", vpc_id, igw_id)
    next(vpc_gen)
    new_vpc_id = _stack_output(cfn, stack_name, "VpcId")
    assert_that(new_vpc_id).is_equal_to(vpc_id)
    next(vpc_gen, None)  # Release vpc to have it reaped


@pytest.mark.local
def test_public_existing_vpc(cfn, public):
    """Validate that we can provide a VPC and IGW to create networking in Public networking."""
    vpc_id = _stack_output(cfn, public, "VpcId")
    igw_id = _stack_output(cfn, public, "InternetGatewayId")

    # Create a new stack using existing VPC / IGW
    stack_name = f"{public}-2"
    vpc_gen = _create_vpc(cfn, stack_name, PUBLIC_TEMPLATE, public_cidr="10.0.0.16/28", vpc_id=vpc_id, igw_id=igw_id)
    next(vpc_gen)
    new_vpc_id = _stack_output(cfn, stack_name, "VpcId")
    assert_that(new_vpc_id).is_equal_to(vpc_id)
    next(vpc_gen, None)  # Release vpc to have it reaped
