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
from pcluster.config.mappings import EBS
from tests.pcluster.config.defaults import DefaultDict


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict",
    [
        ({}, DefaultDict["ebs"].value),
        (
            {
                "SharedDir": "NONE",
                "EBSSnapshotId": "NONE",
                "VolumeType": "NONE",
                "VolumeSize": "NONE",
                "VolumeIOPS": "NONE",
                "EBSEncryption": "NONE",
                "EBSKMSKeyId": "NONE",
                "EBSVolumeId": "NONE",
            },
            DefaultDict["ebs"].value,
        ),
        (
            {
                "SharedDir": "/shareddir",
                "EBSSnapshotId": "snap-id",
                "VolumeType": "io1",
                "VolumeSize": "30",
                "VolumeIOPS": "200",
                "EBSEncryption": "true",
                "EBSKMSKeyId": "kms-key",
                "EBSVolumeId": "ebs-id",
            },
            {
                "shared_dir": "/shareddir",
                "ebs_snapshot_id": "snap-id",
                "volume_type": "io1",
                "volume_size": 30,
                "volume_iops": 200,
                "encrypted": True,
                "ebs_kms_key_id": "kms-key",
                "ebs_volume_id": "ebs-id",
            },
        ),
    ],
)
def test_ebs_section_from_cfn(mocker, cfn_params_dict, expected_section_dict):
    utils.assert_section_from_cfn(mocker, EBS, cfn_params_dict, expected_section_dict)


@pytest.mark.parametrize(
    "section_dict, expected_config_parser_dict, expected_message",
    [
        # default
        ({}, {"ebs default": {}}, None),
        # default values
        ({"volume_type": "gp2"}, {"ebs default": {"volume_type": "gp2"}}, "No section"),
        # other values
        ({"volume_type": "io1"}, {"ebs default": {"volume_type": "io1"}}, None),
        ({"volume_type": "io2"}, {"ebs default": {"volume_type": "io2"}}, None),
        ({"volume_size": 30}, {"ebs default": {"volume_size": "30"}}, None),
    ],
)
def test_ebs_section_to_file(mocker, section_dict, expected_config_parser_dict, expected_message):
    utils.assert_section_to_file(mocker, EBS, section_dict, expected_config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_cfn_params",
    [
        (
            DefaultDict["ebs"].value,
            {
                "SharedDir": "NONE",
                "EBSSnapshotId": "NONE",
                "VolumeType": "gp2",
                "VolumeSize": "NONE",
                "VolumeIOPS": "NONE",
                "EBSEncryption": "false",
                "EBSKMSKeyId": "NONE",
                "EBSVolumeId": "NONE",
                "VolumeThroughput": "125",
            },
        ),
        (
            {
                "shared_dir": "test",
                "ebs_snapshot_id": "test",
                "volume_type": "test",
                "volume_size": 30,
                "volume_iops": 200,
                "encrypted": True,
                "ebs_kms_key_id": "test",
                "ebs_volume_id": "test",
                "volume_throughput": "125",
            },
            {
                "SharedDir": "test",
                "EBSSnapshotId": "test",
                "VolumeType": "test",
                "VolumeSize": "30",
                "VolumeIOPS": "200",
                "EBSEncryption": "true",
                "EBSKMSKeyId": "test",
                "EBSVolumeId": "test",
                "VolumeThroughput": "125",
            },
        ),
    ],
)
def test_ebs_section_to_cfn(mocker, section_dict, expected_cfn_params):
    utils.assert_section_to_cfn(mocker, EBS, section_dict, expected_cfn_params)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        ("ebs_snapshot_id", None, None, None),
        ("volume_type", None, "gp2", None),
        ("volume_size", None, None, None),
        ("volume_iops", None, None, None),
        ("volume_throughput", None, 125, None),
        ("encrypted", None, False, None),
        ("ebs_kms_key_id", None, None, None),
        ("ebs_volume_id", None, None, None),
    ],
)
def test_ebs_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, EBS, param_key, param_value, expected_value, expected_message)
