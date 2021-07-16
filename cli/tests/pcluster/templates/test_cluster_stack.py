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

import pytest
import yaml
from assertpy import assert_that
from freezegun import freeze_time

from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import load_json_dict, load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.config.dummy_cluster_config import dummy_awsbatch_cluster_config, dummy_slurm_cluster_config
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket


def test_slurm_cluster_builder(mocker):
    mock_aws_api(mocker)
    # mock bucket initialization parameters
    mock_bucket(mocker)

    generated_template = CDKTemplateBuilder().build_cluster_template(
        cluster_config=dummy_slurm_cluster_config(mocker), bucket=dummy_cluster_bucket(), stack_name="clustername"
    )
    print(yaml.dump(generated_template))
    # TODO assert content of the template by matching expected template


def test_awsbatch_cluster_builder(mocker):
    mock_aws_api(mocker)
    # mock bucket initialization parameters
    mock_bucket(mocker)

    generated_template = CDKTemplateBuilder().build_cluster_template(
        cluster_config=dummy_awsbatch_cluster_config(mocker), bucket=dummy_cluster_bucket(), stack_name="clustername"
    )
    print(yaml.dump(generated_template))
    # TODO assert content of the template by matching expected template


@pytest.mark.parametrize(
    "config_file_name, expected_head_node_dna_json_file_name",
    [
        ("slurm-imds-secured-true.yaml", "slurm-imds-secured-true.head-node.dna.json"),
        ("slurm-imds-secured-false.yaml", "slurm-imds-secured-false.head-node.dna.json"),
        ("awsbatch-imds-secured-false.yaml", "awsbatch-imds-secured-false.head-node.dna.json"),
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


def _get_cfn_init_file_content(template, resource, file):
    cfn_init = template["Resources"][resource]["Metadata"]["AWS::CloudFormation::Init"]
    content_join = cfn_init["deployConfigFiles"]["files"][file]["content"]["Fn::Join"]
    content_separator = content_join[0]
    content_elements = content_join[1]
    return content_separator.join(str(elem) for elem in content_elements)
