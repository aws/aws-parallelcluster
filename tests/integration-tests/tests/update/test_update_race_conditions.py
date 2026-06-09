# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from datetime import datetime, timezone

import boto3
import pytest
from assertpy import assert_that, soft_assertions
from diagnosis_utils import get_cluster_nodes_snapshot
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from utils import get_username_for_os, match_regex_in_log

from tests.common.schedulers_common import SlurmCommands
from tests.common.utils import get_deployed_config_version

logger = logging.getLogger(__name__)

BLOCKING_S3_KEY_PREFIX = "block_bootstrap"
NODE_TYPE_COMPUTE = "ComputeNode"
NODE_TYPE_LOGIN = "LoginNode"
PHASE_ON_NODE_START = "OnNodeStart"
PHASE_ON_NODE_CONFIGURED = "OnNodeConfigured"
SERVICE_MANAGEMENT_CMD_BY_NODE_TYPE = {
    NODE_TYPE_COMPUTE: "systemctl",
    NODE_TYPE_LOGIN: "systemctl",
}
UPDATE_DETECTION_SERVICE_BY_NODE_TYPE = {
    NODE_TYPE_COMPUTE: "pcluster-check-update.timer",
    NODE_TYPE_LOGIN: "pcluster-check-update.timer",
}
UPDATE_ACTION_SCRIPT_BY_NODE_TYPE = {
    NODE_TYPE_COMPUTE: "/opt/parallelcluster/scripts/cfn-hup-update-action.sh",
    NODE_TYPE_LOGIN: "/opt/parallelcluster/scripts/cfn-hup-update-action.sh",
}
LOG_FILE_BY_NODE_TYPE = {
    NODE_TYPE_COMPUTE: "/var/log/parallelcluster/pcluster-check-update.log",
    NODE_TYPE_LOGIN: "/var/log/parallelcluster/pcluster-check-update.log",
}


def get_node_ip(rce, node_name):
    result = rce.run_remote_command(
        f"scontrol show node {node_name} | grep NodeAddr | awk -F= '{{print $2}}' | awk '{{print $1}}'"
    )
    ip = result.stdout.strip()
    logger.info(f"Resolved node {node_name} to IP {ip}")
    return ip


def get_login_node_ip(cluster, instance_id):
    for node in cluster.describe_login_nodes():
        if node["instanceId"] == instance_id:
            return node["privateIpAddress"]
    raise Exception(f"Login node {instance_id} not found")


def get_node_rce(rce, cluster, node_type, node_id):
    if node_type == NODE_TYPE_COMPUTE:
        cn_ip = get_node_ip(rce, node_id)
        return RemoteCommandExecutor(cluster, compute_node_ip=cn_ip)
    elif node_type == NODE_TYPE_LOGIN:
        login_node_ip = get_login_node_ip(cluster, node_id)
        username = get_username_for_os(cluster.os)
        return RemoteCommandExecutor(cluster, login_node_ip=login_node_ip, bastion=f"{username}@{cluster.head_node_ip}")
    else:
        raise ValueError(f"Unsupported node type: {node_type}")


def get_blocking_s3_key(node_type: str, phase: str):
    return f"{BLOCKING_S3_KEY_PREFIX}_{node_type}_{phase}"


def get_blocking_s3_uri(bucket_name: str, node_type: str, phase: str):
    return f"s3://{bucket_name}/{get_blocking_s3_key(node_type, phase)}"


def block_node_boostrap(region, bucket_name, node_type: str, phase: str):
    s3_key = get_blocking_s3_key(node_type, phase)
    boto3.client("s3", region_name=region).put_object(Bucket=bucket_name, Key=s3_key, Body=b"")
    logger.info(f"Created bootstrap blocking marker s3://{bucket_name}/{s3_key} for {node_type} in phase {phase}")


def unblock_node_bootstrap(region, bucket_name, node_type: str, phase: str):
    s3_key = get_blocking_s3_key(node_type, phase)
    boto3.client("s3", region_name=region).delete_object(Bucket=bucket_name, Key=s3_key)
    logger.info(f"Removed bootstrap blocking marker s3://{bucket_name}/{s3_key} for {node_type} in phase {phase}")


