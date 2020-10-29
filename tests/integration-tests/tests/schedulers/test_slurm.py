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

import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds

from tests.common.assertions import assert_no_errors_in_logs, assert_no_node_in_ec2, assert_scaling_worked
from tests.common.mpi_common import compile_mpi_ring
from tests.common.schedulers_common import SlurmCommands, TorqueCommands


@pytest.mark.regions(["us-east-2"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("instance", "scheduler", "os")
def test_slurm(region, pcluster_config_reader, clusters_factory, test_datadir, architecture):
    """
    Test all AWS Slurm related features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    scaledown_idletime = 3
    # For OSs running _test_mpi_job_termination, spin up 2 compute nodes at cluster creation to run test
    # Else do not spin up compute node and start running regular slurm tests
    supports_impi = architecture == "x86_64"
    cluster_config = pcluster_config_reader(scaledown_idletime=scaledown_idletime)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = SlurmCommands(remote_command_executor)
    _test_slurm_version(remote_command_executor)

    if supports_impi:
        _test_mpi_job_termination(remote_command_executor, test_datadir)

    _assert_no_node_in_cluster(region, cluster.cfn_name, slurm_commands)
    _test_job_dependencies(slurm_commands, region, cluster.cfn_name, scaledown_idletime)
    _test_job_arrays_and_parallel_jobs(
        slurm_commands,
        region,
        cluster.cfn_name,
        scaledown_idletime,
        partition="ondemand",
        instance_type="c5.xlarge",
        cpu_per_instance=4,
    )
    _gpu_resource_check(slurm_commands, partition="gpu", instance_type="g3.8xlarge")
    _test_cluster_limits(
        slurm_commands, partition="ondemand", instance_type="c5.xlarge", max_count=5, cpu_per_instance=4
    )
    _test_cluster_gpu_limits(
        slurm_commands, partition="gpu", instance_type="g3.8xlarge", max_count=5, gpu_per_instance=2
    )
    # Test torque command wrapper
    _test_torque_job_submit(remote_command_executor, test_datadir)
    assert_no_errors_in_logs(remote_command_executor, "slurm")


@pytest.mark.regions(["eu-west-1"])
@pytest.mark.instances(["c5.xlarge", "m6g.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_slurm_pmix(pcluster_config_reader, clusters_factory):
    """Test interactive job submission using PMIx."""
    num_computes = 2
    cluster_config = pcluster_config_reader(queue_size=num_computes)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # Ensure the expected PMIx version is listed when running `srun --mpi=list`.
    # Since we're installing PMIx v3.1.5, we expect to see pmix and pmix_v3 in the output.
    # Sample output:
    # [ec2-user@ip-172-31-33-187 ~]$ srun 2>&1 --mpi=list
    # srun: MPI types are...
    # srun: none
    # srun: openmpi
    # srun: pmi2
    # srun: pmix
    # srun: pmix_v3
    mpi_list_output = remote_command_executor.run_remote_command("srun 2>&1 --mpi=list").stdout
    assert_that(mpi_list_output).matches(r"\s+pmix($|\s+)")
    assert_that(mpi_list_output).matches(r"\s+pmix_v3($|\s+)")

    # Compile and run an MPI program interactively
    mpi_module = "openmpi"
    binary_path = "/shared/ring"
    compile_mpi_ring(mpi_module, remote_command_executor, binary_path=binary_path)
    interactive_command = f"module load {mpi_module} && srun --mpi=pmix -N {num_computes} {binary_path}"
    remote_command_executor.run_remote_command(interactive_command)


def _test_mpi_job_termination(remote_command_executor, test_datadir):
    """
    Test canceling mpirun job will not leave stray processes.

    IntelMPI is known to leave stray processes after job termination if slurm process tracking is not setup correctly,
    i.e. using ProctrackType=proctrack/pgid
    Test IntelMPI script to make sure no stray processes after the job is cancelled
    This bug cannot be reproduced using OpenMPI
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
    _assert_job_state(slurm_commands, job_id, job_state="RUNNING")
    # Sleep a bit to avoid race condition
    time.sleep(5)
    _check_mpi_process(remote_command_executor, slurm_commands, test_datadir, num_nodes=2, after_completion=False)
    slurm_commands.cancel_job(job_id)

    # Make sure mpirun job is cancelled
    _assert_job_state(slurm_commands, job_id, job_state="CANCELLED")

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


def _test_cluster_gpu_limits(slurm_commands, partition, instance_type, max_count, gpu_per_instance):
    """Test edge cases regarding the number of GPUs."""
    logging.info("Testing scheduler does not accept jobs when requesting for more GPUs than available")
    # Expect commands below to fail with exit 1
    _submit_command_and_assert_job_rejected(
        slurm_commands,
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": "--gpus-per-task {0}".format(gpu_per_instance + 1),
            "raise_on_error": False,
        },
    )
    _submit_command_and_assert_job_rejected(
        slurm_commands,
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": "--gres=gpu:{0}".format(gpu_per_instance + 1),
            "raise_on_error": False,
        },
    )
    _submit_command_and_assert_job_rejected(
        slurm_commands,
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": "-G:{0}".format(gpu_per_instance * max_count + 1),
            "raise_on_error": False,
        },
    )
    logging.info("Testing scheduler does not accept jobs when requesting job containing conflicting options")
    _submit_command_and_assert_job_rejected(
        slurm_commands,
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": "-G 1 --cpus-per-gpu 32 --cpus-per-task 20",
            "raise_on_error": False,
        },
    )

    # Commands below should be correctly submitted
    slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "slots": gpu_per_instance,
            "other_options": "-G {0} --gpus-per-task=1".format(gpu_per_instance),
        }
    )
    slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": "--gres=gpu:{0}".format(gpu_per_instance),
        }
    )
    # Submit job without '-N' option(nodes=-1)
    slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "nodes": -1,
            "other_options": "-G {0} --gpus-per-node={1}".format(gpu_per_instance * max_count, gpu_per_instance),
        }
    )


