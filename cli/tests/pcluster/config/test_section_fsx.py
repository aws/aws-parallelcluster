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
        (
            {"FSXOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE"},
            DefaultDict["fsx"].value,
        ),
        (
            {"FSXOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE"},
            DefaultDict["fsx"].value,
        ),
        (
            {"FSXOptions": "test,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE"},
            utils.merge_dicts(DefaultDict["fsx"].value, {"shared_dir": "test"}),
        ),
        (
            {
                "FSXOptions": "test,test1,10,test2,20,test3,test4,test5,SCRATCH_1,"
                "50,01:00,5,false,backup-0a1b2c3d4e5f6a7b8,NEW_CHANGED,HDD,READ"
            },
            {
                "shared_dir": "test",
                "fsx_fs_id": "test1",
                "storage_capacity": 10,
                "fsx_kms_key_id": "test2",
                "imported_file_chunk_size": 20,
                "export_path": "test3",
                "import_path": "test4",
                "weekly_maintenance_start_time": "test5",
                "deployment_type": "SCRATCH_1",
                "per_unit_storage_throughput": 50,
                "daily_automatic_backup_start_time": "01:00",
                "automatic_backup_retention_days": 5,
                "copy_tags_to_backups": False,
                "fsx_backup_id": "backup-0a1b2c3d4e5f6a7b8",
                "auto_import_policy": "NEW_CHANGED",
                "storage_type": "HDD",
                "drive_cache_type": "READ",
            },
        ),
        (
            {
                "FSXOptions": "test,test1,10,test2,20,test3,test4,test5,SCRATCH_1,"
                "50,01:00,5,false,backup-0a1b2c3d4e5f6a7b8,NEW_CHANGED,HDD,NONE"
            },
            {
                "shared_dir": "test",
                "fsx_fs_id": "test1",
                "storage_capacity": 10,
                "fsx_kms_key_id": "test2",
                "imported_file_chunk_size": 20,
                "export_path": "test3",
                "import_path": "test4",
                "weekly_maintenance_start_time": "test5",
                "deployment_type": "SCRATCH_1",
                "per_unit_storage_throughput": 50,
                "daily_automatic_backup_start_time": "01:00",
                "automatic_backup_retention_days": 5,
                "copy_tags_to_backups": False,
                "fsx_backup_id": "backup-0a1b2c3d4e5f6a7b8",
                "auto_import_policy": "NEW_CHANGED",
                "storage_type": "HDD",
                "drive_cache_type": "NONE",
            },
        ),
        (
            {
                "FSXOptions": "test,test1,10,test2,20,test3,test4,test5,SCRATCH_1,"
                "50,01:00,5,false,backup-0a1b2c3d4e5f6a7b8,NEW_CHANGED,SSD,NONE"
            },
            {
                "shared_dir": "test",
                "fsx_fs_id": "test1",
                "storage_capacity": 10,
                "fsx_kms_key_id": "test2",
                "imported_file_chunk_size": 20,
                "export_path": "test3",
                "import_path": "test4",
                "weekly_maintenance_start_time": "test5",
                "deployment_type": "SCRATCH_1",
                "per_unit_storage_throughput": 50,
                "daily_automatic_backup_start_time": "01:00",
                "automatic_backup_retention_days": 5,
                "copy_tags_to_backups": False,
                "fsx_backup_id": "backup-0a1b2c3d4e5f6a7b8",
                "auto_import_policy": "NEW_CHANGED",
                "storage_type": "SSD",
            },
        ),
        (
            {
                "FSXOptions": "test,test1,10,test2,20,test3,test4,test5,SCRATCH_1,"
                "50,01:00,5,false,backup-0a1b2c3d4e5f6a7b8,NONE,NONE,NONE"
            },
            {
                "shared_dir": "test",
                "fsx_fs_id": "test1",
                "storage_capacity": 10,
                "fsx_kms_key_id": "test2",
                "imported_file_chunk_size": 20,
                "export_path": "test3",
                "import_path": "test4",
                "weekly_maintenance_start_time": "test5",
                "deployment_type": "SCRATCH_1",
                "per_unit_storage_throughput": 50,
                "daily_automatic_backup_start_time": "01:00",
                "automatic_backup_retention_days": 5,
                "copy_tags_to_backups": False,
                "fsx_backup_id": "backup-0a1b2c3d4e5f6a7b8",
                "auto_import_policy": None,
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
        # invalid value
        ({"fsx default": {"deployment_type": "BLAH"}}, None, "'deployment_type' has an invalid value 'BLAH'"),
        # invalid value
        ({"fsx default": {"per_unit_storage_throughput": 1000}}, None, "has an invalid value '1000'"),
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
        ("shared_dir", "NONE", "NONE", None),  # Note: NONE is considered as a valid path
        ("fsx_fs_id", None, None, None),
        ("fsx_fs_id", "", None, "has an invalid value"),
        ("fsx_fs_id", "wrong_value", None, "has an invalid value"),
        ("fsx_fs_id", "fs-12345", None, "has an invalid value"),
        ("fsx_fs_id", "fs-123456789", None, "has an invalid value"),
        ("fsx_fs_id", "NONE", "NONE", None),  # Note: NONE is considered valid
        ("fsx_fs_id", "fs-12345678", None, "has an invalid value"),
        ("fsx_fs_id", "fs-12345678901234567", "fs-12345678901234567", None),
        ("storage_capacity", None, None, None),
        ("storage_capacity", "", None, "must be an Integer"),
        ("storage_capacity", "NONE", None, "must be an Integer"),
        ("storage_capacity", "wrong_value", None, "must be an Integer"),
        ("storage_capacity", "10", 10, None),
        ("storage_capacity", "3", 3, None),
        ("fsx_kms_key_id", None, None, None),
        ("fsx_kms_key_id", "", "", None),
        ("fsx_kms_key_id", "fake_value", "fake_value", None),
        ("fsx_kms_key_id", "test", "test", None),
        ("fsx_kms_key_id", "NONE", "NONE", None),  # NONE is evaluated as a valid kms id
        ("imported_file_chunk_size", None, None, None),
        ("imported_file_chunk_size", "", None, "must be an Integer"),
        ("imported_file_chunk_size", "NONE", None, "must be an Integer"),
        ("imported_file_chunk_size", "wrong_value", None, "must be an Integer"),
        ("imported_file_chunk_size", "10", 10, None),
        ("imported_file_chunk_size", "3", 3, None),
        # TODO add regex for export path
        ("export_path", None, None, None),
        ("export_path", "", "", None),
        ("export_path", "fake_value", "fake_value", None),
        ("export_path", "http://test", "http://test", None),
        ("export_path", "s3://test/test2", "s3://test/test2", None),
        ("export_path", "NONE", "NONE", None),
        # TODO add regex for import path
        ("import_path", None, None, None),
        ("import_path", "", "", None),
        ("import_path", "fake_value", "fake_value", None),
        ("import_path", "http://test", "http://test", None),
        ("import_path", "s3://test/test2", "s3://test/test2", None),
        ("import_path", "NONE", "NONE", None),
        # TODO add regex for weekly_maintenance_start_time
        ("weekly_maintenance_start_time", None, None, None),
        ("weekly_maintenance_start_time", "", None, "has an invalid value"),
        ("weekly_maintenance_start_time", "fake_value", "fake_value", "has an invalid value"),
        ("weekly_maintenance_start_time", "10:00", "10:00", "has an invalid value"),
        ("weekly_maintenance_start_time", "1:10:00", "1:10:00", None),
        ("weekly_maintenance_start_time", "NONE", "NONE", None),
        ("weekly_maintenance_start_time", "1:1000", "1:1000", "has an invalid value"),
        ("deployment_type", "SCRATCH_1", "SCRATCH_1", None),
        ("deployment_type", "SCRATCH_2", "SCRATCH_2", None),
        ("deployment_type", "PERSISTENT_1", "PERSISTENT_1", None),
        (
            "deployment_type",
            "INVALID_VALUE",
            "INVALID_VALUE",
            " 'deployment_type' has an invalid value 'INVALID_VALUE'",
        ),
        ("per_unit_storage_throughput", "12", 12, None),
        ("per_unit_storage_throughput", "40", 40, None),
        ("per_unit_storage_throughput", "50", 50, None),
        ("per_unit_storage_throughput", "100", 100, None),
        ("per_unit_storage_throughput", "200", 200, None),
        ("per_unit_storage_throughput", "101", 101, "'per_unit_storage_throughput' has an invalid value '101'"),
        ("daily_automatic_backup_start_time", None, None, None),
        ("daily_automatic_backup_start_time", "", "", "'daily_automatic_backup_start_time' has an invalid value ''"),
        ("daily_automatic_backup_start_time", "01:00", "01:00", None),
        ("daily_automatic_backup_start_time", "23:00", "23:00", None),
        (
            "daily_automatic_backup_start_time",
            "25:00",
            "25:00",
            "'daily_automatic_backup_start_time' has an invalid value '25:00'",
        ),
        (
            "daily_automatic_backup_start_time",
            "2300",
            "2300",
            "'daily_automatic_backup_start_time' has an invalid value '2300'",
        ),
        ("automatic_backup_retention_days", None, None, None),
        ("automatic_backup_retention_days", "", None, "must be an Integer"),
        ("automatic_backup_retention_days", "0", 0, None),
        ("automatic_backup_retention_days", "35", 35, None),
        ("automatic_backup_retention_days", "36", 36, "'automatic_backup_retention_days' has an invalid value '36'"),
        ("copy_tags_to_backups", None, None, None),
        ("copy_tags_to_backups", "", None, "must be a Boolean"),
        ("copy_tags_to_backups", "NONE", None, "must be a Boolean"),
        ("copy_tags_to_backups", "true", True, None),
        ("copy_tags_to_backups", "false", False, None),
        ("fsx_backup_id", None, None, None),
        ("fsx_backup_id", "", None, "'fsx_backup_id' has an invalid value ''"),
        (
            "fsx_backup_id",
            "back-0a1b2c3d4e5f6a7b8",
            None,
            "'fsx_backup_id' has an invalid value 'back-0a1b2c3d4e5f6a7b8'",
        ),
        (
            "fsx_backup_id",
            "backup-0A1B2C3d4e5f6a7b8",
            None,
            "'fsx_backup_id' has an invalid value 'backup-0A1B2C3d4e5f6a7b8'",
        ),
        ("fsx_backup_id", "backup-0a1b2c3d4e5f6a7b8", "backup-0a1b2c3d4e5f6a7b8", None),
        ("auto_import_policy", None, None, None),
        ("auto_import_policy", "NEW", "NEW", None),
        ("auto_import_policy", "NEW_CHANGED", "NEW_CHANGED", None),
        ("storage_type", None, None, None),
        ("storage_type", "SSD", "SSD", None),
        ("storage_type", "HDD", "HDD", None),
        (
            "storage_type",
            "INVALID_VALUE",
            "INVALID_VALUE",
            " 'storage_type' has an invalid value 'INVALID_VALUE'",
        ),
        ("drive_cache_type", None, "NONE", None),
        ("drive_cache_type", "READ", "READ", None),
        (
            "drive_cache_type",
            "INVALID_VALUE",
            "INVALID_VALUE",
            " 'drive_cache_type' has an invalid value 'INVALID_VALUE'",
        ),
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
                DefaultCfnParams["cluster_sit"].value,
                DefaultCfnParams["fsx"].value,
                {"MasterSubnetId": "subnet-12345678", "AvailabilityZone": "mocked_avail_zone"},
            ),
        ),
        (
            "test2",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "MasterSubnetId": "subnet-12345678",
                    "AvailabilityZone": "mocked_avail_zone",
                    "FSXOptions": "fsx,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,"
                    "NONE,NONE",
                },
            ),
        ),
        (
            "test3",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "MasterSubnetId": "subnet-12345678",
                    "AvailabilityZone": "mocked_avail_zone",
                    "FSXOptions": "fsx,fs-12345678901234567,10,key1,1020,s3://test-export,"
                    "s3://test-import,1:10:17,SCRATCH_1,50,01:00,5,false,NONE,NEW_CHANGED,HDD,READ",
                },
            ),
        ),
        (
            "test3",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "MasterSubnetId": "subnet-12345678",
                    "AvailabilityZone": "mocked_avail_zone",
                    "FSXOptions": "fsx,fs-12345678901234567,10,key1,1020,s3://test-export,"
                    "s3://test-import,1:10:17,SCRATCH_1,50,01:00,5,false,NONE,NEW_CHANGED,HDD,READ",
                },
            ),
        ),
        ("test1,test2", SystemExit()),
        ("test4", SystemExit()),
        ("test5", SystemExit()),
        (
            "test6",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "MasterSubnetId": "subnet-12345678",
                    "AvailabilityZone": "mocked_avail_zone",
                    "FSXOptions": "/fsx,NONE,3600,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,"
                    "NONE,"
                    "NONE",
                },
            ),
        ),
        (
            "test7",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "MasterSubnetId": "subnet-12345678",
                    "AvailabilityZone": "mocked_avail_zone",
                    "FSXOptions": "fsx,fs-12345678901234567,10,key1,1020,s3://test-export,"
                    "s3://test-import,1:10:17,SCRATCH_1,50,01:00,5,false,NONE,NONE,HDD,NONE",
                },
            ),
        ),
        (
            "test8",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "MasterSubnetId": "subnet-12345678",
                    "AvailabilityZone": "mocked_avail_zone",
                    "FSXOptions": "fsx,fs-12345678901234567,10,key1,1020,s3://test-export,"
                    "s3://test-import,1:10:17,SCRATCH_1,50,01:00,5,false,NONE,NONE,HDD,READ",
                },
            ),
        ),
        (
            "test9",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "MasterSubnetId": "subnet-12345678",
                    "AvailabilityZone": "mocked_avail_zone",
                    "FSXOptions": "fsx,fs-12345678901234567,10,key1,1020,s3://test-export,"
                    "s3://test-import,1:10:17,SCRATCH_1,50,01:00,5,false,NONE,NONE,SSD,NONE",
                },
            ),
        ),
    ],
)
def test_fsx_from_file_to_cfn(mocker, pcluster_config_reader, settings_label, expected_cfn_params):
    """Unit tests for parsing EFS related options."""
    mocker.patch("pcluster.config.cfn_param_types.get_efs_mount_target_id", return_value="mount_target_id")
    mocker.patch("pcluster.config.cfn_param_types.get_availability_zone_of_subnet", return_value="mocked_avail_zone")
    utils.assert_section_params(mocker, pcluster_config_reader, settings_label, expected_cfn_params)
