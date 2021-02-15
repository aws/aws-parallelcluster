# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import pytest
from assertpy import assert_that
from utils import get_compute_nodes_instance_ids


@pytest.mark.dimensions("us-west-2", "c5.xlarge", "alinux2", "slurm")
@pytest.mark.dimensions("eu-west-2", "c5.xlarge", "centos7", "sge")
@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_cluster_in_private_subnet(region, pcluster_config_reader, clusters_factory):
    # This test just creates a cluster in the private subnet and just checks that no failures occur
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    assert_that(cluster).is_not_none()

    assert_that(len(get_compute_nodes_instance_ids(cluster.cfn_name, region))).is_equal_to(1)
