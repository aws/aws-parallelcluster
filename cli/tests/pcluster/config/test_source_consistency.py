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

import json
import os

from assertpy import assert_that

import tests.pcluster.config.utils as utils
from pcluster.config.mappings import ALIASES, AWS, CLUSTER_SIT, CW_LOG, DCV, EBS, EFS, FSX, GLOBAL, RAID, SCALING, VPC
from tests.pcluster.config.defaults import CFN_CLI_RESERVED_PARAMS, CFN_SIT_CONFIG_NUM_OF_PARAMS, DefaultCfnParams

EXISTING_SECTIONS = [ALIASES, AWS, CLUSTER_SIT, CW_LOG, DCV, EBS, EFS, FSX, GLOBAL, RAID, SCALING, VPC]


def test_mapping_consistency():
    """Verify for typos or wrong keys in the mappings.py file."""
    # TODO: use jsonschema to validate mappings dict.
    for section_definition in EXISTING_SECTIONS:
        for section_key, _ in section_definition.items():
            assert_that(
                section_key,
                description="{0} is not allowed in {1} section definition".format(
                    section_key, section_definition.get("key")
                ),
            ).is_in(
                "type",
                "key",
                "default_label",
                "autocreate",
                "cfn_param_mapping",
                "params",
                "validators",
                "max_resources",
                "cluster_model",
            )

        for param_key, param_definition in section_definition.get("params").items():

            for param_definition_key, _ in param_definition.items():
                assert_that(
                    param_definition_key,
                    description="{0} is not allowed in {1} param definition".format(param_definition_key, param_key),
                ).is_in(
                    "type",
                    "cfn_param_mapping",
                    "allowed_values",
                    "validators",
                    "default",
                    "referred_section",
                    "update_policy",
                    "required",
                    "visibility",
                )
                # Update policy must be always specified
                assert_that(
                    param_definition.get("update_policy"),
                    description="Missing update policy for parameter '{0}'".format(param_key),
                ).is_not_none()


def test_defaults_consistency():
    """Verifies that the defaults values for the CFN parameters used in the tests are the same in the CFN template."""
    template_num_of_params = _get_pcluster_cfn_num_of_params()

    # verify that the number of parameters in the template is lower than the limit of 200 parameters
    # https://docs.aws.amazon.com/en_us/AWSCloudFormation/latest/UserGuide/parameters-section-structure.html
    assert_that(template_num_of_params).is_less_than_or_equal_to(200)

    # verify number of parameters used for tests with number of parameters in CFN template
    total_number_of_params = CFN_SIT_CONFIG_NUM_OF_PARAMS + len(CFN_CLI_RESERVED_PARAMS)
    assert_that(total_number_of_params).is_equal_to(template_num_of_params)

    # The EC2IAMPoicies parameter is expected to differ by default from the default value in the
    # CFN template. This is because CloudWatch logging is enabled by default, and the appropriate
    # policy is added to this parameter in a transparent fashion.
    ignored_params = CFN_CLI_RESERVED_PARAMS + ["EC2IAMPolicies"]

    # ClusterConfigMetadata parameter is expected to differ from the default value in the CFN template because config
    # metadata is generated dynamically based on user's configuration.
    ignored_params += ["ClusterConfigMetadata"]

    # ComputeInstanceType parameter is expected to differ from the default value in the CFN template because
    # it is dynamically generated based on the AWS region
    ignored_params += ["ComputeInstanceType"]

    cfn_params = [section_cfn_params.value for section_cfn_params in DefaultCfnParams]
    default_cfn_values = utils.merge_dicts(*cfn_params)

    # verify default parameter values used for tests with default values in CFN template
    pcluster_cfn_json = _get_pcluster_cfn_json()
    for param_key, param in pcluster_cfn_json["Parameters"].items():
        if param_key not in ignored_params:
            default_value = param.get("Default", None)
            if default_value:
                assert_that(default_value, description=param_key).is_equal_to(default_cfn_values.get(param_key, None))


def _get_pcluster_cfn_json():
    """Get main ParallelCluster CFN json file."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    json_file = os.path.join(current_dir, "..", "..", "..", "..", "cloudformation", "aws-parallelcluster.cfn.json")

    with open(json_file, "r") as f:
        pcluster_cfn_json = json.load(f)

    return pcluster_cfn_json


def _get_pcluster_cfn_num_of_params():
    """Get number of Parameters from main ParallelCluster CFN json."""
    pcluster_cfn_json = _get_pcluster_cfn_json()
    return len(pcluster_cfn_json["Parameters"])
