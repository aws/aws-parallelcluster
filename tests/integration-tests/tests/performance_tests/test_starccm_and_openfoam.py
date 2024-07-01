import json
import logging
from concurrent.futures import ThreadPoolExecutor

import boto3
import pytest
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor

from tests.common.utils import assert_no_file_handler_leak, get_compute_ip_to_num_files
from tests.performance_tests.common import _log_output_performance_difference

# timeout in seconds
STARCCM_INSTALLATION_TIMEOUT = 1800
STARCCM_JOB_TIMEOUT = 600
STARCCM_LICENCE_SECRET = "starccm-license-secret"

OPENFOAM_INSTALLATION_TIMEOUT = 300
OPENFOAM_JOB_TIMEOUT = 5400  # Takes long time because during the first time, it's not only execute the job but also

TASK_VCPUS = 36  # vCPUs are cut in a half because multithreading is disabled
BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS_STARCCM = {
    "alinux2023": {8: 62.414, 16: 31.998, 32: 20.422},  # v3.10.0
    "alinux2": {8: 64.475, 16: 33.173, 32: 17.899},  # v3.1.3
    "ubuntu2204": {8: 75.502, 16: 36.353, 32: 19.688},  # v3.7.0
    "ubuntu2004": {8: 67.384, 16: 36.434, 32: 19.449},  # v3.1.3
    "centos7": {8: 67.838, 16: 36.568, 32: 20.935},  # v3.1.3
    "rhel8": {8: 66.494, 16: 36.154, 32: 20.347},  # v3.6.0
    "rocky8": {8: 66.859, 16: 36.184, 32: 21.090},  # v3.8.0
}

BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS_OPENFOAM = {
    "alinux2": {8: 754, 16: 366, 32: 182},  # v3.1.3
    "ubuntu2204": {8: 742, 16: 376, 32: 185},  # v3.7.0 just a placeholder, Ubuntu22.04 not supported
    "ubuntu2004": {8: 750, 16: 382, 32: 187},  # v3.1.3
    "centos7": {8: 755, 16: 371, 32: 190},  # v3.1.3
    "rhel8": {8: 742, 16: 376, 32: 185},  # v3.6.0 just a placeholder, RHEL8 not supported
    "rocky8": {8: 742, 16: 376, 32: 185},  # v3.8.0 just a placeholder, Rocky8 not supported
}

OSS_REQUIRING_EXTRA_DEPS = ["alinux2023", "rhel8", "rocky8"]


def get_starccm_secrets(region_name):
    secrets_manager_client = boto3.client("secretsmanager", region_name=region_name)
    response = secrets_manager_client.get_secret_value(SecretId=STARCCM_LICENCE_SECRET)["SecretString"]
    secrets = json.loads(response)
    return secrets["podkey"], secrets["licpath"]


def openfoam_installed(headnode):
    cmd = '[ -d "/shared/SubspaceBenchmarks" ]'
    try:
        headnode.run_remote_command(cmd, log_error=False)
        return True
    except RemoteCommandExecutionError:
        logging.info("OpenFOAM is not installed on the head node.")
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


def starccm_installed(headnode):
    cmd = "/shared/STAR-CCM+/18.02.008/STAR-CCM+18.02.008/star/bin/starccm+ --version"
    try:
        headnode.run_remote_command(cmd, log_error=False)
        return True
    except RemoteCommandExecutionError:
        logging.info("STAR-CCM+ is not installed on the head node.")
        return False


def run_starccm_test(remote_command_executor, scheduler_commands, test_datadir, number_of_nodes, podkey, licpath):
    num_of_tasks = number_of_nodes * TASK_VCPUS
    result = remote_command_executor.run_remote_command(
        f'sbatch --ntasks={num_of_tasks} starccm.slurm.sh "{podkey}" "{licpath}"'
    )
    logging.info(f"Submitting StarCCM+ job with {number_of_nodes} nodes")
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id, timeout=STARCCM_JOB_TIMEOUT)
    scheduler_commands.assert_job_succeeded(job_id)
    perf_test_result = remote_command_executor.run_remote_script(
        (str(test_datadir / "starccm.results.sh")), args=[job_id], hide=False
    )
    observed_value = float(perf_test_result.stdout)
    logging.info(f"The elapsed time for {number_of_nodes} nodes is {observed_value} seconds")
    return observed_value


