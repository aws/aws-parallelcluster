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
    "efa_enabled, instance_type, network_cards_list, expected_interfaces, efa_interface_type, max_efa, max_cards",
    [
        # GB200 EFA enabled: NCI-0=interface (MaxENIs=15 but no EFA on NCI-0), odd=efa-only, even=efa-only
        (
            True,
            "p6e-gb200.WHATEVER_SIZE",
            [NetworkCard(0, 15), NetworkCard(1), NetworkCard(2, 2), NetworkCard(3), NetworkCard(4, 2)],
            [
                {"network_card_index": 0, "interface_type": None, "device_index": 0},
                {"network_card_index": 1, "interface_type": "efa-only", "device_index": 0},
                {"network_card_index": 2, "interface_type": "efa-only", "device_index": 1},
                {"network_card_index": 3, "interface_type": "efa-only", "device_index": 0},
                {"network_card_index": 4, "interface_type": "efa-only", "device_index": 1},
            ],
            None,
            16,
            17,
        ),
        # GB200 EFA disabled: skip odd cards, even cards get interface (unchanged)
        (
            False,
            "p6e-gb200.WHATEVER_SIZE",
            [NetworkCard(0, 15), NetworkCard(1), NetworkCard(2, 2), NetworkCard(3), NetworkCard(4, 2)],
            [
                {"network_card_index": 0, "interface_type": None, "device_index": 0},
                {"network_card_index": 2, "interface_type": None, "device_index": 1},
                {"network_card_index": 4, "interface_type": None, "device_index": 1},
            ],
            None,
            16,
            17,
        ),
        # Generic multi-NIC EFA enabled: NCI-0=interface+efa-only, NCI-1+=efa-only
        (
            True,
            "NOTp6e-gb200.WHATEVER_SIZE",
            [NetworkCard(0, 2), NetworkCard(1, 2), NetworkCard(2, 2)],
            [
                {"network_card_index": 0, "interface_type": None, "device_index": 0},
                {"network_card_index": 0, "interface_type": "efa-only", "device_index": 1},
                {"network_card_index": 1, "interface_type": "efa-only", "device_index": 1},
                {"network_card_index": 2, "interface_type": "efa-only", "device_index": 1},
            ],
            None,
            3,
            3,
        ),
        # Generic multi-NIC EFA enabled, MaxENIs=1 per card (hpc6id-like): NCI-0 fallback to efa, NCI-1+=efa-only
        (
            True,
            "NOTp6e-gb200.WHATEVER_SIZE",
            [NetworkCard(0), NetworkCard(1), NetworkCard(2)],
            [
                {"network_card_index": 0, "interface_type": "efa", "device_index": 0},
                {"network_card_index": 1, "interface_type": "efa-only", "device_index": 0},
                {"network_card_index": 2, "interface_type": "efa-only", "device_index": 0},
            ],
            None,
            3,
            3,
        ),
        # Generic multi-NIC EFA disabled (unchanged)
        (
            False,
            "NOTp6e-gb200.WHATEVER_SIZE",
            [NetworkCard(0, 2), NetworkCard(1, 2), NetworkCard(2, 2)],
            [
                {"network_card_index": 0, "interface_type": None, "device_index": 0},
                {"network_card_index": 1, "interface_type": None, "device_index": 1},
                {"network_card_index": 2, "interface_type": None, "device_index": 1},
            ],
            None,
            3,
            3,
        ),
        # B300 EFA enabled: NCI-0=interface (MaxEfa<MaxCards), NCI-1+=efa-only
        (
            True,
            "p6-b300.WHATEVER_SIZE",
            [NetworkCard(0, 4), NetworkCard(1, 4), NetworkCard(2, 4), NetworkCard(3, 4), NetworkCard(4, 4)],
            [
                {"network_card_index": 0, "interface_type": None, "device_index": 0},
                {"network_card_index": 1, "interface_type": "efa-only", "device_index": 1},
                {"network_card_index": 2, "interface_type": "efa-only", "device_index": 1},
                {"network_card_index": 3, "interface_type": "efa-only", "device_index": 1},
                {"network_card_index": 4, "interface_type": "efa-only", "device_index": 1},
            ],
            None,
            16,
            17,
        ),
        # B300 EFA disabled (unchanged)
        (
            False,
            "p6-b300.WHATEVER_SIZE",
            [NetworkCard(0, 4), NetworkCard(1, 4), NetworkCard(2, 4)],
            [
                {"network_card_index": 0, "interface_type": None, "device_index": 0},
                {"network_card_index": 1, "interface_type": None, "device_index": 1},
                {"network_card_index": 2, "interface_type": None, "device_index": 1},
            ],
            None,
            16,
            17,
        ),
        # Single-NIC EFA enabled: NCI-0=interface+efa-only
        (
            True,
            "c5n.18xlarge",
            [NetworkCard(0, 15)],
            [
                {"network_card_index": 0, "interface_type": None, "device_index": 0},
                {"network_card_index": 0, "interface_type": "efa-only", "device_index": 1},
            ],
            None,
            1,
            1,
        ),
        # Single-NIC EFA enabled, MaxENIs=1 (hpc5a-like): fallback to efa
        (
            True,
            "hpc5a.48xlarge",
            [NetworkCard(0)],
            [
                {"network_card_index": 0, "interface_type": "efa", "device_index": 0},
            ],
            None,
            1,
            1,
        ),
        # Legacy opt-out: EfaInterfaceType=efa restores old behavior
        (
            True,
            "NOTp6e-gb200.WHATEVER_SIZE",
            [NetworkCard(0, 2), NetworkCard(1, 2), NetworkCard(2, 2)],
            [
                {"network_card_index": 0, "interface_type": "efa", "device_index": 0},
                {"network_card_index": 1, "interface_type": "efa", "device_index": 1},
                {"network_card_index": 2, "interface_type": "efa", "device_index": 1},
            ],
            "efa",
            3,
            3,
        ),
        # Legacy opt-out on GB200: restores PC 3.14 behavior (even=efa, odd=efa-only)
        (
            True,
            "p6e-gb200.WHATEVER_SIZE",
            [NetworkCard(0, 15), NetworkCard(1), NetworkCard(2, 2), NetworkCard(3), NetworkCard(4, 2)],
            [
                {"network_card_index": 0, "interface_type": None, "device_index": 0},
                {"network_card_index": 1, "interface_type": "efa-only", "device_index": 0},
                {"network_card_index": 2, "interface_type": "efa", "device_index": 1},
                {"network_card_index": 3, "interface_type": "efa-only", "device_index": 0},
                {"network_card_index": 4, "interface_type": "efa", "device_index": 1},
            ],
            "efa",
            16,
            17,
        ),
        # Legacy opt-out on B300: NCI-0 stays interface, NCI-1+ switch to efa
        (
            True,
            "p6-b300.WHATEVER_SIZE",
            [NetworkCard(0, 4), NetworkCard(1, 4), NetworkCard(2, 4), NetworkCard(3, 4)],
            [
                {"network_card_index": 0, "interface_type": None, "device_index": 0},
                {"network_card_index": 1, "interface_type": "efa", "device_index": 1},
                {"network_card_index": 2, "interface_type": "efa", "device_index": 1},
                {"network_card_index": 3, "interface_type": "efa", "device_index": 1},
            ],
            "efa",
            16,
            17,
        ),
    ],
)
def test_add_compute_resource_launch_template(
    mocker,
    efa_enabled,
    instance_type,
    test_datadir,
    network_cards_list,
    expected_interfaces,
    efa_interface_type,
    max_efa,
    max_cards,
):
    mock_compute_resource = MagicMock()
    mock_compute_resource.name = "test-compute-resource"
    mock_compute_resource.instance_types = [instance_type]
    mock_compute_resource.efa.enabled = efa_enabled
    mock_compute_resource.network_cards_list = network_cards_list
    mock_compute_resource.max_efa_interfaces = max_efa
    mock_compute_resource.max_network_cards = max_cards

    mock_queue = MagicMock()
    mock_queue.name = "test-queue"

    network_interfaces = add_network_interfaces(
        mock_queue, mock_compute_resource, ["sg-12345"], efa_interface_type=efa_interface_type
    )

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


