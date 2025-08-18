# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import json
import logging
from datetime import datetime

import boto3
import pytest
from assertpy import assert_that
from clusters_factory import Cluster
from remote_command_executor import RemoteCommandExecutor

from tests.common.assertions import assert_regex_in_file, wait_for_instances_in_compute_resource
from tests.common.schedulers_common import SlurmCommands
from tests.common.utils import is_existing_remote_file, read_remote_file, terminate_nodes_manually

# This is the capacity block reservation for p6e-gb200.36xlarge.
# Given the limited availability of this capacity we test this instance type on demand,
# hardwiring the reservation id here when we need it.
CAPACITY_BLOCK_RESERVATION_ID = "cr-123456789"

# We use placeholder IPs just to get IMEX started.
# These values are hardwired in the cookbook.
FAKE_IPS = ["0.0.0.0"] * 9


def submit_job_imex_status(rce: RemoteCommandExecutor, queue: str, max_nodes: int = 1):
    logging.info("Submitting job to check IMEX status")
    slurm = SlurmCommands(rce)
    job_id = slurm.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "/opt/parallelcluster/shared/nvidia-imex-status.job",
            "partition": queue,
            "nodes": max_nodes,
        }
    )
    slurm.wait_job_completed(job_id)
    slurm.assert_job_succeeded(job_id)
    return job_id


def assert_imex_nodes_config_is_correct(rce: RemoteCommandExecutor, launch_template_id: str, expected_ips: list):
    logging.info(f"Checking IMEX nodes config contains the expected nodes: {expected_ips}")
    imex_nodes_config_file = f"/opt/parallelcluster/shared/nvidia-imex/nodes_config_{launch_template_id}.cfg"
    imex_config_content = read_remote_file(rce, imex_nodes_config_file)
    imex_config_content_clean = [line for line in imex_config_content.split("\n") if not line.strip().startswith("#")]
    actual_ips = [ip.strip() for ip in imex_config_content_clean]
    assert_that(actual_ips).contains_only(*expected_ips)
    logging.info(f"IMEX nodes config {imex_nodes_config_file} contains the expected nodes: {expected_ips}")


def assert_no_errors_in_logs(cluster: Cluster, queue: str, compute_resource: str):
    rce = RemoteCommandExecutor(cluster)
    logs = ["/var/log/nvidia-imex-verbose.log", "/var/log/parallelcluster/nvidia-imex-prolog.log"]
    for compute_node_ip in cluster.get_compute_nodes_private_ip(queue, compute_resource):
        for log in logs:
            logging.info(f"Checking file {log} log does not contain any error")
            if log == "/var/log/nvidia-imex-verbose.log" and not is_existing_remote_file(rce, log):
                logging.info("IMEX log file not found. Not an issue as IMEX writes logs there only in case of errors.")
                continue
            assert_regex_in_file(cluster, compute_node_ip, log, r"(warn|error|fail)", negate=True)


