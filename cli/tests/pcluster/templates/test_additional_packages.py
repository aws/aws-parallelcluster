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


@pytest.mark.parametrize("enabled", [True, False])
def test_intel_one_api_toolkits(mocker, test_datadir, enabled, pcluster_config_reader):
    """Test the output template has the right root volume size, timeout, dna.json according to the input config file."""
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    input_yaml = load_yaml_dict(pcluster_config_reader(enabled=enabled))

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    resources = generated_template["Resources"]
    head_node_launch_template = resources["HeadNodeLaunchTemplate"]

    # Check root volume size
    block_device_mappings = head_node_launch_template["Properties"]["LaunchTemplateData"]["BlockDeviceMappings"]
    for block_device in block_device_mappings:
        if block_device["DeviceName"] == "/dev/sda1":
            if enabled:
                assert_that(block_device["Ebs"]["VolumeSize"]).is_equal_to(70)
            else:
                assert_that(block_device["Ebs"]["VolumeSize"]).is_equal_to(40)

    # Check dna.json is correctly set
    dna_json_list = head_node_launch_template["Metadata"]["AWS::CloudFormation::Init"]["deployConfigFiles"]["files"][
        "/tmp/dna.json"
    ]["content"]["Fn::Join"][1]
    dna_json = ""
    for item in dna_json_list:
        if isinstance(item, str):
            dna_json += item
    if enabled:
        assert_that(dna_json).contains('"install_intel_base_toolkit": "true",')
        assert_that(dna_json).contains('"install_intel_hpc_toolkit": "true",')
        assert_that(dna_json).contains('"install_intel_python": "true",')
    else:
        assert_that(dna_json).does_not_contain('"install_intel_base_toolkit": "true",')
        assert_that(dna_json).does_not_contain('"install_intel_hpc_toolkit": "true",')
        assert_that(dna_json).does_not_contain('"install_intel_python": "true",')

    # Check timeout
    for resource_name, resource_value in resources.items():
        if "HeadNodeWaitCondition" in resource_name and "Handle" not in resource_name:
            if enabled:
                assert_that(resource_value["Properties"]["Timeout"]).is_equal_to(str(2400))
            else:
                assert_that(resource_value["Properties"]["Timeout"]).is_equal_to(str(1800))
