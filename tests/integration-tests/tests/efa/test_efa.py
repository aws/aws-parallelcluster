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
from utils import get_compute_nodes_instance_ids

from tests.common.assertions import assert_no_errors_in_logs
from tests.common.mpi_common import _test_mpi
from tests.common.schedulers_common import get_scheduler_commands
from tests.common.utils import fetch_instance_slots


@pytest.mark.regions(["us-east-1", "us-gov-west-1"])
@pytest.mark.instances(["c5n.18xlarge", "p3dn.24xlarge", "i3en.24xlarge"])
@pytest.mark.schedulers(["sge", "slurm"])
@pytest.mark.usefixtures("os")
def test_sit_efa(region, scheduler, instance, pcluster_config_reader, clusters_factory, test_datadir):
    """
    Test all EFA Features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    max_queue_size = 2
    slots_per_instance = fetch_instance_slots(region, instance)
    cluster_config = pcluster_config_reader(max_queue_size=max_queue_size)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    _test_efa_installation(scheduler_commands, remote_command_executor, efa_installed=True)
    _test_mpi(remote_command_executor, slots_per_instance, scheduler)
    logging.info("Running on Instances: {0}".format(get_compute_nodes_instance_ids(cluster.cfn_name, region)))
    _test_osu_benchmarks("openmpi", remote_command_executor, scheduler_commands, test_datadir, slots_per_instance)
    _test_osu_benchmarks("intelmpi", remote_command_executor, scheduler_commands, test_datadir, slots_per_instance)
    _test_shm_transfer_is_enabled(scheduler_commands, remote_command_executor)

    assert_no_errors_in_logs(remote_command_executor, scheduler)


@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5n.18xlarge"])
@pytest.mark.oss(["alinux2"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("os")
def test_hit_efa(region, scheduler, instance, pcluster_config_reader, clusters_factory, test_datadir):
    """
    Test all EFA Features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    max_queue_size = 2
    slots_per_instance = fetch_instance_slots(region, instance)
    cluster_config = pcluster_config_reader(max_queue_size=max_queue_size)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    _test_efa_installation(scheduler_commands, remote_command_executor, efa_installed=True, partition="efa-enabled")
    _test_efa_installation(scheduler_commands, remote_command_executor, efa_installed=False, partition="efa-disabled")
    _test_mpi(remote_command_executor, slots_per_instance, scheduler, partition="efa-enabled")
    logging.info("Running on Instances: {0}".format(get_compute_nodes_instance_ids(cluster.cfn_name, region)))
    _test_osu_benchmarks(
        "openmpi",
        remote_command_executor,
        scheduler_commands,
        test_datadir,
        slots_per_instance,
        partition="efa-enabled",
    )
    _test_osu_benchmarks(
        "intelmpi",
        remote_command_executor,
        scheduler_commands,
        test_datadir,
        slots_per_instance,
        partition="efa-enabled",
    )
    _test_shm_transfer_is_enabled(scheduler_commands, remote_command_executor, partition="efa-enabled")

    assert_no_errors_in_logs(remote_command_executor, scheduler)


def _test_efa_installation(scheduler_commands, remote_command_executor, efa_installed=True, partition=None):
    # Output contains:
    # 00:06.0 Ethernet controller: Amazon.com, Inc. Device efa0
    logging.info("Testing EFA installed")
    if partition:
        result = scheduler_commands.submit_command("lspci -n > /shared/lspci.out", partition=partition)
    else:
        result = scheduler_commands.submit_command("lspci -n > /shared/lspci.out")

    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    # Check if EFA interface is on compute node
    result = remote_command_executor.run_remote_command("cat /shared/lspci.out")
    if efa_installed:
        assert_that(result.stdout).contains("1d0f:efa0")
    else:
        assert_that(result.stdout).does_not_contain("1d0f:efa0")

    # Check EFA interface not present on master
    result = remote_command_executor.run_remote_command("lspci -n")
    assert_that(result.stdout).does_not_contain("1d0f:efa0")


def _test_osu_benchmarks(
    mpi_version, remote_command_executor, scheduler_commands, test_datadir, slots_per_instance, partition=None
):
    logging.info("Running OSU benchmarks for {0}".format(mpi_version))
    remote_command_executor.run_remote_script(
        str(test_datadir / "init_osu_benchmarks.sh"),
        args=[mpi_version],
        hide=True,
        additional_files=[str(test_datadir / "osu-micro-benchmarks-5.6.3.tar.gz")],
    )
    if partition:
        result = scheduler_commands.submit_script(
            str(test_datadir / "osu_submit_{0}.sh".format(mpi_version)),
            slots=2 * slots_per_instance,
            partition=partition,
        )
    else:
        result = scheduler_commands.submit_script(
            str(test_datadir / "osu_submit_{0}.sh".format(mpi_version)), slots=2 * slots_per_instance
        )
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    output = remote_command_executor.run_remote_command("cat /shared/osu.out").stdout
    latency = re.search(r"0\s+(\d\d)\.", output).group(1)
    assert_that(int(latency)).is_less_than_or_equal_to(24)


def _test_shm_transfer_is_enabled(scheduler_commands, remote_command_executor, partition=None):
    logging.info("Testing SHM Transfer is enabled")
    if partition:
        result = scheduler_commands.submit_command("fi_info -p efa 2>&1 > /shared/fi_info.out", partition=partition)
    else:
        result = scheduler_commands.submit_command("fi_info -p efa 2>&1 > /shared/fi_info.out")
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
    result = remote_command_executor.run_remote_command("cat /shared/fi_info.out")
    assert_that(result.stdout).does_not_contain("SHM transfer will be disabled because of ptrace protection")