def assert_imex_status(
    rce: RemoteCommandExecutor,
    job_id: str,
    ips: list,
    service_status: str = "UP",
    node_status: str = "READY",
    connection_status: str = "CONNECTED",
):
    """
    Assert that the output returned by the nvidia-imex-ctl command represent a healthy status for IMEX.
    IMEX is considered healthy if every node of the domain reports a healthy status, i.e:
      * every node is READY
      * every node is CONNECTED to every other node

    Example of healthy IMEX status:
    {
     "nodes": {
      "0": {
       "status": "READY",
       "host": "192.168.103.159",
       "connections": {
        "1": {
         "host": "192.168.107.187",
         "status": "CONNECTED",
         "changed": true
        },
        "0": {
         "host": "192.168.103.159",
         "status": "CONNECTED",
         "changed": true
        }
       },
       "changed": true,
       "version": "570.172.08"
      },
      "1": {
       "status": "READY",
       "host": "192.168.107.187",
       "connections": {
        "0": {
         "host": "192.168.103.159",
         "status": "CONNECTED",
         "changed": true
        },
        "1": {
         "host": "192.168.107.187",
         "status": "CONNECTED",
         "changed": true
        }
       },
       "changed": true,
       "version": "570.172.08"
      }
     },
     "timestamp": "8/8/2025 17:38:02.641",
     "status": "UP"
    }

    Example of IMEX status for a node where IMEx has not been configured:
    {
     "nodes": {
      "0": {
       "status": "UNAVAILABLE",
       "host": "0.0.0.0",
       "connections": {
        "0": {
         "host": "0.0.0.0",
         "status": "INVALID",
         "changed": false
        }
       },
       "changed": false,
       "version": ""
      }
     },
     "timestamp": "8/11/2025 20:08:55.625",
     "status": "DOWN"
    }
    """
    slurm = SlurmCommands(rce)
    unique_ips = set(ips)

    imex_statuses = []
    for reporting_node_ip in unique_ips:
        # When fake ips are used we cannot retrieve the node name from the ip.
        # We retrieve the nodename from the list of nodes executing the job to check IMEX status.
        if reporting_node_ip in FAKE_IPS:
            reporting_node_name = slurm.get_batch_host_for_job(job_id)
        else:
            reporting_node_name = slurm.get_nodename_from_ip(reporting_node_ip)
        logging.info(f"Retrieving IMEX status reported by node {reporting_node_ip} with hostname {reporting_node_name}")
        result_file_name = f"result_{job_id}_{reporting_node_name}"
        result_stdout = rce.run_remote_command(f"cat {result_file_name}.out").stdout
        result_stderr = rce.run_remote_command(f"cat {result_file_name}.err").stdout
        if service_status == "UP":
            assert_that(result_stderr).is_empty()
        logging.info(
            f"IMEX status reported by node {reporting_node_ip} with hostname {reporting_node_name}: {result_stdout}"
        )
        imex_statuses.append(json.loads(result_stdout))
    latest_imex_status = max(imex_statuses, key=lambda i: datetime.strptime(i["timestamp"], "%m/%d/%Y %H:%M:%S.%f"))
    logging.info(f"Checking IMEX connections according to the latest status: {latest_imex_status}")
    assert_that(latest_imex_status["status"]).is_equal_to(service_status)
    for ip_source in unique_ips:
        node_item = next(filter(lambda i: i["host"] == ip_source, latest_imex_status["nodes"].values()), None)
        assert_that(node_item).is_not_none()
        assert_that(node_item["status"]).is_equal_to(node_status)
        for ip_destination in unique_ips:
            connection_item = next(
                filter(lambda i: i["host"] == ip_destination, node_item["connections"].values()), None
            )
            assert_that(connection_item).is_not_none()
            assert_that(connection_item["status"]).is_equal_to(connection_status)


def assert_imex_healthy(cluster: Cluster, queue: str, compute_resource: str, max_nodes: int = 1):
    rce = RemoteCommandExecutor(cluster)

    launch_template_id = cluster.get_compute_nodes_launch_template_logical_id(queue, compute_resource)
    logging.info(
        f"Launch template for nodes in queue {queue} and compute resource {compute_resource}: " f"{launch_template_id}"
    )

    job_id = submit_job_imex_status(rce, queue, max_nodes)

    logging.info(
        f"Retrieving private IP addresses for {max_nodes} compute nodes "
        f"in queue {queue} and compute resource {compute_resource}"
    )
    ips = cluster.get_compute_nodes_private_ip(queue, compute_resource, ["running"], max_nodes)
    logging.info(f"Private IP addresses for nodes in queue {queue} and compute resource {compute_resource}: " f"{ips}")

    assert_imex_nodes_config_is_correct(rce, launch_template_id, ips)
    assert_imex_status(rce, job_id, ips, service_status="UP", node_status="READY", connection_status="CONNECTED")
    assert_no_errors_in_logs(cluster, queue, compute_resource)


def assert_imex_not_configured(cluster: Cluster, queue: str, compute_resource: str, max_nodes: int = 1):
    rce = RemoteCommandExecutor(cluster)

    launch_template_id = cluster.get_compute_nodes_launch_template_logical_id(queue, compute_resource)
    logging.info(
        f"Launch template for nodes in queue {queue} and " f"compute resource {compute_resource}: {launch_template_id}"
    )

    job_id = submit_job_imex_status(rce, queue, max_nodes)

    assert_imex_nodes_config_is_correct(rce, launch_template_id, FAKE_IPS)
    assert_imex_status(
        rce, job_id, FAKE_IPS, service_status="DOWN", node_status="UNAVAILABLE", connection_status="INVALID"
    )


