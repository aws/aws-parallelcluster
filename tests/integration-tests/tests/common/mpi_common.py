import logging
import pathlib

from assertpy import assert_that
from tests.common.assertions import assert_no_errors_in_logs, assert_scaling_worked
from tests.common.schedulers_common import get_scheduler_commands

OS_TO_OPENMPI_MODULE_MAP = {
    "alinux": "openmpi",
    "centos7": "openmpi",
    "ubuntu1604": "openmpi",
    "centos6": "openmpi-x86_64",
    "ubuntu1404": "no_module_available",
}


def _test_mpi(
    remote_command_executor,
    slots_per_instance,
    scheduler,
    os,
    region=None,
    stack_name=None,
    scaledown_idletime=None,
    verify_scaling=False,
):
    logging.info("Testing mpi job")
    datadir = pathlib.Path(__file__).parent / "data/mpi/"
    mpi_module = OS_TO_OPENMPI_MODULE_MAP[os]
    # Compile mpi script
    command = "mpicc -o mpi_hello_world mpi_hello_world.c"
    if mpi_module != "no_module_available":
        command = "module load {0} && {1}".format(mpi_module, command)
    remote_command_executor.run_remote_command(command, additional_files=[str(datadir / "mpi_hello_world.c")])
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    # submit script using additional files
    result = scheduler_commands.submit_script(
        str(datadir / "mpi_submit_{0}.sh".format(mpi_module)), slots=2 * slots_per_instance
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
    assert_that(mpi_out.splitlines()).is_length(2)
    assert_that(mpi_out).matches(r"Hello world from processor ip-.+, rank 0 out of 2 processors")
    assert_that(mpi_out).matches(r"Hello world from processor ip-.+, rank 1 out of 2 processors")

    assert_no_errors_in_logs(remote_command_executor, ["/var/log/sqswatcher", "/var/log/jobwatcher"])
