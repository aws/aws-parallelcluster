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
from pcluster.config.mappings import FSX
from tests.pcluster.config.defaults import DefaultCfnParams, DefaultDict


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict",
    [
        (DefaultCfnParams["fsx"].value, DefaultDict["fsx"].value),
        ({}, DefaultDict["fsx"].value),
        ({"FSXOptions": "NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE"}, DefaultDict["fsx"].value),
        ({"FSXOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE"}, DefaultDict["fsx"].value),
        (
            {"FSXOptions": "test,NONE,NONE,NONE,NONE,NONE,NONE,NONE"},
            {
                "shared_dir": "test",
                "fsx_fs_id": None,
                "storage_capacity": None,
                "fsx_kms_key_id": None,
                "imported_file_chunk_size": None,
                "export_path": None,
                "import_path": None,
                "weekly_maintenance_start_time": None,
            },
        ),
        (
            {"FSXOptions": "test,test1,10,test2,20,test3,test4,test5"},
            {
                "shared_dir": "test",
                "fsx_fs_id": "test1",
                "storage_capacity": 10,
                "fsx_kms_key_id": "test2",
                "imported_file_chunk_size": 20,
                "export_path": "test3",
                "import_path": "test4",
                "weekly_maintenance_start_time": "test5",
            },
        ),
    ],
)
def test_fsx_section_from_cfn(mocker, cfn_params_dict, expected_section_dict):
    utils.assert_section_from_cfn(mocker, FSX, cfn_params_dict, expected_section_dict)


