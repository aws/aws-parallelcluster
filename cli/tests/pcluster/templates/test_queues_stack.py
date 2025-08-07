import json
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that
from freezegun import freeze_time

from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.templates.queues_stack import add_network_interfaces
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
    "config_file_name, expected_compute_node_dna_json_file_name, expected_compute_node_extra_json_file_name",
    [
        ("config-1.yaml", "dna-1.json", "extra-1.json"),
        ("config-2.yaml", "dna-2.json", "extra-2.json"),
    ],
)
def test_compute_nodes_dna_json(
    mocker,
    test_datadir,
    config_file_name,
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
    compute_node_dna_json = render_join(
        compute_node_lt["Properties"]["LaunchTemplateData"]["UserData"]["Fn::Base64"]["Fn::Sub"][1]["DnaJson"][
            "Fn::Join"
        ]
    )

    compute_node_extra_json = compute_node_lt["Properties"]["LaunchTemplateData"]["UserData"]["Fn::Base64"]["Fn::Sub"][
        1
    ]["ExtraJson"]

    # Expected dna.json and extra.json
    expected_compute_node_dna_json = load_json_dict(test_datadir / expected_compute_node_dna_json_file_name)
    expected_compute_node_extra_json = load_json_dict(test_datadir / expected_compute_node_extra_json_file_name)

    # Assertions on dna.json
    assert_that(json.loads(compute_node_dna_json)).is_equal_to(expected_compute_node_dna_json)

    # Assertions on extra.json
    assert_that(json.loads(compute_node_extra_json)).is_equal_to(expected_compute_node_extra_json)


class NetworkCard:
    def __init__(self, index, max_interfaces=1):
        self._index = index
        self._max_interfaces = max_interfaces

    def network_card_index(self):
        return self._index

    def maximum_network_interfaces(self):
        return self._max_interfaces


@pytest.mark.parametrize(
    "efa_enabled, instance_type, network_cards_list, expected_interfaces",
    [
        (
            True,
            "p6e-gb200.WHATEVER_SIZE",
            [NetworkCard(0), NetworkCard(1), NetworkCard(2, 2), NetworkCard(3), NetworkCard(4, 2)],
            [
                {"network_card_index": 0, "interface_type": None, "device_index": 0},
                {"network_card_index": 1, "interface_type": "efa-only", "device_index": 0},
                {"network_card_index": 2, "interface_type": "efa", "device_index": 1},
                {"network_card_index": 3, "interface_type": "efa-only", "device_index": 0},
                {"network_card_index": 4, "interface_type": "efa", "device_index": 1},
            ],
        ),
        (
            False,
            "p6e-gb200.WHATEVER_SIZE",
            [NetworkCard(0), NetworkCard(1), NetworkCard(2, 2), NetworkCard(3), NetworkCard(4, 2)],
            [
                {"network_card_index": 0, "interface_type": None, "device_index": 0},
                {"network_card_index": 2, "interface_type": None, "device_index": 1},
                {"network_card_index": 4, "interface_type": None, "device_index": 1},
            ],
        ),
        (
            True,
            "NOTp6e-gb200.WHATEVER_SIZE",
            [NetworkCard(0), NetworkCard(1, 2), NetworkCard(2, 2)],
            [
                {"network_card_index": 0, "interface_type": "efa", "device_index": 0},
                {"network_card_index": 1, "interface_type": "efa", "device_index": 1},
                {"network_card_index": 2, "interface_type": "efa", "device_index": 1},
            ],
        ),
        (
            False,
            "NOTp6e-gb200.WHATEVER_SIZE",
            [NetworkCard(0), NetworkCard(1, 2), NetworkCard(2, 2)],
            [
                {"network_card_index": 0, "interface_type": None, "device_index": 0},
                {"network_card_index": 1, "interface_type": None, "device_index": 1},
                {"network_card_index": 2, "interface_type": None, "device_index": 1},
            ],
        ),
    ],
)
def test_add_compute_resource_launch_template(
    mocker, efa_enabled, instance_type, test_datadir, network_cards_list, expected_interfaces
):
    mock_compute_resource = MagicMock()
    mock_compute_resource.name = "test-compute-resource"
    mock_compute_resource.instance_types = [instance_type]
    mock_compute_resource.efa.enabled = efa_enabled
    mock_compute_resource.network_cards_list = network_cards_list

    mock_queue = MagicMock()
    mock_queue.name = "test-queue"

    network_interfaces = add_network_interfaces(mock_queue, mock_compute_resource, ["sg-12345"])

    assert len(network_interfaces) == len(expected_interfaces)

    for actual, expected in zip(network_interfaces, expected_interfaces):
        assert actual.network_card_index == expected["network_card_index"]
        assert actual.interface_type == expected["interface_type"]
        assert actual.device_index == expected["device_index"]


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
