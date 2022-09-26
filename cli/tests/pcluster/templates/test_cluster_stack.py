# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from datetime import datetime

import pytest
import yaml
from assertpy import assert_that
from freezegun import freeze_time

from pcluster.aws.aws_resources import InstanceTypeInfo
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import load_json_dict, load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket
from tests.pcluster.utils import load_cluster_model_from_yaml


@pytest.mark.parametrize(
    "config_file_name",
    [
        "slurm.required.yaml",
        "slurm.full.yaml",
        "awsbatch.simple.yaml",
        "awsbatch.full.yaml",
        "scheduler_plugin.required.yaml",
        "scheduler_plugin.full.yaml",
    ],
)
def test_cluster_builder_from_configuration_file(mocker, capsys, config_file_name):
    mock_aws_api(mocker)
    # mock bucket initialization parameters
    mock_bucket(mocker)
    input_yaml, cluster = load_cluster_model_from_yaml(config_file_name)
    generated_template = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )
    _, err = capsys.readouterr()
    assert_that(err).is_empty()  # Assertion failure may become an update of dependency warning deprecations.
    yaml.dump(generated_template)


@pytest.mark.parametrize(
    "config_file_name, expected_scheduler_plugin_stack",
    [
        ("scheduler-plugin-without-template.yaml", {}),
        (
            "scheduler-plugin-with-template.yaml",
            {
                "Type": "AWS::CloudFormation::Stack",
                "Properties": {
                    "TemplateURL": "https://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete.s3.fake-region.amazonaws."
                    "com/parallelcluster/clusters/dummy-cluster-randomstring123/templates/"
                    "scheduler-plugin-substack.cfn",
                    "Parameters": {
                        "ClusterName": "clustername",
                        "ParallelClusterStackId": {"Ref": "AWS::StackId"},
                        "VpcId": "vpc-123",
                        "HeadNodeRoleName": {"Ref": "RoleHeadNode"},
                        "ComputeFleetRoleNames": {"Ref": "Role15b342af42246b70"},
                        "LaunchTemplate1f8c19f38f8d4f7fVersion": {
                            "Fn::GetAtt": ["ComputeFleetLaunchTemplate1f8c19f38f8d4f7f3489FB83", "LatestVersionNumber"]
                        },
                        "LaunchTemplateA6f65dee6703df4aVersion": {
                            "Fn::GetAtt": ["ComputeFleetLaunchTemplateA6f65dee6703df4a27E3DD2A", "LatestVersionNumber"]
                        },
                    },
                },
            },
        ),
        (
            "scheduler-plugin-with-head-node-instance-role.yaml",
            {
                "Type": "AWS::CloudFormation::Stack",
                "Properties": {
                    "TemplateURL": "https://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete.s3.fake-region."
                    "amazonaws.com/parallelcluster/clusters/dummy-cluster-randomstring123/templates/"
                    "scheduler-plugin-substack.cfn",
                    "Parameters": {
                        "ClusterName": "clustername",
                        "ParallelClusterStackId": {"Ref": "AWS::StackId"},
                        "VpcId": "vpc-123",
                        "HeadNodeRoleName": "",
                        "ComputeFleetRoleNames": {"Ref": "Role15b342af42246b70"},
                        "LaunchTemplate1f8c19f38f8d4f7fVersion": {
                            "Fn::GetAtt": ["ComputeFleetLaunchTemplate1f8c19f38f8d4f7f3489FB83", "LatestVersionNumber"]
                        },
                        "LaunchTemplateA6f65dee6703df4aVersion": {
                            "Fn::GetAtt": ["ComputeFleetLaunchTemplateA6f65dee6703df4a27E3DD2A", "LatestVersionNumber"]
                        },
                    },
                },
            },
        ),
        (
            "scheduler-plugin-with-compute-fleet-instance-role.yaml",
            {
                "Type": "AWS::CloudFormation::Stack",
                "Properties": {
                    "TemplateURL": "https://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete.s3.fake-region.amazonaws."
                    "com/parallelcluster/clusters/dummy-cluster-randomstring123/templates/"
                    "scheduler-plugin-substack.cfn",
                    "Parameters": {
                        "ClusterName": "clustername",
                        "ParallelClusterStackId": {"Ref": "AWS::StackId"},
                        "VpcId": "vpc-123",
                        "HeadNodeRoleName": "",
                        "ComputeFleetRoleNames": "",
                        "LaunchTemplate1f8c19f38f8d4f7fVersion": {
                            "Fn::GetAtt": ["ComputeFleetLaunchTemplate1f8c19f38f8d4f7f3489FB83", "LatestVersionNumber"]
                        },
                        "LaunchTemplateA6f65dee6703df4aVersion": {
                            "Fn::GetAtt": ["ComputeFleetLaunchTemplateA6f65dee6703df4a27E3DD2A", "LatestVersionNumber"]
                        },
                        "LaunchTemplate7916067054f91933Version": {
                            "Fn::GetAtt": ["ComputeFleetLaunchTemplate7916067054f919332FB9590D", "LatestVersionNumber"]
                        },
                    },
                },
            },
        ),
        (
            "scheduler_plugin.full.yaml",
            {
                "Type": "AWS::CloudFormation::Stack",
                "Properties": {
                    "TemplateURL": "https://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete.s3.fake-region.amazonaws."
                    "com/parallelcluster/clusters/dummy-cluster-randomstring123/templates/"
                    "scheduler-plugin-substack.cfn",
                    "Parameters": {
                        "ClusterName": "clustername",
                        "ParallelClusterStackId": {"Ref": "AWS::StackId"},
                        "VpcId": "vpc-123",
                        "HeadNodeRoleName": "",
                        "ComputeFleetRoleNames": {"Ref": "Role15b342af42246b70"},
                        "LaunchTemplate1f8c19f38f8d4f7fVersion": {
                            "Fn::GetAtt": ["ComputeFleetLaunchTemplate1f8c19f38f8d4f7f3489FB83", "LatestVersionNumber"]
                        },
                        "LaunchTemplateA6f65dee6703df4aVersion": {
                            "Fn::GetAtt": ["ComputeFleetLaunchTemplateA6f65dee6703df4a27E3DD2A", "LatestVersionNumber"]
                        },
                        "LaunchTemplate7916067054f91933Version": {
                            "Fn::GetAtt": ["ComputeFleetLaunchTemplate7916067054f919332FB9590D", "LatestVersionNumber"]
                        },
                        "LaunchTemplateA46d18b906a50d3aVersion": {
                            "Fn::GetAtt": ["ComputeFleetLaunchTemplateA46d18b906a50d3a347605B0", "LatestVersionNumber"]
                        },
                    },
                },
            },
        ),
    ],
)
def test_scheduler_plugin_substack(mocker, config_file_name, expected_scheduler_plugin_stack, test_datadir):
    mock_aws_api(mocker)
    # mock bucket initialization parameters
    mock_bucket(mocker)
    if config_file_name == "scheduler_plugin.full.yaml":
        input_yaml, cluster = load_cluster_model_from_yaml(config_file_name)
    else:
        input_yaml, cluster = load_cluster_model_from_yaml(config_file_name, test_datadir)
    generated_template = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )
    print(yaml.dump(generated_template))
    assert_that(generated_template["Resources"].get("SchedulerPluginStack", {})).is_equal_to(
        expected_scheduler_plugin_stack
    )


