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

import pytest
from assertpy import assert_that

from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket_object_utils
from tests.pcluster.utils import get_resources


@pytest.mark.parametrize(
    "config_file_name,permissions_boundary",
    [
        ("config.yaml", "arn:aws:iam:123456789:policy/APolicy"),
    ],
)
def test_iam_permissions_boundary(mocker, test_datadir, config_file_name, permissions_boundary):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    role_head_node = get_resources(generated_template, type="AWS::IAM::Role", name="RoleHeadNode").get("RoleHeadNode")

    assert_that(role_head_node).is_not_none()
    assert_that(role_head_node["Properties"]["PermissionsBoundary"]).is_equal_to(permissions_boundary)
