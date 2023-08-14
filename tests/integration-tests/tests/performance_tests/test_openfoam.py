import logging

import pytest
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor

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
    [[8, 16, 32]],
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
        remote_command_executor.run_remote_command(
            f'bash openfoam.slurm.sh "{subspace_benchmarks_dir}" "{node}" 2>&1',
            additional_files=[str(test_datadir / "openfoam.slurm.sh")],
            timeout=OPENFOAM_JOB_TIMEOUT,
        )
        perf_test_result = remote_command_executor.run_remote_script(
            (str(test_datadir / "openfoam.results.sh")), hide=False
        )
        output = perf_test_result.stdout.strip()
        elapsed_time = output.split("\n")[-1].strip()
        baseline_value = BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS[node]
        logging.info(f"The elapsed time for {node} nodes is {elapsed_time} seconds")
        percentage_difference = perf_test_difference(int(elapsed_time), node)
        if percentage_difference < 0:
            outcome = "improvement"
        else:
            outcome = "degradation"
            performance_degradation[node] = elapsed_time
        logging.info(
            f"Nodes: {node}, Baseline: {baseline_value} seconds, Observed: {elapsed_time} seconds, "
            f"Percentage difference: {percentage_difference}%, Outcome: {outcome}"
        )
    if performance_degradation:
        degraded_nodes = performance_degradation.keys()
        pytest.fail(
            f"Performance test results show performance degradation for the following nodes:" f"{degraded_nodes}"
        )
    else:
        logging.info("Performance test results show no performance degradation")
