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
import math
import re

import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor

from tests.common.assertions import assert_no_errors_in_logs, assert_scaling_worked
from tests.common.schedulers_common import SgeCommands
from tests.schedulers.common import assert_overscaling_when_job_submitted_during_scaledown


@pytest.mark.regions(["eu-central-1"])
@pytest.mark.instances(["c5.xlarge", "m6g.xlarge"])
@pytest.mark.schedulers(["sge"])
@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_sge(region, pcluster_config_reader, clusters_factory):
    """
    Test all AWS SGE related features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    scaledown_idletime = 3
    max_queue_size = 5
    max_slots = 4
    cluster_config = pcluster_config_reader(scaledown_idletime=scaledown_idletime, max_queue_size=max_queue_size)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_sge_version(remote_command_executor)
    _test_non_runnable_jobs(remote_command_executor, max_queue_size, max_slots, region, cluster, scaledown_idletime)
    _test_job_dependencies(remote_command_executor, region, cluster.cfn_name, scaledown_idletime)
    _test_job_arrays_and_parallel_jobs(remote_command_executor, region, cluster.cfn_name, scaledown_idletime, max_slots)
    assert_overscaling_when_job_submitted_during_scaledown(
        remote_command_executor, "sge", region, cluster.cfn_name, scaledown_idletime
    )
    # TODO: _test_dynamic_max_cluster_size

    assert_no_errors_in_logs(remote_command_executor, "sge")


def _test_sge_version(remote_command_executor):
    logging.info("Testing SGE Version")
    version = remote_command_executor.run_remote_command("qstat -help | head -n 1").stdout
    assert_that(version).is_equal_to("SGE 8.1.9")


def _test_non_runnable_jobs(remote_command_executor, max_queue_size, max_slots, region, cluster, scaledown_idletime):
    logging.info("Testing jobs that violate scheduling requirements")
    sge_commands = SgeCommands(remote_command_executor)

    # Make sure the cluster has at least 1 node in the queue so that we can verify cluster scales down correctly
    if sge_commands.compute_nodes_count() == 0:
        result = sge_commands.submit_command("sleep 1")
        job_id = sge_commands.assert_job_submitted(result.stdout)
        sge_commands.wait_job_completed(job_id)
    assert_that(sge_commands.compute_nodes_count()).is_greater_than(0)

    logging.info("Testing cluster doesn't scale when job requires a capacity that is higher than the max available")
    result = sge_commands.submit_command("sleep 1000", slots=(max_slots * max_queue_size) + 1)
    max_slots_job_id = sge_commands.assert_job_submitted(result.stdout)
    assert_that(_get_job_state(remote_command_executor, max_slots_job_id)).is_equal_to("qw")

    logging.info("Testing cluster doesn't scale when job is set on hold")
    result = sge_commands.submit_command("sleep 1000", hold=True)
    hold_job_id = sge_commands.assert_job_submitted(result.stdout)
    assert_that(_get_job_state(remote_command_executor, hold_job_id)).is_equal_to("hqw")

    logging.info("Testing cluster scales down when pending jobs cannot be submitted")
    assert_scaling_worked(sge_commands, region, cluster.cfn_name, scaledown_idletime, expected_max=1, expected_final=0)
    # Assert jobs are still pending
    pending_jobs = remote_command_executor.run_remote_command("qstat -s p | tail -n +3 | awk '{ print $1 }'").stdout
    pending_jobs = pending_jobs.splitlines()
    assert_that(pending_jobs).contains(max_slots_job_id, hold_job_id)


def _test_job_dependencies(remote_command_executor, region, stack_name, scaledown_idletime):
    logging.info("Testing cluster doesn't scale when job dependencies are not satisfied")
    sge_commands = SgeCommands(remote_command_executor)
    result = sge_commands.submit_command("sleep 60", nodes=1)
    job_id = sge_commands.assert_job_submitted(result.stdout)
    result = remote_command_executor.run_remote_command(
        "echo 'sleep 1' | qsub -hold_jid {0}".format(job_id), raise_on_error=False
    )
    dependent_job_id = sge_commands.assert_job_submitted(result.stdout)

    assert_that(_get_job_state(remote_command_executor, dependent_job_id)).is_equal_to("hqw")

    # Assert scaling worked as expected
    assert_scaling_worked(sge_commands, region, stack_name, scaledown_idletime, expected_max=1, expected_final=0)
    # Assert jobs were completed
    sge_commands.assert_job_succeeded(job_id)
    sge_commands.assert_job_succeeded(dependent_job_id)


def _test_job_arrays_and_parallel_jobs(remote_command_executor, region, stack_name, scaledown_idletime, max_slots):
    logging.info("Testing cluster scales correctly with array jobs and parallel jobs")
    sge_commands = SgeCommands(remote_command_executor)

    result = remote_command_executor.run_remote_command("echo 'sleep 1' | qsub -t 1-5", raise_on_error=False)
    array_job_id = sge_commands.assert_job_submitted(result.stdout, is_array=True)

    result = remote_command_executor.run_remote_command("echo 'sleep 1' | qsub -pe mpi 4", raise_on_error=False)
    parallel_job_id = sge_commands.assert_job_submitted(result.stdout)

    # Assert scaling worked as expected
    expected_max = math.ceil(float(5 + 4) / max_slots)
    assert_scaling_worked(
        sge_commands, region, stack_name, scaledown_idletime, expected_max=expected_max, expected_final=0
    )
    # Assert jobs were completed
    sge_commands.assert_job_succeeded(array_job_id)
    sge_commands.assert_job_succeeded(parallel_job_id)


def _get_job_state(remote_command_executor, job_id):
    pending_jobs = remote_command_executor.run_remote_command("qstat | tail -n +3 | awk '{ print $1,$5 }'").stdout
    match = re.search(r"{0} (\w+)".format(job_id), pending_jobs)
    assert_that(match).is_not_none()
    return match.group(1)
