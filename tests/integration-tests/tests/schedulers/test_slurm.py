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
import time

import boto3
import pytest
from retrying import retry

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from tests.common.assertions import assert_asg_desired_capacity, assert_no_errors_in_logs, assert_scaling_worked
from tests.common.schedulers_common import SlurmCommands
from tests.schedulers.common import assert_overscaling_when_job_submitted_during_scaledown
from time_utils import minutes, seconds


@pytest.mark.regions(["us-east-2"])
@pytest.mark.instances(["c5.xlarge", "m6g.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("instance", "scheduler")
def test_slurm(region, os, pcluster_config_reader, clusters_factory, test_datadir, architecture):
    """
    Test all AWS Slurm related features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    scaledown_idletime = 3
    max_queue_size = 5
    # IntelMPI not available on centos6
    # For OSs running _test_mpi_job_termination, spin up 2 compute nodes at cluster creation to run test
    # Else do not spin up compute node and start running regular slurm tests
    supports_impi = os not in ["centos6"] and architecture == "x86_64"
    initial_queue_size = 2 if supports_impi else 0
    cluster_config = pcluster_config_reader(
        scaledown_idletime=scaledown_idletime, max_queue_size=max_queue_size, initial_queue_size=initial_queue_size
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_slurm_version(remote_command_executor)

    if supports_impi:
        _test_mpi_job_termination(remote_command_executor, test_datadir)

    _test_dynamic_max_cluster_size(remote_command_executor, region, cluster.asg, max_queue_size=max_queue_size)
    _test_cluster_limits(remote_command_executor, max_queue_size)
    _test_job_dependencies(remote_command_executor, region, cluster.cfn_name, scaledown_idletime, max_queue_size)
    _test_job_arrays_and_parallel_jobs(remote_command_executor, region, cluster.cfn_name, scaledown_idletime)
    assert_overscaling_when_job_submitted_during_scaledown(
        remote_command_executor, "slurm", region, cluster.cfn_name, scaledown_idletime
    )
    _test_dynamic_dummy_nodes(remote_command_executor, region, cluster.asg, max_queue_size)

    assert_no_errors_in_logs(remote_command_executor, ["/var/log/sqswatcher", "/var/log/jobwatcher"])


@pytest.mark.regions(["us-east-2"])
@pytest.mark.instances(["g3.8xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("os", "instance", "scheduler")
@pytest.mark.slurm_gpu
def test_slurm_gpu(region, pcluster_config_reader, clusters_factory):
    """
    Test Slurm GPU related features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    scaledown_idletime = 1
    max_queue_size = 4
    cluster_config = pcluster_config_reader(scaledown_idletime=scaledown_idletime, max_queue_size=max_queue_size)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _gpu_test_scaleup(remote_command_executor, region, cluster.asg, cluster.cfn_name, scaledown_idletime, num_gpus=2)
    _test_dynamic_dummy_nodes(remote_command_executor, region, cluster.asg, max_queue_size, slots=32, gpus=2)
    _gpu_test_cluster_limits(remote_command_executor, max_queue_size, 2)
    _gpu_resource_check(remote_command_executor)
    _gpu_test_conflicting_options(remote_command_executor, 2)

    assert_no_errors_in_logs(remote_command_executor, ["/var/log/sqswatcher", "/var/log/jobwatcher"])


def _test_mpi_job_termination(remote_command_executor, test_datadir):
    """
    Test canceling mpirun job will not leave stray processes.

    IntelMPI is known to leave stray processes after job termination if slurm process tracking is not setup correctly,
    i.e. using ProctrackType=proctrack/pgid
    Test IntelMPI script to make sure no stray processes after the job is cancelled
    This bug cannot be reproduced using OpenMPI
    Test should run on all OSs except for centos6, where IntelMPI is not available
    """
    logging.info("Testing no stray process left behind after mpirun job is terminated")
    slurm_commands = SlurmCommands(remote_command_executor)
    # Assert initial condition
    assert_that(slurm_commands.compute_nodes_count()).is_equal_to(2)

    # Submit mpi_job, which runs Intel MPI benchmarks with intelmpi
    # Leaving 1 vcpu on each node idle so that the process check job can run while mpi_job is running
    result = slurm_commands.submit_script(str(test_datadir / "mpi_job.sh"))
    job_id = slurm_commands.assert_job_submitted(result.stdout)

    # Check that mpi processes are started
    _assert_job_state(remote_command_executor, job_id, job_state="RUNNING")
    _check_mpi_process(remote_command_executor, slurm_commands, test_datadir, num_nodes=2, after_completion=False)
    slurm_commands.cancel_job(job_id)

    # Make sure mpirun job is cancelled
    _assert_job_state(remote_command_executor, job_id, job_state="CANCELLED")

    # Check that mpi processes are terminated
    _check_mpi_process(remote_command_executor, slurm_commands, test_datadir, num_nodes=2, after_completion=True)


def _check_mpi_process(remote_command_executor, slurm_commands, test_datadir, num_nodes, after_completion):
    """Submit script and check for MPI processes."""
    # Clean up old datafiles
    remote_command_executor.run_remote_command("rm -f /shared/check_proc.out")
    result = slurm_commands.submit_command("ps aux | grep IMB | grep MPI >> /shared/check_proc.out", nodes=num_nodes)
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    proc_track_result = remote_command_executor.run_remote_command("cat /shared/check_proc.out")
    if after_completion:
        assert_that(proc_track_result.stdout).does_not_contain("IMB-MPI1")
    else:
        assert_that(proc_track_result.stdout).contains("IMB-MPI1")


def _gpu_test_cluster_limits(remote_command_executor, max_queue_size, num_gpus):
    """Test edge cases regarding the number of GPUs."""
    logging.info("Testing scheduler does not accept jobs when requesting for more GPUs than available")
    slurm_commands = SlurmCommands(remote_command_executor)
    # Expect commands below to fail with exit 1
    _submit_and_assert_job_rejected_node_config(
        remote_command_executor, "sbatch -N 1 --wrap='sleep 1' --gpus-per-task {0}".format(num_gpus + 1)
    )
    _submit_and_assert_job_rejected_node_config(
        remote_command_executor, "sbatch -N 1 --wrap='sleep 1' --gres=gpu:{0}".format(num_gpus + 1)
    )
    _submit_and_assert_job_rejected_node_config(
        remote_command_executor, "sbatch -G {0} --wrap='sleep 1'".format(num_gpus * max_queue_size + 1)
    )

    # Commands below should be correctly submitted
    result = slurm_commands.submit_command(
        "sleep 1", nodes=1, slots=num_gpus, other_options="-G {0} --gpus-per-task=1".format(num_gpus)
    )
    slurm_commands.assert_job_submitted(result.stdout)
    result = slurm_commands.submit_command("sleep 1", nodes=1, other_options="--gres=gpu:{0}".format(num_gpus))
    slurm_commands.assert_job_submitted(result.stdout)
    # Submit job without '-N' option(nodes=-1)
    result = slurm_commands.submit_command(
        "sleep 1", nodes=-1, other_options="-G {0} --gpus-per-node={1}".format(num_gpus * max_queue_size, num_gpus)
    )
    slurm_commands.assert_job_submitted(result.stdout)


def _submit_and_assert_job_rejected_node_config(remote_command_executor, command):
    """Submit a limit-violating job and assert the job is failed at submission."""
    result = remote_command_executor.run_remote_command("{0}".format(command), raise_on_error=False)
    assert_that(result.stdout).contains(
        "sbatch: error: Batch job submission failed: Requested node configuration is not available"
    )


def _gpu_test_conflicting_options(remote_command_executor, num_gpus):
    """Test GPU-related conflicting option senerios."""
    logging.info("Testing scheduler does not accept jobs when requesting job containing conflicting options")

    result = remote_command_executor.run_remote_command(
        "sbatch -G 1 --cpus-per-gpu 32 -N 1 --cpus-per-task 20 --wrap='sleep 1'", raise_on_error=False
    )
    assert_that(result.stdout).contains(
        "sbatch: error: Batch job submission failed: Requested node configuration is not available"
    )


def _gpu_resource_check(remote_command_executor):
    """Test GPU related resources are correctly allocated."""
    logging.info("Testing number of GPU/CPU resources allocated to job")
    slurm_commands = SlurmCommands(remote_command_executor)

    result = remote_command_executor.run_remote_command("sbatch -G 1 --cpus-per-gpu 5 --wrap='sleep 1'")
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    job_info = slurm_commands.get_job_info(job_id)
    assert_that(job_info).contains("TresPerJob=gpu:1", "CpusPerTres=gpu:5")

    result = remote_command_executor.run_remote_command("sbatch --gres=gpu:2 --cpus-per-gpu 6 --wrap='sleep 1'")
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    job_info = slurm_commands.get_job_info(job_id)
    assert_that(job_info).contains("TresPerNode=gpu:2", "CpusPerTres=gpu:6")


def _gpu_test_scaleup(remote_command_executor, region, asg_name, stack_name, scaledown_idletime, num_gpus):
    """Test cluster is scaling up correctly and GPU jobs are not aborted on slurmctld restart."""
    logging.info("Testing cluster scales correctly with GPU jobs")
    slurm_commands = SlurmCommands(remote_command_executor)
    # Assert initial conditions
    _assert_asg_has_no_node(region, asg_name)
    _assert_no_nodes_in_scheduler(slurm_commands)
    # g3.8xlarge has 32 vcpus and 2 GPUs, hardcoding tests for g3.8xlarge
    job_ids = []

    # sbatch --wrap 'sleep 10' -G 3
    result = slurm_commands.submit_command(command="sleep 10", nodes=-1, other_options="-G 3")
    job_ids.append(slurm_commands.assert_job_submitted(result.stdout))
    # Nodes/resources available after this job:
    # [{cpu:31, gpu:0}, {cpu:31, gpu:0}]

    # sbatch --wrap 'sleep 10' --cpus-per-gpu=10 --gpus-per-task=1
    result = slurm_commands.submit_command(
        command="sleep 10", nodes=-1, other_options="--cpus-per-gpu=10 --gpus-per-task=1"
    )
    job_ids.append(slurm_commands.assert_job_submitted(result.stdout))
    # Nodes/resources available after this job:
    # [{cpu:31, gpu:0}, {cpu:31, gpu:0}, {cpu:22, gpu:1}]

    # sbatch --wrap 'sleep 10' -N 1 --gpus-per-node=1 -c 22 -n 1
    result = slurm_commands.submit_command(
        command="sleep 10", nodes=1, slots=1, other_options="--gpus-per-node=1 -c 23"
    )
    job_ids.append(slurm_commands.assert_job_submitted(result.stdout))
    # Nodes/resources available after this job:
    # [{cpu:31, gpu:0}, {cpu:31, gpu:0}, {cpu:22, gpu:1}, {cpu:19, gpu:1}]

    # sbatch --wrap 'sleep 10' -c 31 -n 1
    result = slurm_commands.submit_command(command="sleep 10", nodes=-1, slots=1, other_options="-c 31")
    job_ids.append(slurm_commands.assert_job_submitted(result.stdout))
    # Nodes/resources available after this job:
    # [{cpu:0, gpu:0}, {cpu:31, gpu:0}, {cpu:22, gpu:1}, {cpu:19, gpu:1}]

    # Assert scaling worked as expected
    assert_scaling_worked(slurm_commands, region, stack_name, scaledown_idletime, expected_max=4, expected_final=0)
    # Assert jobs were completed
    for job_id in job_ids:
        slurm_commands.assert_job_succeeded(job_id)


def _test_slurm_version(remote_command_executor):
    logging.info("Testing Slurm Version")
    version = remote_command_executor.run_remote_command("sinfo -V").stdout
    assert_that(version).is_equal_to("slurm 19.05.5")


def _test_dynamic_max_cluster_size(remote_command_executor, region, asg_name, max_queue_size):
    logging.info("Testing max cluster size updated when ASG limits change")

    # assert initial condition
    slurm_commands = SlurmCommands(remote_command_executor)
    _assert_no_nodes_in_scheduler(slurm_commands)

    asg_client = boto3.client("autoscaling", region_name=region)

    # Check current dummy-nodes settings
    asg = asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name]).get("AutoScalingGroups")[0]
    current_max_size = asg.get("MaxSize")
    _assert_dummy_nodes(remote_command_executor, current_max_size)

    # Change ASG value and check dummy-nodes settings
    new_max_size = 1
    asg_client.update_auto_scaling_group(AutoScalingGroupName=asg_name, MaxSize=new_max_size)
    # sleeping for 200 seconds since daemons fetch this data every 3 minutes
    time.sleep(200)
    _assert_dummy_nodes(remote_command_executor, new_max_size)

    # Check slurmctld start with no node
    new_max_size = 0
    asg_client.update_auto_scaling_group(AutoScalingGroupName=asg_name, MaxSize=new_max_size)
    time.sleep(200)
    _assert_dummy_nodes(remote_command_executor, new_max_size)

    # Restore initial cluster size
    asg_client.update_auto_scaling_group(AutoScalingGroupName=asg_name, MaxSize=max_queue_size)
    # sleeping for 200 seconds since daemons fetch this data every 3 minutes
    time.sleep(200)
    _assert_dummy_nodes(remote_command_executor, max_queue_size)


