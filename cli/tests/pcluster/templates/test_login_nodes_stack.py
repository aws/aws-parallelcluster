import email
import json

import pytest
import yaml
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
    login_node_user_data = login_node_lt["Properties"]["LaunchTemplateData"]["UserData"]["Fn::Base64"]["Fn::Sub"]
    login_node_user_data_template = login_node_user_data[0]
    login_node_user_data_substitutions = login_node_user_data[1]

    login_node_dna_json = render_join(login_node_user_data_substitutions["DnaJson"]["Fn::Join"])
    login_node_extra_json = login_node_user_data_substitutions["ExtraJson"]

    # Expected dna.json and extra.json
    expected_login_node_dna_json = load_json_dict(test_datadir / expected_login_node_dna_json_file_name)
    expected_login_node_extra_json = load_json_dict(test_datadir / expected_login_node_extra_json_file_name)

    # Assertions on dna.json
    assert_that(json.loads(login_node_dna_json)).is_equal_to(expected_login_node_dna_json)

    # Assertions on extra.json
    assert_that(json.loads(login_node_extra_json)).is_equal_to(expected_login_node_extra_json)

    # Assertions on the cloud-init write_files directives that materialize dna.json and
    # extra.json to check they are created with the correct ownership and permissions.
    expected_owner = "root:root"
    expected_permissions = "0644"

    _assert_write_files_directive(login_node_user_data_template, "/tmp/dna.json", expected_owner, expected_permissions)
    _assert_write_files_directive(
        login_node_user_data_template, "/tmp/extra.json", expected_owner, expected_permissions
    )


def _assert_write_files_directive(mime_user_data: str, path: str, expected_owner: str, expected_permissions: str):
    """Assert the cloud-init write_files directive for the given path exists with the expected ownership/permissions."""
    message = email.message_from_string(mime_user_data)
    directive = None
    for part in message.walk():
        if part.get_content_type() == "text/cloud-config":
            write_files = yaml.safe_load(part.get_payload()).get("write_files") or []
            directive = next((d for d in write_files if d.get("path") == path), None)
            break
    assert_that(directive).is_not_none()
    assert_that(directive["owner"]).is_equal_to(expected_owner)
    assert_that(directive["permissions"]).is_equal_to(expected_permissions)


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
