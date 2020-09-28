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
from remote_command_executor import RemoteCommandExecutor

from tests.common.schedulers_common import get_scheduler_commands


@pytest.mark.regions(["us-west-2"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["sge", "slurm"])
@pytest.mark.oss(["centos7", "centos8", "alinux2", "ubuntu1804"])
@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
def test_spot_default(scheduler, pcluster_config_reader, clusters_factory):
    """Test that a cluster with spot instances can be created with default spot_price_value."""
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    assert_that(scheduler_commands.compute_nodes_count()).is_equal_to(1)