def _test_dynamic_dummy_nodes(remote_command_executor, region, asg_name, max_queue_size, slots=4, gpus=0):
    logging.info("Testing dummy nodes are automatically reconfigured based on actual compute nodes")
    slurm_commands = SlurmCommands(remote_command_executor)
    # Assert initial conditions
    _assert_asg_has_no_node(region, asg_name)
    _assert_no_nodes_in_scheduler(slurm_commands)

    _assert_dummy_nodes(remote_command_executor, max_queue_size, slots, gpus)
    result = slurm_commands.submit_command("sleep 1", nodes=1)
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    _assert_dummy_nodes(remote_command_executor, max_queue_size - 1, slots, gpus)


def _test_job_dependencies(remote_command_executor, region, stack_name, scaledown_idletime, max_queue_size):
    logging.info("Testing cluster doesn't scale when job dependencies are not satisfied")
    slurm_commands = SlurmCommands(remote_command_executor)
    result = slurm_commands.submit_command("sleep 60", nodes=1)
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    result = remote_command_executor.run_remote_command("sbatch -N 1 --wrap='sleep 1' -d afterok:{0}".format(job_id))
    dependent_job_id = slurm_commands.assert_job_submitted(result.stdout)

    # Wait for reason to be computed
    time.sleep(3)
    assert_that(slurm_commands.get_job_info(job_id)).contains(
        "JobState=PENDING Reason=Nodes_required_for_job_are_DOWN,_DRAINED"
        "_or_reserved_for_jobs_in_higher_priority_partitions"
    )
    assert_that(slurm_commands.get_job_info(dependent_job_id)).contains("JobState=PENDING Reason=Dependency")

    assert_scaling_worked(slurm_commands, region, stack_name, scaledown_idletime, expected_max=1, expected_final=0)
    # Assert scheduler configuration is correct
    _assert_dummy_nodes(remote_command_executor, max_queue_size)
    assert_that(_retrieve_slurm_compute_nodes_from_config(remote_command_executor)).is_empty()
    # Assert jobs were completed
    _assert_job_completed(remote_command_executor, job_id)
    _assert_job_completed(remote_command_executor, dependent_job_id)


