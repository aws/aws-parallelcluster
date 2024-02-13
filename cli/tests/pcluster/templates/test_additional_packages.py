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
    "config_file_name,enabled",
    [
        ("config-enabled.yaml", True),
        ("config-disabled.yaml", False),
    ],
)
def test_intel_hpc_platform(mocker, test_datadir, config_file_name, enabled):
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
        tag_specs = template["Properties"]["LaunchTemplateData"]["TagSpecifications"]
        instance_tags = next(filter(lambda ts: ts["ResourceType"] == "instance", tag_specs), None)
        assert_that(instance_tags).is_not_none()
        tag = next(filter(lambda t: t["Key"] == "parallelcluster:intel-hpc", instance_tags["Tags"]), None)

        if enabled:
            assert_that(tag).is_not_none()
            assert_that(tag["Value"]).is_equal_to("enable_intel_hpc_platform=true")
        else:
            assert_that(tag).is_none()

    for _, template in get_resources(generated_template, type="AWS::EC2::Instance", name="HeadNode").items():
        tags = template["Properties"]["Tags"]
        assert_that(tags).is_not_none()
        tag = next(filter(lambda t: t["Key"] == "parallelcluster:intel-hpc", tags), None)

        if enabled:
            assert_that(tag).is_not_none()
            assert_that(tag["Value"]).is_equal_to("enable_intel_hpc_platform=true")
        else:
            assert_that(tag).is_none()