@pytest.mark.parametrize(
    "number_of_nodes",
    [[8, 16, 32]],
)
def test_starccm(
    vpc_stack,
    instance,
    os,
    region,
    scheduler,
    pcluster_config_reader,
    shared_clusters_factory,
    number_of_nodes,
    test_datadir,
    scheduler_commands_factory,
    s3_bucket_factory,
):
    logging.info("start to create s3")
    bucket_name = s3_bucket_factory()
    s3 = boto3.client("s3")
    s3.upload_file(str(test_datadir / "dependencies.install.sh"), bucket_name, "scripts/dependencies.install.sh")

    cluster_config = pcluster_config_reader(
        bucket_name=bucket_name,
        install_extra_deps=os in OSS_REQUIRING_EXTRA_DEPS,
        number_of_nodes=max(number_of_nodes),
    )
    test_region = region
    logging.info(f"test region is {test_region}")
    cluster = shared_clusters_factory(cluster_config, test_region)
    logging.info("Cluster Created")

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    init_num_files = get_compute_ip_to_num_files(remote_command_executor, scheduler_commands)

    if not starccm_installed(remote_command_executor):
        logging.info("Installing StarCCM+")
        remote_command_executor.run_remote_script(
            str(test_datadir / "starccm.install.sh"), timeout=STARCCM_INSTALLATION_TIMEOUT, hide=False
        )
    logging.info("StarCCM+ Installed")
    podkey, licpath = get_starccm_secrets(region)
    performance_degradation = {}

    # Copy additional files in advanced to avoid conflict when running 8 and 16 nodes tests in parallel
    remote_command_executor._copy_additional_files([str(test_datadir / "starccm.slurm.sh")])
    # Run 8 and 16 node tests in parallel
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_8 = executor.submit(
            run_starccm_test, remote_command_executor, scheduler_commands, test_datadir, 8, podkey, licpath
        )
        future_16 = executor.submit(
            run_starccm_test, remote_command_executor, scheduler_commands, test_datadir, 16, podkey, licpath
        )
        observed_value_8 = future_8.result()
        observed_value_16 = future_16.result()

    # Run 32 node test
    observed_value_32 = run_starccm_test(remote_command_executor, scheduler_commands, test_datadir, 32, podkey, licpath)

    # Check results and log performance degradation
    for node, observed_value in zip(number_of_nodes, [observed_value_8, observed_value_16, observed_value_32]):
        baseline_value = BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS_STARCCM[os][node]
        _log_output_performance_difference(node, performance_degradation, observed_value, baseline_value)

    assert_no_file_handler_leak(init_num_files, remote_command_executor, scheduler_commands)

    if performance_degradation:
        pytest.fail(f"Performance degradation detected: {performance_degradation}")
    else:
        logging.info("Performance test results show no performance degradation")


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
    shared_clusters_factory,
    number_of_nodes,
    test_datadir,
    s3_bucket_factory,
):
    bucket_name = s3_bucket_factory()
    s3 = boto3.client("s3")
    s3.upload_file(str(test_datadir / "dependencies.install.sh"), bucket_name, "scripts/dependencies.install.sh")

    cluster_config = pcluster_config_reader(
        bucket_name=bucket_name,
        install_extra_deps=os in number_of_nodes,
        number_of_nodes=max(number_of_nodes),
    )
    test_region = region
    logging.info(f"test region is {test_region}")
    cluster = shared_clusters_factory(cluster_config, test_region)
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
        baseline_value = BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS_OPENFOAM[os][node]
        _log_output_performance_difference(node, performance_degradation, observed_value, baseline_value)

    if performance_degradation:
        pytest.fail(f"Performance degradation detected: {performance_degradation}")
    else:
        logging.info("Performance test results show no performance degradation")
