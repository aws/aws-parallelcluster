# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import logging

import pytest

from tests.common.assertions import assert_head_node_is_running


@pytest.mark.usefixtures("instance", "scheduler", "os")
def test_byos(region, pcluster_config_reader, clusters_factory):
    """Test usage of a custom scheduler integration."""
    logging.info("Testing custom scheduler integration.")

    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)

    assert_head_node_is_running(region, cluster)
