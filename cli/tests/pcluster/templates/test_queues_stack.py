import json

import pytest
from assertpy import assert_that
from freezegun import freeze_time

from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import load_json_dict, load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket_object_utils
from tests.pcluster.templates.test_cluster_stack import IamPolicyAssertion, get_generated_template_and_cdk_assets
from tests.pcluster.utils import get_asset_content_with_resource_name


@pytest.mark.parametrize(
    "config_file_name, iam_policy_assertions",
    [
        (
            "config.yaml",
            [
                IamPolicyAssertion(
                    expected_statements=[
                        {
                            "Action": "ec2:DescribeInstanceAttribute",
                            "Effect": "Allow",
                            "Resource": "*",
                            "Sid": "Ec2",
                        },
                        {
                            "Action": "s3:GetObject",
                            "Effect": "Allow",
                            "Resource": {
                                "Fn::Join": [
                                    "",
                                    [
                                        "arn:",
                                        {"Ref": "AWS::Partition"},
                                        ":s3:::",
                                        {"Ref": "AWS::Region"},
                                        "-aws-parallelcluster/*",
                                    ],
                                ]
                            },
                            "Sid": "S3GetObj",
                        },
                        {
                            "Action": ["s3:GetObject", "s3:ListBucket"],
                            "Effect": "Allow",
                            "Resource": [
                                {
                                    "Fn::Join": [
                                        "",
                                        [
                                            "arn:",
                                            {"Ref": "AWS::Partition"},
                                            ":s3:::parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                                        ],
                                    ]
                                },
                                {
                                    "Fn::Join": [
                                        "",
                                        [
                                            "arn:",
                                            {"Ref": "AWS::Partition"},
                                            ":s3:::parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete/"
                                            "parallelcluster/clusters/dummy-cluster-randomstring123/*",
                                        ],
                                    ]
                                },
                            ],
                            "Sid": "S3GetLaunchTemplate",
                        },
                        {
                            "Action": "cloudformation:DescribeStackResource",
                            "Effect": "Allow",
                            "Resource": {
                                "Ref": "AWS::StackId",
                            },
                            "Sid": "CloudFormation",
                        },
                        {
                            "Action": [
                                "dynamodb:UpdateItem",
                                "dynamodb:PutItem",
                                "dynamodb:GetItem",
                            ],
                            "Effect": "Allow",
                            "Resource": {
                                "Fn::Join": [
                                    "",
                                    [
                                        "arn:",
                                        {"Ref": "AWS::Partition"},
                                        ":dynamodb:",
                                        {"Ref": "AWS::Region"},
                                        ":",
                                        {"Ref": "AWS::AccountId"},
                                        ":table/parallelcluster-clustername",
                                    ],
                                ]
                            },
                            "Sid": "DynamoDBTable",
                        },
                    ]
                ),
            ],
        ),
    ],
)
def test_compute_nodes_iam_permissions(
    mocker,
    config_file_name,
    iam_policy_assertions,
    test_datadir,
):
    generated_template, cdk_assets = get_generated_template_and_cdk_assets(
        mocker,
        config_file_name,
        test_datadir,
    )

    asset_content_iam_policies = get_asset_content_with_resource_name(
        cdk_assets,
        "ParallelClusterPolicies15b342af42246b70",
    )
    for iam_policy_assertion in iam_policy_assertions:
        iam_policy_assertion.assert_iam_policy_properties(
            asset_content_iam_policies, "ParallelClusterPolicies15b342af42246b70"
        )


@freeze_time("2024-01-15T15:30:45")
@pytest.mark.parametrize(
    "config_file_name, expected_common_dna_json_file_name, "
    "expected_compute_node_dna_json_file_name, expected_compute_node_extra_json_file_name",
    [
        ("config-1.yaml", "common-dna-1.json", "compute-dna-1.json", "extra-1.json"),
        ("config-2.yaml", "common-dna-2.json", "compute-dna-2.json", "extra-2.json"),
    ],
)
def test_compute_nodes_dna_json(
    mocker,
    test_datadir,
    config_file_name,
    expected_common_dna_json_file_name,
    expected_compute_node_dna_json_file_name,
    expected_compute_node_extra_json_file_name,
):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    # Read yaml and render CF Template
    input_yaml = load_yaml_dict(test_datadir / config_file_name)
    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)
    _, cdk_assets = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    # Generated dna.json and extra.json
    compute_node_lt_asset = get_asset_content_with_resource_name(cdk_assets, "LaunchTemplateA7211c84b953696f")
    compute_node_lt = compute_node_lt_asset["Resources"]["LaunchTemplateA7211c84b953696f"]
    compute_node_cfn_init_files = compute_node_lt["Metadata"]["AWS::CloudFormation::Init"]["deployConfigFiles"]["files"]
    common_dna_json = compute_node_cfn_init_files["/tmp/common-dna.json"]
    compute_node_dna_json = compute_node_cfn_init_files["/tmp/compute-dna.json"]
    compute_node_extra_json = compute_node_cfn_init_files["/tmp/extra.json"]

    # Expected dna.json and extra.json
    expected_commom_dna_json = load_json_dict(test_datadir / expected_common_dna_json_file_name)
    expected_compute_node_dna_json = load_json_dict(test_datadir / expected_compute_node_dna_json_file_name)
    expected_compute_node_extra_json = load_json_dict(test_datadir / expected_compute_node_extra_json_file_name)
    expected_owner = expected_group = "root"
    expected_mode = "000644"

    # Assertions on dna.json

    for file_json, expected_json, keys in [
        (common_dna_json, expected_commom_dna_json, "Fn::Join"),
        (compute_node_dna_json, expected_compute_node_dna_json, None),
    ]:
        if keys:
            rendered_content = render_join(file_json["content"][keys])
        else:
            rendered_content = file_json["content"]
        rendered_json = json.loads(rendered_content)
        assert_that(file_json["owner"]).is_equal_to(expected_owner)
        assert_that(file_json["group"]).is_equal_to(expected_group)
        assert_that(file_json["mode"]).is_equal_to(expected_mode)
        assert_that(rendered_json).is_equal_to(expected_json)

    # Assertions on extra.json
    assert_that(compute_node_extra_json["owner"]).is_equal_to(expected_owner)
    assert_that(compute_node_extra_json["group"]).is_equal_to(expected_group)
    assert_that(compute_node_extra_json["mode"]).is_equal_to(expected_mode)
    assert_that(json.loads(compute_node_extra_json["content"])).is_equal_to(expected_compute_node_extra_json)


def render_join(elem: dict):
    sep = str(elem[0])
    body = elem[1]
    rendered_body = []
    for item in body:
        if isinstance(item, str):
            rendered_body.append(str(item).strip())
        elif isinstance(item, dict):
            rendered_body.append(str(json.dumps(item).replace('"', '\\"')).strip())
        else:
            raise ValueError("Found unsupported item type while rendering Fn::Join")
    return sep.join(rendered_body)
