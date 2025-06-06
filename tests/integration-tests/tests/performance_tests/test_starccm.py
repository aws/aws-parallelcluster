import json
import logging

import boto3
import pytest
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor

from tests.common.utils import assert_no_file_handler_leak, fetch_instance_slots, get_compute_ip_to_num_files
from tests.performance_tests.common import _log_output_performance_difference, push_result_to_dynamodb

# timeout in seconds
STARCCM_INSTALLATION_TIMEOUT = 1800
STARCCM_JOB_TIMEOUT = 600
STARCCM_LICENCE_SECRET = "starccm-license-secret"
BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS = {
    "alinux2023": {8: 62.414, 16: 31.998, 32: 20.422},  # v3.10.0
    "alinux2": {8: 64.475, 16: 33.173, 32: 17.899},  # v3.1.3
    "ubuntu2404": {8: 75.502, 16: 36.353, 32: 19.688},  # v3.13.0
    "ubuntu2204": {8: 75.502, 16: 36.353, 32: 19.688},  # v3.7.0
    "ubuntu2004": {8: 67.384, 16: 36.434, 32: 19.449},  # v3.1.3
    "centos7": {8: 67.838, 16: 36.568, 32: 20.935},  # v3.1.3
    "rhel8": {8: 66.494, 16: 36.154, 32: 20.347},  # v3.6.0
    "rhel9": {8: 66.494, 16: 36.154, 32: 20.347},  # v3.9.0
    "rocky8": {8: 66.859, 16: 36.184, 32: 21.090},  # v3.8.0
    "rocky9": {8: 66.859, 16: 36.184, 32: 21.090},  # v3.9.0
}

OSS_REQUIRING_EXTRA_DEPS = ["alinux2023", "rhel8", "rocky8"]


def get_starccm_secrets(region_name):
    secrets_manager_client = boto3.client("secretsmanager", region_name=region_name)
    response = secrets_manager_client.get_secret_value(SecretId=STARCCM_LICENCE_SECRET)["SecretString"]
    secrets = json.loads(response)
    return secrets["podkey"], secrets["licpath"]


def starccm_installed(headnode):
    cmd = "/shared/STAR-CCM+/18.02.008/STAR-CCM+18.02.008/star/bin/starccm+ --version"
    try:
        headnode.run_remote_command(cmd, log_error=False)
        return True
    except RemoteCommandExecutionError:
        logging.info("STAR-CCM+ is not installed on the head node.")
        return False


def calculate_observed_value(result, remote_command_executor, scheduler_commands, test_datadir, number_of_nodes):
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id, timeout=STARCCM_JOB_TIMEOUT)
    scheduler_commands.assert_job_succeeded(job_id)
    perf_test_result = remote_command_executor.run_remote_script(
        (str(test_datadir / "starccm.results.sh")), args=[job_id], hide=False
    )
    observed_value = float(perf_test_result.stdout)
    logging.info(f"The elapsed time for {number_of_nodes} nodes is {observed_value} seconds")
    return observed_value


@pytest.mark.usefixtures("serial_execution_by_instance")
def test_starccm(
    vpc_stack,
    instance,
    os,
    region,
    scheduler,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
    s3_bucket_factory,
):
    number_of_nodes = [8, 16, 32]
    # Create S3 bucket for custom actions scripts
    bucket_name = s3_bucket_factory()
    s3 = boto3.client("s3")
    s3.upload_file(str(test_datadir / "dependencies.install.sh"), bucket_name, "scripts/dependencies.install.sh")

    cluster_config = pcluster_config_reader(
        bucket_name=bucket_name,
        install_extra_deps=os in OSS_REQUIRING_EXTRA_DEPS,
        number_of_nodes=max(number_of_nodes),
    )
    cluster = clusters_factory(cluster_config)
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

    max_node_num = max(number_of_nodes)
    final_result = []
    for num_of_nodes in number_of_nodes:
        parallelism = int(max_node_num / num_of_nodes)
        result = []
        logging.info(f"Submitting StarCCM+ job with {num_of_nodes} nodes")
        instance_slots = fetch_instance_slots(region, instance, multithreading_disabled=True)
        run_command = f'sbatch --ntasks={num_of_nodes * instance_slots} starccm.slurm.sh "{podkey}" "{licpath}"'
        multiple_runs = []
        # Run at least twice up to whatever parallelism allows to maximize usage of available nodes
        number_of_runs = max(parallelism, 2)
        for _ in range(number_of_runs):
            multiple_runs.append(remote_command_executor.run_remote_command(run_command))
        for run in multiple_runs:
            result.append(
                calculate_observed_value(run, remote_command_executor, scheduler_commands, test_datadir, num_of_nodes)
            )
        final_result.append((num_of_nodes, sum(result) / len(result)))  # Use average to reduce noise of each runs.
        logging.info(f"Finished StarCCM+ job with {num_of_nodes} nodes")

    push_result_to_dynamodb("StarCCM", final_result, instance, os)

    # Check results and log performance degradation
    for node, observed_value in final_result:
        baseline_value = BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS[os][node]
        _log_output_performance_difference(node, performance_degradation, observed_value, baseline_value)

    assert_no_file_handler_leak(init_num_files, remote_command_executor, scheduler_commands)

    if performance_degradation:
        pytest.fail(f"Performance degradation detected: {performance_degradation}")
    else:
        logging.info("Performance test results show no performance degradation")
