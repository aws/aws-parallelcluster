import datetime
import logging

import pytest
from assertpy import assert_that
from benchmarks.common.metrics_reporter import produce_benchmark_metrics_report
from remote_command_executor import RemoteCommandExecutor
from time_utils import minutes

from tests.common.assertions import assert_no_msg_in_logs
from tests.common.scaling_common import get_scaling_metrics


@pytest.mark.parametrize(
    "max_nodes",
    [1000],
)
def test_scaling(
    vpc_stack,
    instance,
    os,
    region,
    scheduler,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
    max_nodes,
):
    cluster_config = pcluster_config_reader(max_nodes=max_nodes)
    cluster = clusters_factory(cluster_config)

    logging.info("Cluster Created")

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    logging.info(f"Submitting an array of {max_nodes} jobs on {max_nodes} nodes")
    job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "srun sleep 10",
            "partition": "queue-0",
            "nodes": max_nodes,
            "slots": max_nodes,
        }
    )

    logging.info(f"Waiting for job to be running: {job_id}")
    scheduler_commands.wait_job_running(job_id)
    logging.info(f"Job {job_id} is running")

    logging.info(f"Cancelling job: {job_id}")
    scheduler_commands.cancel_job(job_id)
    logging.info(f"Job {job_id} cancelled")

    logging.info("Verifying no bootstrap errors in logs")
    assert_no_msg_in_logs(
        remote_command_executor,
        log_files=["/var/log/parallelcluster/clustermgtd"],
        log_msg=["Found the following bootstrap failure nodes"],
    )


def _datetime_to_minute_granularity(dt: datetime):
    return dt.replace(second=0, microsecond=0)


def _get_scaling_time(ec2_capacity_time_series: list, timestamps: list, scaling_target: int, start_time: datetime):
    scaling_target_index = ec2_capacity_time_series.index(scaling_target)
    timestamp_at_full_cluster_size = timestamps[scaling_target_index]
    scaling_target_time = datetime.datetime.fromtimestamp(
        float(timestamp_at_full_cluster_size), tz=datetime.timezone.utc
    )
    return scaling_target_time, int((scaling_target_time - start_time).total_seconds())


@pytest.mark.parametrize(
    "scaling_max_time_in_mins, scaling_target, shared_headnode_storage, head_node_instance_type",
    [
        (10, 2000, None, "c5.24xlarge"),  # TODO: Pass these values from an external source
    ],
)
def test_scaling_stress_test(
    instance,
    os,
    region,
    scheduler,
    request,
    pcluster_config_reader,
    scheduler_commands_factory,
    clusters_factory,
    scaling_max_time_in_mins,
    scaling_target,
    head_node_instance_type,
    shared_headnode_storage,
):
    """
    This test scales a cluster up and down while periodically monitoring some primary metrics.
    The metrics monitored are:
    - Number of EC2 instances launched
    - Number of successfully bootstrapped compute nodes that have joined the cluster
    - Number of jobs pending or in configuration
    - Number of jobs currently running

    The above metrics are uploaded to CloudWatch.
    The output of this test are:
    - Log messages with the Scale up and Scale down time in seconds
    - Log with the Metrics Source that can be used from CloudWatch Console
    - A Metrics Image showing the scale up and scale down using a linear graph with annotations
    """

    # Creating cluster with intended head node instance type and scaling parameters
    cluster_config = pcluster_config_reader(
        # Prevent nodes being set down before wee start monitoring the scale down metrics
        scaledown_idletime=scaling_max_time_in_mins,
        scaling_target=scaling_target,
        head_node_instance_type=head_node_instance_type,
        shared_headnode_storage=shared_headnode_storage,
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    # Submit a simple job to trigger the launch all compute nodes
    scaling_job = {
        # Keep job running until we explicitly cancel it and start monitoring scale down
        "command": f"srun sleep {minutes(scaling_max_time_in_mins) // 1000}",
        "nodes": scaling_target,
    }
    job_id = scheduler_commands.submit_command_and_assert_job_accepted(scaling_job)

    # Set start time at minute granularity (to simplify calculation and visualising on CloudWatch)
    start_time = _datetime_to_minute_granularity(datetime.datetime.now(tz=datetime.timezone.utc))

    # Monitor the cluster during scale up
    ec2_capacity_time_series, compute_nodes_time_series, timestamps, end_time = get_scaling_metrics(
        remote_command_executor,
        max_monitoring_time=minutes(scaling_max_time_in_mins),
        region=region,
        cluster_name=cluster.name,
        publish_metrics=True,
        target_cluster_size=scaling_target,
    )
    # Extract scale up duration and timestamp from the monitoring metrics collected above
    scaling_target_time, scale_up_time = _get_scaling_time(
        ec2_capacity_time_series, timestamps, scaling_target, start_time
    )

    # Cancel the running job and scale dow the cluster using the update-compute-fleet command
    scheduler_commands.cancel_job(job_id)
    cluster.stop()

    # Monitor the cluster during scale down
    scale_down_start_timestamp = _datetime_to_minute_granularity(datetime.datetime.now(tz=datetime.timezone.utc))
    ec2_capacity_time_series, compute_nodes_time_series, timestamps, end_time = get_scaling_metrics(
        remote_command_executor,
        max_monitoring_time=minutes(scaling_max_time_in_mins),
        region=region,
        cluster_name=cluster.name,
        publish_metrics=True,
        target_cluster_size=0,
    )
    # Extract scale down duration and timestamp from the monitoring metrics collected above
    _, scale_down_time = _get_scaling_time(ec2_capacity_time_series, timestamps, 0, scale_down_start_timestamp)

    # Summarize the scaling metrics in a report (logs and metrics image)
    scaling_results = {
        "Region": region,
        "OS": os,
        "ComputeNode": instance,
        "HeadNode": head_node_instance_type,
        "ScaleUpTime": scale_up_time,
        "ScaleDownTime": scale_down_time,
    }

    logging.info(f"Scaling Results: {scaling_results}")

    produce_benchmark_metrics_report(
        title=", ".join("{0}[{1}] ".format(key, val) for (key, val) in scaling_results.items()),
        region=region,
        cluster_name=cluster.cfn_name,
        start_time=start_time,
        end_time=end_time,
        scaling_target=scaling_target,
        request=request,
        scaling_target_time=_datetime_to_minute_granularity(scaling_target_time) + datetime.timedelta(minutes=1),
    )
    # Verify that there was no over-scaling
    assert_that(max(compute_nodes_time_series)).is_equal_to(scaling_target)
    assert_that(max(ec2_capacity_time_series)).is_equal_to(scaling_target)
    assert_that(compute_nodes_time_series[-1]).is_equal_to(0)
