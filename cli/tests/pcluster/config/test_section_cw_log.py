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
from pcluster.config.mappings import CW_LOG
from tests.pcluster.config.defaults import DefaultCfnParams, DefaultDict


@pytest.mark.parametrize(
    "config_parser_dict, expected_dict_params, expected_message",
    [
        # default
        ({"cw_log default": {}}, {}, None),
        # right value
        ({"cw_log default": {"enable": "True"}}, {}, None),
        ({"cw_log default": {"enable": "False"}}, {"enable": False}, None),
        # invalid value
        ({"cw_log default": {"enable": "not_a_bool"}}, None, "must be a Boolean"),
        # invalid key
        ({"cw_log default": {"invalid_key": "fake_value"}}, None, "'invalid_key' is not allowed in the .* section"),
        (
            {"cw_log default": {"invalid_key": "fake_value", "invalid_key2": "fake_value"}},
            None,
            "'invalid_key.*,invalid_key.*' are not allowed in the .* section",
        ),
    ],
)
def test_cw_log_section_from_file(mocker, config_parser_dict, expected_dict_params, expected_message):
    """Verify that cw_log behaves as expected when parsed in a config file."""
    utils.assert_section_from_file(mocker, CW_LOG, config_parser_dict, expected_dict_params, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_config_parser_dict, expected_message",
    [
        # default values are not written back to config files
        ({}, {"cw_log default": {}}, "No section.*"),
        ({"enable": True, "retention_days": 14}, {"cw_log default": {"enable": True}}, "No section: 'cw_log default'"),
        ({"enable": True, "retention_days": 1}, {"cw_log default": {"enable": True}}, "No option 'enable'"),
        (
            {"enable": False, "retention_days": 14},
            {"cw_log default": {"retention_days": 14}},
            "No option 'retention_days'",
        ),
        # Non-default values are written back to config files
        ({"enable": False, "retention_days": 14}, {"cw_log default": {"enable": "false"}}, None),
        ({"enable": True, "retention_days": 1}, {"cw_log default": {"retention_days": "1"}}, None),
    ],
)
def test_cw_log_settings_section_to_file(mocker, section_dict, expected_config_parser_dict, expected_message):
    """Verify that the cw_log_settings section is as expected when writing back to a file."""
    utils.assert_section_to_file(mocker, CW_LOG, section_dict, expected_config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        # Enable parameter
        ("enable", None, True, None),
        ("enable", "true", True, None),
        ("enable", "false", False, None),
        ("enable", "not_a_bool", None, "'enable' must be a Boolean"),
        ("enable", "", None, "'enable' must be a Boolean"),
    ],
)
def test_cw_log_settings_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    """Verify that the cw_log_settings config file section results in the correct CFN parameters."""
    utils.assert_param_from_file(mocker, CW_LOG, param_key, param_value, expected_value, expected_message)


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict",
    [
        # Defaults in various forms
        (DefaultCfnParams["cw_log"].value, DefaultDict["cw_log"].value),
        ({}, DefaultDict["cw_log"].value),
        ({"CWLogOptions": "   true  ,   14     "}, DefaultDict["cw_log"].value),
        ({"CWLogOptions": "true,14"}, DefaultDict["cw_log"].value),
        # Non-default values
        ({"CWLogOptions": "false,14"}, {"enable": False, "retention_days": 14}),
        ({"CWLogOptions": "true,3"}, {"enable": True, "retention_days": 3}),
    ],
)
def test_cw_log_settings_section_from_cfn(mocker, cfn_params_dict, expected_section_dict):
    """Verify expected cw_log_settings config file section results from given CFN params."""
    utils.assert_section_from_cfn(mocker, CW_LOG, cfn_params_dict, expected_section_dict)