@retry(wait_fixed=seconds(10), stop_max_delay=minutes(20))
def wait_for_readiness_check_last_retry(rce, after_utc=None):
    match, lines = match_regex_in_log(
        rce,
        "/var/log/chef-client.log",
        r"Retrying execution of execute\[Check cluster readiness\], 1 attempt left",
        after_utc=after_utc,
    )
    if not match:
        raise Exception(f"Readiness check has not reached the second-last retry yet. Last lines: {lines}")
    logger.info(f"Readiness check reached second-last iteration (1 attempt left): {lines}")


@retry(wait_fixed=seconds(5), stop_max_delay=minutes(1))
def get_login_nodes_nested_stack_name(cluster, region):
    """Retrieve the physical resource ID (stack name) of the LoginNodesNestedStack from the parent stack."""
    client = boto3.client("cloudformation", region_name=region)
    paginator = client.get_paginator("list_stack_resources")
    for page in paginator.paginate(StackName=cluster.name):
        for resource in page["StackResourceSummaries"]:
            if resource["LogicalResourceId"].startswith("LoginNodesNestedStack"):
                return resource["PhysicalResourceId"]
    raise Exception("LoginNodesNestedStack resource not found in parent stack")


@retry(wait_fixed=seconds(5), stop_max_delay=minutes(10))
def wait_for_login_nodes_lt_update_complete(cluster, region, after_utc=None):
    expected_status = "UPDATE_COMPLETE"
    after_dt = datetime.fromisoformat(after_utc.replace("Z", "+00:00")) if after_utc else None
    nested_stack_name = get_login_nodes_nested_stack_name(cluster, region)
    client = boto3.client("cloudformation", region_name=region)
    paginator = client.get_paginator("describe_stack_events")
    for page in paginator.paginate(StackName=nested_stack_name):
        for event in page["StackEvents"]:
            if (
                event.get("LogicalResourceId", "").startswith("LoginNodeLaunchTemplate")
                and event["ResourceType"] == "AWS::EC2::LaunchTemplate"
                and event["ResourceStatus"] == "UPDATE_COMPLETE"
                and (not after_dt or event["Timestamp"] >= after_dt)
            ):
                logger.info(f"LoginNodeLaunchTemplate reached expected status {expected_status}: {event['EventId']}")
                return
    raise Exception(
        f"LoginNodeLaunchTemplate has not reached the expected status {expected_status} (after_utc={after_utc})"
    )


@retry(wait_fixed=seconds(10), stop_max_delay=minutes(5))
def wait_for_node_update_failure(rce, cluster, node_type, node_id, os, after_utc=None):
    node_rce = get_node_rce(rce, cluster, node_type, node_id)
    log_file = LOG_FILE_BY_NODE_TYPE[node_type]
    match, lines = match_regex_in_log(
        node_rce,
        log_file,
        r"(?i)Permission denied",
        after_utc=after_utc,
    )
    if not match:
        raise Exception(f"No evidence of update failure on {node_type} {node_id} yet. Last lines: {lines}")
    logger.info(
        f"Found evidence of update failure on {node_type} {node_id} due to missing execute permissions: {lines}"
    )


@retry(wait_fixed=seconds(10), stop_max_delay=minutes(30))
def wait_for_head_node_update_recipe_complete(rce, after_utc=None):
    match, matched_content = match_regex_in_log(
        rce,
        "/var/log/chef-client.log",
        r"Cinc Client Run complete",
        after_utc=after_utc,
    )
    if not match:
        raise Exception("Head node chef-client run has not completed yet.")
    logger.info(f"Head node chef-client run completed: {matched_content}")


