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

"""
Integration tests for verifying fixes related to cluster update rollback scenarios.

This test validates the following fixes:
- [F1] clustermgtd remains running after both update and rollback fail
- [F2] cfn-hup does not enter an endless loop after rollback to a state older than 24h
- [F3] dna.json files are cleaned up after update failure

Test Plan:
1. Create cluster with 3 static compute nodes
2. Inject cfn-signal failure on head node (simulating expired wait condition)
3. Inject failure on CN1 (disable cfn-hup) BEFORE update
4. Update cluster config by adding a new queue
5. Update fails because CN1 won't apply update (cluster readiness check fails)
6. During update's cluster readiness check (before rollback starts): inject failure on CN2
   - CN2 has already applied the update at this point
   - Disabling cfn-hup prevents CN2 from rolling back
   - Cluster readiness check has 10 attempts (~15 min window)
7. Rollback starts after update fails
8. Rollback fails because CN2 won't rollback (still has update target config)
9. Verify fixes:
   - clustermgtd is running
   - dna.json files are deleted
   - CN3 (healthy node) has correct config version (source config before update)
   - metadata_db.json is updated
   - cfn-hup is not in endless loop
"""

import logging
import time

import boto3
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from utils import get_compute_nodes_instance_ids

from tests.common.schedulers_common import SlurmCommands

logger = logging.getLogger(__name__)


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_update_rollback_fixes(
    region,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
):
    """
    Test that cluster update rollback fixes work correctly.

    This test verifies:
    1. clustermgtd remains running after update and rollback failures
    2. cfn-hup does not enter endless loop when cfn-signal fails
    3. dna.json files are cleaned up properly
    """
    # Create cluster with initial configuration (3 static compute nodes)
    init_config_file = pcluster_config_reader()
    cluster = clusters_factory(init_config_file)

    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = SlurmCommands(remote_command_executor)

    # Wait for all static nodes to be ready
    _wait_for_static_nodes_ready(slurm_commands, expected_count=3)

    # Get compute node hostnames
    compute_nodes = slurm_commands.get_compute_nodes()
    assert_that(len(compute_nodes)).is_greater_than_or_equal_to(3)
    logger.info(f"Compute nodes: {compute_nodes}")

    cn1, cn2, cn3 = compute_nodes[0], compute_nodes[1], compute_nodes[2]

    # Get instance IDs for DynamoDB queries
    instance_ids = get_compute_nodes_instance_ids(cluster.name, region)
    logger.info(f"Compute node instance IDs: {instance_ids}")

    # Map hostnames to instance IDs
    cn1_instance_id = _get_instance_id_for_node(region, remote_command_executor, cn1, instance_ids)
    cn2_instance_id = _get_instance_id_for_node(region, remote_command_executor, cn2, instance_ids)
    cn3_instance_id = _get_instance_id_for_node(region, remote_command_executor, cn3, instance_ids)
    logger.info(f"CN1: {cn1} -> {cn1_instance_id}")
    logger.info(f"CN2: {cn2} -> {cn2_instance_id}")
    logger.info(f"CN3: {cn3} -> {cn3_instance_id}")

    # Get initial config version from DynamoDB (dna.json is cleaned up after successful create)
    initial_config_version = _get_config_version_from_ddb(region, cluster.name, cn3_instance_id)
    logger.info(f"Initial config version (from DDB): {initial_config_version}")

    # Step 2: Inject cfn-signal failure on head node
    # This simulates the scenario where wait condition handle has expired
    logger.info("Injecting cfn-signal failure on head node...")
    _inject_cfn_signal_failure(remote_command_executor)

    # Step 3: Disable cfn-hup on CN1 BEFORE update
    # This ensures CN1 won't apply the update, causing cluster readiness check to fail
    logger.info(f"Disabling cfn-hup on CN1 ({cn1}) before update...")
    _disable_cfn_hup_on_compute_node(remote_command_executor, cn1)

    # Step 4: Trigger cluster update with wait=False (non-blocking)
    logger.info("Triggering cluster update (non-blocking)...")
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.update.yaml")

    # Get the target config version from the update config file
    # We'll use this to verify CN2 has applied the update before disabling its cfn-hup
    cluster.update(str(updated_config_file), wait=False, raise_on_error=False, log_error=False)

    # Step 6: Wait for CN2 to complete the update, then disable its cfn-hup
    # CN2 needs to successfully apply the update first (have the new config version in DDB)
    # Then we disable cfn-hup so it won't rollback (keeping the update target config)
    logger.info("Waiting for CN2 to complete update before disabling its cfn-hup...")
    _wait_for_node_config_version_change(
        region, cluster.name, cn2_instance_id, initial_config_version, timeout_minutes=15
    )

    logger.info(f"CN2 has applied the update. Disabling cfn-hup on CN2 ({cn2})...")
    _disable_cfn_hup_on_compute_node(remote_command_executor, cn2)

    # Wait for stack to reach UPDATE_ROLLBACK_COMPLETE state
    logger.info("Waiting for stack to reach UPDATE_ROLLBACK_COMPLETE...")
    final_status = _wait_for_stack_rollback_complete(cluster, region)
    logger.info(f"Stack final status: {final_status}")

    # Step 9: Verify fixes
    logger.info("Verifying fixes...")

    # Verify clustermgtd is running
    _verify_clustermgtd_running(remote_command_executor)

    # Verify dna.json files are deleted
    _verify_dna_json_cleaned_up(remote_command_executor)

    # Verify CN3 has correct config version in DynamoDB (should be initial/rollback version)
    _verify_compute_node_config_version_in_ddb(region, cluster.name, cn3_instance_id, initial_config_version)

    # Verify metadata_db.json is updated (cfn-hup processed the change)
    _verify_metadata_db_updated(remote_command_executor)

    # Verify cfn-hup is not in endless loop
    _verify_no_cfn_hup_endless_loop(remote_command_executor)

    logger.info("All verifications passed!")