def _mock_instance_type_info(instance_type):
    instance_types_info = {
        "c4.xlarge": InstanceTypeInfo(
            {
                "InstanceType": "c4.xlarge",
                "VCpuInfo": {
                    "DefaultVCpus": 4,
                    "DefaultCores": 2,
                    "DefaultThreadsPerCore": 2,
                    "ValidCores": [1, 2],
                    "ValidThreadsPerCore": [1, 2],
                },
                "EbsInfo": {"EbsOptimizedSupport": "default"},
                "NetworkInfo": {"EfaSupported": False, "MaximumNetworkCards": 3},
                "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
            }
        ),
        "t2.micro": InstanceTypeInfo(
            {
                "InstanceType": "t2.micro",
                "VCpuInfo": {
                    "DefaultVCpus": 4,
                    "DefaultCores": 2,
                    "DefaultThreadsPerCore": 2,
                    "ValidCores": [1, 2],
                    "ValidThreadsPerCore": [1, 2],
                },
                "EbsInfo": {"EbsOptimizedSupport": "unsupported"},
                "NetworkInfo": {"EfaSupported": False, "MaximumNetworkCards": 2},
                "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
            }
        ),
    }

    return instance_types_info[instance_type]


@pytest.mark.parametrize(
    "config_file_name, has_instance_type, no_of_network_interfaces, includes_ebs_optimized, is_ebs_optimized",
    [
        ("cluster-using-flexible-instance-types.yaml", False, 2, False, None),
        ("cluster-using-single-instance-type.yaml", True, 3, True, True),
    ],
)
def test_compute_launch_template_properties(
    mocker,
    config_file_name,
    has_instance_type,
    no_of_network_interfaces,
    includes_ebs_optimized,
    is_ebs_optimized,
    test_datadir,
):
    def get_launch_template_data_property(lt_property):
        return (
            generated_template["Resources"]
            .get("ComputeFleetLaunchTemplate64e1c3597ca4c32652225395", {})
            .get("Properties", {})
            .get("LaunchTemplateData", {})
            .get(lt_property, None)
        )

    mock_aws_api(mocker, mock_instance_type_info=False)

    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_instance_type_info",
        side_effect=_mock_instance_type_info,
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    input_yaml, cluster = load_cluster_model_from_yaml(config_file_name, test_datadir)
    generated_template = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    instance_type = get_launch_template_data_property("InstanceType")
    if has_instance_type:
        assert_that(instance_type).is_not_none()
    else:
        assert_that(instance_type).is_none()

    network_interfaces = get_launch_template_data_property("NetworkInterfaces")
    assert_that(network_interfaces).is_length(no_of_network_interfaces)

    ebs_optimized = get_launch_template_data_property("EbsOptimized")
    if includes_ebs_optimized:
        assert_that(ebs_optimized).is_equal_to(is_ebs_optimized)
    else:
        assert_that(ebs_optimized).is_none()