def _test_cluster_limits(remote_command_executor, max_queue_size):
    logging.info("Testing scheduler rejects jobs that require a capacity that is higher than the max available")

    # Check node limit job is rejected at submission
    result = remote_command_executor.run_remote_command(
        "sbatch -N {0} --wrap='sleep 1'".format(max_queue_size + 1), raise_on_error=False
    )
    assert_that(result.stdout).contains("sbatch: error: Batch job submission failed: Node count specification invalid")

    # Check cpu limit job is rejected at submission
    result = remote_command_executor.run_remote_command(
        "sbatch -N 1 --wrap='sleep 1' --cpus-per-task 5", raise_on_error=False
    )
    assert_that(result.stdout).contains(
        "sbatch: error: Batch job submission failed: Requested node configuration is not available"
    )


def _test_job_arrays_and_parallel_jobs(remote_command_executor, region, stack_name, scaledown_idletime):
    logging.info("Testing cluster scales correctly with array jobs and parallel jobs")
    slurm_commands = SlurmCommands(remote_command_executor)

    result = remote_command_executor.run_remote_command("sbatch --wrap 'sleep 1' -a 1-5")
    array_job_id = slurm_commands.assert_job_submitted(result.stdout)

    result = remote_command_executor.run_remote_command("sbatch --wrap 'sleep 1' -c 3 -n 2")
    parallel_job_id = slurm_commands.assert_job_submitted(result.stdout)

    # Assert scaling worked as expected
    assert_scaling_worked(slurm_commands, region, stack_name, scaledown_idletime, expected_max=3, expected_final=0)
    # Assert jobs were completed
    _assert_job_completed(remote_command_executor, array_job_id)
    _assert_job_completed(remote_command_executor, parallel_job_id)


