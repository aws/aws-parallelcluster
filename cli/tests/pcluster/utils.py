# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import itertools
import os
from copy import deepcopy

import pytest
from assertpy import assert_that

from pcluster.constants import LAMBDA_VPC_ACCESS_MANAGED_POLICY
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import get_chunks, load_yaml_dict
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket


def load_cluster_model_from_yaml(config_file_name, test_datadir=None):
    if test_datadir:
        path = test_datadir / config_file_name
    else:
        # If test_datadir is not specified, find configs in example_configs directory
        path = f"{os.path.dirname(__file__)}/example_configs/{config_file_name}"
    input_yaml = load_yaml_dict(path)
    print(input_yaml)
    copy_input_yaml = deepcopy(input_yaml)
    cluster = ClusterSchema(cluster_name="clustername").load(copy_input_yaml)
    print(cluster)
    return input_yaml, cluster


def get_resources(
    generated_template: dict, name: str = None, type: str = None, properties: dict = None, deletion_policy: str = None
):
    return dict(
        (res_name, res_value)
        for res_name, res_value in generated_template.get("Resources", {}).items()
        if (name is None or res_name == name)
        and (type is None or res_value.get("Type") == type)
        and (deletion_policy is None or res_value.get("DeletionPolicy") == deletion_policy)
        and (
            properties is None
            or all(
                res_value.get("Properties", {}).get(prop_name) == prop_value
                for prop_name, prop_value in properties.items()
            )
        )
    )


def get_asset_content_with_resource_name(assets, resource_name):
    """Get the asset with a top-level resource matching the given logical ID from a list of assets."""
    for asset in assets:
        asset_content = asset.get("content")
        if asset_content:
            if asset_content["Resources"].get(resource_name):
                return asset_content
    return None


def get_head_node_policy(template, enforce_not_null=True):
    policy = get_resources(template, type="AWS::IAM::Policy", name="ParallelClusterPoliciesHeadNode").get(
        "ParallelClusterPoliciesHeadNode"
    )
    if enforce_not_null:
        assert_that(policy).is_not_none()
    return policy


def get_statement_by_sid(policy, sid, enforce_not_null=True):
    statements = policy["Properties"]["PolicyDocument"]["Statement"]
    statement = next(filter(lambda s: s.get("Sid") == sid, statements), None)
    if enforce_not_null:
        assert_that(statement).is_not_none()
    return statement


def flatten(array):
    return list(itertools.chain(array))


def assert_lambdas_have_expected_vpc_config_and_managed_policy(generated_template, expected_vpc_config):
    resources = generated_template.get("Resources")

    for lambda_function in _get_lambda_functions(resources):
        role = resources.get(_get_role_name(lambda_function))

        if expected_vpc_config:
            assert_that(_get_vpc_config(lambda_function)).is_equal_to(expected_vpc_config)
            assert_that(_get_managed_policy_arns(role)).contains(LAMBDA_VPC_ACCESS_MANAGED_POLICY)
        else:
            assert_that(_get_vpc_config(lambda_function)).is_none()
            assert_that(_get_managed_policy_arns(role)).does_not_contain(LAMBDA_VPC_ACCESS_MANAGED_POLICY)


def _get_vpc_config(lambda_function):
    return lambda_function.get("Properties").get("VpcConfig")


def _get_role_name(lambda_function):
    return lambda_function.get("Properties").get("Role").get("Fn::GetAtt")[0]


def _get_lambda_functions(resources):
    return [res for res in resources.values() if res.get("Type") == "AWS::Lambda::Function"]


def _get_managed_policy_arns(role):
    return {arn.get("Fn::Sub") for arn in role.get("Properties").get("ManagedPolicyArns", [])}


def load_cfn_templates_from_config(config_file_path, pcluster_config_reader):
    rendered_config_file = pcluster_config_reader(config_file_path)
    cluster_config = ClusterSchema(cluster_name="clustername").load(load_yaml_dict(rendered_config_file))
    return CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )


@pytest.mark.parametrize(
    "input_lst, desired_size, expected_output",
    [
        ([], None, [[]]),
        ([], 5, [[]]),
        ([0, 1, 2, 3, 4, 5], None, [[0, 1, 2, 3, 4, 5]]),
        (
            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22],
            None,
            [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19], [20, 21, 22]],
        ),
        (
            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22],
            10,
            [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [10, 11, 12, 13, 14, 15, 16, 17, 18, 19], [20, 21, 22]],
        ),
    ],
)
def test_get_chunks(input_lst, desired_size, expected_output):
    if desired_size:
        chunks = get_chunks(input_lst, desired_size)
    else:
        chunks = get_chunks(input_lst)
    index = 0
    for chunk in chunks:
        assert_that(chunk).is_equal_to(expected_output[index])
        index += 1
