# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from pcluster.config.mappings import SCALING
from tests.pcluster.config.defaults import DefaultCfnParams, DefaultDict


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict",
    [
        (DefaultCfnParams["scaling"].value, DefaultDict["scaling"].value),
        ({}, DefaultDict["scaling"].value),
        ({"ScaleDownIdleTime": "NONE"}, DefaultDict["scaling"].value),
        ({"ScaleDownIdleTime": "20"}, {"scaledown_idletime": 20}),
    ],
)
def test_scaling_section_from_cfn(mocker, cfn_params_dict, expected_section_dict):
    utils.assert_section_from_cfn(mocker, SCALING, cfn_params_dict, expected_section_dict)


@pytest.mark.parametrize(
    "config_parser_dict, expected_dict_params, expected_message",
    [
        # default
        ({"scaling default": {}}, {}, None),
        # right value
        ({"scaling default": {"scaledown_idletime": "3"}}, {"scaledown_idletime": 3}, None),
        # invalid value
        ({"scaling default": {"scaledown_idletime": "wrong_value"}}, None, "must be an Integer"),
        # invalid key
        ({"scaling default": {"invalid_key": "fake_value"}}, None, "'invalid_key' is not allowed in the .* section"),
    ],
)
def test_scaling_section_from_file(mocker, config_parser_dict, expected_dict_params, expected_message):
    utils.assert_section_from_file(mocker, SCALING, config_parser_dict, expected_dict_params, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_config_parser_dict, expected_message",
    [
        # default
        ({}, {"scaling default": {}}, None),
        # default values
        ({"scaledown_idletime": 10}, {"scaling default": {"scaledown_idletime": "10"}}, "No section.*"),
        # other values
        ({"scaledown_idletime": 11}, {"scaling default": {"scaledown_idletime": "11"}}, None),
    ],
)
def test_scaling_section_to_file(mocker, section_dict, expected_config_parser_dict, expected_message):
    utils.assert_section_to_file(mocker, SCALING, section_dict, expected_config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_cfn_params",
    [
        (DefaultDict["scaling"].value, DefaultCfnParams["scaling"].value),
        ({"scaledown_idletime": 20}, {"ScaleDownIdleTime": "20"}),
    ],
)
def test_scaling_section_to_cfn(mocker, section_dict, expected_cfn_params):
    utils.assert_section_to_cfn(mocker, SCALING, section_dict, expected_cfn_params)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        ("scaledown_idletime", None, 10, None),
        ("scaledown_idletime", "", "", "must be an Integer"),
        ("scaledown_idletime", "NONE", None, "must be an Integer"),
        ("scaledown_idletime", "wrong_value", None, "must be an Integer"),
        ("scaledown_idletime", "10", 10, None),
        ("scaledown_idletime", "3", 3, None),
    ],
)
def test_scaling_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, SCALING, param_key, param_value, expected_value, expected_message)
