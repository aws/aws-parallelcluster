import json
import logging
import os as os_lib
import pathlib
import shutil
from math import ceil
from os import makedirs

import boto3
from assertpy import assert_that
from retrying import retry
from time_utils import seconds
from utils import get_username_for_os

from tests.common.utils import fetch_instance_slots

# Common settings used by all test scenarios
# You can change these variables to adapt the performance test to your needs.
HEAD_NODE_INSTANCE_TYPE = "c5n.xlarge"
MULTITHREADING_DISABLED = False
JOB_COMMAND = "/shared/assets/workloads/env-info.sh ; sleep 60"
NUM_ITERATIONS = 10
NUM_COMPUTE_NODES = 10

# You should not change these variables as they are ment to be shared as they are among different test cases
PYTEST_PARAMETERIZE_ARGUMENTS = "num_compute_nodes, num_users"
PYTEST_PARAMETERIZE_VALUES = [(NUM_COMPUTE_NODES, 1)]
TEST_RUNNER_SCRIPT = "/shared/assets/workloads/scale-test/run-scale-test.sh"
ROUND_UP_FACTOR = 100_000_000
PERF_TEST_DIFFERENCE_TOLERANCE = 3

METRICS = [
    dict(name="jobRunTime", unit="ms"),
    dict(name="jobWaitingTime", unit="ms"),
    dict(name="jobWarmupLeaderNodeTime", unit="ms"),
    dict(name="jobWarmupFirstNodeTime", unit="ms"),
    dict(name="jobWarmupLastNodeTime", unit="ms"),
    dict(name="instancePreInstallUpTime", unit="s"),
    dict(name="instancePostInstallUpTime", unit="s"),
]

STATISTICS = ["min", "max", "avg", "std", "med", "prc25", "prc75"]


def upload_bootstrap_scripts(s3_bucket_factory_shared, region):
    """Uploads all files in ./../resources/bootstrap to S3 at s3://{regional_bucket}/performance-tests/bootstrap."""
    bucket_name = s3_bucket_factory_shared[region]
    bootstrap_scripts_dir = f"{pathlib.Path(__file__).parent}/resources/bootstrap"
    bootstrap_scripts_key_prefix = "performance-tests/bootstrap"
    upload_all_files(bucket_name, bootstrap_scripts_key_prefix, bootstrap_scripts_dir)
    return bucket_name, bootstrap_scripts_key_prefix


@retry(stop_max_attempt_number=5, wait_fixed=seconds(3))
def upload_all_files(bucket_name, key_prefix, directory_path):
    """Uploads all files in local directory to a S3 bucket."""
    bucket = boto3.resource("s3").Bucket(bucket_name)
    for file in os_lib.listdir(os_lib.fsencode(directory_path)):
        filename = os_lib.fsdecode(file)
        bucket.upload_file(f"{directory_path}/{filename}", f"{key_prefix}/{filename}")


def submit_performance_test(
    remote_command_executor,
    cluster,
    os,
    num_compute_nodes,
    compute_node_instance_type,
    multithreading_disabled,
    num_users,
):
    """
    Launches performance tests in the background.
    Returns the pid of the background process and the directory where results are written.
    """
    test_name = f"{cluster.name}-{num_compute_nodes}nodes"
    num_jobs_per_iteration = num_compute_nodes
    num_processes_per_job = fetch_instance_slots(
        cluster.region, compute_node_instance_type, multithreading_disabled=multithreading_disabled
    )
    job_users = [get_username_for_os(os)] + [f"PclusterUser{i}" for i in range(1, num_users)]
    results_dir = f"/shared/performance-tests/results/{test_name}"
    log_file = f"{test_name}.log"
    pid_file = f"{test_name}.pid"

    # The command below launches performance tests in the background.
    # Logs are written in the log_file, while pid_file will contain the PID of the background process.
    # In this way the command execution can be asynchronously monitored.
    performance_test_launch_command = f"""
    '{TEST_RUNNER_SCRIPT}' '{NUM_ITERATIONS}' '{num_jobs_per_iteration}' '{num_processes_per_job}' '{','.join(job_users)}' '{JOB_COMMAND}' '{results_dir}' > '{log_file}' 2>&1 &
    echo $! > '{pid_file}'
    cat '{pid_file}'
    """  # noqa: E501

    result = remote_command_executor.run_remote_command(performance_test_launch_command, pty=False)
    assert_that(result.failed).is_false()
    pid = result.stdout.strip()
    return pid, results_dir


@retry(stop_max_attempt_number=5, wait_fixed=seconds(3))
def read_remote_file(remote_command_executor, file_path):
    """Reads the content of a remote file."""
    logging.info(f"Retrieving remote file {file_path}")
    result = remote_command_executor.run_remote_command(f"cat {file_path}")
    assert_that(result.failed).is_false()
    return result.stdout.strip()


@retry(stop_max_attempt_number=60, wait_fixed=seconds(180))
def wait_process_completion(remote_command_executor, pid):
    """Waits for a process with the given pid to terminate."""
    logging.info("Waiting for performance test to complete")
    command = f"""
    ps --pid {pid} > /dev/null
    [ "$?" -ne 0 ] && echo "COMPLETE" || echo "RUNNING"
    """
    result = remote_command_executor.run_remote_command(command)
    if result.stdout == "RUNNING":
        raise Exception("The process is still running")
    else:
        return result.stdout.strip()


