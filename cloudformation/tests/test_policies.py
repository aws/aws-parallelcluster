"""Test the CloudFormation Template for policies."""
import random
import string

import boto3
import botocore
import pytest
from assertpy import assert_that
from cfn_flip import load_yaml

TEMPLATE = "../policies/parallelcluster-policies.yaml"


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


def test_match_api():
    """Validate minimal changes with the API's yaml."""
    source_path = "../../api/infrastructure/parallelcluster-api.yaml"
    policies_path = "../policies/parallelcluster-policies.yaml"

    with open(source_path, encoding="utf-8") as source_file:
        source = load_yaml(source_file.read())

    with open(policies_path, encoding="utf-8") as policies_file:
        policies = load_yaml(policies_file.read())

    # These params match except for the description
    for key in ["Region", "EnableFSxS3Access", "FsxS3Buckets", "PermissionsBoundaryPolicy"]:
        drop_keys = {"Description"}
        dest_dict = {k: v for k, v in policies["Parameters"][key].items() if k not in drop_keys}
        source_dict = {k: v for k, v in source["Parameters"][key].items() if k not in drop_keys}
        assert_that(dest_dict).is_equal_to(source_dict)

    for key in policies["Resources"].keys():
        drop_keys = {"Condition"}

        source_key = {
            "ParallelClusterFSxS3AccessPolicy": "FSxS3AccessPolicy",
            "ParallelClusterLambdaRole": "ParallelClusterUserRole",
        }.get(key, key)

        source_dict = {k: v for k, v in source["Resources"][source_key].items() if k not in drop_keys}
        dest_dict = {k: v for k, v in policies["Resources"][key].items() if k not in drop_keys}

        if key == "ParallelClusterLambdaRole":

            def remove_batch_if(arn):
                return arn if ("Ref" in arn or "Fn::Sub" in arn) else arn["Fn::If"][1]

            dest_dict["Properties"]["ManagedPolicyArns"] = list(
                map(remove_batch_if, dest_dict["Properties"]["ManagedPolicyArns"])
            )

        # Rename UserRole to LambdaRole, ignore policy name mismatch
        if key == "ParallelClusterFSxS3AccessPolicy":
            source_dict["Properties"]["Roles"][0]["Ref"] = "ParallelClusterLambdaRole"
            del source_dict["Properties"]["PolicyName"]
            del dest_dict["Properties"]["PolicyName"]

        # Rename UserRole to LambdaRole
        if key == "DefaultParallelClusterIamAdminPolicy":
            source_dict["Properties"]["Roles"][0]["Ref"] = "ParallelClusterLambdaRole"

        assert_that(dest_dict).is_equal_to(source_dict)