def _wait_for_static_nodes_ready(slurm_commands, expected_count, timeout_minutes=10):
    """Wait for static compute nodes to be ready."""

    @retry(wait_fixed=seconds(30), stop_max_delay=minutes(timeout_minutes))
    def _check_nodes():
        nodes = slurm_commands.get_compute_nodes()
        assert_that(len(nodes)).is_greater_than_or_equal_to(expected_count)
        return nodes

    return _check_nodes()


def _get_instance_id_for_node(region, remote_command_executor, node_name, instance_ids):
    """Get the EC2 instance ID for a given Slurm node name."""
    # Get the private IP of the node from Slurm
    result = remote_command_executor.run_remote_command(
        f"scontrol show node {node_name} | grep NodeAddr | awk -F= '{{print $2}}' | awk '{{print $1}}'"
    )
    node_ip = result.stdout.strip()

    # Find the instance ID with this IP
    ec2 = boto3.client("ec2", region_name=region)

    for instance_id in instance_ids:
        response = ec2.describe_instances(InstanceIds=[instance_id])
        for reservation in response["Reservations"]:
            for instance in reservation["Instances"]:
                if instance.get("PrivateIpAddress") == node_ip:
                    return instance_id

    raise ValueError(f"Could not find instance ID for node {node_name} with IP {node_ip}")


def _get_config_version_from_ddb(region, cluster_name, instance_id):
    """
    Get the current cluster config version from DynamoDB.

    This is more reliable than reading dna.json which is cleaned up after successful operations.
    """
    dynamodb = boto3.client("dynamodb", region_name=region)
    table_name = f"parallelcluster-{cluster_name}"
    ddb_key = f"CLUSTER_CONFIG.{instance_id}"

    response = dynamodb.get_item(TableName=table_name, Key={"Id": {"S": ddb_key}})

    if "Item" in response:
        data = response["Item"].get("Data", {}).get("M", {})
        return data.get("cluster_config_version", {}).get("S", "")

    raise ValueError(f"No DynamoDB record found for instance {instance_id}")


