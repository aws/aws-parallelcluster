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

from pcluster.config.mappings import CLUSTER_SIT, SCALING
from tests.pcluster.config.utils import get_cfnparam_definition, get_mocked_pcluster_config


@pytest.mark.parametrize(
    "section_definition, param_key, param_value, expected_value",
    [
        # Param
        (CLUSTER_SIT, "key_name", None, "NONE"),
        (CLUSTER_SIT, "key_name", "test", "test"),
        (CLUSTER_SIT, "key_name", "NONE", "NONE"),
        # BoolParam
        (CLUSTER_SIT, "encrypted_ephemeral", None, "NONE"),
        (CLUSTER_SIT, "encrypted_ephemeral", True, "true"),
        (CLUSTER_SIT, "encrypted_ephemeral", False, "false"),
        # IntParam
        (SCALING, "scaledown_idletime", 10, "10"),
        (SCALING, "scaledown_idletime", 10, "10"),
        (SCALING, "scaledown_idletime", 3, "3"),
        (
            CLUSTER_SIT,
            "extra_json",
            {"cluster": {"cfn_scheduler_slots": "cores"}, "extra_key": "extra_value"},
            '{"cfncluster": {"cfn_scheduler_slots": "cores"}, "extra_key": "extra_value"}',
        ),
        (
            CLUSTER_SIT,
            "extra_json",
            {"cfncluster": {"cfn_scheduler_slots": "cores"}, "extra_key": "extra_value"},
            '{"cfncluster": {"cfn_scheduler_slots": "cores"}, "extra_key": "extra_value"}',
        ),
        # SpotPriceParam --> FloatParam
        (CLUSTER_SIT, "spot_price", None, "0"),
        (CLUSTER_SIT, "spot_price", 0.0009, "0.0009"),
        (CLUSTER_SIT, "spot_price", 0.0, "0"),
        (CLUSTER_SIT, "spot_price", 10, "10"),
        (CLUSTER_SIT, "spot_price", 3, "3"),
        # SharedDirParam
        (CLUSTER_SIT, "shared_dir", "test", "test"),
        (CLUSTER_SIT, "shared_dir", None, "/shared"),
        # AdditionalIamPoliciesParam
        (CLUSTER_SIT, "additional_iam_policies", None, "NONE"),
        (CLUSTER_SIT, "additional_iam_policies", [], "NONE"),
        (CLUSTER_SIT, "additional_iam_policies", ["policy1"], "policy1"),
        (CLUSTER_SIT, "additional_iam_policies", ["policy1", "policy2"], "policy1,policy2"),
    ],
)
def test_param_to_cfn_value(mocker, section_definition, param_key, param_value, expected_value):
    pcluster_config = get_mocked_pcluster_config(mocker)

    param_definition, param_type = get_cfnparam_definition(section_definition, param_key)
    param = param_type(section_definition.get("key"), "default", param_key, param_definition, pcluster_config)
    param.value = param_value
    cfn_value = param.get_cfn_value()
    assert_that(cfn_value).is_equal_to(expected_value)


@pytest.mark.parametrize(
    "section_definition, param_key, param_value, expected_cfn_params",
    [
        # Param
        (CLUSTER_SIT, "key_name", None, {"KeyName": "NONE"}),
        (CLUSTER_SIT, "key_name", "NONE", {"KeyName": "NONE"}),
        (CLUSTER_SIT, "key_name", "test", {"KeyName": "test"}),
        # BoolParam
        (CLUSTER_SIT, "encrypted_ephemeral", None, {"EncryptedEphemeral": "NONE"}),
        (CLUSTER_SIT, "encrypted_ephemeral", True, {"EncryptedEphemeral": "true"}),
        (CLUSTER_SIT, "encrypted_ephemeral", False, {"EncryptedEphemeral": "false"}),
        # IntParam
        (SCALING, "scaledown_idletime", None, {"ScaleDownIdleTime": "10"}),
        (SCALING, "scaledown_idletime", 10, {"ScaleDownIdleTime": "10"}),
        (SCALING, "scaledown_idletime", 3, {"ScaleDownIdleTime": "3"}),
        # SharedDirParam
        (CLUSTER_SIT, "shared_dir", "test", {"SharedDir": "test"}),
        # (CLUSTER_SIT, "shared_dir", {"ebs": [], "shared_dir": "test"}, {"SharedDir": "test"}),
        # (CLUSTER_SIT, "shared_dir", {"ebs": [{"label": "fake_ebs"}], "shared_dir": "unused_value"}, {}),
        # ArgsParam
        (CLUSTER_SIT, "pre_install_args", '"R wget"', {"PreInstallArgs": '\\"R wget\\"'}),
        (CLUSTER_SIT, "pre_install_args", "'R wget'", {"PreInstallArgs": "'R wget'"}),
        (CLUSTER_SIT, "pre_install_args", "R wget", {"PreInstallArgs": "R wget"}),
        (CLUSTER_SIT, "post_install_args", '"R wget"', {"PostInstallArgs": '\\"R wget\\"'}),
        (CLUSTER_SIT, "post_install_args", "'R wget'", {"PostInstallArgs": "'R wget'"}),
        (CLUSTER_SIT, "post_install_args", "R wget", {"PostInstallArgs": "R wget"}),
    ],
)
def test_param_to_cfn(mocker, section_definition, param_key, param_value, expected_cfn_params):
    pcluster_config = get_mocked_pcluster_config(mocker)

    param_definition, param_type = get_cfnparam_definition(section_definition, param_key)
    param = param_type(section_definition.get("key"), "default", param_key, param_definition, pcluster_config)
    param.value = param_value
    cfn_params = param.to_cfn()
    assert_that(cfn_params).is_equal_to(expected_cfn_params)