def _retrieve_slurm_dummy_nodes_from_config(remote_command_executor, gres=False):
    slurm_nodes = _retrieve_slurm_nodes_from_config(remote_command_executor, gres)
    print(slurm_nodes.splitlines())
    return [node for node in slurm_nodes.splitlines() if "NodeName" in node and "dummy-compute" in node]


def _retrieve_slurm_compute_nodes_from_config(remote_command_executor):
    slurm_nodes = _retrieve_slurm_nodes_from_config(remote_command_executor)
    print(slurm_nodes.splitlines())
    return [node for node in slurm_nodes.splitlines() if "NodeName" in node and "dummy-compute" not in node]


def _retrieve_slurm_nodes_from_config(remote_command_executor, gres=False):
    if gres:
        retrieve_nodes_command = "sudo cat /opt/slurm/etc/slurm_parallelcluster_gres.conf"
    else:
        retrieve_nodes_command = "sudo cat /opt/slurm/etc/slurm_parallelcluster_nodes.conf"
    return remote_command_executor.run_remote_command(retrieve_nodes_command).stdout


def _retrieve_slurm_dummy_nodes(remote_command_executor, gres=False):
    retrieve_dummy_nodes_command = "scontrol -F show nodes | grep 'State=FUTURE'"
    return len(remote_command_executor.run_remote_command(retrieve_dummy_nodes_command).stdout.split("\n"))


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(7))
def _assert_no_nodes_in_scheduler(scheduler_commands):
    assert_that(scheduler_commands.compute_nodes_count()).is_equal_to(0)


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(7))
def _assert_asg_has_no_node(region, asg_name):
    assert_asg_desired_capacity(region, asg_name, expected=0)


