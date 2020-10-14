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
import configparser
import pytest
from assertpy import assert_that

from pcluster.config.mappings import CLUSTER_SIT, SCALING
from tests.pcluster.config.utils import get_cfnparam_definition, get_mocked_pcluster_config


@pytest.mark.parametrize(
    "section_definition, param_key, param_value, expected_value",
    [
        # Param
        (CLUSTER_SIT, "key_name", None, None),
        (CLUSTER_SIT, "key_name", "test", "test"),
        (CLUSTER_SIT, "key_name", "NONE", "NONE"),
        (CLUSTER_SIT, "base_os", "alinux", "alinux"),
        (CLUSTER_SIT, "base_os", "ubuntu1804", "ubuntu1804"),
        (CLUSTER_SIT, "base_os", "ubuntu1404", "ubuntu1404"),  # no longer supported value
        # BoolParam
        (CLUSTER_SIT, "encrypted_ephemeral", None, None),
        (CLUSTER_SIT, "encrypted_ephemeral", False, None),
        (CLUSTER_SIT, "encrypted_ephemeral", True, "true"),
        # IntParam
        (SCALING, "scaledown_idletime", None, None),
        (SCALING, "scaledown_idletime", 10, None),
        (SCALING, "scaledown_idletime", 3, "3"),
        # JsonParam
        (CLUSTER_SIT, "extra_json", None, None),
        (CLUSTER_SIT, "extra_json", {}, {}),
        (
            CLUSTER_SIT,
            "extra_json",
            {"cluster": {"cfn_scheduler_slots": "cores"}},
            '{"cluster": {"cfn_scheduler_slots": "cores"}}',
        ),
    ],
)
def test_param_to_file(mocker, section_definition, param_key, param_value, expected_value):
    section_label = "default"
    section_name = section_definition.get("key") + " " + section_label
    config_parser = configparser.ConfigParser()
    config_parser.add_section(section_name)

    pcluster_config = get_mocked_pcluster_config(mocker)

    param_definition, param_type = get_cfnparam_definition(section_definition, param_key)
    param = param_type(section_definition.get("key"), section_label, param_key, param_definition, pcluster_config)
    param.value = param_value or param_definition.get("default")
    param.to_file(config_parser)

    if expected_value:
        assert_that(config_parser.has_option(section_name, param_key))
        assert_that(config_parser.get(section_name, param_key)).is_equal_to(expected_value)
    else:
        assert_that(config_parser.has_option(section_name, param_key)).is_false()
