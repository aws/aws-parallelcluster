# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import pathlib
from shutil import copyfile

from constants import OSU_BENCHMARK_VERSION
from jinja2 import Environment, FileSystemLoader

OSU_COMMON_DATADIR = pathlib.Path(__file__).parent / "data/osu/"
SUPPORTED_MPIS = ["openmpi", "intelmpi"]


def compile_osu(mpi_variant, remote_command_executor):
    init_script = render_jinja_template(
        template_file_path=OSU_COMMON_DATADIR / "init_osu_benchmarks.sh", osu_benchmark_version=OSU_BENCHMARK_VERSION
    )
    remote_command_executor.run_remote_script(
        str(init_script),
        args=[mpi_variant],
        hide=True,
        additional_files=[
            str(OSU_COMMON_DATADIR / f"osu-micro-benchmarks-{OSU_BENCHMARK_VERSION}.tgz"),
            str(OSU_COMMON_DATADIR / "config.guess"),
            str(OSU_COMMON_DATADIR / "config.sub"),
        ],
    )


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
    submission_script_template_path=None,
    rendered_template_path=None,
    timeout=None,
):
    """
    Run the given OSU benchmark.

    :param mpi_version: string, should be one of SUPPORTED_MPIS
    :param benchmark_group: string, which of the MPI benchmarks to run. As of 5.7.1 this includes collective, one-sided,
                            pt2pt, and startup
    :param benchmark_name: string, name of the benchmark to run from the given group
    :param partition: string, partition on which to benchmark job (assumes the use of Slurm scheduler)
    :param remote_command_executor: RemoteCommandExecutor instance, used to submit jobs
    :param scheduler_commands: SchedulerlurmCommands instance, used to submit jobs
    :param num_of_instances: int, number of instances to run benchmark across
    :param slots_per_instance: int, number of processes to run on each node
    :param test_datadir: Path, used to construct default output path when rendering submission script template
    :param submission_script_template_path: string, override default path for source submission script template
    :param rendered_template_path: string, override destination path when rendering submission script template
    :param timeout: int, maximum number of minutes to wait for job to complete
    :return: string, stdout of the benchmark job
    """
    logging.info(f"Running OSU benchmark {OSU_BENCHMARK_VERSION}: {benchmark_name} for {mpi_version}")

    if mpi_version not in SUPPORTED_MPIS:
        raise Exception(f"Unsupported MPI: '{mpi_version}'. Must be one of {' '.join(SUPPORTED_MPIS)}")

    compile_osu(mpi_version, remote_command_executor)

    # Prepare submission script and pass to the scheduler for the job submission
    if not submission_script_template_path:
        submission_script_template_path = OSU_COMMON_DATADIR / f"osu_{benchmark_group}_submit_{mpi_version}.sh"
    if not rendered_template_path:
        rendered_template_path = test_datadir / f"osu_{benchmark_group}_submit_{mpi_version}_{benchmark_name}.sh"
    copyfile(submission_script_template_path, rendered_template_path)
    slots = num_of_instances * slots_per_instance
    submission_script = render_jinja_template(
        template_file_path=rendered_template_path,
        benchmark_name=benchmark_name,
        osu_benchmark_version=OSU_BENCHMARK_VERSION,
        num_of_processes=slots,
    )
    if partition:
        result = scheduler_commands.submit_script(str(submission_script), slots=slots, partition=partition)
    else:
        result = scheduler_commands.submit_script(str(submission_script), slots=slots)
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id, timeout=timeout)
    scheduler_commands.assert_job_succeeded(job_id)

    output = remote_command_executor.run_remote_command(f"cat /shared/{benchmark_name}.out").stdout
    return output


def render_jinja_template(template_file_path, **kwargs):
    file_loader = FileSystemLoader(str(os_lib.path.dirname(template_file_path)))
    env = Environment(loader=file_loader)
    rendered_template = env.get_template(os_lib.path.basename(template_file_path)).render(**kwargs)
    logging.info("Writing the following to %s\n%s", template_file_path, rendered_template)
    with open(template_file_path, "w", encoding="utf-8") as f:
        f.write(rendered_template)
    return template_file_path
