# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

import boto3
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor

from tests.common.assertions import assert_no_errors_in_logs
from tests.common.osu_common import run_individual_osu_benchmark
from tests.common.utils import fetch_instance_slots, get_installed_parallelcluster_version, run_system_analyzer

# We collected OSU benchmarks results for c5n.18xlarge only.
OSU_BENCHMARKS_INSTANCES = ["c5n.18xlarge"]


@pytest.mark.usefixtures("serial_execution_by_instance")
def test_osu(
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
    if instance not in OSU_BENCHMARKS_INSTANCES:
        raise Exception(
            f"OSU benchmarks can't be run on instance {instance}. "
            f"Only these instances are supported: {OSU_BENCHMARKS_INSTANCES}"
        )

    if architecture == "x86_64":
        head_node_instance = "c5.18xlarge"
    else:
        head_node_instance = "c6g.16xlarge"

    slots_per_instance = fetch_instance_slots(region, instance, multithreading_disabled=True)
    cluster_config = pcluster_config_reader(head_node_instance=head_node_instance)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    run_system_analyzer(cluster, scheduler_commands_factory, request, partition="efa-enabled")

    benchmark_failures = []

    # Run OSU benchmarks in efa-enabled queue.
    for mpi_version in mpi_variants:
        benchmark_failures.extend(
            _test_osu_benchmarks_pt2pt(
                mpi_version,
                remote_command_executor,
                scheduler_commands,
                test_datadir,
                os,
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
                os,
                instance,
                num_instances=32,
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

    assert_no_errors_in_logs(remote_command_executor, scheduler, skip_ice=True)


def _test_osu_benchmarks_pt2pt(
    mpi_version,
    remote_command_executor,
    scheduler_commands,
    test_datadir,
    os,
    instance,
    slots_per_instance,
    partition=None,
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
        failures = _check_osu_benchmarks_results(test_datadir, os, instance, mpi_version, benchmark_name, output)
        if failures > accepted_number_of_failures:
            failed_benchmarks.append(f"{mpi_version}-{benchmark_name}")

    return failed_benchmarks


def _test_osu_benchmarks_collective(
    mpi_version,
    remote_command_executor,
    scheduler_commands,
    test_datadir,
    os,
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
        failures = _check_osu_benchmarks_results(test_datadir, os, instance, mpi_version, benchmark_name, output)
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


def _check_osu_benchmarks_results(test_datadir, os, instance, mpi_version, benchmark_name, output):
    logging.info(output)
    # Check avg latency for all packet sizes
    failures = 0
    metric_data = []
    metric_namespace = "ParallelCluster/test_efa"
    for packet_size, value in re.findall(r"(\d+)\s+(\d+)\.", output):
        with open(
            str(test_datadir / "osu_benchmarks" / "results" / os / instance / mpi_version / benchmark_name),
            encoding="utf-8",
        ) as result:
            previous_result = re.search(rf"{packet_size}\s+(\d+)\.", result.read()).group(1)

            if benchmark_name == "osu_bibw":
                # Invert logic because osu_bibw is in MB/s
                tolerated_value = float(previous_result) - (float(previous_result) * 0.2)
                is_failure = int(value) < tolerated_value
            else:
                multiplier = 0.3 if benchmark_name == "osu_latency" else 0.2
                tolerated_value = float(previous_result) + max(float(previous_result) * multiplier, 10)

                is_failure = int(value) > tolerated_value

            message = (
                f"{mpi_version} - {benchmark_name} - packet size {packet_size}: "
                f"tolerated: {tolerated_value}, current: {value}"
            )

            dimensions = {
                "PclusterVersion": get_installed_parallelcluster_version(),
                "MpiVariant": mpi_version,
                "Instance": instance,
                "OsuBenchmarkName": benchmark_name,
                "PacketSize": packet_size,
                "OperatingSystem": os,
            }
            metric_data.append(
                {
                    "MetricName": "Latency",
                    "Dimensions": [{"Name": name, "Value": str(value)} for name, value in dimensions.items()],
                    "Value": int(value),
                    "Unit": "Microseconds",
                }
            )

            if is_failure:
                failures = failures + 1
                logging.error(message)
            else:
                logging.info(message)
    boto3.client("cloudwatch").put_metric_data(Namespace=metric_namespace, MetricData=metric_data)

    return failures
