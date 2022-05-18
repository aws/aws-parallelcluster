import pytest
from remote_command_executor import RemoteCommandExecutor

from tests.performance_tests.common import (
    HEAD_NODE_INSTANCE_TYPE,
    MULTITHREADING_DISABLED,
    PYTEST_PARAMETERIZE_ARGUMENTS,
    PYTEST_PARAMETERIZE_VALUES,
    check_performance_results,
    submit_performance_test,
    upload_bootstrap_scripts,
    wait_process_completion,
    write_results_to_output_dir,
)
from tests.performance_tests.plotting.performance_tests_plots import generate_plots


@pytest.mark.parametrize(PYTEST_PARAMETERIZE_ARGUMENTS, PYTEST_PARAMETERIZE_VALUES)
def test_simple(
    region,
    scheduler,
    instance,
    os,
    pcluster_config_reader,
    test_datadir,
    s3_bucket_factory_shared,
    request,
    clusters_factory,
    num_compute_nodes,
    num_users,
):
    # Cluster Creation
    bootstrap_scripts_bucket, bootstrap_scripts_prefix = upload_bootstrap_scripts(s3_bucket_factory_shared, region)
    config_params = {
        "head_node_instance_type": HEAD_NODE_INSTANCE_TYPE,
        "compute_instance_type": instance,
        "num_compute_nodes": num_compute_nodes,
        "bucket_bootstrap_scripts": bootstrap_scripts_bucket,
        "bucket_bootstrap_scripts_prefix": bootstrap_scripts_prefix,
        "multithreading_disabled": MULTITHREADING_DISABLED,
    }
    cluster_config = pcluster_config_reader(**config_params)
    cluster = clusters_factory(cluster_config)

    # Performance Test Execution
    remote_command_executor = RemoteCommandExecutor(cluster)
    pid, results_dir = submit_performance_test(
        remote_command_executor, cluster, os, num_compute_nodes, instance, MULTITHREADING_DISABLED, num_users
    )
    wait_process_completion(remote_command_executor, pid)

    # Results
    configuration_name = "simple"
    performance_tests_dir, data_dir, baseline_statistics_path, candidate_statistics_path = write_results_to_output_dir(
        request, configuration_name, num_compute_nodes, remote_command_executor, results_dir
    )

    # Plots
    generate_plots(data_dir, f"{performance_tests_dir}/plots", ["baseline", configuration_name], [num_compute_nodes])

    # Statistics Checks
    check_performance_results(baseline_statistics_path, candidate_statistics_path)
