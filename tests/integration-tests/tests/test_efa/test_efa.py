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
import logging

import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor


@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5n.18xlarge", "p3dn.24xlarge", "i3en.24xlarge"])
@pytest.mark.oss(["alinux", "centos7"])
@pytest.mark.schedulers(["sge", "slurm"])
@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_efa(region, pcluster_config_reader, clusters_factory):
    """
    Test all EFA Features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    scaledown_idletime = 3
    max_queue_size = 5
    cluster_config = pcluster_config_reader(scaledown_idletime=scaledown_idletime, max_queue_size=max_queue_size)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_efa_installed(remote_command_executor)


def _test_efa_installed(remote_command_executor):
    # Output contains:
    # 00:06.0 Ethernet controller: Amazon.com, Inc. Device efa0
    logging.info("Testing EFA Installed")
    version = remote_command_executor.run_remote_command("qrsh /sbin/lspci").stdout
    assert_that(version).contains("00:06.0 Ethernet controller: Amazon.com, Inc. Device efa0")
