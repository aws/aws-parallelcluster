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
BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS = {8: 60.0233, 16: 31.3820, 32: 17.2294}
PERF_TEST_DIFFERENCE_TOLERANCE = 5


def get_starccm_secrets(region_name):
    secrets_manager_client = boto3.client("secretsmanager", region_name=region_name)
    response = secrets_manager_client.get_secret_value(SecretId=STARCCM_LICENCE_SECRET)["SecretString"]
    secrets = json.loads(response)
    return secrets["podkey"], secrets["licpath"]


def perf_test_difference(perf_test_result, number_of_nodes):
    baseline_result = BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS[number_of_nodes]
    percentage_difference = 100 * (perf_test_result - baseline_result) / baseline_result
    return percentage_difference


def starccm_installed(headnode):
    cmd = "/shared/ec2-user/STAR-CCM+/18.02.008/STAR-CCM+18.02.008/star/bin/starccm+ --version"
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
):
    cluster_config = pcluster_config_reader(number_of_nodes=max(number_of_nodes))
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
        logging.info(f"The elapsed time for {node} nodes is {perf_test_result.stdout} seconds")
        baseline_value = BASELINE_CLUSTER_SIZE_ELAPSED_SECONDS[node]
        percentage_difference = perf_test_difference(float(perf_test_result.stdout), node)
        if percentage_difference < 0:
            outcome = "improvement"
        else:
            outcome = "degradation"
        logging.info(
            f"Nodes: {node}, Baseline: {baseline_value} seconds, Observed: {perf_test_result.stdout} seconds, "
            f"Percentage difference: {percentage_difference}%, Outcome: {outcome}"
        )
        if percentage_difference > PERF_TEST_DIFFERENCE_TOLERANCE:
            performance_degradation[node] = perf_test_result.stdout
    if performance_degradation:
        degraded_nodes = performance_degradation.keys()
        pytest.fail(
            f"Performance test results show performance degradation for the following nodes:" f"{degraded_nodes}"
        )
    else:
        logging.info("Performance test results show no performance degradation")
