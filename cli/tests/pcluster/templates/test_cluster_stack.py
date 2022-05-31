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
