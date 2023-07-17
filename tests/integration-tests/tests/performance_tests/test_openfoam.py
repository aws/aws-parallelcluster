import logging

import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
# from tests.common.utils import read_remote_file
# from tests.common.utils import wait_process_completion, read_remote_file

# timeout in seconds
OPENFOAM_INSTALLATION_TIMEOUT = 300
OPENFOAM_JOB_TIMEOUT = 5400  # Takes long time because during the first time, it's not only execute the job but also
# builds and installs many things
TASK_VCPUS = 36  # vCPUs are cut in a half because multithreading is disabled
BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS = {8: 742, 16: 376, 32: 185}
PERF_TEST_DIFFERENCE_TOLERANCE = 5


def perf_test_difference(perf_test_result, number_of_nodes):
    baseline_result = BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS[number_of_nodes]
    percentage_difference = 100 * (perf_test_result - baseline_result) / baseline_result
    return percentage_difference


def openfoam_installed(headnode):
    cmd = '[ -d "/shared/ec2-user/SubspaceBenchmarks" ]'
    try:
        headnode.run_remote_command(cmd)
        return True
    except RemoteCommandExecutionError:
        return False


@pytest.mark.parametrize(
    "number_of_nodes",
    [[8]],
)
def test_openfoam(
        vpc_stack,
        instance,
        os,
        region,
        scheduler,
        pcluster_config_reader,
        clusters_factory,
        number_of_nodes,
        test_datadir,
):
    cluster_config = pcluster_config_reader(number_of_nodes=max(number_of_nodes))
    cluster = clusters_factory(cluster_config)
    logging.info("Cluster Created")
    remote_command_executor = RemoteCommandExecutor(cluster)
    if not openfoam_installed(remote_command_executor):
        logging.info("Installing OpenFOAM")
        remote_command_executor.run_remote_script(
            str(test_datadir / "openfoam.install.sh"), timeout=OPENFOAM_INSTALLATION_TIMEOUT, hide=False
        )
    logging.info("OpenFOAM Installed")
    performance_degradation = {}
    subspace_benchmarks_dir = "/shared/ec2-user/SubspaceBenchmarks"
    for node in number_of_nodes:
        logging.info(f"Submitting OpenFOAM job with {node} nodes")
        remote_command_executor.run_remote_command(f'bash openfoam.slurm.sh "{subspace_benchmarks_dir}" "{node}" 2>&1',
                                                   additional_files=[str(test_datadir / "openfoam.slurm.sh")],
                                                   timeout=OPENFOAM_JOB_TIMEOUT,
                                                   )
        # pid = read_remote_file(remote_command_executor, '/tmp/openfoam.pid')
        # logging.info(f"Waiting for OpenFOAM job to complete with pid = {pid}")
        # wait_process_completion(remote_command_executor, pid)
        perf_test_result = remote_command_executor.run_remote_script(
            (str(test_datadir / "openfoam.results.sh")), hide=False
        )
        output = perf_test_result.stdout.strip()
        elapsed_time = output.split("\n")[-1].strip()
        logging.info(f"The elapsed time for {node} nodes is {elapsed_time}")
        percentage_difference = perf_test_difference(int(elapsed_time), node)
        logging.info(
            f"Percentage difference for cluster size {node} between observed elapsed time "
            f"({elapsed_time}) and baseline ({BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS[node]}):"
            f" {percentage_difference}"
        )
        if percentage_difference > PERF_TEST_DIFFERENCE_TOLERANCE:
            performance_degradation[node] = perf_test_result
    assert_that(performance_degradation).is_empty()
