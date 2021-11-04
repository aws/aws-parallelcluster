# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import time
from copy import deepcopy

import boto3
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds

from tests.common.assertions import assert_head_node_is_running

LAUNCH_TEMPLATES_CONFIG_PATH = "/opt/parallelcluster/shared/launch_templates_config.json"
BYOS_SUBSTACK_OUTPUTS_PATH = "/opt/parallelcluster/shared/byos_substack_outputs.json"
BYOS_LOG_PATH = "/var/log/parallelcluster/byos-plugin.log"
BYOS_HOME = "/home/byos"
BYOS_USERS_LIST = ["user1", "byosUser"]


@pytest.mark.usefixtures("instance", "scheduler", "os")
def test_byos(region, pcluster_config_reader, s3_bucket_factory, clusters_factory, test_datadir):
    """Test usage of a custom scheduler integration."""
    logging.info("Testing custom scheduler integration.")

    # Create bucket and upload resources
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    for file in ["byos_infra.cfn.yaml", "artifact"]:
        bucket.upload_file(str(test_datadir / file), f"byos/{file}")
    # Create cluster
    byos_user_list = deepcopy(BYOS_USERS_LIST)
    cluster_config = pcluster_config_reader(bucket=bucket_name, user1=byos_user_list.pop(), user2=byos_user_list.pop())
    cluster = clusters_factory(cluster_config)
    # Verify head node is running
    assert_head_node_is_running(region, cluster)
    # Command executor
    command_executor = RemoteCommandExecutor(cluster)
    # Start and wait for compute node to setup
    compute_node = _start_compute_node(region, cluster, command_executor)
    # Test even handler execution
    _test_event_handler_execution(command_executor, compute_node)
    # Test artifacts are downloaded
    _test_artifacts_download(command_executor)
    # Test substack outputs
    _test_subtack_outputs(command_executor)
    # Test users are created
    _test_users(command_executor, compute_node)


def _get_launch_templates(command_executor):
    """Get LT from head node"""
    launch_templates_config_content = command_executor.run_remote_command(f"cat {LAUNCH_TEMPLATES_CONFIG_PATH}").stdout
    assert_that(launch_templates_config_content).is_not_empty()
    launch_templates_config = json.loads(launch_templates_config_content)
    launch_templates_list = []
    for queue in launch_templates_config.get("Queues").values():
        for compute_resource in queue.get("ComputeResources").values():
            launch_templates_list.append(compute_resource.get("LaunchTemplate").get("Id"))
    assert_that(launch_templates_list).is_length(3)

    return launch_templates_list


def _start_compute_node(region, cluster, command_executor):
    """Start and wait compute node to finish setup"""
    # Get one launch template for compute node
    lt = _get_launch_templates(command_executor)[0]
    run_instance_command = (
        f"aws ec2 run-instances --region {region}"
        f" --instance-initiated-shutdown-behavior terminate"
        f" --count 1"
        f" --launch-template LaunchTemplateId={lt}"
    )
    command_executor.run_remote_command(run_instance_command)
    # Wait instance to start
    time.sleep(3)
    compute_nodes = cluster.describe_cluster_instances(node_type="Compute")
    assert_that(compute_nodes).is_length(1)
    compute_node = compute_nodes[0]
    instance_id = compute_node.get("instanceId")
    # Wait instance to go running
    _wait_instance_running(region, [instance_id])
    # Wait instance to complete cloud-init
    _wait_compute_cloudinit_done(command_executor, compute_node)

    return compute_node


def _wait_instance_running(region, instance_ids):
    """Wait EC2 instance to go running"""
    logging.info(f"Waiting for {instance_ids} to be running")
    boto3.client("ec2", region_name=region).get_waiter("instance_running").wait(
        InstanceIds=instance_ids, WaiterConfig={"Delay": 60, "MaxAttempts": 5}
    )


@retry(wait_fixed=seconds(10), stop_max_delay=minutes(3))
def _wait_compute_cloudinit_done(command_executor, compute_node):
    """Wait till cloud-init complete on a given compute node"""
    compute_node_private_ip = compute_node.get("privateIpAddress")
    compute_cloudinit_status_output = command_executor.run_remote_command(
        f"ssh -q {compute_node_private_ip} sudo cloud-init status"
    ).stdout
    assert_that(compute_cloudinit_status_output).contains("status: done")


def _test_event_handler_execution(command_executor, compute_node):
    """Test event handler execution and environment"""
    head_byos_log_output = command_executor.run_remote_command(f"cat {BYOS_LOG_PATH}").stdout
    for event in ["HeadInit", "HeadConfigure", "HeadFinalize"]:
        assert_that(head_byos_log_output).contains(f"[{event}] - INFO: {event} executed")
        _test_event_handler_environment(event, head_byos_log_output)

    compute_node_private_ip = compute_node.get("privateIpAddress")
    compute_byos_log_output = command_executor.run_remote_command(
        f"ssh -q {compute_node_private_ip} cat {BYOS_LOG_PATH}"
    ).stdout
    for event in ["ComputeInit", "ComputeConfigure", "ComputeFinalize"]:
        assert_that(compute_byos_log_output).contains(f"[{event}] - INFO: {event} executed")
        _test_event_handler_environment(event, compute_byos_log_output)


def _test_event_handler_environment(event, log_output):
    """Test event handler environment"""
    for var in [
        "PCLUSTER_CLUSTER_CONFIG",
        "PCLUSTER_LAUNCH_TEMPLATES",
        "PCLUSTER_INSTANCE_TYPES_DATA",
        "PCLUSTER_CLUSTER_NAME",
        "PCLUSTER_CFN_STACK_ARN",
        "PCLUSTER_BYOS_CFN_SUBSTACK_ARN",
        "PCLUSTER_BYOS_CFN_SUBSTACK_OUTPUTS",
        "PCLUSTER_SHARED_BYOS_DIR",
        "PCLUSTER_LOCAL_BYOS_DIR",
        "PCLUSTER_AWS_REGION",
        "AWS_REGION",
        "PCLUSTER_OS",
        "PCLUSTER_ARCH",
        "PCLUSTER_VERSION",
        "PCLUSTER_HEADNODE_PRIVATE_IP",
        "PCLUSTER_HEADNODE_HOSTNAME",
        # TODO
        # PCLUSTER_CLUSTER_CONFIG_OLD,
        # PROXY
    ]:
        assert_that(log_output).contains(f"[{event}] - INFO: {var}=")


def _test_artifacts_download(command_executor):
    """Test artifacts download"""
    home_listing = command_executor.run_remote_command(f"sudo ls {BYOS_HOME}").stdout
    assert_that(home_listing).contains("develop.zip")
    assert_that(home_listing).contains("artifact")


def _test_subtack_outputs(command_executor):
    """Test substack output is fetched by head node"""
    head_byos_substack_outputs = command_executor.run_remote_command(f"cat {BYOS_SUBSTACK_OUTPUTS_PATH}").stdout
    assert_that(head_byos_substack_outputs).contains('"TestOutput":"TestValue"')


def _test_users(command_executor, compute_node):
    """Test custom scheduler users"""
    compute_node_private_ip = compute_node.get("privateIpAddress")
    for user in BYOS_USERS_LIST:
        command_executor.run_remote_command(f"getent passwd {user}")
        command_executor.run_remote_command(f"ssh -q {compute_node_private_ip} getent passwd {user}")
