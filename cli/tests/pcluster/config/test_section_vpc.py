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
from pcluster.config.mappings import VPC
from tests.pcluster.config.defaults import DefaultCfnParams, DefaultDict


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict",
    [
        (DefaultCfnParams["vpc"].value, DefaultDict["vpc"].value),
        ({}, DefaultDict["vpc"].value),
        (
            {
                "VPCId": "NONE",
                "MasterSubnetId": "NONE",
                "AccessFrom": "NONE",
                "AdditionalSG": "NONE",
                "ComputeSubnetId": "NONE",
                "ComputeSubnetCidr": "NONE",
                "UsePublicIps": "true",
                "VPCSecurityGroupId": "NONE",
                "AvailabilityZone": "NONE",
            },
            DefaultDict["vpc"].value,
        ),
        (
            {
                "VPCId": "vpc-12345678",
                "MasterSubnetId": "subnet-12345678",
                "AccessFrom": "1.1.1.1/32",
                "AdditionalSG": "sg-12345678",
                "ComputeSubnetId": "subnet-12345678",
                "ComputeSubnetCidr": "1.1.1.1/32",
                "UsePublicIps": "false",
                "VPCSecurityGroupId": "sg-12345678",
            },
            {
                "vpc_id": "vpc-12345678",
                "master_subnet_id": "subnet-12345678",
                "ssh_from": "1.1.1.1/32",
                "additional_sg": "sg-12345678",
                "compute_subnet_id": "subnet-12345678",
                "compute_subnet_cidr": "1.1.1.1/32",
                "use_public_ips": False,
                "vpc_security_group_id": "sg-12345678",
                "master_availability_zone": "my-avail-zone",
                "compute_availability_zone": "my-avail-zone",
            },
        ),
    ],
)
def test_vpc_section_from_cfn(mocker, cfn_params_dict, expected_section_dict):
    utils.assert_section_from_cfn(mocker, VPC, cfn_params_dict, expected_section_dict)


@pytest.mark.parametrize(
    "config_parser_dict, expected_dict_params, expected_message",
    [
        # default
        ({"vpc default": {}}, {}, None),
        # right value
        ({"vpc default": {"vpc_id": "vpc-12345678"}}, {"vpc_id": "vpc-12345678"}, None),
        ({"vpc default": {"ssh_from": "0.0.0.0/32"}}, {"ssh_from": "0.0.0.0/32"}, None),
        # invalid value
        ({"vpc default": {"vpc_id": "wrong_value"}}, None, "has an invalid value"),
        ({"vpc default": {"ssh_from": "wrong_value"}}, None, "has an invalid value"),
        # invalid key
        ({"vpc default": {"invalid_key": "fake_value"}}, None, "'invalid_key' is not allowed in the .* section"),
        (
            {"vpc default": {"invalid_key": "fake_value", "invalid_key2": "fake_value"}},
            None,
            "'invalid_key.*,invalid_key.*' are not allowed in the .* section",  # NOTE: the order is not preserved
        ),
    ],
)
def test_vpc_section_from_file(mocker, config_parser_dict, expected_dict_params, expected_message):
    utils.assert_section_from_file(mocker, VPC, config_parser_dict, expected_dict_params, expected_message)