def _inject_cfn_signal_failure(remote_command_executor):
    """
    Inject cfn-signal failure by creating a wrapper script that always fails.

    This simulates the scenario where the wait condition handle has expired.
    """
    # Get the cfn-signal path from environment variable
    cmd = (
        "bash -c 'source /etc/parallelcluster/pcluster_cookbook_environment.sh 2>/dev/null "
        "&& echo $CFN_BOOTSTRAP_VIRTUALENV_PATH'"
    )
    result = remote_command_executor.run_remote_command(cmd)
    cfn_bin_path = result.stdout.strip()

    if not cfn_bin_path:
        # Fallback: find the path
        result = remote_command_executor.run_remote_command("find /opt -name cfn-signal -type f 2>/dev/null | head -1")
        cfn_signal_path = result.stdout.strip()
        if cfn_signal_path:
            cfn_bin_path = cfn_signal_path.rsplit("/cfn-signal", 1)[0]
        else:
            # Default path
            cfn_bin_path = "/opt/parallelcluster/pyenv/versions/3.12.11/envs/cfn_bootstrap_virtualenv/bin"

    logger.info(f"CFN bin path: {cfn_bin_path}")

    # Create a wrapper script that makes cfn-signal fail
    # This simulates an expired wait condition handle
    wrapper_script = """#!/bin/bash
# Wrapper script to simulate cfn-signal failure (expired wait condition)
# Log the call for debugging
echo "$(date): cfn-signal called with args: $@" >> /tmp/cfn-signal-wrapper.log
echo "Simulated cfn-signal failure: wait condition expired" >&2
exit 1
"""
    # Write wrapper script
    remote_command_executor.run_remote_command(
        f"cat << 'EOF' | sudo tee /tmp/cfn-signal-wrapper.sh > /dev/null\n{wrapper_script}EOF"
    )
    remote_command_executor.run_remote_command("sudo chmod +x /tmp/cfn-signal-wrapper.sh")

    # Backup original cfn-signal and replace with wrapper
    # Note: CFN_BOOTSTRAP_VIRTUALENV_PATH already points to bin dir, so just append /cfn-signal
    remote_command_executor.run_remote_command(f"sudo cp {cfn_bin_path}/cfn-signal {cfn_bin_path}/cfn-signal.bak")
    remote_command_executor.run_remote_command(f"sudo cp /tmp/cfn-signal-wrapper.sh {cfn_bin_path}/cfn-signal")
    logger.info("cfn-signal wrapper installed")


def _disable_cfn_hup_on_compute_node(remote_command_executor, node_name):
    """
    Disable cfn-hup on a compute node using srun.

    Uses supervisorctl to stop cfn-hup service on the compute node.
    """
    logger.info(f"Disabling cfn-hup on compute node {node_name}...")

    # Get supervisorctl path
    result = remote_command_executor.run_remote_command(
        "find /opt/parallelcluster -name supervisorctl -type f 2>/dev/null | head -1"
    )
    supervisorctl_path = result.stdout.strip()
    if not supervisorctl_path:
        supervisorctl_path = "/opt/parallelcluster/pyenv/versions/3.12.11/envs/cookbook_virtualenv/bin/supervisorctl"

    # Stop cfn-hup using srun
    remote_command_executor.run_remote_command(f"srun -w {node_name} sudo {supervisorctl_path} stop cfn-hup")

    # Verify cfn-hup is stopped
    result = remote_command_executor.run_remote_command(f"srun -w {node_name} sudo {supervisorctl_path} status cfn-hup")
    assert_that(result.stdout).contains("STOPPED")
    logger.info(f"cfn-hup stopped on {node_name} ✓")


def _wait_for_stack_rollback_complete(cluster, region, timeout_minutes=60):
    """Wait for CloudFormation stack to reach UPDATE_ROLLBACK_COMPLETE state."""
    client = boto3.client("cloudformation", region_name=region)

    @retry(wait_fixed=seconds(30), stop_max_delay=minutes(timeout_minutes))
    def _check_rollback_complete():
        stack_status = client.describe_stacks(StackName=cluster.name)["Stacks"][0]["StackStatus"]
        logger.info(f"Current stack status: {stack_status}")
        if stack_status != "UPDATE_ROLLBACK_COMPLETE":
            raise Exception(f"Stack not in UPDATE_ROLLBACK_COMPLETE state: {stack_status}")
        return stack_status

    return _check_rollback_complete()