@retry(wait_fixed=seconds(10), stop_max_delay=minutes(30))
def wait_for_stack_rollback_complete(cluster):
    client = boto3.client("cloudformation", region_name=cluster.region)
    stack_status = client.describe_stacks(StackName=cluster.name)["Stacks"][0]["StackStatus"]
    logger.info(f"Current stack status: {stack_status}")
    if stack_status != "UPDATE_ROLLBACK_COMPLETE":
        raise Exception(f"Stack not in UPDATE_ROLLBACK_COMPLETE state: {stack_status}")
    return stack_status


def check_deployed_config_version(rce, cluster, node_name: str):
    updated_config_version = get_deployed_config_version(cluster)
    cn_ip = get_node_ip(rce, node_name)
    cn_config_version = get_deployed_config_version(cluster, compute_node_ip=cn_ip)
    return cn_config_version == updated_config_version


def start_slow_dynamic_node(region, bucket_name, rce, node_name: str, phase: str):
    block_node_boostrap(region, bucket_name, NODE_TYPE_COMPUTE, phase)
    SlurmCommands(rce).submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 300",
            "host": node_name,
        }
    )


def launch_slow_login_node(region, bucket_name, cluster, phase):
    block_node_boostrap(region, bucket_name, NODE_TYPE_LOGIN, phase)
    original_login_node_ids = {n["instanceId"] for n in cluster.describe_login_nodes()}
    login_node_to_terminate = next(iter(original_login_node_ids))
    boto3.client("ec2", region_name=cluster.region).terminate_instances(InstanceIds=[login_node_to_terminate])
    logger.info(
        f"Terminated login node {login_node_to_terminate}. "
        f"Waiting for a replacement login node that will be slowed down in {phase}"
    )
    new_login_node_id = wait_for_new_login_node(cluster, original_login_node_ids)
    logger.info(f"New login node {new_login_node_id} has joined the cluster")
    return new_login_node_id


@retry(wait_fixed=seconds(10), stop_max_delay=minutes(10))
def wait_for_new_login_node(cluster, original_instance_ids):
    current_instance_ids = {n["instanceId"] for n in cluster.describe_login_nodes()}
    new_ids = current_instance_ids - original_instance_ids
    if not new_ids:
        raise Exception(
            f"No new login node found yet. " f"Original: {original_instance_ids}, current: {current_instance_ids}"
        )
    return next(iter(new_ids))


def block_update_detection(rce, cluster, node_type, node_id):
    node_rce = get_node_rce(rce, cluster, node_type, node_id)
    service_management_cmd = SERVICE_MANAGEMENT_CMD_BY_NODE_TYPE[node_type]
    service = UPDATE_DETECTION_SERVICE_BY_NODE_TYPE[node_type]
    cmd = f"sudo {service_management_cmd} stop {service}"
    node_rce.run_remote_command(cmd)
    logger.info(f"Stopped {service} on {node_type} {node_id}")


def unblock_update_detection(rce, cluster, node_type, node_id):
    node_rce = get_node_rce(rce, cluster, node_type, node_id)
    service_management_cmd = SERVICE_MANAGEMENT_CMD_BY_NODE_TYPE[node_type]
    service = UPDATE_DETECTION_SERVICE_BY_NODE_TYPE[node_type]
    cmd = f"sudo {service_management_cmd} start {service}"
    node_rce.run_remote_command(cmd)
    logger.info(f"Started {service} on {node_type} {node_id}")


def inject_transient_update_failure(rce, cluster, node_type, node_id):
    node_rce = get_node_rce(rce, cluster, node_type, node_id)
    script_path = UPDATE_ACTION_SCRIPT_BY_NODE_TYPE[node_type]
    node_rce.run_remote_command(f"sudo chmod -x {script_path}")
    logger.info(
        f"Removed execute permissions from {script_path} on {node_type} {node_id} "
        f"to inject transient update failure"
    )


def remove_transient_update_failure(rce, cluster, node_type, node_id):
    node_rce = get_node_rce(rce, cluster, node_type, node_id)
    script_path = UPDATE_ACTION_SCRIPT_BY_NODE_TYPE[node_type]
    node_rce.run_remote_command(f"sudo chmod +x {script_path}")
    logger.info(f"Restored execute permissions on {script_path} on {node_type} {node_id}")


