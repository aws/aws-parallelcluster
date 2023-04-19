# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import json

import pytest
from assertpy import assert_that

from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket_object_utils
from tests.pcluster.utils import get_head_node_policy, get_resources, get_statement_by_sid


@pytest.mark.parametrize(
    "config_file_name",
    [
        ("config.yaml"),
    ],
)
def test_additional_security_groups(mocker, test_datadir, config_file_name):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    for _, template in get_resources(
        generated_template,
        type="AWS::EC2::LaunchTemplate",
        properties={"LaunchTemplateName": "clustername-queue1-compute_resource1"},
    ).items():
        network_interfaces = template["Properties"]["LaunchTemplateData"]["NetworkInterfaces"]
        network_interface = next(filter(lambda ni: ni["DeviceIndex"] == 0, network_interfaces), None)
        assert_that(network_interface).is_not_none()
        assert_that(network_interface["Groups"]).contains_only("sg-12345678", {"Ref": "ComputeSecurityGroup"})


@pytest.mark.parametrize(
    "config_file_name",
    [
        ("config.yaml"),
    ],
)
def test_permissions_for_slurm_db_secret(mocker, test_datadir, config_file_name):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    head_node_policy = get_head_node_policy(generated_template)
    statement = get_statement_by_sid(policy=head_node_policy, sid="AllowGettingSlurmDbSecretValue")
    assert_that(statement["Effect"]).is_equal_to("Allow")
    assert_that(statement["Action"]).is_equal_to("secretsmanager:GetSecretValue")
    assert_that(statement["Resource"]).is_equal_to("arn:aws:secretsmanager:eu-west-1:123456789:secret:a-secret-name")


@pytest.mark.parametrize(
    "config_file_name",
    [
        ("config.yaml"),
    ],
)
def test_head_node_custom_pass_role(mocker, test_datadir, config_file_name):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    head_node_policy = get_head_node_policy(generated_template)
    statement = get_statement_by_sid(policy=head_node_policy, sid="PassRole")
    assert_that(statement["Effect"]).is_equal_to("Allow")
    assert_that(statement["Action"]).is_equal_to("iam:PassRole")
    assert_that(statement["Resource"]).is_equal_to("arn:aws:iam::123456789:role/role-name")


@pytest.mark.parametrize(
    "config_file_name",
    [
        ("config.yaml"),
    ],
)
def test_head_node_base_pass_role(mocker, test_datadir, config_file_name):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    head_node_policy = get_head_node_policy(generated_template)
    statement = get_statement_by_sid(policy=head_node_policy, sid="PassRole")
    assert_that(statement["Effect"]).is_equal_to("Allow")
    assert_that(statement["Action"]).is_equal_to("iam:PassRole")
    assert_that(json.dumps(statement["Resource"])).contains("role/parallelcluster/clustername/*")


@pytest.mark.parametrize(
    "config_file_name",
    [
        ("config.yaml"),
    ],
)
def test_head_node_mixed_pass_role(mocker, test_datadir, config_file_name):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    print(json.dumps(generated_template, sort_keys=True, indent=4))

    head_node_policy = get_head_node_policy(generated_template)
    statement = get_statement_by_sid(policy=head_node_policy, sid="PassRole")
    assert_that(statement["Effect"]).is_equal_to("Allow")
    assert_that(statement["Action"]).is_equal_to("iam:PassRole")
    resources = statement["Resource"]
    assert_that(resources).contains("arn:aws:iam::123456789:role/role-name")
    default_resource = next(filter(lambda r: r != "arn:aws:iam::123456789:role/role-name", resources), None)
    assert_that(default_resource).is_not_none()
    assert_that(json.dumps(default_resource)).contains("role/a-prefix/clustername/*")
