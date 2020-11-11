# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import configparser
import pytest
from assertpy import assert_that

from pcluster.cluster_model import ClusterModel, infer_cluster_model


@pytest.mark.parametrize(
    "config_parser_cluster_dict, cfn_stack, expected_cluster_model",
    [
        # queue_settings present in config
        ({"queue_settings": "queue1, queue2"}, None, ClusterModel.HIT),
        # no queue_settings in config and no cfn params
        ({}, None, ClusterModel.SIT),
        # no queue_settings in config and slurm scheduler in cfn params
        (
            {},
            {
                "Parameters": [{"ParameterKey": "Scheduler", "ParameterValue": "slurm"}],
                "Tags": [{"Key": "Version", "Value": "2.10.0"}],
            },
            ClusterModel.HIT,
        ),
        (
            {},
            {
                "Parameters": [{"ParameterKey": "Scheduler", "ParameterValue": "slurm"}],
                "Tags": [{"Key": "Version", "Value": "2.9.0"}],
            },
            ClusterModel.HIT,
        ),
        # slurm scheduler in cfn params but SIT version
        (
            {},
            {
                "Parameters": [{"ParameterKey": "Scheduler", "ParameterValue": "slurm"}],
                "Tags": [{"Key": "Version", "Value": "2.8.91"}],
            },
            ClusterModel.SIT,
        ),
        # no queue_settings in config and no slurm scheduler in cfn params
        (
            {},
            {
                "Parameters": [{"ParameterKey": "Scheduler", "ParameterValue": "sge"}],
                "Tags": [{"Key": "Version", "Value": "2.8.91"}],
            },
            ClusterModel.SIT,
        ),
        (
            {},
            {
                "Parameters": [{"ParameterKey": "Scheduler", "ParameterValue": "torque"}],
                "Tags": [{"Key": "Version", "Value": "2.10.0"}],
            },
            ClusterModel.SIT,
        ),
    ],
)
def test_cluster_model(config_parser_cluster_dict, cfn_stack, expected_cluster_model):
    config_parser_dict = {"cluster default": config_parser_cluster_dict}

    config_parser = configparser.ConfigParser()
    config_parser.read_dict(config_parser_dict)

    cluster_model = infer_cluster_model(config_parser, "default", cfn_stack)
    assert_that(cluster_model).is_equal_to(expected_cluster_model)