def _node_label(node):
    return f"Node {node['nodeType']} {node['instanceId']} ({node['privateIpAddress']})"


def assert_config_version_dna_matches_ddb(cluster_nodes_snapshot):
    for node in cluster_nodes_snapshot["instances"]:
        # We do not need to check HeadNode because that is the source of truth
        if node["nodeType"] == "HeadNode":
            continue
        node_label = _node_label(node)
        if node["deployed_config_version"] is None:
            assert_that(node["errors"]).described_as(
                f"{node_label} deployed config version could not be retrieved"
            ).is_empty()
        if node["ddb_config_version"] is None:
            assert_that(node["errors"]).described_as(
                f"{node_label} DynamoDB config version could not be retrieved"
            ).is_empty()
        assert_that(node["ddb_config_version"]).described_as(
            f"{node_label} DynamoDB config version ({node['ddb_config_version']}) "
            f"does not match deployed config version ({node['deployed_config_version']})"
        ).is_equal_to(node["deployed_config_version"])


def assert_config_version_matches_head_node(snapshot, expected_failure_instance_ids=None):
    expected_failure_instance_ids = expected_failure_instance_ids or set()
    head_nodes = [n for n in snapshot["instances"] if n["nodeType"] == "HeadNode"]
    assert_that(head_nodes).described_as("Head node not found in snapshot").is_not_empty()
    head_config_version = head_nodes[0]["deployed_config_version"]
    assert_that(head_config_version).described_as("Head node config version could not be retrieved").is_not_none()
    for node in snapshot["instances"]:
        # We do not need to check HeadNode because that is the source of truth
        if node["nodeType"] == "HeadNode":
            continue
        prefix = _node_label(node)
        if node["deployed_config_version"] is None:
            assert_that(node["errors"]).described_as(
                f"{prefix} deployed config version could not be retrieved"
            ).is_empty()
            continue
        if node["instanceId"] in expected_failure_instance_ids:
            if node["deployed_config_version"] != head_config_version:
                logger.warning(
                    f"{prefix} deployed config version ({node['deployed_config_version']}) "
                    f"does not match head node ({head_config_version}) "
                    "(expected failure due to [RaceCondition 5], not blocking the test)"
                )
            continue
        assert_that(node["deployed_config_version"]).described_as(
            f"{prefix} deployed config version ({node['deployed_config_version']}) "
            f"does not match head node ({head_config_version})"
        ).is_equal_to(head_config_version)


def assert_correct_recipe_order(snapshot):
    finalize_recipe = "aws-parallelcluster-entrypoints::finalize"
    update_recipe = "aws-parallelcluster-entrypoints::update"
    for node in snapshot["instances"]:
        if node["nodeType"] == "HeadNode":
            continue
        prefix = _node_label(node)
        recipes_data = node["recipes"]
        if recipes_data is None:
            assert_that(node["errors"]).described_as(f"{prefix} recipes could not be retrieved").is_empty()
            continue
        recipes = [r["recipe"] for r in recipes_data]
        assert_that(recipes).described_as(f"{prefix} is missing the finalize recipe").contains(finalize_recipe)
        if update_recipe in recipes:
            last_finalize_idx = len(recipes) - 1 - recipes[::-1].index(finalize_recipe)
            first_update_idx = recipes.index(update_recipe)
            assert_that(first_update_idx).described_as(
                f"{prefix} executed the update recipe (position {first_update_idx}) "
                f"before the last finalize recipe (position {last_finalize_idx}). Recipes: {recipes_data}"
            ).is_greater_than(last_finalize_idx)