@pytest.mark.parametrize(
    "section_definition, section_dict, expected_config_parser_dict, expected_message",
    [
        # default
        (VPC, {}, {"vpc default": {}}, None),
        # default values
        (VPC, {"ssh_from": "0.0.0.0/0"}, {"vpc default": {"ssh_from": "0.0.0.0/0"}}, "No section"),
        # other values
        (VPC, {"ssh_from": "1.1.1.1/32"}, {"vpc default": {"ssh_from": "1.1.1.1/32"}}, None),
        (VPC, {"additional_sg": "sg-12345678"}, {"vpc default": {"additional_sg": "sg-12345678"}}, None),
        (VPC, {"use_public_ips": False}, {"vpc default": {"use_public_ips": "false"}}, None),
    ],
)
def test_vpc_section_to_file(mocker, section_definition, section_dict, expected_config_parser_dict, expected_message):
    utils.assert_section_to_file(mocker, VPC, section_dict, expected_config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_cfn_params",
    [
        (DefaultDict["vpc"].value, DefaultCfnParams["vpc"].value),
        (
            {
                "vpc_id": "test",
                "master_subnet_id": "test",
                "ssh_from": "test",
                "additional_sg": "test",
                "compute_subnet_id": "test",
                "compute_subnet_cidr": "test",
                "use_public_ips": False,
                "vpc_security_group_id": "test",
                "master_availability_zone": "my-avail-zone",
            },
            {
                "VPCId": "test",
                "MasterSubnetId": "test",
                "AccessFrom": "test",
                "AdditionalSG": "test",
                "ComputeSubnetId": "test",
                "ComputeSubnetCidr": "test",
                "UsePublicIps": "false",
                "VPCSecurityGroupId": "test",
                "AvailabilityZone": "my-avail-zone",
            },
        ),
    ],
)
def test_vpc_section_to_cfn(mocker, section_dict, expected_cfn_params):
    utils.assert_section_to_cfn(mocker, VPC, section_dict, expected_cfn_params)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        ("vpc_id", None, None, None),
        ("vpc_id", "", None, "Allowed values are"),
        ("vpc_id", "wrong_value", None, "Allowed values are"),
        ("vpc_id", "vpc-12345", None, "Allowed values are"),
        ("vpc_id", "vpc-123456789", None, "Allowed values are"),
        ("vpc_id", "NONE", None, "Allowed values are"),
        ("vpc_id", "vpc-12345678", "vpc-12345678", None),
        ("vpc_id", "vpc-12345678901234567", "vpc-12345678901234567", None),
        ("master_subnet_id", None, None, None),
        ("master_subnet_id", "", None, "Allowed values are"),
        ("master_subnet_id", "wrong_value", None, "Allowed values are"),
        ("master_subnet_id", "subnet-12345", None, "Allowed values are"),
        ("master_subnet_id", "subnet-123456789", None, "Allowed values are"),
        ("master_subnet_id", "NONE", None, "Allowed values are"),
        ("master_subnet_id", "subnet-12345678", "subnet-12345678", None),
        ("master_subnet_id", "subnet-12345678901234567", "subnet-12345678901234567", None),
        ("ssh_from", None, "0.0.0.0/0", None),
        ("ssh_from", "", None, "Allowed values are"),
        ("ssh_from", "wrong_value", None, "Allowed values are"),
        ("ssh_from", "111.111.111.111", None, "Allowed values are"),
        ("ssh_from", "111.111.111.111/222", None, "Allowed values are"),
        ("ssh_from", "NONE", None, "Allowed values are"),
        ("ssh_from", "1.1.1.1/0", "1.1.1.1/0", None),
        ("ssh_from", "1.1.1.1/8", "1.1.1.1/8", None),
        ("ssh_from", "1.1.1.1/16", "1.1.1.1/16", None),
        ("ssh_from", "1.1.1.1/32", "1.1.1.1/32", None),
        ("ssh_from", "1.1.1.1/33", None, "Allowed values are"),
        ("ssh_from", "11.11.11.11/32", "11.11.11.11/32", None),
        ("ssh_from", "111.111.111.111/22", "111.111.111.111/22", None),
        ("ssh_from", "255.255.255.255/32", "255.255.255.255/32", None),
        ("ssh_from", "192.168.0.0./24", None, "Allowed values are"),
        ("additional_sg", None, None, None),
        ("additional_sg", "", None, "Allowed values are"),
        ("additional_sg", "wrong_value", None, "Allowed values are"),
        ("additional_sg", "sg-12345", None, "Allowed values are"),
        ("additional_sg", "sg-123456789", None, "Allowed values are"),
        ("additional_sg", "NONE", None, "Allowed values are"),
        ("additional_sg", "sg-12345678", "sg-12345678", None),
        ("additional_sg", "sg-12345678901234567", "sg-12345678901234567", None),
        ("compute_subnet_id", None, None, None),
        ("compute_subnet_id", "", None, "Allowed values are"),
        ("compute_subnet_id", "wrong_value", None, "Allowed values are"),
        ("compute_subnet_id", "subnet-12345", None, "Allowed values are"),
        ("compute_subnet_id", "subnet-123456789", None, "Allowed values are"),
        ("compute_subnet_id", "NONE", None, "Allowed values are"),
        ("compute_subnet_id", "subnet-12345678", "subnet-12345678", None),
        ("compute_subnet_id", "subnet-12345678901234567", "subnet-12345678901234567", None),
        ("compute_subnet_cidr", None, None, None),
        ("compute_subnet_cidr", "", None, "Allowed values are"),
        ("compute_subnet_cidr", "wrong_value", None, "Allowed values are"),
        ("compute_subnet_cidr", "111.111.111.111", None, "Allowed values are"),
        ("compute_subnet_cidr", "111.111.111.111/222", None, "Allowed values are"),
        ("compute_subnet_cidr", "NONE", None, "Allowed values are"),
        ("compute_subnet_cidr", "1.1.1.1/0", "1.1.1.1/0", None),
        ("compute_subnet_cidr", "1.1.1.1/8", "1.1.1.1/8", None),
        ("compute_subnet_cidr", "1.1.1.1/16", "1.1.1.1/16", None),
        ("compute_subnet_cidr", "1.1.1.1/32", "1.1.1.1/32", None),
        ("compute_subnet_cidr", "1.1.1.1/33", None, "Allowed values are"),
        ("compute_subnet_cidr", "11.11.11.11/32", "11.11.11.11/32", None),
        ("compute_subnet_cidr", "111.111.111.111/22", "111.111.111.111/22", None),
        ("use_public_ips", None, True, None),
        ("use_public_ips", "", None, "must be a Boolean"),
        ("use_public_ips", "NONE", None, "must be a Boolean"),
        ("use_public_ips", "true", True, None),
        ("use_public_ips", "false", False, None),
        ("vpc_security_group_id", None, None, None),
        ("vpc_security_group_id", "", None, "Allowed values are"),
        ("vpc_security_group_id", "wrong_value", None, "Allowed values are"),
        ("vpc_security_group_id", "sg-12345", None, "Allowed values are"),
        ("vpc_security_group_id", "sg-123456789", None, "Allowed values are"),
        ("vpc_security_group_id", "NONE", None, "Allowed values are"),
        ("vpc_security_group_id", "sg-12345678", "sg-12345678", None),
        ("vpc_security_group_id", "sg-12345678901234567", "sg-12345678901234567", None),
        ("master_availability_zone", "fake_value", None, None),  # it is not a config parameter
    ],
)
def test_vpc_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, VPC, param_key, param_value, expected_value, expected_message)
