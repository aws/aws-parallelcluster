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

from assertpy import assert_that
from pcluster.config.mappings import CLUSTER, SCALING
from tests.pcluster.config.utils import get_mocked_pcluster_config, get_param_definition


@pytest.mark.parametrize(
    "section_definition, param_key, param_value, expected_value",
    [
        # Param
        (CLUSTER, "key_name", None, "NONE"),
        (CLUSTER, "key_name", "test", "test"),
        (CLUSTER, "key_name", "NONE", "NONE"),
        # BoolParam
        (CLUSTER, "encrypted_ephemeral", None, "NONE"),
        (CLUSTER, "encrypted_ephemeral", True, "true"),
        (CLUSTER, "encrypted_ephemeral", False, "false"),
        # IntParam
        (SCALING, "scaledown_idletime", 10, "10"),
        (SCALING, "scaledown_idletime", 10, "10"),
        (SCALING, "scaledown_idletime", 3, "3"),
        (
            CLUSTER,
            "extra_json",
            {"cluster": {"cfn_scheduler_slots": "cores"}, "extra_key": "extra_value"},
            '{"cfncluster": {"cfn_scheduler_slots": "cores"}, "extra_key": "extra_value"}',
        ),
        (
            CLUSTER,
            "extra_json",
            {"cfncluster": {"cfn_scheduler_slots": "cores"}, "extra_key": "extra_value"},
            '{"cfncluster": {"cfn_scheduler_slots": "cores"}, "extra_key": "extra_value"}',
        ),
        # SpotPriceParam --> FloatParam
        (CLUSTER, "spot_price", None, "0"),
        (CLUSTER, "spot_price", 0.0009, "0.0009"),
        (CLUSTER, "spot_price", 0.0, "0"),
        (CLUSTER, "spot_price", 10, "10"),
        (CLUSTER, "spot_price", 3, "3"),
        # SharedDirParam
        (CLUSTER, "shared_dir", "test", "test"),
        (CLUSTER, "shared_dir", None, "/shared"),
        # AdditionalIamPoliciesParam
        (CLUSTER, "additional_iam_policies", None, "NONE"),
        (CLUSTER, "additional_iam_policies", [], "NONE"),
        (CLUSTER, "additional_iam_policies", ["policy1"], "policy1"),
        (CLUSTER, "additional_iam_policies", ["policy1", "policy2"], "policy1,policy2"),
    ],
)
def test_param_to_cfn_value(mocker, section_definition, param_key, param_value, expected_value):
    pcluster_config = get_mocked_pcluster_config(mocker)

    param_definition, param_type = get_param_definition(section_definition, param_key)
    param = param_type(section_definition.get("key"), "default", param_key, param_definition, pcluster_config)
    param.value = param_value
    cfn_value = param.get_cfn_value()
    assert_that(cfn_value).is_equal_to(expected_value)


@pytest.mark.parametrize(
    "section_definition, param_key, param_value, expected_cfn_params",
    [
        # Param
        (CLUSTER, "key_name", None, {"KeyName": "NONE"}),
        (CLUSTER, "key_name", "NONE", {"KeyName": "NONE"}),
        (CLUSTER, "key_name", "test", {"KeyName": "test"}),
        # BoolParam
        (CLUSTER, "encrypted_ephemeral", None, {"EncryptedEphemeral": "NONE"}),
        (CLUSTER, "encrypted_ephemeral", True, {"EncryptedEphemeral": "true"}),
        (CLUSTER, "encrypted_ephemeral", False, {"EncryptedEphemeral": "false"}),
        # IntParam
        (SCALING, "scaledown_idletime", None, {"ScaleDownIdleTime": "10"}),
        (SCALING, "scaledown_idletime", 10, {"ScaleDownIdleTime": "10"}),
        (SCALING, "scaledown_idletime", 3, {"ScaleDownIdleTime": "3"}),
        # SharedDirParam
        (CLUSTER, "shared_dir", "test", {"SharedDir": "test"}),
        # (CLUSTER, "shared_dir", {"ebs": [], "shared_dir": "test"}, {"SharedDir": "test"}),
        # (CLUSTER, "shared_dir", {"ebs": [{"label": "fake_ebs"}], "shared_dir": "unused_value"}, {}),
    ],
)
def test_param_to_cfn(mocker, section_definition, param_key, param_value, expected_cfn_params):
    pcluster_config = get_mocked_pcluster_config(mocker)

    param_definition, param_type = get_param_definition(section_definition, param_key)
    param = param_type(section_definition.get("key"), "default", param_key, param_definition, pcluster_config)
    param.value = param_value
    cfn_params = param.to_cfn()
    assert_that(cfn_params).is_equal_to(expected_cfn_params)
