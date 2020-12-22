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
import time

import boto3
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from time_utils import minutes

from tests.common.assertions import assert_no_errors_in_logs, assert_scaling_worked
from tests.common.scaling_common import watch_compute_nodes
from tests.common.schedulers_common import TorqueCommands
from tests.schedulers.common import assert_overscaling_when_job_submitted_during_scaledown


@pytest.mark.regions(["us-west-2"])
@pytest.mark.instances(["c5.xlarge", "m6g.xlarge"])
@pytest.mark.schedulers(["torque"])
@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_torque(region, pcluster_config_reader, clusters_factory):
    """
    Test all AWS Torque related features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    scaledown_idletime = 2
    max_queue_size = 5
    max_slots = 4
    initial_queue_size = 3  # in order to speed-up _test_jobs_executed_concurrently test
    cluster_config = pcluster_config_reader(
        scaledown_idletime=scaledown_idletime, max_queue_size=max_queue_size, initial_queue_size=initial_queue_size
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_torque_version(remote_command_executor)
    _test_jobs_executed_concurrently(remote_command_executor, max_slots)
    _test_non_runnable_jobs(remote_command_executor, max_queue_size, max_slots, region, cluster, scaledown_idletime)
    _test_job_dependencies(remote_command_executor, region, cluster.cfn_name, scaledown_idletime)
    _test_job_arrays_and_parallel_jobs(remote_command_executor, region, cluster.cfn_name, scaledown_idletime, max_slots)
    _test_dynamic_cluster_limits(remote_command_executor, max_queue_size, max_slots, region, cluster.asg)
    assert_overscaling_when_job_submitted_during_scaledown(
        remote_command_executor, "torque", region, cluster.cfn_name, scaledown_idletime
    )

    assert_no_errors_in_logs(remote_command_executor, "torque")


def _test_torque_version(remote_command_executor):
    logging.info("Testing Torque Version")
    version = remote_command_executor.run_remote_command("qstat --version").stdout
    assert_that(version.splitlines()[0]).is_equal_to("Version: 6.1.2")


def _test_non_runnable_jobs(remote_command_executor, max_queue_size, max_slots, region, cluster, scaledown_idletime):
    logging.info("Testing jobs that violate scheduling requirements")
    torque_commands = TorqueCommands(remote_command_executor)

    # Make sure the cluster has at least 1 node in the queue so that we can verify cluster scales down correctly
    if torque_commands.compute_nodes_count() == 0:
        result = torque_commands.submit_command("sleep 1")
        job_id = torque_commands.assert_job_submitted(result.stdout)
        torque_commands.wait_job_completed(job_id)
    assert_that(torque_commands.compute_nodes_count()).is_greater_than(0)

    logging.info("Testing cluster doesn't scale when job requires a capacity that is higher than the max available")
    # nodes limit enforced by scheduler
    result = remote_command_executor.run_remote_command(
        "echo 'sleep 1000' | qsub -l nodes={0}".format(max_queue_size + 1), raise_on_error=False
    )
    assert_that(result.stdout).contains("Job exceeds queue resource limits")
    # ppn limit enforced by daemons
    result = remote_command_executor.run_remote_command(
        "echo 'sleep 1000' | qsub -l nodes=1:ppn={0}".format(max_slots + 1), raise_on_error=False
    )
    ppn_job_id = torque_commands.assert_job_submitted(result.stdout)
    # ppn total limit enforced by scheduler
    result = remote_command_executor.run_remote_command(
        "echo 'sleep 1000' | qsub -l nodes=1:ppn={0}".format((max_slots * max_queue_size) + 1), raise_on_error=False
    )
    assert_that(result.stdout).contains("Job exceeds queue resource limits")
    # ncpus limit enforced by scheduler
    result = remote_command_executor.run_remote_command(
        "echo 'sleep 1000' | qsub -l ncpus={0}".format(max_slots + 1), raise_on_error=False
    )
    assert_that(result.stdout).contains("Job exceeds queue resource limits")

    logging.info("Testing cluster doesn't scale when job is set on hold")
    result = remote_command_executor.run_remote_command("echo 'sleep 1000' | qsub -l nodes=1 -h", raise_on_error=False)
    hold_job_id = torque_commands.assert_job_submitted(result.stdout)

    logging.info("Testing cluster scales down when pending jobs cannot be submitted")
    assert_scaling_worked(
        torque_commands, region, cluster.cfn_name, scaledown_idletime, expected_max=1, expected_final=0
    )
    # Assert jobs are still pending
    assert_that(_get_job_state(remote_command_executor, ppn_job_id)).is_equal_to("Q")
    assert_that(_get_job_state(remote_command_executor, hold_job_id)).is_equal_to("H")


def _test_job_dependencies(remote_command_executor, region, stack_name, scaledown_idletime):
    logging.info("Testing cluster doesn't scale when job dependencies are not satisfied")
    torque_commands = TorqueCommands(remote_command_executor)
    result = torque_commands.submit_command("sleep 60", nodes=1)
    job_id = torque_commands.assert_job_submitted(result.stdout)
    result = remote_command_executor.run_remote_command(
        "echo 'sleep 1' | qsub -W depend=afterok:{0}".format(job_id), raise_on_error=False
    )
    dependent_job_id = torque_commands.assert_job_submitted(result.stdout)

    assert_that(_get_job_state(remote_command_executor, dependent_job_id)).is_equal_to("H")

    # Assert scaling worked as expected
    assert_scaling_worked(torque_commands, region, stack_name, scaledown_idletime, expected_max=1, expected_final=0)
    # Assert jobs were completed
    _assert_job_completed(remote_command_executor, job_id)
    _assert_job_completed(remote_command_executor, dependent_job_id)


def _test_job_arrays_and_parallel_jobs(remote_command_executor, region, stack_name, scaledown_idletime, max_slots):
    logging.info("Testing cluster scales correctly with array jobs and parallel jobs")
    torque_commands = TorqueCommands(remote_command_executor)

    result = remote_command_executor.run_remote_command(
        "echo 'sleep 30' | qsub -t 1-{0}".format(max_slots), raise_on_error=False
    )
    array_job_id = torque_commands.assert_job_submitted(result.stdout)

    result = remote_command_executor.run_remote_command("echo 'sleep 30' | qsub -l nodes=2:ppn=1", raise_on_error=False)
    parallel_job_id = torque_commands.assert_job_submitted(result.stdout)

    # Assert scaling worked as expected
    assert_scaling_worked(torque_commands, region, stack_name, scaledown_idletime, expected_max=3, expected_final=0)
    # Assert jobs were completed
    for i in range(1, max_slots + 1):
        _assert_job_completed(remote_command_executor, array_job_id.replace("[]", "[{0}]".format(i)))
    _assert_job_completed(remote_command_executor, parallel_job_id)


def _test_jobs_executed_concurrently(remote_command_executor, max_slots):
    logging.info("Testing jobs are executed concurrently and nodes are fully allocated")
    torque_commands = TorqueCommands(remote_command_executor)

    # GIVEN: a cluster with 3 free nodes
    assert_that(torque_commands.compute_nodes_count()).is_equal_to(3)

    # WHEN: an array job that requires 3 nodes and all slots is submitted
    jobs_start_time = int(remote_command_executor.run_remote_command("date +%s").stdout)
    job_exec_time = 30
    job_ids = []
    for i in range(0, 3 * max_slots):
        result = torque_commands.submit_command(
            f"sleep {job_exec_time} && hostname > /shared/job{i} && date +%s >> /shared/end_time", nodes=1, slots=1
        )
        job_id = torque_commands.assert_job_submitted(result.stdout)
        job_ids.append(job_id)

    # THEN: cluster scales down correctly after completion
    watch_compute_nodes(torque_commands, minutes(10), 0)
    for id in job_ids:
        _assert_job_completed(remote_command_executor, id)

    # THEN: each host executes 4 jobs in the expected time
    jobs_to_hosts_count = (
        remote_command_executor.run_remote_command("cat /shared/job* | sort | uniq -c | awk '{print $1}'")
        .stdout.strip()
        .splitlines()
    )
    assert_that(jobs_to_hosts_count).is_equal_to(["4", "4", "4"])
    # verify execution time
    jobs_completion_time = int(
        remote_command_executor.run_remote_command("cat /shared/end_time | sort -n | tail -1").stdout.split()[-1]
    )
    assert_that(jobs_completion_time - jobs_start_time).is_greater_than(0).is_less_than(2 * job_exec_time)


def _test_dynamic_cluster_limits(remote_command_executor, max_queue_size, max_slots, region, asg_name):
    logging.info("Testing cluster limits are dynamically updated")
    torque_commands = TorqueCommands(remote_command_executor)

    # Make sure cluster is scaled to 0 when this test starts
    assert_that(torque_commands.compute_nodes_count()).is_equal_to(0)
    # sleeping for 1 second to give time to sqswatcher to reconfigure the head node with np = max_nodes * node_slots
    # operation that is performed right after sqswatcher removes the compute nodes from the scheduler
    time.sleep(1)
    _assert_scheduler_configuration(remote_command_executor, torque_commands, max_slots, max_queue_size)

    # Submit a job to scale up to 1 node
    result = torque_commands.submit_command("sleep 1", nodes=1)
    job_id = torque_commands.assert_job_submitted(result.stdout)
    # Change ASG max size
    asg_client = boto3.client("autoscaling", region_name=region)
    new_max_size = max_queue_size + 1
    asg_client.update_auto_scaling_group(AutoScalingGroupName=asg_name, MaxSize=new_max_size)
    # sleeping for 200 seconds since daemons fetch this data every 3 minutes
    time.sleep(200)
    # Wait for job completion to be sure cluster scaled
    torque_commands.wait_job_completed(job_id)

    _assert_scheduler_configuration(remote_command_executor, torque_commands, max_slots, new_max_size)

    # Restore initial cluster size
    asg_client.update_auto_scaling_group(AutoScalingGroupName=asg_name, MaxSize=max_queue_size)
    # sleeping for 200 seconds since daemons fetch this data every 3 minutes
    time.sleep(200)
    # make sure cluster scaled to 0
    watch_compute_nodes(torque_commands, minutes(10), 0)
    _assert_scheduler_configuration(remote_command_executor, torque_commands, max_slots, max_queue_size)


def _get_job_state(remote_command_executor, job_id):
    result = remote_command_executor.run_remote_command("qstat -f {0}".format(job_id))
    match = re.search(r"job_state = (\w+)", result.stdout)
    return match.group(1)


def _assert_scheduler_configuration(remote_command_executor, torque_commands, max_slots, max_queue_size):
    compute_nodes_count = torque_commands.compute_nodes_count()
    hostname = remote_command_executor.run_remote_command("hostname").stdout
    result = remote_command_executor.run_remote_command("pbsnodes {0}".format(hostname)).stdout
    assert_that(result).contains("np = {0}\n".format((max_queue_size - compute_nodes_count) * max_slots))

    torque_config = remote_command_executor.run_remote_command("sudo /opt/torque/bin/qmgr -c 'p s'").stdout
    assert_that(torque_config).contains("set queue batch resources_max.ncpus = {0}\n".format(max_slots))
    assert_that(torque_config).contains(
        "set queue batch resources_available.nodect = {0}\n".format(max_queue_size * max_slots)
    )
    assert_that(torque_config).contains(
        "set server resources_available.nodect = {0}\n".format(max_queue_size * max_slots)
    )
    assert_that(torque_config).contains("set queue batch resources_max.nodect = {0}\n".format(max_queue_size))
    assert_that(torque_config).contains("set server resources_max.nodect = {0}\n".format(max_queue_size))


def _assert_job_completed(remote_command_executor, job_id):
    try:
        result = remote_command_executor.run_remote_command("qstat -f {0}".format(job_id), log_error=False)
        return "exit_status = 0" in result.stdout
    except RemoteCommandExecutionError as e:
        # Handle the case when job is deleted from history
        assert_that(e.result.stdout).contains("Unknown Job Id")
