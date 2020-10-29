import logging
import pathlib

from assertpy import assert_that

from tests.common.assertions import assert_no_errors_in_logs, assert_scaling_worked
from tests.common.schedulers_common import get_scheduler_commands

MPI_COMMON_DATADIR = pathlib.Path(__file__).parent / "data/mpi/"


def compile_mpi_ring(mpi_module, remote_command_executor, binary_path="ring"):
    """
    Copy the source for an MPI ring program to a running cluster and compile the program.

    By default the resulting binary is written to ${HOME}/ring. This can be changed via the binary_path arg.
    """
    command = f"module load {mpi_module} && mpicc -o {binary_path} ring.c"
    remote_command_executor.run_remote_command(command, additional_files=[str(MPI_COMMON_DATADIR / "ring.c")])


def _test_mpi(
    remote_command_executor,
    slots_per_instance,
    scheduler,
    region=None,
    stack_name=None,
    scaledown_idletime=None,
    verify_scaling=False,
    partition=None,
):
    logging.info("Testing mpi job")
    mpi_module = "openmpi"
    # Compile mpi script
    compile_mpi_ring(mpi_module, remote_command_executor)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    if partition:
        # submit script using additional files
        result = scheduler_commands.submit_script(
            str(MPI_COMMON_DATADIR / "mpi_submit_{0}.sh".format(mpi_module)),
            slots=2 * slots_per_instance,
            partition=partition,
        )
    else:
        # submit script using additional files
        result = scheduler_commands.submit_script(
            str(MPI_COMMON_DATADIR / "mpi_submit_{0}.sh".format(mpi_module)), slots=2 * slots_per_instance
        )
    job_id = scheduler_commands.assert_job_submitted(result.stdout)

    if verify_scaling:
        assert_scaling_worked(
            scheduler_commands, region, stack_name, scaledown_idletime, expected_max=2, expected_final=0
        )
        # not checking assert_job_succeeded after cluster scale down cause the scheduler history might be gone
    else:
        scheduler_commands.wait_job_completed(job_id)
        scheduler_commands.assert_job_succeeded(job_id)

    mpi_out = remote_command_executor.run_remote_command("cat /shared/mpi.out").stdout
    # mpi_out expected output
    # Hello world from processor ip-192-168-53-169, rank 0 out of 2 processors
    # Process 0 received token -1 from process 1
    # Hello world from processor ip-192-168-60-9, rank 1 out of 2 processors
    # Process 1 received token -1 from process 0
    assert_that(mpi_out.splitlines()).is_length(4)
    # Slurm HIT DNS name is the same as nodename and starts with partition
    # Example: efa-enabled-st-c5n18xlarge-2
    if partition:
        nodename_prefix = partition
    elif scheduler == "slurm":
        nodename_prefix = ""
    else:
        nodename_prefix = "ip-"
    assert_that(mpi_out).matches(
        r"Hello world from processor {0}.+, rank 0 out of 2 processors".format(nodename_prefix)
    )
    assert_that(mpi_out).matches(
        r"Hello world from processor {0}.+, rank 1 out of 2 processors".format(nodename_prefix)
    )
    assert_that(mpi_out).contains("Process 0 received token -1 from process 1")
    assert_that(mpi_out).contains("Process 1 received token -1 from process 0")

    assert_no_errors_in_logs(remote_command_executor, scheduler)
