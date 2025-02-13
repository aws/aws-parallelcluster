from dataclasses import dataclass
from typing import Union

import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor

from tests.common.assertions import assert_head_node_is_running

HEALTH_CHECK_LOG_FILE = "/var/log/parallelcluster/slurm_health_check.log"


@dataclass
class NodeHealthStatus:
    """Class to keep track of expected health status of a node"""

    node_name: str
    health_check_executed: bool
    latest_job: Union[int, None]


@pytest.mark.usefixtures("instance", "os", "scheduler")
def test_cluster_with_gpu_health_checks(
    region,
    architecture,
    pcluster_config_reader,
    s3_bucket_factory,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
):
    """Test cluster with GPU Checks."""

    expected_nodes_health_statuses = {
        "queue-1": {
            "compute-resource-1": NodeHealthStatus(
                node_name="queue-1-dy-compute-resource-1-1",
                health_check_executed=False,
                latest_job=None,
            ),
            "compute-resource-2": NodeHealthStatus(
                node_name="queue-1-dy-compute-resource-2-1",
                health_check_executed=True,
                latest_job=None,
            ),
            "compute-resource-3": NodeHealthStatus(
                node_name="queue-1-st-compute-resource-3-1",
                health_check_executed=True,
                latest_job=None,
            ),
            "compute-resource-4": NodeHealthStatus(
                node_name="queue-1-dy-compute-resource-4-1",
                health_check_executed=False,
                latest_job=None,
            ),
            "compute-resource-5": NodeHealthStatus(
                node_name="queue-1-dy-compute-resource-5-1",
                health_check_executed=False,
                latest_job=None,
            ),
            "compute-resource-6": NodeHealthStatus(
                node_name="queue-1-dy-compute-resource-6-1",
                health_check_executed=False,
                latest_job=None,
            ),
        },
        "queue-2": {
            "compute-resource-1": NodeHealthStatus(
                node_name="queue-2-dy-compute-resource-1-1",
                health_check_executed=True,
                latest_job=None,
            ),
            "compute-resource-2": NodeHealthStatus(
                node_name="queue-2-dy-compute-resource-2-1",
                health_check_executed=False,
                latest_job=None,
            ),
        },
    }
    if architecture == "x86_64":
        non_gpu_instance = "c5.xlarge"
    else:
        non_gpu_instance = "m6g.xlarge"
    cluster_config = pcluster_config_reader(non_gpu_instance=non_gpu_instance)
    cluster = clusters_factory(cluster_config)
    assert_head_node_is_running(region, cluster)
    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = scheduler_commands_factory(remote_command_executor)

    # Submit job to the test nodes
    queue_cr_expected_nodes_health_statuses = expected_nodes_health_statuses.items()
    for queue, cr_expected_nodes_health_statuses in queue_cr_expected_nodes_health_statuses:
        no_of_nodes = len(cr_expected_nodes_health_statuses.keys())
        job_id = slurm_commands.submit_command_and_assert_job_accepted(
            submit_command_args={
                "command": "srun sleep 1",
                "host": ",".join(
                    node_health_status.node_name for cr, node_health_status in cr_expected_nodes_health_statuses.items()
                ),
                "partition": queue,
                "slots": no_of_nodes,
                "nodes": no_of_nodes,
            }
        )
        for node_health_status in cr_expected_nodes_health_statuses.values():
            node_health_status.latest_job = job_id

    # Wait for all jobs to be completed
    slurm_commands.wait_job_queue_empty()

    # Check if GPU Health Checks Manager was started on all nodes and actual Health Checks executed for nodes where
    # its enabled and the instance type is GPU-enabled.
    for _, cr_expected_nodes_health_statuses in queue_cr_expected_nodes_health_statuses:
        for node_health_status in cr_expected_nodes_health_statuses.values():
            node_address = slurm_commands.get_node_addr(node_name=node_health_status.node_name)
            _assert_file_content_in_compute_node(
                HEALTH_CHECK_LOG_FILE,
                node_address,
                cluster,
                [rf".*JobID {node_health_status.latest_job}.*Running GPU Health Check with DCGMI.*"],
                should_exist=node_health_status.health_check_executed,
            )

    # Simulate failing GPU Health Check and assert the node is set to DRAIN
    # The node targeted in this test is a static node to avoid interruptions
    # related to ScaleDown.
    _test_failing_gpu_health_checks(
        slurm_commands=slurm_commands,
        cluster=cluster,
        remote_command_executor=remote_command_executor,
        target_node=expected_nodes_health_statuses["queue-1"]["compute-resource-3"],
        target_queue="queue-1",
        failure_script_path=test_datadir / "mock_failing_gpu_health_check.sh",
        successful_script_path=test_datadir / "mock_successful_gpu_health_check.sh",
        rollback_script_path=test_datadir / "restore_gpu_health_check.sh",
    )


def _test_failing_gpu_health_checks(
    slurm_commands,
    cluster,
    remote_command_executor,
    target_node,
    target_queue,
    failure_script_path,
    successful_script_path,
    rollback_script_path,
):
    # Mock failing GPU Health Checks
    failure_script_output = remote_command_executor.run_remote_script(failure_script_path).stdout
    assert_that(failure_script_output).contains("Mocked failing GPU Health Check")

    # Run job on the node
    job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "srun sleep 1",
            "host": target_node.node_name,
            "partition": target_queue,
        }
    )

    # Assert that node is set to drain due to failing prologue/health check script
    slurm_commands.wait_nodes_status("drained", filter_by_nodes=[target_node.node_name])

    # Mock successful health check
    successful_script_output = remote_command_executor.run_remote_script(successful_script_path).stdout
    assert_that(successful_script_output).contains("Mocked successful GPU Health Check")

    # Assert that the node is replaced and job is executed
    slurm_commands.wait_nodes_status("idle", filter_by_nodes=[target_node.node_name])
    slurm_commands.wait_job_queue_empty()

    # Confirm health check was successful
    _assert_file_content_in_compute_node(
        HEALTH_CHECK_LOG_FILE,
        slurm_commands.get_node_addr(node_name=target_node.node_name),
        cluster,
        [rf".*JobID {job_id}.*HealthCheckManager finished with exit code '0'*"],
        should_exist=True,
    )

    # Restore correct health check configuration
    rollback_script_output = remote_command_executor.run_remote_script(rollback_script_path).stdout
    assert_that(rollback_script_output).contains("Health check configuration restored")


def _assert_file_content_in_compute_node(file_path, compute_node_ip, cluster, patterns, should_exist=True):
    compute_node_remote_command_executor = RemoteCommandExecutor(cluster, compute_node_ip=compute_node_ip)
    results_from_compute_node = compute_node_remote_command_executor.run_remote_command(
        command=f"cat {file_path}"
    ).stdout

    for pattern in patterns:
        if should_exist:
            assert_that(results_from_compute_node).matches(pattern)
        else:
            assert_that(results_from_compute_node).does_not_match(pattern)
