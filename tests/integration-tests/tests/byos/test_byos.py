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

import boto3
import pytest
import yaml
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds

from tests.common.assertions import assert_head_node_is_running, assert_instance_replaced_or_terminating
from tests.common.utils import get_installed_parallelcluster_version

PCLUSTER_CLUSTER_CONFIG = "/home/byos/.parallelcluster/cluster-config.yaml"
PCLUSTER_LAUNCH_TEMPLATES = "/home/byos/.parallelcluster/launch_templates_config.json"
PCLUSTER_INSTANCE_TYPES_DATA = "/home/byos/.parallelcluster/instance-types-data.json"
PCLUSTER_BYOS_CFN_SUBSTACK_OUTPUTS = "/home/byos/.parallelcluster/byos_substack_outputs.json"
PCLUSTER_SHARED_BYOS_DIR = "/opt/parallelcluster/shared/byos"
PCLUSTER_LOCAL_BYOS_DIR = "/opt/parallelcluster/byos"

BYOS_LOG_PATH = "/var/log/parallelcluster/byos-plugin.log"
BYOS_HOME = "/home/byos"
BYOS_USERS_LIST = ["user1", "byosUser"]

ANOTHER_INSTANCE_TYPE = "c4.xlarge"


@pytest.mark.usefixtures("instance", "scheduler")
def test_byos_integration(
    region, os, architecture, instance, pcluster_config_reader, s3_bucket_factory, clusters_factory, test_datadir
):
    """Test usage of a custom scheduler integration."""
    logging.info("Testing plugin scheduler integration.")

    # Setup:
    # Get EC2 client
    ec2_client = boto3.client("ec2", region_name=region)
    # Create bucket and upload resources
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    for file in ["byos_infra.cfn.yaml", "artifact"]:
        bucket.upload_file(str(test_datadir / file), f"byos/{file}")
    # Create cluster
    cluster_config = pcluster_config_reader(
        bucket=bucket_name,
        another_instance=ANOTHER_INSTANCE_TYPE,
        user1=BYOS_USERS_LIST[0],
        user2=BYOS_USERS_LIST[1],
    )
    cluster = clusters_factory(cluster_config)
    # Verify head node is running
    assert_head_node_is_running(region, cluster)
    head_node = _get_ec2_instance_from_id(
        ec2_client, cluster.describe_cluster_instances(node_type="HeadNode")[0].get("instanceId")
    )
    # Command executor
    command_executor = RemoteCommandExecutor(cluster)
    # Start and wait for compute node to setup
    compute_node = _start_compute_node(ec2_client, region, cluster, command_executor)

    # Tests:
    # Test even handler execution
    _test_event_handler_execution(cluster, region, os, architecture, command_executor, head_node, compute_node)
    # Test artifacts are downloaded
    _test_artifacts_download(command_executor)
    # Test artifacts shared from head to compute node
    _test_artifacts_shared_from_head(command_executor, compute_node)
    # Test substack outputs
    _test_subtack_outputs(command_executor)
    # Test users are created
    _test_users(command_executor, compute_node)
    # Test user imds
    _test_imds(command_executor)
    # Test cluster configuration
    _test_cluster_config(command_executor, cluster_config)
    # Test instance types data
    _test_instance_types_data(command_executor, instance)
    # Test computes are terminated on cluster deletion
    cluster.delete()
    _test_compute_terminated(compute_node, region)

    # TODO:
    #  test sudo privilege for the users
    #  test log are uploaded to CW


def _get_launch_templates(command_executor):
    """Get LT from head node"""
    launch_templates_config_content = command_executor.run_remote_command(
        f"sudo cat {PCLUSTER_LAUNCH_TEMPLATES}"
    ).stdout
    assert_that(launch_templates_config_content).is_not_empty()
    launch_templates_config = json.loads(launch_templates_config_content)
    launch_templates_list = []
    for queue in launch_templates_config.get("Queues").values():
        for compute_resource in queue.get("ComputeResources").values():
            launch_templates_list.append(compute_resource.get("LaunchTemplate").get("Id"))
    assert_that(launch_templates_list).is_length(3)

    return launch_templates_list


