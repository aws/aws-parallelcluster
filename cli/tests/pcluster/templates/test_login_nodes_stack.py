import json

import pytest
from assertpy import assert_that
from freezegun import freeze_time

from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import load_json_dict, load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket_object_utils
from tests.pcluster.utils import get_asset_content_with_resource_name


@freeze_time("2024-01-15T15:30:45")
@pytest.mark.parametrize(
    "config_file_name, expected_login_node_dna_json_file_name, expected_login_node_extra_json_file_name",
    [
        ("config-1.yaml", "dna-1.json", "extra-1.json"),
        ("config-2.yaml", "dna-2.json", "extra-2.json"),
    ],
)
def test_login_nodes_dna_json(
    mocker,
    test_datadir,
    config_file_name,
    expected_login_node_dna_json_file_name,
    expected_login_node_extra_json_file_name,
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
    login_node_lt_id = "LoginNodeLaunchTemplate2736fab291f04e69"
    login_node_lt_asset = get_asset_content_with_resource_name(cdk_assets, login_node_lt_id)
    login_node_lt = login_node_lt_asset["Resources"][login_node_lt_id]
    login_node_cfn_init_files = login_node_lt["Metadata"]["AWS::CloudFormation::Init"]["deployConfigFiles"]["files"]
    login_node_dna_json = login_node_cfn_init_files["/tmp/dna.json"]
    login_node_extra_json = login_node_cfn_init_files["/tmp/extra.json"]

    # Expected dna.json and extra.json
    expected_login_node_dna_json = load_json_dict(test_datadir / expected_login_node_dna_json_file_name)
    expected_login_node_extra_json = load_json_dict(test_datadir / expected_login_node_extra_json_file_name)
    expected_owner = expected_group = "root"
    expected_mode = "000644"

    # Assertions on dna.json
    rendered_dna_json_content = render_join(login_node_dna_json["content"]["Fn::Join"])
    rendered_dna_json_content_as_json = json.loads(rendered_dna_json_content)
    assert_that(login_node_dna_json["owner"]).is_equal_to(expected_owner)
    assert_that(login_node_dna_json["group"]).is_equal_to(expected_group)
    assert_that(login_node_dna_json["mode"]).is_equal_to(expected_mode)
    assert_that(rendered_dna_json_content_as_json).is_equal_to(expected_login_node_dna_json)

    # Assertions on extra.json
    assert_that(login_node_extra_json["owner"]).is_equal_to(expected_owner)
    assert_that(login_node_extra_json["group"]).is_equal_to(expected_group)
    assert_that(login_node_extra_json["mode"]).is_equal_to(expected_mode)
    assert_that(json.loads(login_node_extra_json["content"])).is_equal_to(expected_login_node_extra_json)


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