def assert_update_recipe_executed_on_old_nodes(snapshot, update_submitted_at, expected_failure_instance_ids=None):
    """Assert that all nodes launched before update_submitted_at have executed the update recipe after that time.

    :param snapshot: cluster nodes snapshot from get_cluster_nodes_snapshot.
    :param update_submitted_at: UTC timestamp string in ISO format (e.g. "2026-03-16T12:34:56.000Z").
    :param expected_failure_instance_ids: optional set of instance IDs where assertion failures are logged as
        warnings instead of causing the test to fail.
    """
    expected_failure_instance_ids = expected_failure_instance_ids or set()
    update_recipe = "aws-parallelcluster-entrypoints::update"
    cutoff = datetime.fromisoformat(update_submitted_at.replace("Z", "+00:00"))
    for node in snapshot["instances"]:
        if node["nodeType"] == "HeadNode":
            continue
        prefix = _node_label(node)
        launch_time_str = node.get("launchTime")
        if launch_time_str is None:
            continue
        launch_time = datetime.fromisoformat(launch_time_str.replace("Z", "+00:00"))
        if launch_time >= cutoff:
            continue
        recipes_data = node["recipes"]
        if recipes_data is None:
            assert_that(node["errors"]).described_as(f"{prefix} recipes could not be retrieved").is_empty()
            continue
        update_entries = [r for r in recipes_data if r["recipe"] == update_recipe and r["timestamp"] is not None]
        update_after_cutoff = [
            r for r in update_entries if datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) >= cutoff
        ]
        if node["instanceId"] in expected_failure_instance_ids:
            if not update_after_cutoff:
                logger.warning(
                    f"{prefix} was launched at {launch_time_str} (before update at {update_submitted_at}) "
                    f"but did not execute the update recipe after the update was submitted "
                    f"(expected failure due to [RaceCondition 5], not blocking the test). Recipes: {recipes_data}"
                )
            continue
        assert_that(update_after_cutoff).described_as(
            f"{prefix} was launched at {launch_time_str} (before update at {update_submitted_at}) "
            f"but did not execute the update recipe after the update was submitted. Recipes: {recipes_data}"
        ).is_not_empty()


