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
        ("fsx_fs_id", None, None, None),
        ("storage_capacity", None, None, None),
        ("fsx_kms_key_id", None, None, None),
        ("export_path", None, None, None),
        ("import_path", None, None, None),
        ("imported_file_chunk_size", None, None, None),
        ("weekly_maintenance_start_time", None, None, None),
        ("daily_automatic_backup_start_time", None, None, None),
        ("automatic_backup_retention_days", None, None, None),
        ("copy_tags_to_backups", None, None, None),
        ("auto_import_policy", None, None, None),
        ("fsx_backup_id", None, None, None),
        ("storage_type", None, None, None),
        ("drive_cache_type", None, "NONE", None),
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
