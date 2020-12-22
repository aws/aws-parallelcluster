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
from pcluster.config.mappings import EFS
from tests.pcluster.config.defaults import DefaultCfnParams, DefaultDict


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict",
    [
        ({"EFSOptions": "NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE"}, DefaultDict["efs"].value),
        ({"EFSOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE"}, DefaultDict["efs"].value),
        (
            {"EFSOptions": "test,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE"},
            {
                "shared_dir": "test",
                "efs_fs_id": None,
                "performance_mode": "generalPurpose",
                "efs_kms_key_id": None,
                "provisioned_throughput": None,
                "encrypted": False,
                "throughput_mode": "bursting",
            },
        ),
        (
            {"EFSOptions": "test,test,maxIO,test,1024,true,provisioned,NONE,NONE"},
            {
                "shared_dir": "test",
                "efs_fs_id": "test",
                "performance_mode": "maxIO",
                "efs_kms_key_id": "test",
                "provisioned_throughput": 1024,
                "encrypted": True,
                "throughput_mode": "provisioned",
            },
        ),
    ],
)
def test_efs_section_from_cfn(mocker, cfn_params_dict, expected_section_dict):
    utils.assert_section_from_cfn(mocker, EFS, cfn_params_dict, expected_section_dict)


@pytest.mark.parametrize(
    "section_dict, expected_config_parser_dict, expected_message",
    [
        # default
        ({}, {"efs default": {}}, None),
        # default values
        (
            {"performance_mode": "generalPurpose"},
            {"efs default": {"performance_mode": "generalPurpose"}},
            "No section.*",
        ),
        # other values
        ({"performance_mode": "maxIO"}, {"efs default": {"performance_mode": "maxIO"}}, None),
        ({"encrypted": True}, {"efs default": {"encrypted": "true"}}, None),
    ],
)
def test_cluster_section_to_file(mocker, section_dict, expected_config_parser_dict, expected_message):
    utils.assert_section_to_file(mocker, EFS, section_dict, expected_config_parser_dict, expected_message)


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
        ("efs_fs_id", None, None, None),
        ("efs_fs_id", "", None, "has an invalid value"),
        ("efs_fs_id", "wrong_value", None, "has an invalid value"),
        ("efs_fs_id", "fs-12345", None, "has an invalid value"),
        ("efs_fs_id", "fs-123456789", None, "has an invalid value"),
        ("efs_fs_id", "NONE", "NONE", None),  # Note: NONE is considered valid
        ("efs_fs_id", "fs-12345678", "fs-12345678", None),
        ("efs_fs_id", "fs-12345678901234567", "fs-12345678901234567", None),
        ("performance_mode", None, "generalPurpose", None),
        ("performance_mode", "", None, "Allowed values are"),
        ("performance_mode", "maxIO", "maxIO", None),
        ("performance_mode", "wrong_value", None, "Allowed values are"),
        ("performance_mode", "NONE", None, "Allowed values are"),
        ("efs_kms_key_id", None, None, None),
        ("efs_kms_key_id", "", "", None),
        ("efs_kms_key_id", "fake_value", "fake_value", None),
        ("efs_kms_key_id", "test", "test", None),
        ("efs_kms_key_id", "NONE", "NONE", None),  # NONE is evaluated as a valid kms id
        ("provisioned_throughput", "0.1", 0.1, None),
        ("provisioned_throughput", "3", 3, None),
        ("provisioned_throughput", "1024.9", 1024.9, None),
        ("provisioned_throughput", "102000", None, "has an invalid value"),
        ("provisioned_throughput", "0.01", None, "has an invalid value"),
        ("provisioned_throughput", "1025", None, "has an invalid value"),
        ("provisioned_throughput", "wrong_value", None, "must be a Float"),
        ("encrypted", None, False, None),
        ("encrypted", "", None, "must be a Boolean"),
        ("encrypted", "NONE", None, "must be a Boolean"),
        ("encrypted", "true", True, None),
        ("encrypted", "false", False, None),
        ("throughput_mode", None, "bursting", None),
        ("throughput_mode", "", "", "has an invalid value"),
        ("throughput_mode", "provisioned", "provisioned", None),
        ("throughput_mode", "wrong_value", None, "Allowed values are"),
        ("throughput_mode", "NONE", None, "Allowed values are"),
    ],
)
def test_efs_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, EFS, param_key, param_value, expected_value, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_cfn_params",
    [
        (DefaultDict["efs"].value, DefaultCfnParams["efs"].value),
        ({"shared_dir": "NONE"}, DefaultCfnParams["efs"].value),
        ({"shared_dir": "test"}, {"EFSOptions": "test,NONE,generalPurpose,NONE,NONE,false,bursting,Valid,Valid"}),
        (
            {
                "shared_dir": "test",
                "efs_fs_id": "test2",
                "performance_mode": "test3",
                "efs_kms_key_id": "test4",
                "provisioned_throughput": 10,
                "encrypted": True,
                "throughput_mode": "test5",
            },
            {"EFSOptions": "test,test2,test3,test4,10,true,test5,Valid,Valid"},
        ),
        (
            {
                "shared_dir": "test",
                "efs_fs_id": None,
                "performance_mode": "test1",
                "efs_kms_key_id": "test2",
                "provisioned_throughput": 1024,
                "encrypted": False,
                "throughput_mode": "test3",
            },
            {"EFSOptions": "test,NONE,test1,test2,1024,false,test3,Valid,Valid"},
        ),
    ],
)
def test_efs_section_to_cfn(mocker, section_dict, expected_cfn_params):
    mocker.patch("pcluster.config.cfn_param_types.get_efs_mount_target_id", return_value="valid_mount_target_id")
    mocker.patch(
        "pcluster.config.pcluster_config.PclusterConfig.get_head_node_availability_zone",
        return_value="mocked_avail_zone",
    )
    utils.assert_section_to_cfn(mocker, EFS, section_dict, expected_cfn_params)