def assert_topology_plugin_configured(
    cluster: Cluster, queue: str, compute_resource: str, expected_block_sizes: str, expected_max_nodes: int
):
    """Verify TopologyPlugin is configured and topology.conf contains correct content."""
    rce = RemoteCommandExecutor(cluster)

    # Check TopologyPlugin is set to topology/block
    logging.info(f"Checking TopologyPlugin configuration for queue {queue}")
    result = rce.run_remote_command("scontrol show config | grep TopologyPlugin")
    # Check like below because it's like "TopologyPlugin          = topology/block"
    assert_that(result.stdout.strip()).contains("TopologyPlugin")
    assert_that(result.stdout.strip()).contains("= topology/block")

    # Check topology.conf exists and contains correct content
    topology_conf_path = "/opt/slurm/etc/topology.conf"
    assert_that(is_existing_remote_file(rce, topology_conf_path)).is_true()

    topology_content = read_remote_file(rce, topology_conf_path)
    logging.info(f"Topology configuration content: {topology_content}")

    # Verify BlockSizes configuration
    expected_block_sizes_content = f"BlockSizes={expected_block_sizes}"
    assert_that(topology_content).contains(expected_block_sizes_content)

    # Verify node naming format - always use range format for g4dn simulating GB200
    expected_block1 = "BlockName=Block1"
    expected_nodes = f"Nodes={queue}-st-{compute_resource}-[1-{expected_max_nodes}]"
    assert_that(topology_content).contains(expected_block1)
    assert_that(topology_content).contains(expected_nodes)

    # Check scontrol show topology output
    logging.info(f"Checking scontrol show topology output for queue {queue}")
    topology_result = rce.run_remote_command("scontrol show topology")
    topology_output = topology_result.stdout.strip()
    logging.info(f"Topology output: {topology_output}")

    # Verify the expected topology output format
    expected_block_index = "BlockIndex=0"
    assert_that(topology_output).contains(expected_block_sizes_content)
    assert_that(topology_output).contains(expected_block_index)
    assert_that(topology_output).contains(expected_block1)
    assert_that(topology_output).contains(expected_nodes)

    logging.info(f"TopologyPlugin correctly configured for queue {queue}")


