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
import os as os_lib
import re
from shutil import copyfile

import boto3
import pytest
from assertpy import assert_that
from jinja2 import Environment, FileSystemLoader
from remote_command_executor import RemoteCommandExecutor
from utils import get_compute_nodes_instance_ids

from tests.common.mpi_common import _test_mpi
from tests.common.schedulers_common import get_scheduler_commands
from tests.common.utils import fetch_instance_slots, run_system_analyzer


@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5n.18xlarge"])
@pytest.mark.oss(["alinux2"])
@pytest.mark.schedulers(["slurm"])
def test_hit_efa(
    os,
    region,
    scheduler,
    instance,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    architecture,
    network_interfaces_count,
    s3_bucket_factory,
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
        multithreading_disabled = True
    else:
        head_node_instance = "c6g.16xlarge"
        multithreading_disabled = False

    slots_per_instance = fetch_instance_slots(region, instance, multithreading_disabled=multithreading_disabled)

    # Post-install script to use P4d targeted ODCR
    bucket_name = ""
    if instance == "p4d.24xlarge":
        bucket_name = s3_bucket_factory()
        bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
        bucket.upload_file(str(test_datadir / "run_instance_override.sh"), "run_instance_override.sh")

    cluster_config = pcluster_config_reader(
        max_queue_size=max_queue_size,
        head_node_instance=head_node_instance,
        multithreading_disabled=multithreading_disabled,
        bucket_name=bucket_name,
    )

    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    _test_efa_installation(scheduler_commands, remote_command_executor, efa_installed=True, partition="efa-enabled")
    _test_mpi(remote_command_executor, slots_per_instance, scheduler, partition="efa-enabled")
    logging.info("Running on Instances: {0}".format(get_compute_nodes_instance_ids(cluster.cfn_name, region)))

    run_system_analyzer(cluster, scheduler, request, partition="efa-enabled")

    if instance in osu_benchmarks_instances:
        benchmark_failures = []
        mpi_versions = ["openmpi"]
        if architecture == "x86_64":
            mpi_versions.append("intelmpi")

        for mpi_version in mpi_versions:
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
                    num_of_instances=max_queue_size,
                    slots_per_instance=slots_per_instance,
                    partition="efa-enabled",
                )
            )
        assert_that(benchmark_failures, description="Some OSU benchmarks are failing").is_empty()

    if network_interfaces_count > 1:
        _test_osu_benchmarks_multiple_bandwidth(
            remote_command_executor, scheduler_commands, test_datadir, slots_per_instance, partition="efa-enabled"
        )
    _test_shm_transfer_is_enabled(scheduler_commands, remote_command_executor, partition="efa-enabled")

    if instance == "p4d.24xlarge" and os != "centos7":
        _test_nccl_benchmarks(remote_command_executor, test_datadir, "openmpi", scheduler_commands)


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
    num_of_instances = 2
    # Accept a max number of 3 failures on a total of 19-23 tests.
    accepted_number_of_failures = 3

    failed_benchmarks = []
    for benchmark_name in ["osu_latency", "osu_bibw"]:
        output = run_osu_benchmarks(
            mpi_version,
            "pt2pt",
            benchmark_name,
            partition,
            remote_command_executor,
            scheduler_commands,
            num_of_instances,
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
    num_of_instances,
    slots_per_instance,
    partition=None,
):
    # OSU collective benchmarks can be executed with any number of instances,
    # 4 instances are enough to see performance differences with c5n.18xlarge.

    # Accept a max number of 4 failures on a total of 23-24 tests.
    accepted_number_of_failures = 4

    failed_benchmarks = []
    for benchmark_name in ["osu_allgather", "osu_bcast", "osu_allreduce", "osu_alltoall"]:
        output = run_osu_benchmarks(
            mpi_version,
            "collective",
            benchmark_name,
            partition,
            remote_command_executor,
            scheduler_commands,
            num_of_instances,
            slots_per_instance,
            test_datadir,
        )
        failures = _check_osu_benchmarks_results(test_datadir, instance, mpi_version, benchmark_name, output)
        if failures > accepted_number_of_failures:
            failed_benchmarks.append(f"{mpi_version}-{benchmark_name}")

    return failed_benchmarks