@pytest.mark.parametrize(
    "config_file_name, expected_head_node_dna_json_file_name",
    [
        ("slurm-imds-secured-true.yaml", "slurm-imds-secured-true.head-node.dna.json"),
        ("slurm-imds-secured-false.yaml", "slurm-imds-secured-false.head-node.dna.json"),
        ("awsbatch-imds-secured-false.yaml", "awsbatch-imds-secured-false.head-node.dna.json"),
        ("scheduler-plugin-imds-secured-true.yaml", "scheduler-plugin-imds-secured-true.head-node.dna.json"),
    ],
)
# Datetime mocking is required because some template values depend on the current datetime value
@freeze_time("2021-01-01T01:01:01")
def test_head_node_dna_json(mocker, test_datadir, config_file_name, expected_head_node_dna_json_file_name):
    mock_aws_api(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    generated_head_node_dna_json = json.loads(
        _get_cfn_init_file_content(template=generated_template, resource="HeadNodeLaunchTemplate", file="/tmp/dna.json")
    )
    expected_head_node_dna_json = load_json_dict(test_datadir / expected_head_node_dna_json_file_name)

    assert_that(generated_head_node_dna_json).is_equal_to(expected_head_node_dna_json)


@freeze_time("2021-01-01T01:01:01")
@pytest.mark.parametrize(
    "config_file_name, expected_head_node_bootstrap_timeout",
    [
        ("slurm.required.yaml", "1800"),
        ("slurm.full.yaml", "1201"),
        ("awsbatch.simple.yaml", "1800"),
        ("awsbatch.full.yaml", "1000"),
        ("scheduler_plugin.required.yaml", "1800"),
        ("scheduler_plugin.full.yaml", "1201"),
    ],
)
def test_head_node_bootstrap_timeout(mocker, config_file_name, expected_head_node_bootstrap_timeout):
    mock_aws_api(mocker)
    # mock bucket initialization parameters
    mock_bucket(mocker)
    input_yaml, cluster = load_cluster_model_from_yaml(config_file_name)
    generated_template = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )
    assert_that(
        generated_template["Resources"]
        .get("HeadNodeWaitCondition" + datetime.utcnow().strftime("%Y%m%d%H%M%S"))
        .get("Properties")
        .get("Timeout")
    ).is_equal_to(expected_head_node_bootstrap_timeout)


def _get_cfn_init_file_content(template, resource, file):
    cfn_init = template["Resources"][resource]["Metadata"]["AWS::CloudFormation::Init"]
    content_join = cfn_init["deployConfigFiles"]["files"][file]["content"]["Fn::Join"]
    content_separator = content_join[0]
    content_elements = content_join[1]
    return content_separator.join(str(elem) for elem in content_elements)


