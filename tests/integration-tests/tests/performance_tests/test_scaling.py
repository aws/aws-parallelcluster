import logging

import pytest
from remote_command_executor import RemoteCommandExecutor


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
            "command": "sleep 1800",
            "partition": "queue-1",
            "other_options": f"--array [1-{max_nodes}] --exclusive",
        }
    )

    logging.info(f"Waiting for job to be running: {job_id}")
    scheduler_commands.wait_job_running(job_id)
    logging.info(f"Job {job_id} is running")

    logging.info(f"Cancelling job: {job_id}")
    scheduler_commands.cancel_job(job_id)
    logging.info(f"Job {job_id} cancelled")