def _test_cluster_limits(slurm_commands, partition, instance_type, max_count, cpu_per_instance):
    logging.info("Testing scheduler rejects jobs that require a capacity that is higher than the max available")

    # Check node limit job is rejected at submission
    _submit_command_and_assert_job_rejected(
        slurm_commands,
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "nodes": (max_count + 1),
            "constraint": instance_type,
            "raise_on_error": False,
        },
    )

    # Check cpu limit job is rejected at submission
    _submit_command_and_assert_job_rejected(
        slurm_commands,
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": "--cpus-per-task {0}".format(cpu_per_instance + 1),
            "raise_on_error": False,
        },
    )


def _submit_command_and_assert_job_rejected(slurm_commands, submit_command_args):
    """Submit a limit-violating job and assert the job is failed at submission."""
    result = slurm_commands.submit_command(**submit_command_args)
    assert_that(result.stdout).contains("sbatch: error: Batch job submission failed:")


def _gpu_resource_check(slurm_commands, partition, instance_type):
    """Test GPU related resources are correctly allocated."""
    logging.info("Testing number of GPU/CPU resources allocated to job")

    job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": "-G 1 --cpus-per-gpu 5",
        }
    )
    job_info = slurm_commands.get_job_info(job_id)
    assert_that(job_info).contains("TresPerJob=gpu:1", "CpusPerTres=gpu:5")

    job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 1",
            "partition": partition,
            "constraint": instance_type,
            "other_options": "--gres=gpu:2 --cpus-per-gpu 6",
        }
    )
    job_info = slurm_commands.get_job_info(job_id)
    assert_that(job_info).contains("TresPerNode=gpu:2", "CpusPerTres=gpu:6")


def _test_slurm_version(remote_command_executor):
    logging.info("Testing Slurm Version")
    version = remote_command_executor.run_remote_command("sinfo -V").stdout
    assert_that(version).is_equal_to("slurm 20.02.4")


def _test_job_dependencies(slurm_commands, region, stack_name, scaledown_idletime):
    logging.info("Testing cluster doesn't scale when job dependencies are not satisfied")
    job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 60", "nodes": 1}
    )
    dependent_job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 1", "nodes": 1, "after_ok": job_id}
    )

    # Wait for reason to be computed
    time.sleep(3)
    # Job should be in CF and waiting for nodes to power_up
    assert_that(slurm_commands.get_job_info(job_id)).contains("JobState=CONFIGURING")
    assert_that(slurm_commands.get_job_info(dependent_job_id)).contains("JobState=PENDING Reason=Dependency")

    assert_scaling_worked(slurm_commands, region, stack_name, scaledown_idletime, expected_max=1, expected_final=0)
    # Assert jobs were completed
    _assert_job_completed(slurm_commands, job_id)
    _assert_job_completed(slurm_commands, dependent_job_id)


def _test_job_arrays_and_parallel_jobs(
    slurm_commands, region, stack_name, scaledown_idletime, partition, instance_type, cpu_per_instance
):
    logging.info("Testing cluster scales correctly with array jobs and parallel jobs")

    # Following 2 jobs requires total of 3 nodes
    array_job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 1",
            "nodes": -1,
            "partition": partition,
            "constraint": instance_type,
            "other_options": "-a 1-{0}".format(cpu_per_instance + 1),
        }
    )

    parallel_job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 1",
            "nodes": -1,
            "slots": 2,
            "partition": partition,
            "constraint": instance_type,
            "other_options": "-c {0}".format(cpu_per_instance - 1),
        }
    )

    # Assert scaling worked as expected
    assert_scaling_worked(slurm_commands, region, stack_name, scaledown_idletime, expected_max=3, expected_final=0)
    # Assert jobs were completed
    _assert_job_completed(slurm_commands, array_job_id)
    _assert_job_completed(slurm_commands, parallel_job_id)


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(7))
def _assert_no_node_in_cluster(region, stack_name, scheduler_commands, partition=None):
    assert_that(scheduler_commands.compute_nodes_count(filter_by_partition=partition)).is_equal_to(0)
    assert_no_node_in_ec2(region, stack_name)


def _assert_job_completed(slurm_commands, job_id):
    _assert_job_state(slurm_commands, job_id, job_state="COMPLETED")


@retry(wait_fixed=seconds(3), stop_max_delay=seconds(15))
def _assert_job_state(slurm_commands, job_id, job_state):
    try:
        result = slurm_commands.get_job_info(job_id)
        assert_that(result).contains("JobState={}".format(job_state))
    except RemoteCommandExecutionError as e:
        # Handle the case when job is deleted from history
        assert_that(e.result.stdout).contains("slurm_load_jobs error: Invalid job id specified")


def _test_torque_job_submit(remote_command_executor, test_datadir):
    """Test torque job submit command in slurm cluster."""
    logging.info("Testing cluster submits job by torque command")
    torque_commands = TorqueCommands(remote_command_executor)
    result = torque_commands.submit_script(str(test_datadir / "torque_job.sh"))
    torque_commands.assert_job_submitted(result.stdout)
