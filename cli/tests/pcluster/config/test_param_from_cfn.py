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
    "section_definition, param_key, cfn_value, expected_value",
    [
        # Param
        (CLUSTER_SIT, "key_name", "", None),
        (CLUSTER_SIT, "key_name", "NONE", None),
        (CLUSTER_SIT, "key_name", "fake_value", "fake_value"),
        (CLUSTER_SIT, "key_name", "test", "test"),
        # BoolParam
        (CLUSTER_SIT, "encrypted_ephemeral", "", False),
        (CLUSTER_SIT, "encrypted_ephemeral", "NONE", False),
        (CLUSTER_SIT, "encrypted_ephemeral", "wrong_value", False),
        (CLUSTER_SIT, "encrypted_ephemeral", "true", True),
        (CLUSTER_SIT, "encrypted_ephemeral", "false", False),
        # IntParam
        (SCALING, "scaledown_idletime", "", 10),
        (SCALING, "scaledown_idletime", "NONE", 10),
        (SCALING, "scaledown_idletime", "wrong_value", 10),
        (SCALING, "scaledown_idletime", "10", 10),
        (SCALING, "scaledown_idletime", "3", 3),
        # TODO FloatParam
        # JsonParam
        (CLUSTER_SIT, "extra_json", "", {}),
        (CLUSTER_SIT, "extra_json", "NONE", {}),
        (CLUSTER_SIT, "extra_json", '{"test": "test1"}', {"test": "test1"}),
        (
            CLUSTER_SIT,
            "extra_json",
            '{ "cluster" : { "cfn_scheduler_slots" : "cores" } }',
            {"cluster": {"cfn_scheduler_slots": "cores"}},
        ),
        (
            CLUSTER_SIT,
            "extra_json",
            '{ "cfncluster" : { "ganglia_enabled" : "true" } }',
            {"cfncluster": {"ganglia_enabled": "true"}},
        ),
        # Tags
        (CLUSTER_SIT, "tags", "", {}),
        (CLUSTER_SIT, "tags", "NONE", {}),
        (CLUSTER_SIT, "tags", '{"key": "value"}', {"key": "value"}),
        # SharedDirParam
        (CLUSTER_SIT, "shared_dir", "", "/shared"),
        (CLUSTER_SIT, "shared_dir", "NONE", "/shared"),
        (CLUSTER_SIT, "shared_dir", "fake_value", "fake_value"),
        (CLUSTER_SIT, "shared_dir", "test", "test"),
        # SpotPriceParam --> FloatParam
        (CLUSTER_SIT, "spot_price", "", 0.0),
        (CLUSTER_SIT, "spot_price", "NONE", 0.0),
        (CLUSTER_SIT, "spot_price", "wrong_value", 0.0),
        (CLUSTER_SIT, "spot_price", "10", 10),
        (CLUSTER_SIT, "spot_price", "3", 3),
        (CLUSTER_SIT, "spot_price", "0.0009", 0.0009),
        (CLUSTER_SIT, "spot_price", "0", 0.0),
        (CLUSTER_SIT, "spot_price", "0.00", 0.0),
        # SpotBidPercentageParam --> IntParam
        (CLUSTER_SIT, "spot_bid_percentage", "", 0),
        (CLUSTER_SIT, "spot_bid_percentage", "NONE", 0),
        (CLUSTER_SIT, "spot_bid_percentage", "wrong_value", 0),
        (CLUSTER_SIT, "spot_bid_percentage", "0.0", 0),
        (CLUSTER_SIT, "spot_bid_percentage", "10.0", 0),
        (CLUSTER_SIT, "spot_bid_percentage", "10", 10),
        # AdditionalIamPoliciesParam --> CommaSeparatedParam
        (CLUSTER_SIT, "additional_iam_policies", "", []),
        (CLUSTER_SIT, "additional_iam_policies", "NONE", []),
        (CLUSTER_SIT, "additional_iam_policies", "fake_value", ["fake_value"]),
        (CLUSTER_SIT, "additional_iam_policies", "test", ["test"]),
        (CLUSTER_SIT, "additional_iam_policies", "policy1,policy2", ["policy1", "policy2"]),
        (CLUSTER_SIT, "additional_iam_policies", "policy1, policy2", ["policy1", "policy2"]),
    ],
)
def test_param_from_cfn_value(mocker, section_definition, param_key, cfn_value, expected_value):
    """Test conversion from cfn value of simple parameters, that don't depends from multiple CFN parameters."""
    param_definition, param_type = get_cfnparam_definition(section_definition, param_key)

    pcluster_config = get_mocked_pcluster_config(mocker)

    param_value = param_type(
        section_definition.get("key"), "default", param_key, param_definition, pcluster_config
    ).get_value_from_string(cfn_value)
    assert_that(param_value).is_equal_to(expected_value)


