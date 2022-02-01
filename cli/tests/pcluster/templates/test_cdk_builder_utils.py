# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from aws_cdk.core import CfnTag

from pcluster.constants import PCLUSTER_CLUSTER_NAME_TAG, PCLUSTER_NODE_TYPE_TAG
from pcluster.templates.cdk_builder_utils import dict_to_cfn_tags, get_cluster_tags, get_default_volume_tags


@pytest.mark.parametrize(
    "tags_dict, expected_result",
    [
        ({}, []),
        ({"key1": "value1"}, [CfnTag(key="key1", value="value1")]),
        (
            {"key1": "value1", "key2": "value2"},
            [CfnTag(key="key1", value="value1"), CfnTag(key="key2", value="value2")],
        ),
    ],
)
def test_dict_to_cfn_tags(tags_dict, expected_result):
    """Verify that dict to CfnTag conversion works as expected."""
    assert_that(dict_to_cfn_tags(tags_dict)).is_equal_to(expected_result)


@pytest.mark.parametrize(
    "stack_name, raw_dict, expected_result",
    [
        ("STACK_NAME", True, {PCLUSTER_CLUSTER_NAME_TAG: "STACK_NAME"}),
        ("STACK_NAME", False, [CfnTag(key=PCLUSTER_CLUSTER_NAME_TAG, value="STACK_NAME")]),
    ],
)
def test_get_cluster_tags(stack_name, raw_dict, expected_result):
    """Verify cluster tags."""
    assert_that(get_cluster_tags(stack_name, raw_dict)).is_equal_to(expected_result)


@pytest.mark.parametrize(
    "stack_name, node_type, raw_dict, expected_result",
    [
        ("STACK_NAME", "HeadNode", True, {PCLUSTER_CLUSTER_NAME_TAG: "STACK_NAME", PCLUSTER_NODE_TYPE_TAG: "HeadNode"}),
        ("STACK_NAME", "Compute", True, {PCLUSTER_CLUSTER_NAME_TAG: "STACK_NAME", PCLUSTER_NODE_TYPE_TAG: "Compute"}),
        (
            "STACK_NAME",
            "HeadNode",
            False,
            [
                CfnTag(key=PCLUSTER_CLUSTER_NAME_TAG, value="STACK_NAME"),
                CfnTag(key=PCLUSTER_NODE_TYPE_TAG, value="HeadNode"),
            ],
        ),
        (
            "STACK_NAME",
            "Compute",
            False,
            [
                CfnTag(key=PCLUSTER_CLUSTER_NAME_TAG, value="STACK_NAME"),
                CfnTag(key=PCLUSTER_NODE_TYPE_TAG, value="Compute"),
            ],
        ),
    ],
)
def test_get_default_volume_tags(stack_name, node_type, raw_dict, expected_result):
    """Verify default volume tags."""
    assert_that(get_default_volume_tags(stack_name, node_type, raw_dict)).is_equal_to(expected_result)