@pytest.mark.parametrize(
    "override_lt_data, expected_overrides",
    [
        # Override NetworkInterfaces only
        pytest.param(
            {"NetworkInterfaces": [{"DeviceIndex": 0, "InterfaceType": "efa", "Groups": ["sg-override"]}]},
            [("LaunchTemplateData.NetworkInterfaces", [{"DeviceIndex": 0, "InterfaceType": "efa", "Groups": ["sg-override"]}])],
            id="Override NetworkInterfaces",
        ),
    ],
)
def test_apply_launch_template_overrides(mocker, override_lt_data, expected_overrides):
    """Test that _apply_launch_template_overrides calls add_property_override for each property."""
    from pcluster.templates.queues_stack import _apply_launch_template_overrides

    # Mock the launch template CDK construct
    mock_launch_template = MagicMock()

    # Mock the compute resource with launch specification overrides
    mock_compute_resource = MagicMock()
    mock_compute_resource.launch_specification_overrides.launch_template_id = "lt-12345678901234567"
    mock_compute_resource.launch_specification_overrides.version = 1

    # Mock the EC2 API call
    mock_aws_api = mocker.patch("pcluster.templates.queues_stack.AWSApi")
    mock_aws_api.instance().ec2.describe_launch_template_version.return_value = override_lt_data

    # Call the function
    _apply_launch_template_overrides(mock_launch_template, mock_compute_resource)

    # Verify the overrides were applied
    assert mock_launch_template.add_property_override.call_count == len(expected_overrides)
    for path, value in expected_overrides:
        mock_launch_template.add_property_override.assert_any_call(path, value)