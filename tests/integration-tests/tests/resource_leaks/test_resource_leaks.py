import logging

import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from utils import get_compute_nodes_instance_ips

from tests.common.assertions import assert_head_node_is_running


@pytest.mark.usefixtures("instance", "os", "scheduler")
def test_resource_leaks(
    region,
    pcluster_config_reader,
    s3_bucket_factory,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
):
    total_sleep_time = 1800  # 30 minutes
    loop_sleep_time = 300  # 5 minutes

    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    assert_head_node_is_running(region, cluster)
    remote_command_executor = RemoteCommandExecutor(cluster)

    compute_node_instance_ip = get_compute_nodes_instance_ips(cluster.name, region)[0]
    lsof_cmd = f"ssh -q {compute_node_instance_ip} 'sudo lsof -p $(pgrep computemgtd) | wc -l'"
    sleep_cmd = f"ssh -q {compute_node_instance_ip} 'sleep {loop_sleep_time}'"

    logging.info("Checking the number of file descriptors...")
    initial_no_file_descs = remote_command_executor.run_remote_command(lsof_cmd).stdout
    logging.info("Initial number of file descriptors: %s", initial_no_file_descs)

    curr_no_file_descs = initial_no_file_descs
    for _ in range(total_sleep_time // loop_sleep_time):
        remote_command_executor.run_remote_command(sleep_cmd)
        curr_no_file_descs = remote_command_executor.run_remote_command(lsof_cmd).stdout
        logging.info("Number of file descriptors after sleeping: %s", curr_no_file_descs)

    assert_that(initial_no_file_descs).is_equal_to(curr_no_file_descs)
