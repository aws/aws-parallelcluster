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
from pcluster.config.mappings import AWS


@pytest.mark.parametrize(
    "config_parser_dict, expected_dict_params, expected_message",
    [
        # right value
        (
            {"aws": {"aws_access_key_id": "test", "aws_secret_access_key": "test2", "aws_region_name": "eu-west-1"}},
            {"aws_access_key_id": "test", "aws_secret_access_key": "test2", "aws_region_name": "eu-west-1"},
            None,
        ),
        # invalid key
        ({"aws": {"invalid_key": "fake_value"}}, None, "'invalid_key' is not allowed in the .* section"),
    ],
)
def test_aws_section_from_file(mocker, config_parser_dict, expected_dict_params, expected_message):
    utils.assert_section_from_file(mocker, AWS, config_parser_dict, expected_dict_params, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_config_parser_dict, expected_message",
    [
        # default
        ({}, {"aws": {}}, None),
        # default values
        ({"aws_region_name": "us-east-1"}, {}, "No section.*"),
        # other values
        ({"aws_region_name": "us-east-1"}, {}, "No section.*"),  # aws section is never written to the file
    ],
)
def test_aws_section_to_file(mocker, section_dict, expected_config_parser_dict, expected_message):
    utils.assert_section_to_file(mocker, AWS, section_dict, expected_config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        ("aws_access_key_id", None, None, None),
        ("aws_access_key_id", "", "", None),
        ("aws_access_key_id", "NONE", "NONE", None),  # NONE is considered valid
        ("aws_access_key_id", "test", "test", None),
        ("aws_secret_access_key", None, None, None),
        ("aws_secret_access_key", "", "", None),
        ("aws_secret_access_key", "NONE", "NONE", None),  # NONE is considered valid
        ("aws_secret_access_key", "test", "test", None),
        ("aws_region_name", "", "", None),
        ("aws_region_name", "NONE", "NONE", None),  # TODO NONE is considered valid --> add regex
        ("aws_region_name", "eu-west-1", "eu-west-1", None),
    ],
)
def test_aws_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, AWS, param_key, param_value, expected_value, expected_message)
