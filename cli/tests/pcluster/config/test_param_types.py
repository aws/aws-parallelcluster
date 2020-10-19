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

import tests.pcluster.config.utils as utils
from pcluster.config.cfn_param_types import CfnParam, CfnSection, VolumeSizeParam
from pcluster.config.mappings import EBS
from pcluster.config.param_types import Param


class TestParam:
    @pytest.mark.parametrize(
        "section_label, should_trigger_error",
        [
            ("LongSectionNameJust1CharTooLong", True),
            ("Longest-Possible_Section-Name1", False),
            ("1BeginWithNumber", True),
            ("_BeginsWithUnderscore", True),
            ("Contains spaces", True),
        ],
    )
    def test_validate_section_label(self, section_label, should_trigger_error, mocker, caplog):
        error_msg = (
            "Failed validation for section queue {0}. Section names can be at most 30 chars long,"
            " must begin with a letter and only contain alphanumeric characters, hyphens and underscores."
        ).format(section_label)
        mocker.patch.object(Param, "__abstractmethods__", new_callable=set)
        param = Param("queue", section_label, None, {}, None, None)
        if should_trigger_error:
            with pytest.raises(SystemExit):
                param._validate_section_label()
            assert_that(caplog.text).contains(error_msg)
        else:
            param._validate_section_label()
            for record in caplog.records:
                assert record.levelname != "ERROR"


@pytest.mark.parametrize(
    "section_dict, expected_value",
    [
        ({"volume_size": 100, "ebs_snapshot_id": "snap-1234567890abcdef0"}, 100),
        ({"ebs_snapshot_id": "snap-1234567890abcdef0"}, 50),
        ({"volume_size": 100}, 100),
        ({"volume_size": 0}, 0),
        ({"volume_size": -5}, -5),
        ({}, 20),
    ],
)
def test_volume_size_refresh(mocker, section_dict, expected_value):
    mocked_pcluster_config = utils.get_mocked_pcluster_config(mocker)
    ebs_section = CfnSection(EBS, mocked_pcluster_config, "default")
    for param_key, param_value in section_dict.items():
        param = EBS.get("params").get(param_key).get("type", CfnParam)
        param.value = param_value
        ebs_section.set_param(param_key, param)
    mocked_pcluster_config.add_section(ebs_section)
    config_parser = configparser.ConfigParser()
    config_parser_dict = {"cluster default": {"ebs_settings": "default"}, "ebs default": section_dict}
    config_parser.read_dict(config_parser_dict)

    volume_size = VolumeSizeParam(
        section_key="ebs",
        section_label="default",
        param_key="volume_size",
        param_definition=EBS.get("params").get("volume_size"),
        pcluster_config=mocked_pcluster_config,
        owner_section=ebs_section,
    ).from_file(config_parser)

    describe_snapshots_response = {
        "Description": "This is my snapshot",
        "Encrypted": False,
        "VolumeId": "vol-049df61146c4d7901",
        "State": "completed",
        "VolumeSize": 50,
        "StartTime": "2014-02-28T21:28:32.000Z",
        "Progress": "100%",
        "OwnerId": "012345678910",
        "SnapshotId": "snap-1234567890abcdef0",
    }

    mocker.patch("pcluster.config.cfn_param_types.get_ebs_snapshot_info", return_value=describe_snapshots_response)

    volume_size.refresh()
    assert_that(volume_size.value).is_equal_to(expected_value)
