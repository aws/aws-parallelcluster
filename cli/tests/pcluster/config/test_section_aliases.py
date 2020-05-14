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
from pcluster.config.mappings import ALIASES


@pytest.mark.parametrize(
    "config_parser_dict, expected_dict_params, expected_message",
    [
        # default
        ({"aliases": {}}, {}, None),
        # right value
        (
            {"aliases": {"ssh": "ssh {CFN_USER}@{MASTER_IP} -i /path/path2/test.pem {ARGS}"}},
            {"ssh": "ssh {CFN_USER}@{MASTER_IP} -i /path/path2/test.pem {ARGS}"},
            None,
        ),
        # invalid key
        ({"aliases": {"scp": "fake_value"}}, None, "'scp' is not allowed in the .* section"),
    ],
)
def test_aliases_section_from_file(mocker, config_parser_dict, expected_dict_params, expected_message):
    utils.assert_section_from_file(mocker, ALIASES, config_parser_dict, expected_dict_params, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_config_parser_dict, expected_message",
    [
        # default
        ({}, {"aliases": {}}, None),
        # default values
        ({"ssh": "ssh {CFN_USER}@{MASTER_IP} {ARGS}"}, {}, "No section.*"),
        # other values --> aliases section is never written to the file
        ({"ssh": "ssh {CFN_USER}@{MASTER_IP} -i /path/path2/test.pem {ARGS}"}, {}, "No section.*"),
    ],
)
def test_aliases_section_to_file(mocker, section_dict, expected_config_parser_dict, expected_message):
    utils.assert_section_to_file(mocker, ALIASES, section_dict, expected_config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        # default
        ("ssh", None, "ssh {CFN_USER}@{MASTER_IP} {ARGS}", None),
        ("ssh", "", "", None),
        # valid values
        ("ssh", "NONE", "NONE", None),
        (
            "ssh",
            "ssh {CFN_USER}@{MASTER_IP} -i /path/path2/test.pem {ARGS}",
            "ssh {CFN_USER}@{MASTER_IP} -i /path/path2/test.pem {ARGS}",
            None,
        ),
    ],
)
def test_aliases_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, ALIASES, param_key, param_value, expected_value, expected_message)
