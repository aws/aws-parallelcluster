import logging
from dataclasses import dataclass
from typing import Union

import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor

from tests.common.assertions import assert_head_node_is_running
from tests.common.utils import get_capacity_reservation_id

HEALTH_CHECK_LOG_FILE = "/var/log/parallelcluster/slurm_health_check.log"

# Instance families that are only available through Capacity Blocks.
CAPACITY_BLOCK_INSTANCE_PREFIXES = ("p5", "p6")

# Number of Capacity Block nodes the test asks for, the same count the efa and ultraserver/test_gb200
# tests request for their p-family capacity-block queues.
CAPACITY_BLOCK_MAX_QUEUE_SIZE = 2

# The GPU health check is executed by the prolog and the DCGMI diagnostic is slow on the intricate GPU
# topology of the p families; the health check manager itself allows it up to 600s. Wait generously for
# the job so a slow-but-healthy check is not mistaken for a failure.
GPU_HEALTH_CHECK_JOB_TIMEOUT_MINUTES = 30


@dataclass
class NodeHealthStatus:
    """Class to keep track of expected health status of a node"""

    node_name: str
    health_check_executed: bool
    latest_job: Union[int, None]


@pytest.mark.usefixtures("scheduler", "serial_execution_by_instance")
def test_cluster_with_gpu_health_checks(
    region,
    os,
    instance,
    architecture,
    pcluster_config_reader,
    s3_bucket_factory,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
    request,
):
    """Test cluster with GPU Checks.

    For instances that are only available through Capacity Blocks (p5/p6 families) the test runs a
    reduced variant: a single queue with a single compute resource backed by a Capacity Block, and the
    only assertion is that the GPU health check ran and succeeded on every node. Any other instance
    type runs the full matrix of GPU/non-GPU compute resources with health checks enabled/disabled.
    """
    if instance.startswith(CAPACITY_BLOCK_INSTANCE_PREFIXES):
        _test_gpu_health_checks_on_capacity_block(
            region=region,
            os=os,
            instance=instance,
            architecture=architecture,
            pcluster_config_reader=pcluster_config_reader,
            clusters_factory=clusters_factory,
            scheduler_commands_factory=scheduler_commands_factory,
            request=request,
        )
        return

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
    cluster_config = pcluster_config_reader(
        non_gpu_instance=_non_gpu_instance(architecture), capacity_reservation_id=None
    )
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


def _test_gpu_health_checks_on_capacity_block(
    region,
    os,
    instance,
    architecture,
    pcluster_config_reader,
    clusters_factory,
    scheduler_commands_factory,
    request,
):
    """Assert the GPU health check runs and succeeds on the nodes of a Capacity Block.

    Searches for an active Capacity Block for the given instance type and runs a single queue with a
    single compute resource on it. A job is then submitted to all nodes and the health check log of
    every node is checked for a successful GPU health check with no failures.
    """
    queue = "queue-1"
    compute_resource = "compute-resource-1"
    max_queue_size = CAPACITY_BLOCK_MAX_QUEUE_SIZE

    capacity_reservations = get_capacity_reservation_id(request, instance, region, max_queue_size, os)
    if not capacity_reservations:
        message = f"Skipping the test as no Capacity Block for {instance} and os {os} was found in {region}"
        logging.warning(message)
        pytest.skip(message)
    capacity_reservation_id = capacity_reservations[0].get("CapacityReservationId")
    logging.info(
        "Using Capacity Block %s for %s node(s) of instance %s", capacity_reservation_id, max_queue_size, instance
    )

    cluster_config = pcluster_config_reader(
        non_gpu_instance=_non_gpu_instance(architecture),
        capacity_reservation_id=capacity_reservation_id,
        max_queue_size=max_queue_size,
    )
    suppress_validators = ["type:UltraserverCapacityBlockSizeValidator"]
    # p6e-gb200 is not officially supported on rhel8/rocky8/rhel9, which this test does not care about:
    # it only exercises the GPU health check.
    if os.startswith(("rhel", "rocky")):
        suppress_validators.append("type:InstanceTypeOSCompatibleValidator")
    cluster = clusters_factory(cluster_config, suppress_validators=suppress_validators)
    assert_head_node_is_running(region, cluster)
    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = scheduler_commands_factory(remote_command_executor)

    # Submit a job to every node of the Capacity Block so that the prolog, and therefore the GPU health
    # check, runs on all of them. The payload is deliberately trivial: what is being tested is the prolog,
    # which Slurm runs to completion before the job's tasks start. On p-family GPU topologies the DCGMI
    # diagnostic can take several minutes, so allow well beyond the 12 minute default when waiting.
    job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "srun sleep 1",
            "partition": queue,
            "nodes": max_queue_size,
            "slots": max_queue_size,
        }
    )
    slurm_commands.wait_job_completed(job_id, timeout=GPU_HEALTH_CHECK_JOB_TIMEOUT_MINUTES)
    slurm_commands.assert_job_succeeded(job_id)

    for compute_node_ip in cluster.get_compute_nodes_private_ip(queue, compute_resource, ["running"], max_queue_size):
        logging.info("Checking the GPU health check succeeded on compute node %s", compute_node_ip)
        health_check_log = _assert_file_content_in_compute_node(
            HEALTH_CHECK_LOG_FILE,
            compute_node_ip,
            cluster,
            # Both the health check script and its manager log as "... - LEVEL - JobID <id> - <message>",
            # so anchor on the job id followed by a non-digit to avoid matching a job id with this one as
            # a prefix (e.g. JobID 1234 when looking for JobID 123).
            [
                rf".*JobID {job_id}\D.*Running GPU Health Check with DCGMI.*",
                rf".*JobID {job_id}\D.*The GPU Health Check succeeded.*",
                rf".*JobID {job_id}\D.*HealthCheckManager finished with exit code '0'.*",
            ],
            log_content=True,
        )
        # Failures are logged at ERROR level, which precedes the job id field in every format written to
        # this file, so no ERROR line for this job may appear. The prolog wrapper script labels the field
        # "Job <id>" while the health check script and its manager use "JobID <id>", hence the optional ID.
        _assert_patterns_in_content(health_check_log, [rf".*ERROR.*Job(?:ID)? {job_id}\D.*"], should_exist=False)


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


def _non_gpu_instance(architecture):
    return "c5.xlarge" if architecture == "x86_64" else "m6g.xlarge"


def _assert_file_content_in_compute_node(
    file_path, compute_node_ip, cluster, patterns, should_exist=True, log_content=False
):
    """Assert the patterns against the content of a remote file and return that content.

    Set log_content to print the whole file, which facilitates troubleshooting since the assertions
    only report which pattern did not match.
    """
    compute_node_remote_command_executor = RemoteCommandExecutor(cluster, compute_node_ip=compute_node_ip)
    results_from_compute_node = compute_node_remote_command_executor.run_remote_command(
        command=f"cat {file_path}"
    ).stdout
    if log_content:
        logging.info("Content of %s on compute node %s:\n%s", file_path, compute_node_ip, results_from_compute_node)
    _assert_patterns_in_content(results_from_compute_node, patterns, should_exist=should_exist)
    return results_from_compute_node


def _assert_patterns_in_content(content, patterns, should_exist=True):
    for pattern in patterns:
        if should_exist:
            assert_that(content).matches(pattern)
        else:
            assert_that(content).does_not_match(pattern)
