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
import pytest

import tests.pcluster.config.utils as utils
from pcluster.config.mappings import COMPUTE_RESOURCE


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        ("instance_type", None, None, None),
        ("instance_type", "t2.micro", "t2.micro", None),
        ("enable_efa", "invalid", None, "must be of 'bool' type"),
        ("enable_efa", "true", True, None),
        ("gpus", "invalid", None, "must be of 'int' type"),
        ("gpus", "2", 2, None),
        ("spot_price", "invalid", None, "must be of 'float' type"),
        ("spot_price", "0.5", 0.5, None),
    ],
)
def test_compute_resource_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, COMPUTE_RESOURCE, param_key, param_value, expected_value, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_config_parser_dict, expected_message",
    [
        # default
        ({}, {"compute_resource default": {}}, None),
        # default values
        ({"instance_type": "t2.micro"}, {"compute_resource default": {"instance_type": "t2.micro"}}, None),
        # other values
        # Private params must not be written in file
        ({"gpus": "8"}, {"compute_resource default": {"gpus": "8"}}, "No section.*"),
        ({"enable_efa": True}, {"compute_resource default": {"enable_efa": True}}, "No section.*"),
    ],
)
def test_compute_resource_section_to_file(mocker, section_dict, expected_config_parser_dict, expected_message):
    utils.assert_section_to_file(mocker, COMPUTE_RESOURCE, section_dict, expected_config_parser_dict, expected_message)