def _assert_dummy_nodes(remote_command_executor, count, slots=4, gpus=0):
    __tracebackhide__ = True
    if gpus > 0:
        # If GPU instance, need to check for extra GPU info in slurm_parallelcluster_nodes.conf
        gpu_entry = "Gres=gpu:tesla:{gpus} ".format(gpus=gpus)
        # Checking dummy nodes in slurm_parallelcluster_gres.conf
        dummy_gres_nodes_config = _retrieve_slurm_dummy_nodes_from_config(remote_command_executor, gres=True)
        assert_that(dummy_gres_nodes_config[0]).is_equal_to(
            "NodeName=dummy-compute[1-{0}] Name=gpu Type=tesla File=/dev/nvidia[0-{1}]".format(count, gpus - 1)
        )
    else:
        gpu_entry = ""
    dummy_nodes_config = _retrieve_slurm_dummy_nodes_from_config(remote_command_executor)
    assert_that(dummy_nodes_config).is_length(1)
    # Checking dummy nodes in slurm_parallelcluster_nodes.conf
    if count == 0:
        assert_that(dummy_nodes_config[0]).is_equal_to(
            'NodeName=dummy-compute-stop CPUs={0} State=DOWN Reason="Cluster is stopped or max size is 0"'.format(slots)
        )
    else:
        assert_that(dummy_nodes_config[0]).is_equal_to(
            "NodeName=dummy-compute[1-{0}] CPUs={1} {2}State=FUTURE".format(count, slots, gpu_entry)
        )
        dummy_nodes_count = _retrieve_slurm_dummy_nodes(remote_command_executor)
        assert_that(dummy_nodes_count).is_equal_to(count)


def _assert_job_completed(remote_command_executor, job_id):
    _assert_job_state(remote_command_executor, job_id, job_state="COMPLETED")


@retry(wait_fixed=seconds(3), stop_max_delay=seconds(15))
def _assert_job_state(remote_command_executor, job_id, job_state):
    try:
        result = remote_command_executor.run_remote_command("scontrol show jobs -o {0}".format(job_id), log_error=False)
        assert_that(result.stdout).contains("JobState={}".format(job_state))
    except RemoteCommandExecutionError as e:
        # Handle the case when job is deleted from history
        assert_that(e.result.stdout).contains("slurm_load_jobs error: Invalid job id specified")
