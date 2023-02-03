"""Test the CloudFormation Template for policies."""

import botocore
import pytest
from assertpy import assert_that

TEMPLATE = "../policies/parallelcluster-policies.yaml"


@pytest.mark.parametrize(
    "parameters",
    [
        ({"Region": "*"}),
        ({"Region": "us-east-1"}),
        ({"EnableFSxS3Access": "true", "FsxS3Buckets": "*"}),
        ({"EnableFSxS3Access": "false"}),
        ({"EnableIamAdminAccess": "true"}),
        ({"EnableFSxS3Access": "true", "FsxS3Buckets": "arn:aws:s3:::bucket"}),
        ({"EnableBatchAccess": "true"}),
    ],
)
@pytest.mark.local
def test_policies(cfn, random_stack_name, parameters):
    """Test various parameter combinations."""
    stack_name = f"pc-cfn-{random_stack_name}"

    with open(TEMPLATE, encoding="utf-8") as inf:
        cfn.create_stack(
            StackName=stack_name,
            TemplateBody=inf.read(),
            Capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
            Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in parameters.items()],
        )

    try:
        cfn.get_waiter("stack_create_complete").wait(StackName=stack_name)
    except botocore.exceptions.WaiterError as exc:
        # Ensure that we always delete the stack even an exception is thrown
        cfn.delete_stack(StackName=stack_name)
        cfn.get_waiter("stack_delete_complete").wait(StackName=stack_name)
        raise exc

    stack = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
    stack_id = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["StackId"]
    status = stack["StackStatus"]
    assert_that(status).is_equal_to("CREATE_COMPLETE")
    cfn.delete_stack(StackName=stack_name)
    cfn.get_waiter("stack_delete_complete").wait(StackName=stack_name)
    status = cfn.describe_stacks(StackName=stack_id)["Stacks"][0]["StackStatus"]
    assert_that(status).is_equal_to("DELETE_COMPLETE")