@pytest.mark.parametrize(
    "settings_label, expected_cfn_params",
    [
        (
            "test1",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                DefaultCfnParams["efs"].value,
                {
                    "MasterSubnetId": "subnet-12345678",
                    "AvailabilityZone": "mocked_avail_zone",
                    "ComputeSubnetId": "subnet-23456789",
                },
            ),
        ),
        (
            "test2",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "MasterSubnetId": "subnet-12345678",
                    "AvailabilityZone": "mocked_avail_zone",
                    "ComputeSubnetId": "subnet-23456789",
                    "EFSOptions": "efs,NONE,generalPurpose,NONE,NONE,false,bursting,Valid,Valid",
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
                    "ComputeSubnetId": "subnet-23456789",
                    "EFSOptions": "efs,fs-12345678,maxIO,key1,1020.0,false,provisioned,Valid,Valid",
                },
            ),
        ),
        (
            "test4",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "MasterSubnetId": "subnet-12345678",
                    "AvailabilityZone": "mocked_avail_zone",
                    "ComputeSubnetId": "subnet-23456789",
                    "EFSOptions": "/efs,NONE,generalPurpose,NONE,NONE,true,bursting,Valid,Valid",
                },
            ),
        ),
        ("test1,test2", SystemExit()),
    ],
)
def test_efs_from_file_to_cfn(mocker, pcluster_config_reader, settings_label, expected_cfn_params):
    """Unit tests for parsing EFS related options."""
    mocker.patch(
        "pcluster.config.cfn_param_types.get_efs_mount_target_id",
        side_effect=lambda efs_fs_id, avail_zone: "master_mt" if avail_zone == "mocked_avail_zone" else None,
    )
    mocker.patch("pcluster.config.cfn_param_types.get_availability_zone_of_subnet", return_value="mocked_avail_zone")
    utils.assert_section_params(mocker, pcluster_config_reader, settings_label, expected_cfn_params)
