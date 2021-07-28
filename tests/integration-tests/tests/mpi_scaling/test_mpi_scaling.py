# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
# express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import logging

import pytest
import time
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from utils import get_compute_nodes_instance_ids

from tests.common.assertions import assert_no_errors_in_logs
from tests.common.schedulers_common import get_scheduler_commands
from tests.common.utils import fetch_instance_slots

TOTAL_MPI_RANKS = 5000


@pytest.mark.regions(["us-east-1", "us-gov-west-1"])
@pytest.mark.instances(["c5n.18xlarge", "c6gn.16xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("os")
def test_mpi_scaling(region, scheduler, instance, pcluster_config_reader, clusters_factory,
                     test_datadir, architecture):
    """
    Test large scale MPI runs for functionality. No performance tests.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """

    slots_per_instance = fetch_instance_slots(region, instance)
    # Hyper threads disabled
    slots_per_instance = slots_per_instance // 2
    max_queue_size = ceiling_division(TOTAL_MPI_RANKS, slots_per_instance)
    cluster_config = pcluster_config_reader(max_queue_size=max_queue_size)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    logging.info("Running on Instances: {0}".format(
        get_compute_nodes_instance_ids(cluster.cfn_name, region)
    ))

    _test_osu_benchmarks("openmpi", remote_command_executor, scheduler_commands, test_datadir,
                         TOTAL_MPI_RANKS)
    if architecture == "x86_64":
        _test_osu_benchmarks("intelmpi", remote_command_executor, scheduler_commands, test_datadir,
                             TOTAL_MPI_RANKS)

    assert_no_errors_in_logs(remote_command_executor, scheduler)


def ceiling_division(n, d):
    return -(n // -d)


def _test_osu_benchmarks(
    mpi_version, remote_command_executor, scheduler_commands, test_datadir, slots, partition=None
):
    """
    Run osu_alltoall & osu_igatherv on max available instances (over 5000 ranks)
    Run smaller osu_alltoallv on more than 64 ranks per instance (on c5n)
    """

    logging.info("Running OSU alltoall for {0}".format(mpi_version))
    remote_command_executor.run_remote_script(
        str(test_datadir / "init_osu_benchmarks.sh"),
        args=[mpi_version],
        hide=True,
        additional_files=[str(test_datadir / "osu-micro-benchmarks-5.6.3.tar.gz")],
    )
    result = scheduler_commands.submit_script(
        str(test_datadir / "osu_alltoall_{0}.sh".format(mpi_version)),
        slots=slots,
        other_options="--exclusive"
    )
    job_id = scheduler_commands.assert_job_submitted(result.stdout)

    # This will need some time to get the instanxces up and run the test. Default wait time
    # is just 5 minutes, so doubling the time here.
    time.sleep(100)

    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    output = remote_command_executor.run_remote_command("cat /shared/osu.out").stdout

    # Assert that there are no errors in output /shared/osu.out
    assert_that(output.lower()).does_not_contain("error")

    logging.info("Running OSU alltoallv for {0}".format(mpi_version))

    result = scheduler_commands.submit_script(
        str(test_datadir / "osu_alltoallv_{0}.sh".format(mpi_version)),
        slots=min(512, slots),
        other_options="--exclusive"
    )
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    time.sleep(100)

    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    output = remote_command_executor.run_remote_command("cat /shared/osu.out").stdout

    # Assert that there are no errors in output /shared/osu.out
    assert_that(output.lower()).does_not_contain("error")