@freeze_time("2021-01-01T01:01:01")
@pytest.mark.parametrize(
    "config_file_name, expected_instance_tags, expected_volume_tags",
    [
        (
            "slurm.full.yaml",
            {},
            {
                "parallelcluster:cluster-name": "clustername",
                "parallelcluster:node-type": "HeadNode",
                # TODO The tag 'parallelcluster:version' is actually included within head node volume tags,
                #  but some refactoring is required to check it within this test.
                # "parallelcluster:version": "[0-9\\.A-Za-z]+",
                "String": "String",
                "two": "two22",
            },
        ),
        (
            "awsbatch.full.yaml",
            {},
            {
                "parallelcluster:cluster-name": "clustername",
                "parallelcluster:node-type": "HeadNode",
                # TODO The tag 'parallelcluster:version' is actually included within head node volume tags,
                #  but some refactoring is required to check it within this test.
                # "parallelcluster:version": "[0-9\\.A-Za-z]+",
                "String": "String",
                "two": "two22",
            },
        ),
        (
            "scheduler_plugin.full.yaml",
            {},
            {
                "parallelcluster:cluster-name": "clustername",
                "parallelcluster:node-type": "HeadNode",
                # TODO The tag 'parallelcluster:version' is actually included within head node volume tags,
                #  but some refactoring is required to check it within this test.
                # "parallelcluster:version": "[0-9\\.A-Za-z]+",
                "String": "String",
                "two": "two22",
            },
        ),
    ],
)
def test_head_node_tags_from_launch_template(mocker, config_file_name, expected_instance_tags, expected_volume_tags):
    mock_aws_api(mocker)
    mock_bucket(mocker)
    input_yaml, cluster = load_cluster_model_from_yaml(config_file_name)
    generated_template = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )
    tags_specifications = (
        generated_template.get("Resources")
        .get("HeadNodeLaunchTemplate")
        .get("Properties")
        .get("LaunchTemplateData")
        .get("TagSpecifications", [])
    )

    instance_tags = next((specs for specs in tags_specifications if specs["ResourceType"] == "instance"), {}).get(
        "Tags", []
    )
    actual_instance_tags = {tag["Key"]: tag["Value"] for tag in instance_tags}
    assert_that(actual_instance_tags).is_equal_to(expected_instance_tags)

    volume_tags = next((specs for specs in tags_specifications if specs["ResourceType"] == "volume"), {}).get(
        "Tags", []
    )
    actual_volume_tags = {tag["Key"]: tag["Value"] for tag in volume_tags}
    assert_that(actual_volume_tags).is_equal_to(expected_volume_tags)


@freeze_time("2021-01-01T01:01:01")
@pytest.mark.parametrize(
    "config_file_name, expected_tags",
    [
        (
            "slurm.full.yaml",
            {
                "Name": "HeadNode",
                "parallelcluster:cluster-name": "clustername",
                "parallelcluster:node-type": "HeadNode",
                "parallelcluster:attributes": "centos7, slurm, [0-9\\.A-Za-z]+, x86_64",
                "parallelcluster:filesystem": "efs=1, multiebs=1, raid=0, fsx=3",
                "parallelcluster:networking": "EFA=NONE",
                # TODO The tag 'parallelcluster:version' is actually included within head node volume tags,
                #  but some refactoring is required to check it within this test.
                # "parallelcluster:version": "[0-9\\.A-Za-z]+",
                "String": "String",
                "two": "two22",
            },
        ),
        (
            "awsbatch.full.yaml",
            {
                "Name": "HeadNode",
                "parallelcluster:cluster-name": "clustername",
                "parallelcluster:node-type": "HeadNode",
                "parallelcluster:attributes": "alinux2, awsbatch, [0-9\\.A-Za-z]+, x86_64",
                "parallelcluster:filesystem": "efs=1, multiebs=0, raid=2, fsx=0",
                "parallelcluster:networking": "EFA=NONE",
                # TODO The tag 'parallelcluster:version' is actually included within head node volume tags,
                #  but some refactoring is required to check it within this test.
                # "parallelcluster:version": "[0-9\\.A-Za-z]+",
                "String": "String",
                "two": "two22",
            },
        ),
        (
            "scheduler_plugin.full.yaml",
            {
                "Name": "HeadNode",
                "parallelcluster:cluster-name": "clustername",
                "parallelcluster:node-type": "HeadNode",
                "parallelcluster:attributes": "centos7, plugin, [0-9\\.A-Za-z]+, x86_64",
                "parallelcluster:filesystem": "efs=1, multiebs=1, raid=0, fsx=1",
                "parallelcluster:networking": "EFA=NONE",
                # TODO The tag 'parallelcluster:version' is actually included within head node volume tags,
                #  but some refactoring is required to check it within this test.
                # "parallelcluster:version": "[0-9\\.A-Za-z]+",
                "String": "String",
                "two": "two22",
            },
        ),
    ],
)
def test_head_node_tags_from_instance_definition(mocker, config_file_name, expected_tags):
    mock_aws_api(mocker)
    mock_bucket(mocker)
    input_yaml, cluster = load_cluster_model_from_yaml(config_file_name)
    generated_template = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )
    tags = generated_template.get("Resources").get("HeadNode").get("Properties").get("Tags", [])

    actual_tags = {tag["Key"]: tag["Value"] for tag in tags}
    assert_that(actual_tags.keys()).is_equal_to(expected_tags.keys())
    for key in actual_tags.keys():
        assert_that(actual_tags[key]).matches(expected_tags[key])
