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
from pcluster.config.mappings import RAID
from tests.pcluster.config.defaults import DefaultCfnParams, DefaultDict


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict",
    [
        (DefaultCfnParams["raid"].value, DefaultDict["raid"].value),
        ({}, DefaultDict["raid"].value),
        ({"RAIDOptions": "NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE"}, DefaultDict["raid"].value),
        ({"RAIDOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE"}, DefaultDict["raid"].value),
        (
            {"RAIDOptions": "test,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE"},
            {
                "shared_dir": "test",
                "raid_type": None,
                "num_of_raid_volumes": 2,
                "volume_type": "gp2",
                "volume_size": 20,
                "volume_iops": None,
                "encrypted": False,
                "ebs_kms_key_id": None,
                "volume_throughput": 125,
            },
        ),
        (
            {"RAIDOptions": "test,0,3,gp2,30,200,true,test"},
            {
                "shared_dir": "test",
                "raid_type": 0,
                "num_of_raid_volumes": 3,
                "volume_type": "gp2",
                "volume_size": 30,
                "volume_iops": 200,
                "encrypted": True,
                "ebs_kms_key_id": "test",
            },
        ),
    ],
)
def test_raid_section_from_cfn(mocker, cfn_params_dict, expected_section_dict):
    utils.assert_section_from_cfn(mocker, RAID, cfn_params_dict, expected_section_dict)


@pytest.mark.parametrize(
    "config_parser_dict, expected_dict_params, expected_message",
    [
        # default
        ({"raid default": {}}, {}, None),
        # right value
        ({"raid default": {"raid_type": 1}}, {"raid_type": 1}, None),
        ({"raid default": {"volume_type": "gp2"}}, {"volume_type": "gp2"}, None),
        # invalid value
        ({"raid default": {"raid_type": "wrong_value"}}, None, "must be an Integer"),
        ({"raid default": {"volume_type": "wrong_value"}}, None, "invalid value"),
        # invalid key
        ({"raid default": {"invalid_key": "fake_value"}}, None, "'invalid_key' is not allowed in the .* section"),
    ],
)
def test_raid_section_from_file(mocker, config_parser_dict, expected_dict_params, expected_message):
    utils.assert_section_from_file(mocker, RAID, config_parser_dict, expected_dict_params, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_config_parser_dict, expected_message",
    [
        # default
        ({}, {"raid default": {}}, None),
        # default values
        ({"volume_throughput": 125}, {"raid default": {"volume_throughput": "125"}}, "No section.*"),
        ({"encrypted": False}, {"raid default": {"encrypted": "false"}}, "No section.*"),
        # other values
        ({"volume_iops": 120}, {"raid default": {"volume_iops": "120"}}, None),
        ({"encrypted": True}, {"raid default": {"encrypted": "true"}}, None),
    ],
)
def test_raid_section_to_file(mocker, section_dict, expected_config_parser_dict, expected_message):
    utils.assert_section_to_file(mocker, RAID, section_dict, expected_config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_cfn_params", [(DefaultDict["raid"].value, DefaultCfnParams["raid"].value)]
)
def test_raid_section_to_cfn(mocker, section_dict, expected_cfn_params):
    utils.assert_section_to_cfn(mocker, RAID, section_dict, expected_cfn_params)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        ("shared_dir", None, None, None),
        ("shared_dir", "", None, "Allowed values are"),
        ("shared_dir", "fake_value", "fake_value", None),
        ("shared_dir", "/test", "/test", None),
        ("shared_dir", "/test/test2", "/test/test2", None),
        ("shared_dir", "/t_ 1-2( ):&;<>t?*+|", "/t_ 1-2( ):&;<>t?*+|", None),
        ("shared_dir", "//test", None, "has an invalid value"),
        ("shared_dir", "./test", None, "has an invalid value"),
        ("shared_dir", "\\test", None, "has an invalid value"),
        ("shared_dir", ".test", None, "has an invalid value"),
        ("shared_dir", "/test/.test2", None, "has an invalid value"),
        ("shared_dir", "/test/.test2/test3", None, "has an invalid value"),
        ("shared_dir", "/test//test2", None, "has an invalid value"),
        ("shared_dir", "/test\\test2", None, "has an invalid value"),
        ("shared_dir", "NONE", "NONE", None),  # NONE is evaluated as a valid path
        ("raid_type", None, None, None),
        ("raid_type", "", None, "must be an Integer"),
        ("raid_type", "NONE", None, "must be an Integer"),
        ("raid_type", "wrong_value", None, "must be an Integer"),
        ("raid_type", "10", None, "invalid value"),
        ("raid_type", "3", None, "invalid value"),
        ("raid_type", "0", 0, None),
        ("raid_type", "1", 1, None),
        ("num_of_raid_volumes", None, 2, None),
        ("num_of_raid_volumes", "", None, "must be an Integer"),
        ("num_of_raid_volumes", "NONE", None, "must be an Integer"),
        ("num_of_raid_volumes", "wrong_value", None, "must be an Integer"),
        ("num_of_raid_volumes", "0", None, "invalid value"),
        ("num_of_raid_volumes", "1", None, "invalid value"),
        ("num_of_raid_volumes", "6", None, "invalid value"),
        ("num_of_raid_volumes", "5", 5, None),
        ("num_of_raid_volumes", "2", 2, None),
        ("volume_type", None, "gp2", None),
        ("volume_type", "", None, "Allowed values are"),
        ("volume_type", "wrong_value", None, "Allowed values are"),
        ("volume_type", "io1", "io1", None),
        ("volume_type", "standard", "standard", None),
        ("volume_type", "NONE", None, "Allowed values are"),
        ("volume_size", None, 20, None),
        ("volume_size", "", None, "must be an Integer"),
        ("volume_size", "NONE", None, "must be an Integer"),
        ("volume_size", "wrong_value", None, "must be an Integer"),
        ("volume_size", "10", 10, None),
        ("volume_size", "3", 3, None),
        ("volume_iops", None, None, None),
        ("volume_iops", "", None, "must be an Integer"),
        ("volume_iops", "NONE", None, "must be an Integer"),
        ("volume_iops", "wrong_value", None, "must be an Integer"),
        ("volume_iops", "10", 10, None),
        ("volume_iops", "3", 3, None),
        ("encrypted", None, False, None),
        ("encrypted", "", None, "must be a Boolean"),
        ("encrypted", "NONE", None, "must be a Boolean"),
        ("encrypted", "true", True, None),
        ("encrypted", "false", False, None),
        ("ebs_kms_key_id", None, None, None),
        ("ebs_kms_key_id", "", "", None),
        ("ebs_kms_key_id", "fake_value", "fake_value", None),
        ("ebs_kms_key_id", "test", "test", None),
        ("ebs_kms_key_id", "NONE", "NONE", None),  # NONE is evaluated as a valid kms id
        ("volume_throughput", "NONE", None, "must be an Integer"),
        ("volume_throughput", "wrong_value", None, "must be an Integer"),
        ("volume_throughput", "150", 150, None),
    ],
)
def test_raid_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, RAID, param_key, param_value, expected_value, expected_message)
