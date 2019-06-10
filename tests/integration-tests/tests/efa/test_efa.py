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
import re

import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from tests.common.assertions import assert_no_errors_in_logs
from tests.common.mpi_common import _test_mpi
from tests.common.schedulers_common import get_scheduler_commands
from tests.common.utils import _fetch_instance_slots


@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5n.18xlarge", "p3dn.24xlarge", "i3en.24xlarge"])
@pytest.mark.oss(["alinux", "centos7", "ubuntu1604"])
@pytest.mark.schedulers(["sge", "slurm"])
def test_efa(region, scheduler, instance, os, pcluster_config_reader, clusters_factory, test_datadir):
    """
    Test all EFA Features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    max_queue_size = 2
    slots_per_instance = _fetch_instance_slots(region, instance)
    cluster_config = pcluster_config_reader(max_queue_size=max_queue_size)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    _test_efa_installed(scheduler_commands, remote_command_executor)
    _test_mpi(remote_command_executor, slots_per_instance, scheduler, os)
    _test_osu_benchmarks(remote_command_executor, scheduler_commands, test_datadir, slots_per_instance)

    assert_no_errors_in_logs(remote_command_executor, ["/var/log/sqswatcher", "/var/log/jobwatcher"])


def _test_efa_installed(scheduler_commands, remote_command_executor):
    # Output contains:
    # 00:06.0 Ethernet controller: Amazon.com, Inc. Device efa0
    logging.info("Testing EFA installed")
    result = scheduler_commands.submit_command("lspci > /shared/lspci.out")

    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    # Check EFA interface is present on compute node
    result = remote_command_executor.run_remote_command("cat /shared/lspci.out")
    assert_that(result.stdout).contains("00:06.0 Ethernet controller: Amazon.com, Inc. Device efa0")

    # Check EFA interface not present on master
    result = remote_command_executor.run_remote_command("lspci")
    assert_that(result.stdout).does_not_contain("00:06.0 Ethernet controller: Amazon.com, Inc. Device efa0")


def _test_osu_benchmarks(remote_command_executor, scheduler_commands, test_datadir, slots_per_instance):
    logging.info("Running OSU benchmarks")
    remote_command_executor.run_remote_script(str(test_datadir / "init_osu_benchmarks.sh"), hide=True)

    result = scheduler_commands.submit_script(str(test_datadir / "osu_submit.sh"), slots=2 * slots_per_instance)
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    output = remote_command_executor.run_remote_command("cat /shared/osu.out").stdout
    latency = re.search(r"0\s+(\d\d)\.", output).group(1)
    assert_that(int(latency)).is_less_than(20)
