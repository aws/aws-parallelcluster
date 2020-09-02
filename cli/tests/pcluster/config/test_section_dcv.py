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
from pcluster.config.mappings import DCV
from tests.pcluster.config.defaults import DefaultCfnParams, DefaultDict


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict",
    [
        (DefaultCfnParams["dcv"].value, DefaultDict["dcv"].value),
        ({}, DefaultDict["dcv"].value),
        ({"DCVOptions": "NONE, NONE, NONE"}, DefaultDict["dcv"].value),
        ({"DCVOptions": "NONE,NONE,NONE"}, DefaultDict["dcv"].value),
        (
            {"DCVOptions": "master,8555,10.10.10.10/10"},
            {"enable": "master", "port": 8555, "access_from": "10.10.10.10/10"},
        ),
        ({"DCVOptions": "master,NONE,NONE"}, {"enable": "master", "port": 8443, "access_from": "0.0.0.0/0"}),
    ],
)
def test_dcv_section_from_cfn(mocker, cfn_params_dict, expected_section_dict):
    utils.assert_section_from_cfn(mocker, DCV, cfn_params_dict, expected_section_dict)


@pytest.mark.parametrize(
    "config_parser_dict, expected_dict_params, expected_message",
    [
        # default
        ({"dcv default": {}}, {}, None),
        # right value
        ({"dcv default": {"enable": "master"}}, {"enable": "master"}, None),
        # invalid value
        ({"dcv default": {"enable": "wrong_value"}}, None, "has an invalid value"),
        ({"dcv default": {"port": "wrong_value"}}, None, "must be an Integer"),
        ({"dcv default": {"access_from": "wrong_value"}}, None, "has an invalid value"),
        # invalid key
        ({"dcv default": {"invalid_key": "fake_value"}}, None, "'invalid_key' is not allowed in the .* section"),
    ],
)
def test_dcv_section_from_file(mocker, config_parser_dict, expected_dict_params, expected_message):
    utils.assert_section_from_file(mocker, DCV, config_parser_dict, expected_dict_params, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_config_parser_dict, expected_message",
    [
        # default
        ({}, {"dcv default": {}}, None),
        # other values
        ({"port": 10}, {"dcv default": {"port": "10"}}, None),
        ({"access_from": "10.0.0.0/10"}, {"dcv default": {"access_from": "10.0.0.0/10"}}, None),
    ],
)
def test_dcv_section_to_file(mocker, section_dict, expected_config_parser_dict, expected_message):
    utils.assert_section_to_file(mocker, DCV, section_dict, expected_config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_cfn_params", [(DefaultDict["dcv"].value, DefaultCfnParams["dcv"].value)]
)
def test_dcv_section_to_cfn(mocker, section_dict, expected_cfn_params):
    utils.assert_section_to_cfn(mocker, DCV, section_dict, expected_cfn_params)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        ("enable", None, None, None),
        ("enable", "", None, "has an invalid value"),
        ("enable", "wrong_value", None, "has an invalid value"),
        ("enable", "NONE", None, "has an invalid value"),
        ("enable", "master", "master", None),
        ("port", None, 8443, None),
        ("port", "", None, "must be an Integer"),
        ("port", "NONE", None, "must be an Integer"),
        ("port", "wrong_value", None, "must be an Integer"),
        ("port", "1", 1, None),
        ("port", "20", 20, None),
        ("access_from", None, "0.0.0.0/0", None),
        ("access_from", "", None, "Allowed values are"),
        ("access_from", "wrong_value", None, "Allowed values are"),
        ("access_from", "111.111.111.111", None, "Allowed values are"),
        ("access_from", "111.111.111.111/222", None, "Allowed values are"),
        ("access_from", "NONE", None, "Allowed values are"),
        ("access_from", "0.0.0.0/0", "0.0.0.0/0", None),
        ("access_from", "1.1.1.1/0", "1.1.1.1/0", None),
        ("access_from", "1.1.1.1/8", "1.1.1.1/8", None),
        ("access_from", "1.1.1.1/15", "1.1.1.1/15", None),
        ("access_from", "1.1.1.1/32", "1.1.1.1/32", None),
        ("access_from", "1.1.1.1/33", None, "Allowed values are"),
        ("access_from", "11.11.11.11/32", "11.11.11.11/32", None),
        ("access_from", "111.111.111.111/22", "111.111.111.111/22", None),
        ("access_from", "255.255.255.255/32", "255.255.255.255/32", None),
        ("access_from", "255.255.255.256/32", None, "Allowed values are"),
    ],
)
def test_dcv_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, DCV, param_key, param_value, expected_value, expected_message)


@pytest.mark.parametrize(
    "settings_label, expected_cfn_params",
    [
        ("test1", SystemExit()),
        ("test2", utils.merge_dicts(DefaultCfnParams["cluster_sit"].value, {"DCVOptions": "master,8443,0.0.0.0/0"})),
        ("test3", utils.merge_dicts(DefaultCfnParams["cluster_sit"].value, {"DCVOptions": "master,8555,10.0.0.0/0"})),
        ("test1,test2", SystemExit()),
        ("test4", SystemExit()),
        ("test5", SystemExit()),
        ("test6", SystemExit()),
    ],
)
def test_dcv_from_file_to_cfn(mocker, pcluster_config_reader, settings_label, expected_cfn_params):
    """Unit tests for parsing EFS related options."""
    mocker.patch("pcluster.config.cfn_param_types.get_efs_mount_target_id", return_value="mount_target_id")
    mocker.patch("pcluster.config.cfn_param_types.get_availability_zone_of_subnet", return_value="mocked_avail_zone")
    utils.assert_section_params(mocker, pcluster_config_reader, settings_label, expected_cfn_params)
