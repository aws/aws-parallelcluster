import json
import logging

import boto3
import pytest
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor

# timeout in seconds
STARCCM_INSTALLATION_TIMEOUT = 1800
STARCCM_JOB_TIMEOUT = 600
STARCCM_LICENCE_SECRET = "starccm-license-secret"
TASK_VCPUS = 36  # vCPUs are cut in a half because multithreading is disabled
BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS = {
    "alinux2": {8: 64.475, 16: 33.173, 32: 17.899},  # v3.1.3
    "ubuntu2204": {8: 75.502, 16: 36.353, 32: 19.688},  # v3.7.0
    "ubuntu2004": {8: 67.384, 16: 36.434, 32: 19.449},  # v3.1.3
    "centos7": {8: 67.838, 16: 36.568, 32: 20.935},  # v3.1.3
    "rhel8": {8: 66.494, 16: 36.154, 32: 20.347},  # v3.6.0
    "rocky8": {8: 66.859, 16: 36.184, 32: 21.090},  # v3.8.0
}
PERF_TEST_DIFFERENCE_TOLERANCE = 3


def get_starccm_secrets(region_name):
    secrets_manager_client = boto3.client("secretsmanager", region_name=region_name)
    response = secrets_manager_client.get_secret_value(SecretId=STARCCM_LICENCE_SECRET)["SecretString"]
    secrets = json.loads(response)
    return secrets["podkey"], secrets["licpath"]


def perf_test_difference(observed_value, baseline_value):
    percentage_difference = 100 * (observed_value - baseline_value) / baseline_value
    return percentage_difference


def starccm_installed(headnode):
    cmd = "/shared/STAR-CCM+/16.02.008/STAR-CCM+16.02.008/star/bin/starccm+ --version"
    try:
        headnode.run_remote_command(cmd)
        return True
    except RemoteCommandExecutionError:
        return False


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
    clusters_factory,
    number_of_nodes,
    test_datadir,
    scheduler_commands_factory,
    s3_bucket_factory,
):
    # Create S3 bucket for custom actions scripts
    bucket_name = s3_bucket_factory()
    s3 = boto3.client("s3")
    s3.upload_file(str(test_datadir / "dependencies.install.sh"), bucket_name, "scripts/dependencies.install.sh")

    cluster_config = pcluster_config_reader(
        bucket_name=bucket_name, install_extra_deps=os in ["rhel8", "rocky8"], number_of_nodes=max(number_of_nodes)
    )
    cluster = clusters_factory(cluster_config)
    logging.info("Cluster Created")
    remote_command_executor = RemoteCommandExecutor(cluster)
    if not starccm_installed(remote_command_executor):
        logging.info("Installing StarCCM+")
        remote_command_executor.run_remote_script(
            str(test_datadir / "starccm.install.sh"), timeout=STARCCM_INSTALLATION_TIMEOUT, hide=False
        )
    logging.info("StarCCM+ Installed")
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    podkey, licpath = get_starccm_secrets(region)
    performance_degradation = {}
    for node in number_of_nodes:
        num_of_tasks = node * TASK_VCPUS
        result = remote_command_executor.run_remote_command(
            f'sbatch --ntasks={num_of_tasks} starccm.slurm.sh "{podkey}" "{licpath}"',
            additional_files=[str(test_datadir / "starccm.slurm.sh")],
        )
        logging.info(f"Submitting StarCCM+ job with {node} nodes")
        job_id = scheduler_commands.assert_job_submitted(result.stdout)
        scheduler_commands.wait_job_completed(job_id, timeout=STARCCM_JOB_TIMEOUT)
        scheduler_commands.assert_job_succeeded(job_id)
        perf_test_result = remote_command_executor.run_remote_script(
            (str(test_datadir / "starccm.results.sh")), args=[job_id], hide=False
        )
        observed_value = float(perf_test_result.stdout)
        logging.info(f"The elapsed time for {node} nodes is {observed_value} seconds")
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