def check_performance_results(baseline_statistics_path, candidate_statistics_path):
    """Checks the candidate statistics against the baseline statistics."""
    logging.info("Checking candidate statistics against baseline statistics")

    with open(baseline_statistics_path, "r") as f:
        baseline_statistics = json.load(f)
    with open(candidate_statistics_path, "r") as f:
        candidate_statistics = json.load(f)
    with open(f"{pathlib.Path(__file__).parent}/resources/results/tolerance.json", "r") as f:
        tolerance_settings = json.load(f)

    logging.info(f"Baseline statistics: {baseline_statistics}")
    logging.info(f"Candidate statistics: {candidate_statistics}")
    logging.info(f"Tolerance settings: {tolerance_settings}")

    failures = []
    empiric_tolerance_report = {metric["name"]: {statistic: None for statistic in STATISTICS} for metric in METRICS}
    suggested_tolerance_settings = {metric["name"]: {statistic: None for statistic in STATISTICS} for metric in METRICS}

    for metric in map(lambda m: m["name"], METRICS):
        for statistic in STATISTICS:
            baseline_value = float(baseline_statistics[metric][statistic])
            candidate_value = float(candidate_statistics[metric][statistic])
            tolerance_value = float(tolerance_settings[metric][statistic])
            threshold_value = float(baseline_value * (1.0 + tolerance_value))
            empiric_tolerance_value = (candidate_value / baseline_value) - 1.0
            empiric_tolerance_report[metric][statistic] = abs(
                ceil(empiric_tolerance_value * ROUND_UP_FACTOR) / ROUND_UP_FACTOR
            )
            suggested_tolerance_settings[metric][statistic] = tolerance_settings[metric][statistic]
            if candidate_value > threshold_value:
                logging.error(
                    f"CHECK FAILED for {metric} {statistic}: "
                    f"baseline is {baseline_value}, candidate is {candidate_value}, "
                    f"threshold is {threshold_value}, empiric_tolerance is {empiric_tolerance_value} "
                    f"tolerance is {tolerance_value}"
                )
                failures.append(
                    {
                        "metric": metric,
                        "statistic": statistic,
                        "baseline": baseline_value,
                        "candidate": candidate_value,
                        "threshold": threshold_value,
                        "empiric_tolerance": empiric_tolerance_value,
                        "tolerance": tolerance_value,
                    }
                )
                suggested_tolerance_settings[metric][statistic] = empiric_tolerance_report[metric][statistic]
            else:
                logging.info(
                    f"CHECK SUCCEEDED for {metric} {statistic}: "
                    f"baseline is {baseline_value}, candidate is {candidate_value}, "
                    f"threshold is {threshold_value}, empiric_tolerance is {empiric_tolerance_value} "
                    f"tolerance is {tolerance_value}"
                )

    logging.info(f"HINT Suggested tolerance settings: {json.dumps(suggested_tolerance_settings)}")

    assert_that(failures).is_empty()


def write_results_to_output_dir(
    request, candidate_configuration, num_compute_nodes, remote_command_executor, results_dir
):
    """
    Writes performance tests results to the outputs_dir configured for the given test session.
    Results will be organized according to the given convention:
     - {outputs_dir}/performance-tests/{configuration_name}/{num_compute_nodes}nodes/samples.json
     - {outputs_dir}/performance-tests/{configuration_name}/{num_compute_nodes}nodes/statistics.json
    """
    performance_tests_dir = f"{request.config.getoption('output_dir')}/performance-tests"
    data_dir = f"{performance_tests_dir}/data"

    configurations = ["baseline", candidate_configuration]
    paths = {configuration: {} for configuration in configurations}
    for configuration in ["baseline", candidate_configuration]:
        configuration_results_dir = f"{data_dir}/{configuration}/{num_compute_nodes}nodes"
        makedirs(configuration_results_dir, exist_ok=True)

        for results_file_name in ["samples.json", "statistics.json"]:
            # Baseline results are copied from local folder
            if configuration == "baseline":
                results_file_path = (
                    f"{pathlib.Path(__file__).parent}/resources/results/{configuration}/{results_file_name}"
                )
                shutil.copyfile(results_file_path, f"{configuration_results_dir}/{results_file_name}")
            # Candidate results are copied from remote folder
            else:
                results_file_content = read_remote_file(remote_command_executor, f"{results_dir}/{results_file_name}")
                results_file_path = f"{configuration_results_dir}/{results_file_name}"
                with open(results_file_path, "w") as f:
                    json.dump(json.loads(results_file_content), f, indent=2)
            paths[configuration][results_file_name] = results_file_path

    return (
        performance_tests_dir,
        data_dir,
        paths["baseline"]["statistics.json"],
        paths[candidate_configuration]["statistics.json"],
    )


def perf_test_difference(observed_value, baseline_value):
    percentage_difference = 100 * (observed_value - baseline_value) / baseline_value
    return percentage_difference


def _log_output_performance_difference(node, performance_degradation, observed_value, baseline_value):
    percentage_difference = perf_test_difference(observed_value, baseline_value)
    if percentage_difference < 0:
        outcome = "improvement"
    elif percentage_difference == 0:
        outcome = "matching baseline"
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
