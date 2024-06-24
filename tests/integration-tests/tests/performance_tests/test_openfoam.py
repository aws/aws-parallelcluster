import logging
from concurrent.futures.thread import ThreadPoolExecutor

import pytest
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor

# timeout in seconds
OPENFOAM_INSTALLATION_TIMEOUT = 300
OPENFOAM_JOB_TIMEOUT = 5400  # Takes long time because during the first time, it's not only execute the job but also
# builds and installs many things
TASK_VCPUS = 36  # vCPUs are cut in a half because multithreading is disabled
BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS = {
    "alinux2": {8: 754, 16: 366, 32: 182},  # v3.1.3
    "ubuntu2204": {8: 742, 16: 376, 32: 185},  # v3.7.0 just a placeholder, Ubuntu22.04 not supported
    "ubuntu2004": {8: 750, 16: 382, 32: 187},  # v3.1.3
    "centos7": {8: 755, 16: 371, 32: 190},  # v3.1.3
    "rhel8": {8: 742, 16: 376, 32: 185},  # v3.6.0 just a placeholder, RHEL8 not supported
    "rocky8": {8: 742, 16: 376, 32: 185},  # v3.8.0 just a placeholder, Rocky8 not supported
}
PERF_TEST_DIFFERENCE_TOLERANCE = 3


def perf_test_difference(observed_value, baseline_value):
    percentage_difference = 100 * (observed_value - baseline_value) / baseline_value
    return percentage_difference


def openfoam_installed(headnode):
    cmd = '[ -d "/shared/SubspaceBenchmarks" ]'
    try:
        headnode.run_remote_command(cmd)
        return True
    except RemoteCommandExecutionError:
        return False


def run_openfoam_test(remote_command_executor, test_datadir, number_of_nodes):
    subspace_benchmarks_dir = "/shared/SubspaceBenchmarks"
    logging.info(f"Submitting OpenFOAM job with {number_of_nodes} nodes")
    remote_command_executor.run_remote_command(
        f'bash openfoam.slurm.sh "{subspace_benchmarks_dir}" "{number_of_nodes}" 2>&1',
        timeout=OPENFOAM_JOB_TIMEOUT,
    )
    perf_test_result = remote_command_executor.run_remote_script(
        (str(test_datadir / "openfoam.results.sh")), hide=False
    )
    output = perf_test_result.stdout.strip()
    observed_value = int(output.split("\n")[-1].strip())
    logging.info(f"The elapsed time for {number_of_nodes} nodes is {observed_value} seconds")
    return observed_value


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

    # Copy additional files in advanced to avoid conflict when running 8 and 16 nodes tests in parallel
    remote_command_executor._copy_additional_files([str(test_datadir / "openfoam.slurm.sh")])
    # Run 8 and 16 node tests in parallel
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_8 = executor.submit(run_openfoam_test, remote_command_executor, test_datadir, 8)
        future_16 = executor.submit(run_openfoam_test, remote_command_executor, test_datadir, 16)
        observed_value_8 = future_8.result()
        observed_value_16 = future_16.result()

    # Run 32 node test
    observed_value_32 = run_openfoam_test(remote_command_executor, test_datadir, 32)

    # Check results and log performance degradation
    for node, observed_value in zip(number_of_nodes, [observed_value_8, observed_value_16, observed_value_32]):
        baseline_value = BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS[os][node]
        percentage_difference = perf_test_difference(observed_value, baseline_value)
        if percentage_difference < 0:
            outcome = "improvement"
        elif percentage_difference <= PERF_TEST_DIFFERENCE_TOLERANCE:
            outcome = "degradation (within tolerance)"
        else:
            outcome = "degradation (above tolerance)"
            performance_degradation[node] = {
                "baseline": baseline_value,
                "observed": observed_value,
                "percentage_difference": percentage_difference,
            }
        logging.info(
            f"Nodes: {node}, Baseline: {baseline_value} seconds, Observed: {observed_value} seconds, "
            f"Percentage difference: {percentage_difference}%, Outcome: {outcome}"
        )

    if performance_degradation:
        pytest.fail(f"Performance degradation detected: {performance_degradation}")
    else:
        logging.info("Performance test results show no performance degradation")
