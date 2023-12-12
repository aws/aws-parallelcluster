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
from utils import get_compute_nodes_instance_ids

from tests.common.assertions import assert_no_errors_in_logs
from tests.common.mpi_common import _test_mpi
from tests.common.utils import fetch_instance_slots, run_system_analyzer


@pytest.mark.usefixtures("serial_execution_by_instance")
def test_efa(
    os,
    region,
    scheduler,
    instance,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    architecture,
    scheduler_commands_factory,
    request,
):
    """
    Test all EFA Features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    if architecture == "x86_64":
        head_node_instance = "c5.18xlarge"
    else:
        head_node_instance = "c6g.16xlarge"

    slots_per_instance = fetch_instance_slots(region, instance, multithreading_disabled=True)
    cluster_config = pcluster_config_reader(head_node_instance=head_node_instance)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    _test_efa_installation(scheduler_commands, remote_command_executor, efa_installed=True, partition="efa-enabled")
    _test_mpi(remote_command_executor, slots_per_instance, scheduler, scheduler_commands, partition="efa-enabled")
    logging.info("Running on Instances: {0}".format(get_compute_nodes_instance_ids(cluster.cfn_name, region)))

    run_system_analyzer(cluster, scheduler_commands_factory, request, partition="efa-enabled")

    _test_shm_transfer_is_enabled(scheduler_commands, remote_command_executor, partition="efa-enabled")

    if instance == "p4d.24xlarge" and os != "centos7":
        _test_nccl_benchmarks(remote_command_executor, test_datadir, "openmpi", scheduler_commands)

    assert_no_errors_in_logs(remote_command_executor, scheduler, skip_ice=True)


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
        assert_that(result.stdout).contains("1d0f:efa")
    else:
        assert_that(result.stdout).does_not_contain("1d0f:efa")

    # Check EFA interface not present on head node
    result = remote_command_executor.run_remote_command("lspci -n")
    assert_that(result.stdout).does_not_contain("1d0f:efa")


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


def _test_nccl_benchmarks(remote_command_executor, test_datadir, mpi_module, scheduler_commands):
    logging.info("Running NCCL benchmarks")
    remote_command_executor.run_remote_script(
        str(test_datadir / "nccl_benchmarks" / "init_nccl_benchmarks.sh"), args=[mpi_module], hide=True, timeout=600
    )

    result = scheduler_commands.submit_script(
        str(test_datadir / "nccl_benchmarks" / "nccl_tests_submit_{0}.sh".format(mpi_module)), nodes=2
    )

    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    result = remote_command_executor.run_remote_command("cat /shared/nccl_tests.out")
    logging.info(f"Test result is: {result}")

    # Expected output with NCCL_BENCHMARKS_VERSION='2.10.0', NCCL_VERSION='2.7.8-1' and OFI_NCCL_VERSION='1.1.1':
    #                                                       out-of-place                       in-place
    #       size         count      type   redop     time   algbw   busbw  error     time   algbw   busbw  error
    #        (B)    (elements)                       (us)  (GB/s)  (GB/s)            (us)  (GB/s)  (GB/s)
    # ...
    # 1073741824     268435456     float     sum    79531   13.50   26.58  2e-06    79371   13.53   26.63  2e-06
    #
    # --------
    # Expected output with NCCL_BENCHMARKS_VERSION='2.13.8', NCCL_VERSION='2.19.4-1' and OFI_NCCL_VERSION='1.7.4-aws':
    #                                                              out-of-place                       in-place
    #       size         count      type   redop    root     time   algbw   busbw #wrong     time   algbw   busbw #wrong
    #        (B)    (elements)                               (us)  (GB/s)  (GB/s)            (us)  (GB/s)  (GB/s)
    # ...
    # 1073741824     268435456     float     sum      -1    44023   24.39   45.73      0    43947   24.43   45.81      0

    # We are looking for packet size 1073741824, 268435456 elements and in-place busbw (GB/s).
    max_bandwidth = remote_command_executor.run_remote_command(
        "cat /shared/nccl_tests.out | grep -E '1073741824\\s+268435456' | awk '{print $12}'"
    ).stdout

    # Expected "in-place busbw" bandwidth with 2 nodes, 8 tasks per node is about 27GB/s
    assert_that(float(max_bandwidth)).is_greater_than(26.0)
