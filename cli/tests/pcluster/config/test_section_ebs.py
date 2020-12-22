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
from tests.pcluster.config.defaults import DefaultCfnParams, DefaultDict


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
        ("shared_dir", None, None, None),
        ("shared_dir", "", None, "has an invalid value"),
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
        ("ebs_snapshot_id", None, None, None),
        ("ebs_snapshot_id", "", None, "has an invalid value"),
        ("ebs_snapshot_id", "wrong_value", None, "has an invalid value"),
        ("ebs_snapshot_id", "snap-12345", None, "has an invalid value"),
        ("ebs_snapshot_id", "snap-123456789", None, "has an invalid value"),
        ("ebs_snapshot_id", "NONE", None, "has an invalid value"),
        ("ebs_snapshot_id", "snap-12345678", "snap-12345678", None),
        ("ebs_snapshot_id", "snap-12345678901234567", "snap-12345678901234567", None),
        ("volume_type", None, "gp2", None),
        ("volume_type", "", None, "Allowed values are"),
        ("volume_type", "wrong_value", None, "Allowed values are"),
        ("volume_type", "st1", "st1", None),
        ("volume_type", "sc1", "sc1", None),
        ("volume_type", "NONE", None, "Allowed values are"),
        ("volume_type", None, "gp2", None),
        ("volume_type", "wrong_value", None, "Allowed values are"),
        ("volume_type", "io1", "io1", None),
        ("volume_type", "io2", "io2", None),
        ("volume_type", "standard", "standard", None),
        ("volume_type", "NONE", None, "Allowed values are"),
        ("volume_size", None, None, None),
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
        ("volume_throughput", None, 125, None),
        ("volume_throughput", "", None, "must be an Integer"),
        ("volume_throughput", "NONE", None, "must be an Integer"),
        ("volume_throughput", "wrong_value", None, "must be an Integer"),
        ("volume_throughput", "200", 200, None),
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
        ("ebs_volume_id", None, None, None),
        ("ebs_volume_id", "", None, "has an invalid value"),
        ("ebs_volume_id", "wrong_value", None, "has an invalid value"),
        ("ebs_volume_id", "vol-12345", None, "has an invalid value"),
        ("ebs_volume_id", "vol-123456789", None, "has an invalid value"),
        ("ebs_volume_id", "NONE", None, "has an invalid value"),
        ("ebs_volume_id", "vol-12345678", "vol-12345678", None),
        ("ebs_volume_id", "vol-12345678901234567", "vol-12345678901234567", None),
    ],
)
def test_ebs_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, EBS, param_key, param_value, expected_value, expected_message)


@pytest.mark.parametrize(
    "settings_label, expected_cfn_params",
    [
        (
            "ebs1",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "NumberOfEBSVol": "1",
                    "SharedDir": "ebs1,NONE,NONE,NONE,NONE",
                    "VolumeType": "io1,gp2,gp2,gp2,gp2",
                    "VolumeSize": "40,NONE,NONE,NONE,NONE",
                    "VolumeIOPS": "200,NONE,NONE,NONE,NONE",
                    "EBSEncryption": "true,false,false,false,false",
                    "EBSKMSKeyId": "kms_key,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "vol-12345678,NONE,NONE,NONE,NONE",
                    "VolumeIOPS": "200,NONE,NONE,NONE,NONE",
                },
            ),
        ),
        (
            "ebs2",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "NumberOfEBSVol": "1",
                    "SharedDir": "ebs2,NONE,NONE,NONE,NONE",
                    "VolumeType": "standard,gp2,gp2,gp2,gp2",
                    "VolumeSize": "30,NONE,NONE,NONE,NONE",
                    "VolumeIOPS": "300,NONE,NONE,NONE,NONE",
                    "EBSEncryption": "false,false,false,false,false",
                    "EBSKMSKeyId": "NONE,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "NONE,NONE,NONE,NONE,NONE",
                },
            ),
        ),
        (
            "ebs3",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "NumberOfEBSVol": "1",
                    "SharedDir": "ebs3,NONE,NONE,NONE,NONE",
                    "VolumeType": "gp3,gp2,gp2,gp2,gp2",
                    "VolumeSize": "30,NONE,NONE,NONE,NONE",
                    "VolumeIOPS": "3000,NONE,NONE,NONE,NONE",
                    "EBSEncryption": "false,false,false,false,false",
                    "EBSKMSKeyId": "NONE,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "NONE,NONE,NONE,NONE,NONE",
                    "VolumeThroughput": "150,125,125,125,125",
                },
            ),
        ),
    ],
)
def test_ebs_from_file_to_cfn(mocker, pcluster_config_reader, settings_label, expected_cfn_params):
    """Unit tests for parsing EBS related options."""
    utils.assert_section_params(mocker, pcluster_config_reader, settings_label, expected_cfn_params)
