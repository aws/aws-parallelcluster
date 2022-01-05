# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
# import logging
import json
import logging
import subprocess as sp

import pytest
from assertpy import assert_that
from tags_utils import (
    convert_tags_dicts_to_tags_list,
    get_compute_node_root_volume_tags,
    get_compute_node_tags,
    get_head_node_root_volume_tags,
    get_head_node_tags,
    get_main_stack_tags,
    get_shared_volume_tags,
)


@pytest.mark.usefixtures("region", "instance")
def test_tag_propagation(pcluster_config_reader, clusters_factory, scheduler, os):
    """
    Verify tags from various sources are propagated to the expected resources.

    The following resources are checked for tags:
    - main CFN stack
    - head node
    - head node's root EBS volume
    - compute node (traditional schedulers)
    - compute node's root EBS volume (traditional schedulers)
    - shared EBS volume
    """
    config_file_tags = {"ConfigFileTag": "ConfigFileTagValue"}
    version_tags = {"parallelcluster:version": get_pcluster_version()}
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    cluster_name_tags = {"parallelcluster:cluster-name": cluster.name}

    test_cases = [
        {
            "resource": "Main CloudFormation Stack",
            "tag_getter": get_main_stack_tags,
            "expected_tags": (version_tags, config_file_tags),
        },
        {
            "resource": "Head Node",
            "tag_getter": get_head_node_tags,
            "expected_tags": (
                cluster_name_tags,
                {"Name": "HeadNode", "parallelcluster:node-type": "HeadNode"},
            ),
        },
        {
            "resource": "Head Node Root Volume",
            "tag_getter": get_head_node_root_volume_tags,
            "expected_tags": (cluster_name_tags, {"parallelcluster:node-type": "HeadNode"}),
            "tag_getter_kwargs": {"cluster": cluster, "os": os},
        },
        {
            "resource": "Compute Node",
            "tag_getter": get_compute_node_tags,
            "expected_tags": (
                cluster_name_tags,
                {"Name": "Compute", "parallelcluster:node-type": "Compute"},
                config_file_tags,
            ),
            "skip": scheduler == "awsbatch",
        },
        {
            "resource": "Compute Node Root Volume",
            "tag_getter": get_compute_node_root_volume_tags,
            "expected_tags": (
                cluster_name_tags,
                {"parallelcluster:node-type": "Compute"},
                config_file_tags if scheduler == "slurm" else {},
            ),
            "tag_getter_kwargs": {"cluster": cluster, "os": os},
            "skip": scheduler == "awsbatch",
        },
        {
            "resource": "Shared EBS Volume",
            "tag_getter": get_shared_volume_tags,
            "expected_tags": (version_tags, config_file_tags),
        },
    ]
    for test_case in test_cases:
        if test_case.get("skip"):
            continue
        logging.info("Verifying tags were propagated to %s", test_case.get("resource"))
        tag_getter = test_case.get("tag_getter")
        # Assume tag getters use lone cluster object arg if none explicitly given
        tag_getter_args = test_case.get("tag_getter_kwargs", {"cluster": cluster})
        observed_tags = tag_getter(**tag_getter_args)
        expected_tags = test_case["expected_tags"]
        assert_that(observed_tags).contains(*convert_tags_dicts_to_tags_list(expected_tags))


def get_pcluster_version():
    """Return the installed version of the pclsuter CLI."""
    return json.loads(sp.check_output("pcluster version".split()).decode().strip()).get("version")
