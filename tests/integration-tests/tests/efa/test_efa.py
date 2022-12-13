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
from tests.common.osu_common import run_individual_osu_benchmark
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
    network_interfaces_count,
    mpi_variants,
    scheduler_commands_factory,
    request,
):
    """
    Test all EFA Features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    # We collected OSU benchmarks results for c5n.18xlarge only.
    osu_benchmarks_instances = ["c5n.18xlarge"]

    # 32 instances are required to see performance differences in collective OSU benchmarks.
    max_queue_size = 32 if instance in osu_benchmarks_instances else 2

    if architecture == "x86_64":
        head_node_instance = "c5.18xlarge"
    else:
        head_node_instance = "c6g.16xlarge"

    slots_per_instance = fetch_instance_slots(region, instance, multithreading_disabled=True)
    cluster_config = pcluster_config_reader(max_queue_size=max_queue_size, head_node_instance=head_node_instance)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    _test_efa_installation(scheduler_commands, remote_command_executor, efa_installed=True, partition="efa-enabled")
    _test_mpi(remote_command_executor, slots_per_instance, scheduler, scheduler_commands, partition="efa-enabled")
    logging.info("Running on Instances: {0}".format(get_compute_nodes_instance_ids(cluster.cfn_name, region)))

    run_system_analyzer(cluster, scheduler_commands_factory, request, partition="efa-enabled")

    if instance in osu_benchmarks_instances:
        benchmark_failures = []

        # Run OSU benchmarks in efa-enabled queue.
        for mpi_version in mpi_variants:
            benchmark_failures.extend(
                _test_osu_benchmarks_pt2pt(
                    mpi_version,
                    remote_command_executor,
                    scheduler_commands,
                    test_datadir,
                    instance,
                    slots_per_instance,
                    partition="efa-enabled",
                )
            )
            benchmark_failures.extend(
                _test_osu_benchmarks_collective(
                    mpi_version,
                    remote_command_executor,
                    scheduler_commands,
                    test_datadir,
                    instance,
                    num_instances=max_queue_size,
                    slots_per_instance=slots_per_instance,
                    partition="efa-enabled",
                )
            )
        assert_that(benchmark_failures, description="Some OSU benchmarks are failing").is_empty()

    if network_interfaces_count > 1:
        _test_osu_benchmarks_multiple_bandwidth(
            instance,
            remote_command_executor,
            scheduler_commands,
            test_datadir,
            slots_per_instance,
            partition="efa-enabled",
        )
    _test_shm_transfer_is_enabled(scheduler_commands, remote_command_executor, partition="efa-enabled")

    if instance == "p4d.24xlarge" and os != "centos7":
        _test_nccl_benchmarks(remote_command_executor, test_datadir, "openmpi", scheduler_commands)

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
        assert_that(result.stdout).contains("1d0f:efa")
    else:
        assert_that(result.stdout).does_not_contain("1d0f:efa")

    # Check EFA interface not present on head node
    result = remote_command_executor.run_remote_command("lspci -n")
    assert_that(result.stdout).does_not_contain("1d0f:efa")


def _test_osu_benchmarks_pt2pt(
    mpi_version, remote_command_executor, scheduler_commands, test_datadir, instance, slots_per_instance, partition=None
):
    # OSU pt2pt benchmarks cannot be executed with more than 2 MPI ranks.
    # Run them in 2 instances with 1 proc per instance, defined by map-by parameter.
    num_instances = 2
    # Accept a max number of 4 failures on a total of 23-24 packet size tests.
    accepted_number_of_failures = 4

    failed_benchmarks = []
    for benchmark_name in ["osu_latency", "osu_bibw"]:
        _, output = run_individual_osu_benchmark(
            mpi_version,
            "pt2pt",
            benchmark_name,
            partition,
            remote_command_executor,
            scheduler_commands,
            num_instances,
            slots_per_instance,
            test_datadir,
        )
        failures = _check_osu_benchmarks_results(test_datadir, instance, mpi_version, benchmark_name, output)
        if failures > accepted_number_of_failures:
            failed_benchmarks.append(f"{mpi_version}-{benchmark_name}")

    return failed_benchmarks


def _test_osu_benchmarks_collective(
    mpi_version,
    remote_command_executor,
    scheduler_commands,
    test_datadir,
    instance,
    num_instances,
    slots_per_instance,
    partition=None,
):
    # Accept a max number of 3 failures on a total of 19-21 packet size tests.
    accepted_number_of_failures = 3

    failed_benchmarks = []
    for benchmark_name in ["osu_allgather", "osu_bcast", "osu_allreduce", "osu_alltoall"]:
        _, output = run_individual_osu_benchmark(
            mpi_version,
            "collective",
            benchmark_name,
            partition,
            remote_command_executor,
            scheduler_commands,
            num_instances,
            slots_per_instance,
            test_datadir,
            timeout=24,
        )
        failures = _check_osu_benchmarks_results(test_datadir, instance, mpi_version, benchmark_name, output)
        if failures > accepted_number_of_failures:
            failed_benchmarks.append(f"{mpi_version}-{benchmark_name}")

    return failed_benchmarks


def _test_osu_benchmarks_multiple_bandwidth(
    instance, remote_command_executor, scheduler_commands, test_datadir, slots_per_instance, partition=None
):
    instance_bandwidth_dict = {
        # Expected bandwidth for p4d and p4de (4 * 100 Gbps NICS -> declared NetworkPerformance 400 Gbps):
        # OMPI 4.1.0: ~330Gbps = 41250MB/s with Placement Group
        # OMPI 4.1.0: ~252Gbps = 31550MB/s without Placement Group
        # OMPI 4.0.5: ~95Gbps = 11875MB/s with Placement Group
        "p4d.24xlarge": 30000,  # Equivalent to a theoretical maximum of a single 240Gbps card
        # 4 100 Gbps NICS -> declared NetworkPerformance 400 Gbps
        "p4de.24xlarge": 30000,  # Equivalent to a theoretical maximum of a single 240Gbps card
        # 2 up to 170 Gbps NICS -> declared NetworkPerformance 200 Gbps
        "hpc6id.32xlarge": 23000,  # Equivalent to a theoretical maximum of a single 184Gbps card
        # 8 100 Gbps NICS -> declared NetworkPerformance 800 Gbps
        "trn1.32xlarge": 80000,  # Equivalent to a theoretical maximum of a single 640Gbps card
    }
    num_instances = 2
    run_individual_osu_benchmark(
        "openmpi",
        "mbw_mr",
        "osu_mbw_mr",
        partition,
        remote_command_executor,
        scheduler_commands,
        num_instances,
        slots_per_instance,
        test_datadir,
    )
    max_bandwidth = remote_command_executor.run_remote_command(
        "cat /shared/osu_mbw_mr.out | tail -n +4 | awk '{print $2}' | sort -n | tail -n 1"
    ).stdout

    expected_bandwidth = instance_bandwidth_dict.get(instance)
    if expected_bandwidth is None:
        pytest.fail(f"Instance {instance} is not valid for multiple bandwidth tests")

    assert_that(float(max_bandwidth)).is_greater_than(expected_bandwidth)


def _check_osu_benchmarks_results(test_datadir, instance, mpi_version, benchmark_name, output):
    logging.info(output)
    # Check avg latency for all packet sizes
    failures = 0
    for packet_size, value in re.findall(r"(\d+)\s+(\d+)\.", output):
        with open(
            str(test_datadir / "osu_benchmarks" / "results" / instance / mpi_version / benchmark_name), encoding="utf-8"
        ) as result:
            previous_result = re.search(rf"{packet_size}\s+(\d+)\.", result.read()).group(1)

            if benchmark_name == "osu_bibw":
                # Invert logic because osu_bibw is in MB/s
                tolerated_value = float(previous_result) - (float(previous_result) * 0.2)
                is_failure = int(value) < tolerated_value
            else:
                # Use a tolerance of 10us for 2 digits values.
                # For 3+ digits values use a 20% tolerance, except for the higher-variance latency benchmark.
                if len(previous_result) <= 2:
                    accepted_tolerance = 10
                else:
                    multiplier = 0.3 if benchmark_name == "osu_latency" else 0.2
                    accepted_tolerance = float(previous_result) * multiplier
                tolerated_value = float(previous_result) + accepted_tolerance

                is_failure = int(value) > tolerated_value

            message = (
                f"{mpi_version} - {benchmark_name} - packet size {packet_size}: "
                f"tolerated: {tolerated_value}, current: {value}"
            )

            if is_failure:
                failures = failures + 1
                logging.error(message)
            else:
                logging.info(message)

    return failures


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

    max_bandwidth = remote_command_executor.run_remote_command(
        "cat /shared/nccl_tests.out | tail -4 | head -1 | awk '{print $11}'"
    ).stdout

    # Expected bandwidth with 2 nodes, 8 tasks per node is about 27GB/s
    assert_that(float(max_bandwidth)).is_greater_than(26.0)