def _test_osu_benchmarks_multiple_bandwidth(
    remote_command_executor, scheduler_commands, test_datadir, slots_per_instance, partition=None
):
    num_of_instances = 2
    run_osu_benchmarks(
        "openmpi",
        "mbw_mr",
        "osu_mbw_mr",
        partition,
        remote_command_executor,
        scheduler_commands,
        num_of_instances,
        slots_per_instance,
        test_datadir,
    )
    max_bandwidth = remote_command_executor.run_remote_command(
        "cat /shared/osu_mbw_mr.out | tail -n +4 | awk '{print $2}' | sort -n | tail -n 1"
    ).stdout

    # Expected bandwidth with 4 NICS:
    # OMPI 4.1.0: ~330Gbps = 41250MB/s with Placement Group
    # OMPI 4.1.0: ~252Gbps = 31550MB/s without Placement Group
    # OMPI 4.0.5: ~95Gbps = 11875MB/s with Placement Group
    expected_bandwidth = 30000
    assert_that(float(max_bandwidth)).is_greater_than(expected_bandwidth)


def run_osu_benchmarks(
    mpi_version,
    benchmark_group,
    benchmark_name,
    partition,
    remote_command_executor,
    scheduler_commands,
    num_of_instances,
    slots_per_instance,
    test_datadir,
):
    osu_benchmark_version = "5.7.1"
    logging.info(f"Running OSU benchmark {osu_benchmark_version}: {benchmark_name} for {mpi_version}")

    # Init OSU benchmarks
    init_script = _render_jinja_template(
        template_file_path=test_datadir / "init_osu_benchmarks.sh", osu_benchmark_version=osu_benchmark_version
    )
    remote_command_executor.run_remote_script(
        str(init_script),
        args=[mpi_version],
        hide=True,
        additional_files=[
            str(test_datadir / "osu_benchmarks" / f"osu-micro-benchmarks-{osu_benchmark_version}.tgz"),
            str(test_datadir / "osu_benchmarks" / "config.guess"),
            str(test_datadir / "osu_benchmarks" / "config.sub"),
        ],
    )

    # Prepare submission script and pass to the scheduler for the job submission
    copyfile(
        test_datadir / f"osu_{benchmark_group}_submit_{mpi_version}.sh",
        test_datadir / f"osu_{benchmark_group}_submit_{mpi_version}_{benchmark_name}.sh",
    )
    slots = num_of_instances * slots_per_instance
    submission_script = _render_jinja_template(
        template_file_path=test_datadir / f"osu_{benchmark_group}_submit_{mpi_version}_{benchmark_name}.sh",
        benchmark_name=benchmark_name,
        osu_benchmark_version=osu_benchmark_version,
        num_of_processes=slots,
    )
    if partition:
        result = scheduler_commands.submit_script(str(submission_script), slots=slots, partition=partition)
    else:
        result = scheduler_commands.submit_script(str(submission_script), slots=slots)
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    output = remote_command_executor.run_remote_command(f"cat /shared/{benchmark_name}.out").stdout
    return output


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


def _render_jinja_template(template_file_path, **kwargs):
    file_loader = FileSystemLoader(str(os_lib.path.dirname(template_file_path)))
    env = Environment(loader=file_loader)
    rendered_template = env.get_template(os_lib.path.basename(template_file_path)).render(**kwargs)
    with open(template_file_path, "w") as f:
        f.write(rendered_template)
    return template_file_path


def _test_nccl_benchmarks(remote_command_executor, test_datadir, mpi_module, scheduler_commands):
    logging.info("Running NCCL benchmarks")
    remote_command_executor.run_remote_script(
        str(test_datadir / "nccl_benchmarks" / "init_nccl_benchmarks.sh"), args=[mpi_module], hide=True, timeout=600
    )

    result = scheduler_commands.submit_script(
        str(test_datadir / "nccl_benchmarks" / f"nccl_tests_submit_{mpi_module}.sh"), nodes=2
    )

    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    max_bandwidth = remote_command_executor.run_remote_command(
        "cat /shared/nccl_tests.out | tail -4 | head -1 | awk '{print $11}'"
    ).stdout

    # Expected bandwidth with 2 nodes, 8 tasks per node is about 27GB/s
    assert_that(float(max_bandwidth)).is_greater_than(26.0)