@pytest.mark.parametrize(
    "config_parser_dict, expected_dict_params, expected_message",
    [
        # default
        ({"fsx default": {}}, {}, None),
        # right value
        ({"fsx default": {"storage_capacity": "3"}}, {"storage_capacity": 3}, None),
        # invalid value
        ({"fsx default": {"storage_capacity": "wrong_value"}}, None, "must be an Integer"),
        # invalid key
        ({"fsx default": {"invalid_key": "fake_value"}}, None, "'invalid_key' is not allowed in the .* section"),
    ],
)
def test_fsx_section_from_file(mocker, config_parser_dict, expected_dict_params, expected_message):
    utils.assert_section_from_file(mocker, FSX, config_parser_dict, expected_dict_params, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_config_parser_dict, expected_message",
    [
        # default
        ({}, {"fsx default": {}}, None),
        # other values
        ({"storage_capacity": 10}, {"fsx default": {"storage_capacity": "10"}}, None),
        ({"fsx_kms_key_id": "test"}, {"fsx default": {"fsx_kms_key_id": "test"}}, None),
    ],
)
def test_fsx_section_to_file(mocker, section_dict, expected_config_parser_dict, expected_message):
    utils.assert_section_to_file(mocker, FSX, section_dict, expected_config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_cfn_params", [(DefaultDict["fsx"].value, DefaultCfnParams["fsx"].value)]
)
def test_fsx_section_to_cfn(mocker, section_dict, expected_cfn_params):
    utils.assert_section_to_cfn(mocker, FSX, section_dict, expected_cfn_params)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        ("shared_dir", None, None, None),
        ("shared_dir", "", None, None),
        ("shared_dir", "fake_value", "fake_value", None),
        ("shared_dir", "/test", "/test", None),
        ("shared_dir", "/test/test2", "/test/test2", None),
        ("shared_dir", "/t_ 1-2( ):&;<>t?*+|", "/t_ 1-2( ):&;<>t?*+|", None),
        ("shared_dir", "//test", None, "has an invalid value"),
        ("shared_dir", "./test", None, "has an invalid value"),
        ("shared_dir", ".\\test", None, "has an invalid value"),
        ("shared_dir", ".test", None, "has an invalid value"),
        ("shared_dir", "NONE", "NONE", None),  # Note: NONE is considered as a valid path
        ("fsx_fs_id", None, None, None),
        ("fsx_fs_id", "", None, None),
        ("fsx_fs_id", "wrong_value", None, "has an invalid value"),
        ("fsx_fs_id", "fs-12345", None, "has an invalid value"),
        ("fsx_fs_id", "fs-123456789", None, "has an invalid value"),
        ("fsx_fs_id", "NONE", "NONE", None),  # Note: NONE is considered valid
        ("fsx_fs_id", "fs-12345678", None, "has an invalid value"),
        ("fsx_fs_id", "fs-12345678901234567", "fs-12345678901234567", None),
        ("storage_capacity", None, None, None),
        ("storage_capacity", "", None, None),
        ("storage_capacity", "NONE", None, "must be an Integer"),
        ("storage_capacity", "wrong_value", None, "must be an Integer"),
        ("storage_capacity", "10", 10, None),
        ("storage_capacity", "3", 3, None),
        ("fsx_kms_key_id", None, None, None),
        ("fsx_kms_key_id", "", None, None),
        ("fsx_kms_key_id", "fake_value", "fake_value", None),
        ("fsx_kms_key_id", "test", "test", None),
        ("fsx_kms_key_id", "NONE", "NONE", None),  # NONE is evaluated as a valid kms id
        ("imported_file_chunk_size", None, None, None),
        ("imported_file_chunk_size", "", None, None),
        ("imported_file_chunk_size", "NONE", None, "must be an Integer"),
        ("imported_file_chunk_size", "wrong_value", None, "must be an Integer"),
        ("imported_file_chunk_size", "10", 10, None),
        ("imported_file_chunk_size", "3", 3, None),
        # TODO add regex for export path
        ("export_path", None, None, None),
        ("export_path", "", None, None),
        ("export_path", "fake_value", "fake_value", None),
        ("export_path", "http://test", "http://test", None),
        ("export_path", "s3://test/test2", "s3://test/test2", None),
        ("export_path", "NONE", "NONE", None),
        # TODO add regex for import path
        ("import_path", None, None, None),
        ("import_path", "", None, None),
        ("import_path", "fake_value", "fake_value", None),
        ("import_path", "http://test", "http://test", None),
        ("import_path", "s3://test/test2", "s3://test/test2", None),
        ("import_path", "NONE", "NONE", None),
        # TODO add regex for weekly_maintenance_start_time
        ("weekly_maintenance_start_time", None, None, None),
        ("weekly_maintenance_start_time", "", None, None),
        ("weekly_maintenance_start_time", "fake_value", "fake_value", None),
        ("weekly_maintenance_start_time", "start_time", "start_time", None),
        ("weekly_maintenance_start_time", "10:00", "10:00", None),
        ("weekly_maintenance_start_time", "NONE", "NONE", None),
    ],
)
def test_fsx_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, FSX, param_key, param_value, expected_value, expected_message)


@pytest.mark.parametrize(
    "settings_label, expected_cfn_params",
    [
        (
            "test1",
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                DefaultCfnParams["fsx"].value,
                {"MasterSubnetId": "subnet-12345678", "AvailabilityZone": "mocked_avail_zone"},
            ),
        ),
        (
            "test2",
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                {
                    "MasterSubnetId": "subnet-12345678",
                    "AvailabilityZone": "mocked_avail_zone",
                    "FSXOptions": "fsx,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
                },
            ),
        ),
        (
            "test3",
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                {
                    "MasterSubnetId": "subnet-12345678",
                    "AvailabilityZone": "mocked_avail_zone",
                    "FSXOptions": "fsx,fs-12345678901234567,10,key1,1020,test-export,test-import,10",
                },
            ),
        ),
        ("test1,test2", SystemExit()),
        ("test4", SystemExit()),
        ("test5", SystemExit()),
    ],
)
def test_fsx_from_file_to_cfn(mocker, pcluster_config_reader, settings_label, expected_cfn_params):
    """Unit tests for parsing EFS related options."""
    mocker.patch("pcluster.config.param_types.get_efs_mount_target_id", return_value="mount_target_id")
    mocker.patch("pcluster.config.param_types.get_avail_zone", return_value="mocked_avail_zone")
    utils.assert_section_params(mocker, pcluster_config_reader, settings_label, expected_cfn_params)
