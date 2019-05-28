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
from tests.common.schedulers_common import get_scheduler_commands


@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5n.18xlarge", "p3dn.24xlarge", "i3en.24xlarge"])
@pytest.mark.oss(["alinux", "centos7"])
@pytest.mark.schedulers(["sge", "slurm"])
@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_efa(scheduler, pcluster_config_reader, clusters_factory, test_datadir):
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
    _test_efa_mpi(remote_command_executor, scheduler, test_datadir)


def _test_efa_installed(remote_command_executor, scheduler):
    # Output contains:
    # 00:06.0 Ethernet controller: Amazon.com, Inc. Device efa0
    logging.info("Testing EFA Installed")
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    result = scheduler_commands.submit_interactive_command("/sbin/lspci")
    assert_that(result.stdout).contains("00:06.0 Ethernet controller: Amazon.com, Inc. Device efa0")


def _test_efa_mpi(remote_command_executor, scheduler, test_datadir):
    logging.info("Testing EFA Installed")
    # Compile mpi script
    result = remote_command_executor.run_remote_command(
        "/opt/amazon/efa/bin/mpicc -o mpi_hello_world mpi_hello_world.c",
        additional_files=[str(test_datadir / "mpi_hello_world.c")],
    ).stdout

    # submit script using additional files
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    result = scheduler_commands.submit_script(str(test_datadir / "{0}_submit.sh".format(scheduler)))
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
