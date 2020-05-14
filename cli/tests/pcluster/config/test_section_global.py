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
from pcluster.config.mappings import GLOBAL


@pytest.mark.parametrize(
    "config_parser_dict, expected_dict_params, expected_message",
    [
        # default
        ({"global": {}}, {}, None),
        # right value
        (
            {"global": {"cluster_template": "test", "update_check": "false", "sanity_check": "false"}},
            {"cluster_template": "test", "update_check": False, "sanity_check": False},
            None,
        ),
        # invalid key
        ({"global": {"invalid_key": "fake_value"}}, None, "'invalid_key' is not allowed in the .* section"),
    ],
)
def test_global_section_from_file(mocker, config_parser_dict, expected_dict_params, expected_message):
    utils.assert_section_from_file(mocker, GLOBAL, config_parser_dict, expected_dict_params, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_config_parser_dict, expected_message",
    [
        # default
        ({}, {"global": {}}, None),
        # default values
        ({"cluster_template": "default", "update_check": True, "sanity_check": True}, {}, "No section.*"),
        # other values --> global section is never written to the file
        ({"cluster_template": "other", "update_check": False, "sanity_check": False}, {}, "No section.*"),
    ],
)
def test_global_section_to_file(mocker, section_dict, expected_config_parser_dict, expected_message):
    utils.assert_section_to_file(mocker, GLOBAL, section_dict, expected_config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        ("cluster_template", None, "default", None),
        ("cluster_template", "", "", None),
        ("cluster_template", "test", "test", None),
        ("cluster_template", "NONE", "NONE", None),  # NONE is considered valid
        ("update_check", None, True, None),
        ("update_check", "", None, "must be a Boolean"),
        ("update_check", "NONE", None, "must be a Boolean"),
        ("update_check", "true", True, None),
        ("update_check", "false", False, None),
        ("sanity_check", None, True, None),
        ("sanity_check", "", None, "must be a Boolean"),
        ("sanity_check", "NONE", None, "must be a Boolean"),
        ("sanity_check", "true", True, None),
        ("sanity_check", "false", False, None),
    ],
)
def test_global_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, GLOBAL, param_key, param_value, expected_value, expected_message)