def _verify_clustermgtd_running(remote_command_executor, timeout_minutes=10):
    """Verify that clustermgtd is running."""
    logger.info("Verifying clustermgtd is running...")

    # Find the supervisorctl path
    result = remote_command_executor.run_remote_command(
        "find /opt/parallelcluster -name supervisorctl -type f 2>/dev/null | head -1"
    )
    supervisorctl_path = result.stdout.strip()

    if not supervisorctl_path:
        supervisorctl_path = "/opt/parallelcluster/pyenv/versions/3.12.11/envs/cookbook_virtualenv/bin/supervisorctl"

    @retry(wait_fixed=seconds(30), stop_max_delay=minutes(timeout_minutes))
    def _check_clustermgtd():
        result = remote_command_executor.run_remote_command(f"sudo {supervisorctl_path} status clustermgtd")
        assert_that(result.stdout).contains("RUNNING")
        return result

    _check_clustermgtd()
    logger.info("clustermgtd is running ✓")


def _verify_dna_json_cleaned_up(remote_command_executor):
    """Verify that dna.json files are cleaned up after update failure."""
    logger.info("Verifying dna.json files are cleaned up...")

    result = remote_command_executor.run_remote_command(
        "find /opt/parallelcluster/shared/dna/ -name '*.json' 2>/dev/null | wc -l"
    )
    json_count = int(result.stdout.strip())
    assert_that(json_count).is_equal_to(0)
    logger.info("dna.json files are cleaned up ✓")


def _wait_for_node_config_version_change(region, cluster_name, instance_id, old_version, timeout_minutes=15):
    """
    Wait for a node's config version in DynamoDB to change from the old version.

    This ensures the node has completed applying the update before we disable its cfn-hup.
    """

    @retry(wait_fixed=seconds(10), stop_max_delay=minutes(timeout_minutes))
    def _check_version():
        try:
            current_version = _get_config_version_from_ddb(region, cluster_name, instance_id)
            logger.info(f"Instance {instance_id} current config version: {current_version}")
            if current_version == old_version:
                raise Exception(f"Config version not changed yet (still {old_version})")
            logger.info(f"Instance {instance_id} config version changed to: {current_version}")
            return current_version
        except ValueError:
            raise Exception(f"DynamoDB record not found for {instance_id}")

    return _check_version()


def _verify_compute_node_config_version_in_ddb(region, cluster_name, instance_id, expected_version):
    """
    Verify that the compute node has the correct config version in DynamoDB.

    DynamoDB key format: CLUSTER_CONFIG.{instance_id}
    Data structure: Data.M.cluster_config_version.S
    """
    logger.info(f"Verifying config version for instance {instance_id} in DynamoDB...")

    dynamodb = boto3.client("dynamodb", region_name=region)
    table_name = f"parallelcluster-{cluster_name}"

    # Query using the exact key format: CLUSTER_CONFIG.{instance_id}
    ddb_key = f"CLUSTER_CONFIG.{instance_id}"

    try:
        response = dynamodb.get_item(TableName=table_name, Key={"Id": {"S": ddb_key}})

        if "Item" in response:
            item = response["Item"]
            # Config version is stored in Data.M.cluster_config_version.S
            data = item.get("Data", {}).get("M", {})
            config_version = data.get("cluster_config_version", {}).get("S", "")
            status = data.get("status", {}).get("S", "")

            logger.info(f"Instance {instance_id} DDB record:")
            logger.info(f"  - config_version: {config_version}")
            logger.info(f"  - status: {status}")
            logger.info(f"  - expected_version: {expected_version}")

            # The healthy node should have rolled back to the source config version
            assert_that(config_version).is_equal_to(expected_version)
            logger.info(f"Compute node {instance_id} has correct config version ✓")
            return

    except Exception as e:
        logger.warning(f"Error querying DynamoDB: {e}")

    # Fallback: try scanning if direct query fails
    logger.warning("Direct DDB query failed, trying scan...")
    response = dynamodb.scan(
        TableName=table_name,
        FilterExpression="contains(Id, :instance_id)",
        ExpressionAttributeValues={":instance_id": {"S": instance_id}},
    )

    if response.get("Items"):
        for item in response["Items"]:
            data = item.get("Data", {}).get("M", {})
            config_version = data.get("cluster_config_version", {}).get("S", "")
            logger.info(f"Instance {instance_id} config version in DDB (via scan): {config_version}")
            assert_that(config_version).is_equal_to(expected_version)
            logger.info(f"Compute node {instance_id} has correct config version ✓")
            return

    # If we reach here, no record was found - this is a test failure
    pytest.fail(f"No DynamoDB record found for instance {instance_id}")


