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
        ("raid_type", None, None, None),
        ("num_of_raid_volumes", None, 2, None),
        ("volume_type", None, "gp2", None),
        ("volume_size", None, 20, None),
    ],
)
def test_raid_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, RAID, param_key, param_value, expected_value, expected_message)