def _start_compute_node(ec2_client, region, cluster, command_executor):
    """Start and wait compute node to finish setup"""
    # Get one launch template for compute node
    lt = _get_launch_templates(command_executor)[0]
    run_instance_command = (
        f"aws ec2 run-instances --region {region}" f" --count 1" f" --launch-template LaunchTemplateId={lt}"
    )
    command_executor.run_remote_command(run_instance_command)
    # Wait instance to start
    time.sleep(3)
    compute_nodes = cluster.describe_cluster_instances(node_type="Compute")
    assert_that(compute_nodes).is_length(1)
    compute_node = compute_nodes[0]
    instance_id = compute_node.get("instanceId")
    # Wait instance to go running
    _wait_instance_running(ec2_client, [instance_id])
    # Wait instance to complete cloud-init
    _wait_compute_cloudinit_done(command_executor, compute_node)

    return compute_node


def _wait_instance_running(ec2_client, instance_ids):
    """Wait EC2 instance to go running"""
    logging.info(f"Waiting for {instance_ids} to be running")
    ec2_client.get_waiter("instance_running").wait(
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


def _test_event_handler_execution(cluster, region, os, architecture, command_executor, head_node, compute_node):
    """Test event handler execution and environment"""
    head_byos_log_output = command_executor.run_remote_command(f"cat {BYOS_LOG_PATH}").stdout
    for event in ["HeadInit", "HeadConfigure", "HeadFinalize"]:
        assert_that(head_byos_log_output).contains(f"[{event}] - INFO: {event} executed")
        _test_event_handler_environment(cluster, region, os, architecture, event, head_byos_log_output, head_node)

    compute_node_private_ip = compute_node.get("privateIpAddress")
    compute_byos_log_output = command_executor.run_remote_command(
        f"ssh -q {compute_node_private_ip} cat {BYOS_LOG_PATH}"
    ).stdout
    for event in ["ComputeInit", "ComputeConfigure", "ComputeFinalize"]:
        assert_that(compute_byos_log_output).contains(f"[{event}] - INFO: {event} executed")
        _test_event_handler_environment(cluster, region, os, architecture, event, compute_byos_log_output, head_node)


def _test_event_handler_environment(cluster, region, os, architecture, event, log_output, head_node):
    """Test event handler environment"""
    for var in [
        f"PCLUSTER_CLUSTER_CONFIG={PCLUSTER_CLUSTER_CONFIG}",
        f"PCLUSTER_LAUNCH_TEMPLATES={PCLUSTER_LAUNCH_TEMPLATES}",
        f"PCLUSTER_INSTANCE_TYPES_DATA={PCLUSTER_INSTANCE_TYPES_DATA}",
        f"PCLUSTER_CLUSTER_NAME={cluster.name}",
        f"PCLUSTER_CFN_STACK_ARN={cluster.cfn_stack_arn}",
        f"PCLUSTER_BYOS_CFN_SUBSTACK_ARN={cluster.cfn_resources.get('ByosStack')}",
        f"PCLUSTER_BYOS_CFN_SUBSTACK_OUTPUTS={PCLUSTER_BYOS_CFN_SUBSTACK_OUTPUTS}",
        f"PCLUSTER_SHARED_BYOS_DIR={PCLUSTER_SHARED_BYOS_DIR}",
        f"PCLUSTER_LOCAL_BYOS_DIR={PCLUSTER_LOCAL_BYOS_DIR}",
        f"PCLUSTER_AWS_REGION={region}",
        f"AWS_REGION={region}",
        f"PCLUSTER_OS={os}",
        f"PCLUSTER_ARCH={architecture}",
        f"PCLUSTER_VERSION={get_installed_parallelcluster_version()}",
        f"PCLUSTER_HEADNODE_PRIVATE_IP={head_node.get('PrivateIpAddress')}",
        f"PCLUSTER_HEADNODE_HOSTNAME={head_node.get('PrivateDnsName').split('.')[0]}",
        # TODO
        # PCLUSTER_<CLUSTER_CONFIG_OLD,
        # PROXY
    ]:
        assert_that(log_output).contains(f"[{event}] - INFO: {var}")


def _test_artifacts_download(command_executor):
    """Test artifacts download"""
    home_listing = command_executor.run_remote_command(f"sudo ls {BYOS_HOME}").stdout
    assert_that(home_listing).contains("aws-parallelcluster-cookbook-3.0.0.tgz")
    assert_that(home_listing).contains("artifact")


def _test_artifacts_shared_from_head(command_executor, compute_node):
    """Test artifacts shared from head to compute node"""
    compute_node_private_ip = compute_node.get("privateIpAddress")
    shared_listing = command_executor.run_remote_command(
        f"ssh -q {compute_node_private_ip} ls {PCLUSTER_SHARED_BYOS_DIR}"
    ).stdout
    assert_that(shared_listing).contains("sharedFromHead")


def _test_subtack_outputs(command_executor):
    """Test substack output is fetched by head node"""
    head_byos_substack_outputs = command_executor.run_remote_command(
        f"sudo cat {PCLUSTER_BYOS_CFN_SUBSTACK_OUTPUTS}"
    ).stdout
    assert_that(head_byos_substack_outputs).contains('"TestOutput":"TestValue"')


def _test_users(command_executor, compute_node):
    """Test custom scheduler users"""
    compute_node_private_ip = compute_node.get("privateIpAddress")
    for user in BYOS_USERS_LIST:
        command_executor.run_remote_command(f"getent passwd {user}")
        command_executor.run_remote_command(f"ssh -q {compute_node_private_ip} getent passwd {user}")


def _get_ec2_instance_from_id(ec2, instance_id):
    return ec2.describe_instances(Filters=[], InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]


def _test_instance_types_data(command_executor, instance_type):
    """Test instance types data is fetched by head node"""
    instance_types_data_content = command_executor.run_remote_command(f"sudo cat {PCLUSTER_INSTANCE_TYPES_DATA}").stdout
    assert_that(instance_types_data_content).is_not_empty()
    instance_types_data = json.loads(instance_types_data_content)
    assert_that(instance_types_data.get(instance_type).get("InstanceType")).is_equal_to(instance_type)
    assert_that(instance_types_data.get(ANOTHER_INSTANCE_TYPE).get("InstanceType")).is_equal_to(ANOTHER_INSTANCE_TYPE)


def _test_imds(command_executor):
    """Test imds setting for custom scheduler users"""
    # BYOS_USERS_LIST[0] with EnableImds: false
    result = command_executor.run_remote_command(
        f'sudo su - {BYOS_USERS_LIST[0]} -c "curl --retry 3 --retry-delay 0 --fail -s'
        " -X PUT 'http://169.254.169.254/latest/api/token'"
        " -H 'X-aws-ec2-metadata-token-ttl-seconds: 300'\"",
        raise_on_error=False,
    )
    assert_that(result.failed).is_equal_to(True)

    # BYOS_USERS_LIST[1] with EnableImds: true
    result = command_executor.run_remote_command(
        f'sudo su - {BYOS_USERS_LIST[1]} -c "curl --retry 3 --retry-delay 0  --fail -s'
        " -X PUT 'http://169.254.169.254/latest/api/token'"
        " -H 'X-aws-ec2-metadata-token-ttl-seconds: 300'\""
    )
    assert_that(result.failed).is_equal_to(False)
    assert_that(result.stdout).is_not_empty()


def _test_cluster_config(command_executor, cluster_config):
    """Test cluster configuration file is fetched by head node"""
    with open(cluster_config, encoding="utf-8") as cluster_config_file:
        source_config = yaml.safe_load(cluster_config_file)
        assert_that(source_config).is_not_empty()

        target_config_content = command_executor.run_remote_command(f"sudo cat {PCLUSTER_CLUSTER_CONFIG}").stdout
        assert_that(target_config_content).is_not_empty()
        target_config = yaml.safe_load(target_config_content)

        assert_that(
            source_config.get("Scheduling").get("ByosSettings").get("SchedulerDefinition").get("Events")
        ).is_equal_to(target_config.get("Scheduling").get("ByosSettings").get("SchedulerDefinition").get("Events"))
        assert_that(source_config.get("Scheduling").get("ByosQeueus")).is_equal_to(
            target_config.get("Scheduling").get("ByosQeueus")
        )
        assert_that(
            source_config.get("Scheduling").get("ByosSettings").get("SchedulerDefinition").get("SystemUsers")
        ).is_equal_to(target_config.get("Scheduling").get("ByosSettings").get("SchedulerDefinition").get("SystemUsers"))


@retry(wait_fixed=seconds(10), stop_max_delay=minutes(3))
def _test_compute_terminated(node, region):
    assert_instance_replaced_or_terminating(instance_id=node.get("instanceId"), region=region)
