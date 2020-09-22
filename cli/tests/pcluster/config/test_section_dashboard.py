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
from pcluster.config.mappings import DASHBOARD


@pytest.mark.parametrize(
    "config_parser_dict, expected_dict_params, expected_message",
    [
        # default
        ({"dashboard default": {}}, {}, None),
        # right value
        ({"dashboard default": {"enable": "True"}}, {}, None),
        ({"dashboard default": {"enable": "False"}}, {"enable": False}, None),
        # invalid value
        ({"dashboard default": {"enable": "not_a_bool"}}, None, "'enable' must be of 'bool' type"),
        # invalid key
        ({"dashboard default": {"invalid_key": "fake_value"}}, None, "'invalid_key' is not allowed in the .* section"),
        (
            {"dashboard default": {"invalid_key": "fake_value", "invalid_key2": "fake_value"}},
            None,
            "'invalid_key.*,invalid_key.*' are not allowed in the .* section",
        ),
    ],
)
def test_dashboard_section_from_file(mocker, config_parser_dict, expected_dict_params, expected_message):
    """Verify that dashboard behaves as expected when parsed in a config file."""
    utils.assert_section_from_file(mocker, DASHBOARD, config_parser_dict, expected_dict_params, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_config_parser_dict, expected_message",
    [
        # default values are not written back to config files
        ({}, {"dashboard default": {}}, "No section.*"),
        ({"enable": True}, {"dashboard default": {"enable": True}}, "No section: 'dashboard default'"),
        # Non-default values are written back to config files
        ({"enable": False}, {"dashboard default": {"enable": "false"}}, None),
    ],
)
def test_dashboard_settings_section_to_file(mocker, section_dict, expected_config_parser_dict, expected_message):
    """Verify that the dashboard_settings section is as expected when writing back to a file."""
    utils.assert_section_to_file(mocker, DASHBOARD, section_dict, expected_config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        # Enable parameter
        ("enable", None, True, None),
        ("enable", "true", True, None),
        ("enable", "false", False, None),
        ("enable", "not_a_bool", None, "'enable' must be of 'bool' type"),
        ("enable", "", None, "'enable' must be of 'bool' type"),
    ],
)
def test_dashboard_settings_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    """Verify that the cw_log_settings config file section results in the correct CFN parameters."""
    utils.assert_param_from_file(mocker, DASHBOARD, param_key, param_value, expected_value, expected_message)