@pytest.mark.parametrize(
    "section_definition, param_key, cfn_params_dict, expected_value",
    [
        # Param
        (CLUSTER_SIT, "key_name", {"KeyName": ""}, None),
        (CLUSTER_SIT, "key_name", {"KeyName": "NONE"}, None),
        (CLUSTER_SIT, "key_name", {"KeyName": "fake_value"}, "fake_value"),
        (CLUSTER_SIT, "key_name", {"KeyName": "test"}, "test"),
        # BoolParam
        (CLUSTER_SIT, "encrypted_ephemeral", {"EncryptedEphemeral": ""}, False),
        (CLUSTER_SIT, "encrypted_ephemeral", {"EncryptedEphemeral": "NONE"}, False),
        (CLUSTER_SIT, "encrypted_ephemeral", {"EncryptedEphemeral": "wrong_value"}, False),
        (CLUSTER_SIT, "encrypted_ephemeral", {"EncryptedEphemeral": "true"}, True),
        (CLUSTER_SIT, "encrypted_ephemeral", {"EncryptedEphemeral": "false"}, False),
        # IntParam
        (SCALING, "scaledown_idletime", {"ScaleDownIdleTime": "10"}, 10),
        (SCALING, "scaledown_idletime", {"ScaleDownIdleTime": "NONE"}, 10),
        (SCALING, "scaledown_idletime", {"ScaleDownIdleTime": "wrong_value"}, 10),
        (SCALING, "scaledown_idletime", {"ScaleDownIdleTime": "10"}, 10),
        (SCALING, "scaledown_idletime", {"ScaleDownIdleTime": "3"}, 3),
        # JsonParam
        (CLUSTER_SIT, "extra_json", {"ExtraJson": "NONE"}, {}),
        (CLUSTER_SIT, "extra_json", {"ExtraJson": '{"test": "test1"}'}, {"test": "test1"}),
        (
            CLUSTER_SIT,
            "extra_json",
            {"ExtraJson": '{ "cluster" : { "cfn_scheduler_slots" : "cores" } }'},
            {"cluster": {"cfn_scheduler_slots": "cores"}},
        ),
        (
            CLUSTER_SIT,
            "extra_json",
            {"ExtraJson": '{ "cfncluster" : { "cfn_scheduler_slots" : "cores" } }'},
            {"cfncluster": {"cfn_scheduler_slots": "cores"}},
        ),
        # AdditionalIamPoliciesParam --> CommaSeparatedParam
        (CLUSTER_SIT, "additional_iam_policies", {"EC2IAMPolicies": ""}, []),
        (CLUSTER_SIT, "additional_iam_policies", {"EC2IAMPolicies": "NONE"}, []),
        (CLUSTER_SIT, "additional_iam_policies", {"EC2IAMPolicies": "fake_value"}, ["fake_value"]),
        (CLUSTER_SIT, "additional_iam_policies", {"EC2IAMPolicies": "test"}, ["test"]),
        (CLUSTER_SIT, "additional_iam_policies", {"EC2IAMPolicies": "policy1,policy2"}, ["policy1", "policy2"]),
        (CLUSTER_SIT, "additional_iam_policies", {"EC2IAMPolicies": "policy1, policy2"}, ["policy1", "policy2"]),
        # ArgsParam
        (CLUSTER_SIT, "pre_install_args", {"PreInstallArgs": '\\"R wget\\"'}, '"R wget"'),
        (CLUSTER_SIT, "pre_install_args", {"PreInstallArgs": "'R wget'"}, "'R wget'"),
        (CLUSTER_SIT, "pre_install_args", {"PreInstallArgs": "R wget"}, "R wget"),
        (CLUSTER_SIT, "post_install_args", {"PostInstallArgs": '\\"R wget\\"'}, '"R wget"'),
        (CLUSTER_SIT, "post_install_args", {"PostInstallArgs": "'R wget'"}, "'R wget'"),
        (CLUSTER_SIT, "post_install_args", {"PostInstallArgs": "R wget"}, "R wget"),
    ],
)
def test_param_from_cfn(mocker, section_definition, param_key, cfn_params_dict, expected_value):
    """Test conversion of simple parameters, that don't depends from multiple CFN parameters."""
    param_definition, param_type = get_cfnparam_definition(section_definition, param_key)
    cfn_params = []
    for cfn_key, cfn_value in cfn_params_dict.items():
        cfn_params.append({"ParameterKey": cfn_key, "ParameterValue": cfn_value})

    pcluster_config = get_mocked_pcluster_config(mocker)

    param_type = param_type(section_definition.get("key"), "default", param_key, param_definition, pcluster_config)
    param = param_type.from_cfn_params(cfn_params)

    assert_that(param.value, description="param key {0}".format(param_key)).is_equal_to(expected_value)
