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
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket


@pytest.mark.parametrize(
    "config_file_name, resource_logical_name, security_group_property, expected_security_group",
    [
        ("efs.config.yaml", "EFS8d3a330efcad8cd3MTstring", "SecurityGroups", "ComputeSecurityGroup"),
        ("fsx-lustre.config.yaml", "FSX0c14c0b8f045af82", "SecurityGroupIds", "ComputeSecurityGroup"),
    ],
)
def test_shared_storage_security_group(
    mocker, test_datadir, config_file_name, resource_logical_name, security_group_property, expected_security_group
):
    mock_aws_api(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    actual_security_group_resource = generated_template["Resources"][resource_logical_name]["Properties"][
        security_group_property
    ]

    assert_that(actual_security_group_resource).is_equal_to([{"Ref": expected_security_group}])
