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
import boto3
import pytest
from assertpy import assert_that
from tests.common.scaling_common import get_max_asg_capacity


@pytest.mark.regions(["us-west-1"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.oss(["alinux"])
@pytest.mark.usefixtures("os", "scheduler")
def test_update(region, pcluster_config_reader, clusters_factory):
    """
    Test 'pcluster update' command.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    max_queue_size = 5
    compute_instance = "c5.xlarge"

    cluster_config = pcluster_config_reader(max_queue_size=max_queue_size, compute_instance=compute_instance)
    cluster, factory = clusters_factory(cluster_config)
    _test_asg_size(region, cluster.cfn_name, max_queue_size)

    _test_update_max_queue(region, cluster, factory)


def _test_update_max_queue(region, cluster, factory):
    new_queue_size = 10
    _update_cluster_property(cluster, "max_queue_size", str(new_queue_size))

    factory.update_cluster(cluster)
    _test_asg_size(region, cluster.cfn_name, new_queue_size)


def _test_asg_size(region, stack_name, queue_size):
    asg_max_size = get_max_asg_capacity(region, stack_name)
    assert_that(asg_max_size).is_equal_to(queue_size)


def _update_cluster_property(cluster, property_name, property_value):
    cluster.config.set("cluster default", property_name, property_value)
    # update configuration file
    cluster.update()
