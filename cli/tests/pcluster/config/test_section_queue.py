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
from pcluster.config.mappings import QUEUE


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        ("compute_type", "ondemand", "ondemand", None),
        ("compute_type", "spot", "spot", None),
        ("compute_type", "invalid", None, "has an invalid value"),
        ("enable_efa", "invalid", None, "must be of 'bool' type"),
        ("enable_efa", "True", True, None),
        ("enable_efa", "False", False, None),
        ("disable_hyperthreading", "invalid", None, "must be of 'bool' type"),
        ("disable_hyperthreading", "True", True, None),
        ("disable_hyperthreading", "False", False, None),
        ("placement_group", "DYNAMIC", "DYNAMIC", None),
    ],
)
def test_queue_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, QUEUE, param_key, param_value, expected_value, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_config_parser_dict, expected_message",
    [
        # default
        ({}, {"queue default": {}}, None),
        # default values
        ({"compute_type": "ondemand"}, {"queue default": {"compute_type": "ondemand"}}, "No section"),
        # other values
        ({"compute_type": "spot"}, {"queue default": {"compute_type": "spot"}}, None),
    ],
)
def test_queue_section_to_file(mocker, section_dict, expected_config_parser_dict, expected_message):
    utils.assert_section_to_file(mocker, QUEUE, section_dict, expected_config_parser_dict, expected_message)