def _verify_metadata_db_updated(remote_command_executor):
    """Verify that metadata_db.json was updated (cfn-hup processed the change)."""
    logger.info("Verifying metadata_db.json is updated...")

    result = remote_command_executor.run_remote_command(
        "test -f /var/lib/cfn-hup/data/metadata_db.json && echo 'exists' || echo 'not found'"
    )
    assert_that(result.stdout.strip()).is_equal_to("exists")

    # Also check the modification time is recent (within last hour)
    result = remote_command_executor.run_remote_command("stat -c %Y /var/lib/cfn-hup/data/metadata_db.json")
    mtime = int(result.stdout.strip())
    current_time = int(remote_command_executor.run_remote_command("date +%s").stdout.strip())
    age_seconds = current_time - mtime

    logger.info(f"metadata_db.json age: {age_seconds} seconds")
    # Should have been updated within the last hour (during the test)
    assert_that(age_seconds).is_less_than(3600)
    logger.info("metadata_db.json exists and was recently updated ✓")


def _verify_no_cfn_hup_endless_loop(remote_command_executor):
    """
    Verify that cfn-hup is not in an endless loop.

    After the fix (|| exit 0), cfn-hup should:
    1. Detect the change
    2. Run the update recipe
    3. cfn-signal fails (our injected failure)
    4. || exit 0 ensures exit code is 0
    5. cfn-hup updates metadata_db.json
    6. No more retries

    We verify by:
    1. Recording the current timestamp
    2. Waiting 3 minutes (cfn-hup polls every minute)
    3. Counting "Data has changed" messages AFTER the recorded timestamp
    4. In an endless loop, we'd see ~3 messages (one per minute)
    5. After the fix, we should see 0 messages (no new changes detected)
    """
    logger.info("Verifying cfn-hup is not in endless loop...")

    # Record the start time for filtering logs
    start_time_result = remote_command_executor.run_remote_command("date '+%Y-%m-%d %H:%M:%S'")
    start_time = start_time_result.stdout.strip()
    logger.info(f"Starting endless loop verification at: {start_time}")

    # Wait for a few cfn-hup cycles
    logger.info("Waiting 3 minutes for cfn-hup cycles...")
    time.sleep(180)

    # Get logs from the last 5 minutes to capture our waiting period
    result = remote_command_executor.run_remote_command(
        "awk -v start=\"$(date -d '5 minutes ago' '+%Y-%m-%d %H:%M:%S')\" "
        "'$0 >= start' /var/log/cfn-hup.log 2>/dev/null | tail -100 || echo 'log not found'"
    )
    log_content = result.stdout

    # Count "Data has changed" messages in recent logs
    change_count = log_content.count("Data has changed from previous state")
    logger.info(f"Found {change_count} 'Data has changed' messages in last 5 minutes of cfn-hup.log")

    # In an endless loop without the fix, we'd see many messages (one per minute = ~3-5 in 3-5 minutes)
    # After the fix, cfn-hup should have already processed the change and not detect new ones
    # We allow up to 2 for edge cases (e.g., if we started right before a poll)
    assert_that(change_count).is_less_than(3)

    # Also check retry messages
    # After the fix, even if cfn-signal fails, || exit 0 should prevent retries
    retry_count = log_content.count("will retry on next iteration")
    logger.info(f"Found {retry_count} 'will retry' messages in last 5 minutes of cfn-hup.log")

    # With the fix, cfn-hup should not retry because the command exits with 0
    assert_that(retry_count).is_equal_to(0)

    logger.info("cfn-hup is not in endless loop ✓")
