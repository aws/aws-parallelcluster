# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import pathlib

import pytest
from assertpy import assert_that
from utils import get_instance_info

NCCL_COMMON_DATADIR = pathlib.Path(__file__).parent / "data/nccl/"


def install_and_run_nccl_benchmarks(remote_command_executor, mpi_module, scheduler_commands, instance):
    logging.info("Running NCCL benchmarks")
    remote_command_executor.run_remote_script(
        str(NCCL_COMMON_DATADIR / "init_nccl_benchmarks.sh"), args=[mpi_module], hide=True, timeout=600
    )

    gpu_per_node = get_instance_info(instance)["GpuInfo"]["Gpus"][0]["Count"]

    result = scheduler_commands.submit_script(
        str(NCCL_COMMON_DATADIR / "nccl_tests_submit_{0}.sh".format(mpi_module)),
        nodes=2,
        ntasks_per_node=gpu_per_node,
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

    out_of_place_max_bandwidth = remote_command_executor.run_remote_command(
        "cat /shared/nccl_tests.out | grep -E '1073741824\\s+268435456' | awk '{print $8}'"
    ).stdout

    instance_bandwidth_dict = {
        # p4d.24xlarge - Expected "in-place busbw" bandwidth with 2 nodes, 8 tasks per node is about 27GB/s
        "p4d.24xlarge": 26.0,
        # p5.48xlarge - Expected "in-place busbw" bandwidth with 2 nodes, 8 tasks per node is about 250GB/s
        "p5.48xlarge": 250.0,
        "p6-b200.48xlarge": 300,
        "p6e-gb200.36xlarge": 500,
    }

    expected_bandwidth = instance_bandwidth_dict.get(instance)
    if expected_bandwidth is None:
        pytest.fail(f"Instance {instance} is not valid for multiple bandwidth tests")

    assert_that(float(max_bandwidth)).is_greater_than(expected_bandwidth)
    if instance == "p6e-gb200.36xlarge":
        # Check "out of place" bandwidth for p6e-GB200
        # because the GPUs are directly connected for different instances on the same ultra server.
        # The "out of place" bandwidth is expected to be similar to the in-place bandwidth.
        assert_that(float(out_of_place_max_bandwidth)).is_greater_than(expected_bandwidth)