# CN_1: a dynamic compute node that completes the bootstrap after the readiness check
# CN_2: a dynamic compute node that completes the bootstrap at the second-last iteration of the readiness check
# CN_3: a static node that fails the update due to a transient failure
# CN_4: a static compute node that is unable to detect the update till the second-last iteration of the readiness check
# LN_1: a login node forcefully terminated to trigger replacement
CN_1 = "q1-dy-cr1-1"
CN_2 = "q1-dy-cr1-2"
CN_3 = "q1-st-cr1-1"
CN_4 = "q1-st-cr1-2"


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_update_race_conditions(
    region,
    os,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
    s3_bucket_factory,
):
    """
    Test that a cluster update succeeds despite exposure to the risk of race conditions on compute and login nodes.

    The test verifies that all the known race conditions below are solved:
        * [RaceCondition 1] A node that completes the bootstrap after the update is not able to execute the update.
           We know this could happen when DNA files are removed at the end of a successful update.
        * [RaceCondition 2] A node that completes the bootstrap close to the end of the readiness check can cause
           the readiness check to fail because it does not have enough time to complete the update.
        * [RaceCondition 3] A node that faces a transient failure in the execution of the update does not retry
           the update.
        * [RaceCondition 4] A node that faces a transient failure in the detection of the update does not retry
           the update.
        * [RaceCondition 5] A login node that is started before the update but completes the config phase during
           the update will skip the update. This happens because the update detection mechanism will see the
           updated launch template and will think thereafter that it has deployed the updated config,
           even if it did not.

    The test creates a cluster with 2 static compute nodes, 1 login node, and capacity for dynamic
    compute nodes. It then performs two successive updates, each designed to exercise different
    race conditions that can occur during the update process.

    Nodes under test:
        CN_1 (q1-dy-cr1-1): dynamic node, bootstrap blocked in OnNodeConfigured before update 1.
        CN_2 (q1-dy-cr1-2): dynamic node, bootstrap blocked in OnNodeConfigured before update 2.
        CN_3 (q1-st-cr1-1): static node, transient failure injected in the execution of its update before update 2.
        CN_4 (q1-st-cr1-2): static node, transient failure injected in the detection of its update before update 2.
        LN_1: login node terminated and replaced by a slow-bootstrapping one before update 2.
        LN_2: an existing login node with a transient update execution failure (chmod -x of the update action script).
        LN_3: an existing login node with update detection blocked (pcluster-check-update.timer stopped).

    Update 1: validates race condition #1
        [RaceCondition 1]  CN_1 is launched with its bootstrap blocked before the update is submitted. The update
        completes while CN_1 is still bootstrapping. CN_1 is then unblocked and given time to
        attempt applying the update. The test verifies that CN_1 was able to pick up the new
        config version despite having started its bootstrap before the update.

    Update 2: validates race conditions #2, #3, #4 and #5
        Before submitting the update, the following conditions are set up:
        - [RaceCondition 2] CN_2 has its bootstrap blocked in OnNodeConfigured, so it will complete bootstrapping
          during the readiness check window.
        - [RaceCondition 3] CN_3 and LN_2 has execute permissions removed from the update action script,
          causing a transient "Permission denied" failure. Permissions are restored after the failure is confirmed,
          so the node can succeed on retry.
        - [RaceCondition 4] CN_4 and LN_3 has its update detection service (pcluster-check-update) stopped, so it misses
          the update notification until the service is restarted near the end of the readiness check.
        - [RaceCondition 5] A login node is terminated and replaced by a slow-bootstrapping one (blocked in
          OnNodeStart). After the login node Launch Template is updated in CloudFormation, the
          slow login node is unblocked so it completes bootstrap with the already-updated LT.
          This node is exposed to a race condition where it bootstraps with the old LT, but when the update
          detection mechanism starts it detects the new LT and will think thereafter to have deployed the
          updated LT. As a result, when the login node ends the bootstrap, it will not detect the update
          because the update detection mechanism thinks it already has deployed the updated config.

    Verifications (soft assertions - all run even if some fail):
        - The cluster stack reaches UPDATE_COMPLETE.
        - Every compute and login node has the same config version as the head node.
        - Every compute and login node executed the update recipe after the finalize recipe.
        - Every node launched before the update executed the update recipe after the update was submitted.
        - The node that completed the bootstrap after the first successful update was able to deploy the update.
    """
    # Upload the blocking bootstrap script to S3
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    block_bootstrap_s3_key = "block_bootstrap.sh"
    bucket.upload_file(str(test_datadir / "block_bootstrap.sh"), block_bootstrap_s3_key)
    block_bootstrap_script_s3_uri = f"s3://{bucket_name}/{block_bootstrap_s3_key}"

    # These args are equal for every cluster creation/update
    common_cluster_config_args = dict(
        resource_bucket=bucket_name,
        block_bootstrap_script_s3_uri=block_bootstrap_script_s3_uri,
        blocking_file_cn_on_node_start=get_blocking_s3_uri(bucket_name, NODE_TYPE_COMPUTE, PHASE_ON_NODE_START),
        blocking_file_cn_on_node_configured=get_blocking_s3_uri(
            bucket_name, NODE_TYPE_COMPUTE, PHASE_ON_NODE_CONFIGURED
        ),
        blocking_file_ln_on_node_start=get_blocking_s3_uri(bucket_name, NODE_TYPE_LOGIN, PHASE_ON_NODE_START),
        blocking_file_ln_on_node_configured=get_blocking_s3_uri(bucket_name, NODE_TYPE_LOGIN, PHASE_ON_NODE_CONFIGURED),
    )

    # Create cluster
    config_file_1 = pcluster_config_reader(
        output_file="pcluster.config.1.yaml",
        login_nodes_count=1,
        **common_cluster_config_args,
    )
    cluster = clusters_factory(config_file_1)
    rce = RemoteCommandExecutor(cluster)

    logger.info(
        f"Launching new dynamic compute node {CN_1}, which will terminate the bootstrap after the cluster update"
    )
    start_slow_dynamic_node(region, bucket_name, rce, CN_1, PHASE_ON_NODE_CONFIGURED)

    logger.info("Submitting cluster update 1")
    config_file_update_1 = pcluster_config_reader(
        output_file="pcluster.config.update-1.yaml",
        login_nodes_count=4,
        **common_cluster_config_args,
    )
    cluster.update(config_file_update_1, wait=True, raise_on_error=True)

    logger.info(f"Unblocking compute node {CN_1}, which will now complete its bootstrap")
    unblock_node_bootstrap(region, bucket_name, NODE_TYPE_COMPUTE, PHASE_ON_NODE_CONFIGURED)

    sleep_time = 300
    logger.info(f"Sleeping {sleep_time}s to give the chance to compute node {CN_1} to apply the update")
    time.sleep(sleep_time)

    logger.info(f"Checking whether the compute node {CN_1} applied the update")
    is_late_node_updated = check_deployed_config_version(rce, cluster, CN_1)
    logger.info(f"The compute node {CN_1} did {'' if is_late_node_updated else 'not '}apply the update")

    logger.info(
        f"Launching new dynamic compute node {CN_2}, which will terminate the bootstrap at the end of readiness check"
    )
    start_slow_dynamic_node(region, bucket_name, rce, CN_2, PHASE_ON_NODE_CONFIGURED)

    logger.info(f"Injecting transient failure into node {CN_3} that will cause update failure")
    inject_transient_update_failure(rce, cluster, NODE_TYPE_COMPUTE, CN_3)

    logger.info(f"Injecting transient failure into node {CN_4} that will delay the detection of the update")
    block_update_detection(rce, cluster, NODE_TYPE_COMPUTE, CN_4)

    logger.info("Launching a slow login node before cluster update 2")
    login_node_1_id = launch_slow_login_node(region, bucket_name, cluster, PHASE_ON_NODE_START)
    logger.info(
        f"New slow login node launched: {login_node_1_id}. "
        "This login node is exposed to race condition that we kept out of scope for PC 3.15.0. "
        "When such race condition occurs, the node is not able to detect the update, "
        "so it ends up with the wrong cluster config version and misses the update recipe."
    )

    logger.info("Injecting transient failures on existing login nodes")
    existing_login_nodes = [n for n in cluster.describe_login_nodes() if n["instanceId"] != login_node_1_id]
    assert_that(len(existing_login_nodes)).described_as(
        f"Expected at least 2 existing login nodes, found {len(existing_login_nodes)}"
    ).is_greater_than_or_equal_to(2)
    login_node_2_id = existing_login_nodes[0]["instanceId"]
    login_node_3_id = existing_login_nodes[1]["instanceId"]

    logger.info(f"Injecting transient update execution failure on login node {login_node_2_id}")
    inject_transient_update_failure(rce, cluster, NODE_TYPE_LOGIN, login_node_2_id)

    logger.info(f"Injecting transient update detection failure on login node {login_node_3_id}")
    block_update_detection(rce, cluster, NODE_TYPE_LOGIN, login_node_3_id)

    logger.info("Submitting cluster update 2")
    config_file_update_2 = pcluster_config_reader(
        output_file="pcluster.config.update-2.yaml",
        login_nodes_count=6,
        **common_cluster_config_args,
    )
    update_2_submit_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    cluster.update(config_file_update_2, raise_on_error=False, wait=False)

    logger.info("Waiting for login nodes launch template to be updated")
    wait_for_login_nodes_lt_update_complete(cluster, region, after_utc=update_2_submit_time)
    logger.info(f"Login nodes LT updated, now unblocking the slow login node {login_node_1_id}")
    unblock_node_bootstrap(region, bucket_name, NODE_TYPE_LOGIN, PHASE_ON_NODE_START)
    logger.info(f"Login node {login_node_1_id} unblocked")

    logger.info(f"Waiting for compute node {CN_3} to fail the update due to transient failure")
    wait_for_node_update_failure(rce, cluster, NODE_TYPE_COMPUTE, CN_3, os)
    logger.info(f"Transient update failure detected on compute node {CN_3}")
    remove_transient_update_failure(rce, cluster, NODE_TYPE_COMPUTE, CN_3)
    logger.info(f"Removed transient failure for compute node {CN_3}. If it retries, it will succeed the update.")

    logger.info(f"Waiting for login node {login_node_2_id} to fail the update due to transient failure")
    wait_for_node_update_failure(rce, cluster, NODE_TYPE_LOGIN, login_node_2_id, os, after_utc=update_2_submit_time)
    logger.info(f"Transient update failure detected on login node {login_node_2_id}")
    remove_transient_update_failure(rce, cluster, NODE_TYPE_LOGIN, login_node_2_id)
    logger.info(
        f"Removed transient failure for login node {login_node_2_id}. " "If it retries, it will succeed the update."
    )

    logger.info("Waiting for the readiness check to reach the second-last iteration")
    wait_for_readiness_check_last_retry(rce, after_utc=update_2_submit_time)
    logger.info("Second last iteration of readiness check detected")

    logger.info(f"Unblocking bootstrap for compute node {CN_2}")
    unblock_node_bootstrap(region, bucket_name, NODE_TYPE_COMPUTE, PHASE_ON_NODE_CONFIGURED)
    logger.info(f"Bootstrap unblocked for compute node {CN_2}")

    logger.info(f"Unblocking detection of update for compute node {CN_4}")
    unblock_update_detection(rce, cluster, NODE_TYPE_COMPUTE, CN_4)
    logger.info(f"Unblocked detection of update for compute node {CN_4}")

    logger.info(f"Unblocking detection of update for login node {login_node_3_id}")
    unblock_update_detection(rce, cluster, NODE_TYPE_LOGIN, login_node_3_id)
    logger.info(f"Unblocked detection of update for login node {login_node_3_id}")

    # NOTE: The test requires the cluster update to succeed (see assertion at the end of the test).
    # However, here we are accepting also the failure states so that we can use the verifications below
    # to gather more information.
    expected_stack_statuses = ["UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_FAILED"]
    logger.info(f"Waiting for the cluster stack to reach a final state: {expected_stack_statuses}")
    actual_cluster_stack_status = cluster.wait_cluster_stack_status(
        expected_statuses=expected_stack_statuses,
        stop_max_delay_minute=30,
    )

    logger.info("Verifications started")
    logger.info(f"Cluster stack status is: {actual_cluster_stack_status}")

    # Known Issue: when the cluster stack reaches the state UPDATE_ROLLBACK_COMPLETE,
    # the head node may not have completed the update recipe yet.
    # So, before collecting the cluster snapshot we must wait for it to prevent false positive test failures.
    if actual_cluster_stack_status == "UPDATE_ROLLBACK_COMPLETE":
        logger.info("Waiting for head node to complete the update recipe before collecting the cluster snapshot")
        wait_for_head_node_update_recipe_complete(rce, after_utc=update_2_submit_time)

    logger.info("Collecting cluster nodes snapshot")
    cluster_snapshot = get_cluster_nodes_snapshot(cluster)
    logger.info(f"Cluster snapshot:\n{json.dumps(cluster_snapshot, indent=2)}")

    with soft_assertions():
        assert_that(actual_cluster_stack_status).described_as(
            f"Cluster stack status should be UPDATE_COMPLETE, but it is {actual_cluster_stack_status}"
        ).is_equal_to("UPDATE_COMPLETE")
        assert_that(is_late_node_updated).described_as(
            f"Compute node {CN_1} completed the bootstrap after update 1 and did not apply the expected update"
        ).is_true()
        assert_config_version_dna_matches_ddb(cluster_snapshot)
        # IMPORTANT NOTE: In ParallelCluster 3.15.0 we are not fixing [RaceCondition 5],
        # so the following two assertions are expected to fail for the slow login node started before update 2.
        assert_config_version_matches_head_node(cluster_snapshot, expected_failure_instance_ids={login_node_1_id})
        assert_update_recipe_executed_on_old_nodes(
            cluster_snapshot, update_2_submit_time, expected_failure_instance_ids={login_node_1_id}
        )
        assert_correct_recipe_order(cluster_snapshot)
    logger.info("Verifications completed")