def assert_topology_plugin_not_configured_for_queue(cluster: Cluster, queue: str, compute_resource: str):
    """Verify that specific queue nodes are not included in topology configuration."""
    rce = RemoteCommandExecutor(cluster)

    # TopologyPlugin should still be configured at cluster level
    logging.info("Checking TopologyPlugin is configured at cluster level")
    result = rce.run_remote_command("scontrol show config | grep TopologyPlugin")
    assert_that(result.stdout.strip()).contains("TopologyPlugin")
    assert_that(result.stdout.strip()).contains("= topology/block")

    # Check topology.conf exists (cluster-wide configuration)
    topology_conf_path = "/opt/slurm/etc/topology.conf"
    assert_that(is_existing_remote_file(rce, topology_conf_path)).is_true()

    # Verify that nodes from this queue are NOT in the topology configuration
    topology_content = read_remote_file(rce, topology_conf_path)
    logging.info(f"Topology configuration content: {topology_content}")

    # Check that q2-cr2 nodes are not mentioned in topology.conf
    queue_nodes_pattern = f"{queue}-st-{compute_resource}"
    assert_that(topology_content).does_not_contain(queue_nodes_pattern)

    # Check scontrol show topology output - should not contain q2-cr2 nodes
    topology_result = rce.run_remote_command("scontrol show topology")
    topology_output = topology_result.stdout.strip()
    logging.info(f"Topology output: {topology_output}")
    assert_that(topology_output).does_not_contain(queue_nodes_pattern)

    logging.info(f"Queue {queue} nodes correctly not included in topology configuration")


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
def test_gb200(
    pcluster_config_reader, file_reader, clusters_factory, test_datadir, s3_bucket_factory, region, instance
):
    """
    Test automated configuration of Nvidia IMEX and Slurm topology plugin.

    This test creates a cluster with the necessary custom actions to configure NVIDIA IMEX and verifies the following:
    1. On the compute resource supporting IMEX (q1-cr1):
       - The IMEX nodes file is configured by the prolog
       - IMEX service is healthy and no errors are reported in IMEX's or prolog's logs
       - TopologyPlugin is set to topology/block
       - /opt/slurm/etc/topology.conf contains correct block configuration for q1-cr1 nodes
       - IMEX gets reconfigured when nodes belonging to the same compute resource get replaced
    2. On the compute resource not supporting IMEX (q2-cr2):
       - The IMEX nodes file is not configured by the prolog, keeping the default values and IMEX is not started
       - TopologyPlugin is configured at cluster level but q2-cr2 nodes are not included in topology configuration
       - /opt/slurm/etc/topology.conf exists but does not contain q2-cr2 nodes

    The test prints in test log the full IMEX status to facilitate troubleshooting.
    The test uses instance type g4dn to simulate a p6e-gb200 instance.
    This is a reasonable approximation for the test because the focus of the test is on IMEX and topology configuration,
    which can be executed on g4dn as well.
    """
    max_queue_size = 2
    capacity_block_reservation_id = CAPACITY_BLOCK_RESERVATION_ID if instance == "p6e-gb200.36xlarge" else None

    # Create an S3 bucket for custom action scripts
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)

    # Upload files to test bucket
    headnode_start_filename = "head_node_start.sh"
    prolog_filename = "90-nvidia-imex.prolog.sh"
    job_filename = "nvidia-imex-status.job"
    bucket.upload_file(str(test_datadir / prolog_filename), prolog_filename)
    bucket.upload_file(str(test_datadir / job_filename), job_filename)
    head_node_start_script_rendered = file_reader(
        input_file=headnode_start_filename,
        output_file=f"{headnode_start_filename}.rendered",
        bucket_name=bucket_name,
        prolog_filename=prolog_filename,
        job_filename=job_filename,
    )
    bucket.upload_file(head_node_start_script_rendered, headnode_start_filename)

    queue_with_imex = "q1"
    compute_resource_with_imex = "cr1"
    queue_without_imex = "q2"
    compute_resource_without_imex = "cr2"

    cluster_config = pcluster_config_reader(
        bucket_name=bucket_name,
        head_node_start_script=headnode_start_filename,
        max_queue_size=max_queue_size,
        queue_with_imex=queue_with_imex,
        compute_resource_with_imex=compute_resource_with_imex,
        queue_without_imex=queue_without_imex,
        compute_resource_without_imex=compute_resource_without_imex,
        capacity_block_reservation_id=capacity_block_reservation_id,
    )
    cluster = clusters_factory(cluster_config)

    # Test IMEX and topology configuration for queue with IMEX support
    assert_imex_healthy(cluster, queue_with_imex, compute_resource_with_imex, max_queue_size)
    assert_topology_plugin_configured(
        cluster, queue_with_imex, compute_resource_with_imex, f"{max_queue_size}", max_queue_size
    )

    # Test that IMEX and topology are not configured for queue without IMEX support
    assert_imex_not_configured(cluster, queue_without_imex, compute_resource_without_imex)
    assert_topology_plugin_not_configured_for_queue(cluster, queue_without_imex, compute_resource_without_imex)

    # Test cluster update with changed topology configuration
    max_queue_size_updated = 3
    updated_cluster_config = pcluster_config_reader(
        config_file="pcluster.config.update.yaml",
        bucket_name=bucket_name,
        head_node_start_script=headnode_start_filename,
        max_queue_size=max_queue_size_updated,
        queue_with_imex=queue_with_imex,
        compute_resource_with_imex=compute_resource_with_imex,
        queue_without_imex=queue_without_imex,
        compute_resource_without_imex=compute_resource_without_imex,
    )

    cluster.update(str(updated_cluster_config))

    # Verify topology plugin configuration after update
    assert_topology_plugin_configured(
        cluster, queue_with_imex, compute_resource_with_imex, f"{max_queue_size_updated}", max_queue_size_updated
    )
    assert_topology_plugin_not_configured_for_queue(cluster, queue_without_imex, compute_resource_without_imex)

    # Forcefully terminate a compute node in the compute resource supporting IMEX
    # to simulate an outage that forces the replacement of the node and consequently the IMEX reconfiguration.
    logging.info(f"Terminating a node in queue {queue_with_imex} and compute resource {compute_resource_with_imex}")
    terminate_nodes_manually(
        [cluster.get_compute_nodes(queue_with_imex, compute_resource_with_imex)[0].get("InstanceId")], region
    )
    wait_for_instances_in_compute_resource(
        cluster, queue_with_imex, compute_resource_with_imex, ["running"], max_queue_size_updated
    )

    # Verify IMEX is still healthy after node replacement
    assert_imex_healthy(cluster, queue_with_imex, compute_resource_with_imex, max_queue_size_updated)
