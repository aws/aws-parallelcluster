# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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


@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["p4d.24xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("os", "scheduler")
def test_nccl(scheduler, instance, pcluster_config_reader, clusters_factory, test_datadir):
    assert_that(instance, description="This test is currently meant only for P4d instances").is_equal_to("p4d.24xlarge")
    assert_that(scheduler, description="This test is currently meant only for Slurm scheduler").is_equal_to("slurm")
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_nccl_benchmarks(remote_command_executor, test_datadir, "openmpi", scheduler_commands)


def _test_nccl_benchmarks(remote_command_executor, test_datadir, mpi_module, scheduler_commands):
    remote_command_executor.run_remote_script(
        str(test_datadir / "init_nccl_benchmarks.sh"),
        args=[mpi_module],
        hide=True,
    )

    result = scheduler_commands.submit_script(
        str(test_datadir / "nccl_tests_submit_{0}.sh".format(mpi_module)), nodes=2
    )

    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    max_bandwidth = remote_command_executor.run_remote_command(
        "cat /shared/nccl_tests.out | tail -4 | head -1 | awk '{print $11}'"
    ).stdout

    # Expected bandwidth with 2 nodes, 8 tasks per node is about 27GB/s
    assert_that(float(max_bandwidth)).is_greater_than(26.0)
