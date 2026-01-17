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

import logging
import time

import boto3
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from utils import get_compute_nodes_instance_ids, get_file_mtime_age_seconds, verify_cluster_node_config_version_in_ddb

from tests.common.schedulers_common import SlurmCommands

logger = logging.getLogger(__name__)

# Number of static compute nodes used in this test
N_STATIC_NODES = 3


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_update_rollback_failure(
    region,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
):
    """
    Test that cluster update rollback failure is handled correctly.

    This test validates the following fixes:
    - [F1] clustermgtd remains running after both update and rollback fail
           (expected when failure occurs after slurm reconfiguration, which is the safe section)
    - [F2] cfn-hup does not enter an endless loop after rollback to a state older than 24h
    - [F3] dna.json files are cleaned up after update and rollback failure

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
       - CN1 (unhealthy) has source config version (never applied update, cfn-hup disabled before update)
       - CN2 (unhealthy) has target config version (applied update, cfn-hup disabled before rollback)
       - CN3 (healthy node) has correct config version (source config before update)
       - metadata_db.json is updated
       - cfn-hup is not in endless loop
    """
    # Create cluster with initial configuration
    init_config_file = pcluster_config_reader(n_static_nodes=N_STATIC_NODES)
    cluster = clusters_factory(init_config_file)

    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = SlurmCommands(remote_command_executor)

    # Wait for all static nodes to be ready
    _wait_for_static_nodes_ready(slurm_commands, expected_count=N_STATIC_NODES)

    # Get compute node hostnames
    compute_nodes = slurm_commands.get_compute_nodes()
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

    # Step 3: Disable pcluster-check-update timer on CN1 BEFORE update
    # This ensures CN1 won't apply the update, causing cluster readiness check to fail
    logger.info(f"Disabling the pcluster-check-update timer on CN1 ({cn1}) before update...")
    _disable_check_update_timer_on_compute_node(remote_command_executor, cn1)

    # Step 4: Trigger cluster update with wait=False (non-blocking)
    logger.info("Triggering cluster update (non-blocking)...")
    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update.yaml", n_static_nodes=N_STATIC_NODES
    )

    # Trigger update (non-blocking) - failure is expected due to CN1 not applying update
    cluster.update(str(updated_config_file), wait=False, raise_on_error=False)

    # Step 6: Wait for CN2 to complete the update, then disable its cfn-hup
    # CN2 needs to successfully apply the update first (have the new config version in DDB)
    # Then we disable cfn-hup so it won't rollback (keeping the update target config)
    logger.info("Waiting for CN2 to complete update before disabling its cfn-hup...")
    _wait_for_node_config_version_change(
        region, cluster.name, cn2_instance_id, initial_config_version, timeout_minutes=15
    )

    logger.info(f"CN2 has applied the update. Disabling pcluster-check-update timer on CN2 ({cn2}) to inject rollback failure...")
    _disable_check_update_timer_on_compute_node(remote_command_executor, cn2)

    # Wait for stack to reach UPDATE_ROLLBACK_COMPLETE state
    logger.info("Waiting for stack to reach UPDATE_ROLLBACK_COMPLETE...")
    final_status = _wait_for_stack_rollback_complete(cluster, region)
    logger.info(f"Stack final status: {final_status}")

    # Wait for head node rollback to complete
    # Note: CFN stack reaches UPDATE_ROLLBACK_COMPLETE before head node finishes rollback recipe
    # Sleep briefly to ensure rollback recipe has started writing to chef-client.log
    time.sleep(10)
    logger.info("Waiting for head node rollback recipe to complete...")
    _wait_for_head_node_rollback_complete(remote_command_executor)

    # Step 9: Verify fixes
    logger.info("Verifying fixes...")

    # Verify clustermgtd is running
    _verify_clustermgtd_running(remote_command_executor)

    # Verify dna.json files are deleted
    _verify_dna_json_cleaned_up(remote_command_executor)

    # Verify CN3 has correct config version in DynamoDB (should be initial/rollback version)
    verify_cluster_node_config_version_in_ddb(region, cluster.name, cn3_instance_id, initial_config_version)

    # Verify metadata_db.json is updated (cfn-hup processed the change)
    _verify_metadata_db_updated(remote_command_executor)

    # Verify cfn-hup is not in endless loop
    _verify_no_cfn_hup_endless_loop(remote_command_executor)

    logger.info("All verifications passed!")


def _get_supervisorctl_path(remote_command_executor):
    """Get the path to supervisorctl on the cluster."""
    result = remote_command_executor.run_remote_command(
        "find /opt/parallelcluster -name supervisorctl -type f 2>/dev/null | head -1"
    )
    path = result.stdout.strip()
    if not path:
        path = "/opt/parallelcluster/pyenv/versions/3.12.11/envs/cookbook_virtualenv/bin/supervisorctl"
    return path


@retry(wait_fixed=seconds(30), stop_max_delay=minutes(10))
def _wait_for_static_nodes_ready(slurm_commands, expected_count):
    """Wait for static compute nodes to be ready."""
    nodes = slurm_commands.get_compute_nodes()
    assert_that(len(nodes)).is_greater_than_or_equal_to(expected_count)
    return nodes


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


def _disable_check_update_timer_on_compute_node(remote_command_executor, node_name):
    """
    Disable pcluster-check-update on a compute node using srun.

    Uses systemctl to stop the pcluster-check-update.timer on the compute node.
    """
    logger.info(f"Disabling pcluster-check-update on compute node {node_name}...")

    # Stop pcluster-check-update.timer using srun
    remote_command_executor.run_remote_command(
        f"srun -w {node_name} sudo systemctl stop pcluster-check-update.timer"
    )

    # Verify pcluster-check-update.timer is stopped
    result = remote_command_executor.run_remote_command(
        f"srun -w {node_name} systemctl is-active pcluster-check-update.timer",
        raise_on_error=False,
    )
    assert_that(result.stdout.strip()).contains("inactive")
    logger.info(f"pcluster-check-update.timer stopped on {node_name} ✓")


@retry(wait_fixed=seconds(30), stop_max_delay=minutes(60))
def _wait_for_stack_rollback_complete(cluster, region):
    """Wait for CloudFormation stack to reach UPDATE_ROLLBACK_COMPLETE state."""
    client = boto3.client("cloudformation", region_name=region)
    stack_status = client.describe_stacks(StackName=cluster.name)["Stacks"][0]["StackStatus"]
    logger.info(f"Current stack status: {stack_status}")
    if stack_status != "UPDATE_ROLLBACK_COMPLETE":
        raise Exception(f"Stack not in UPDATE_ROLLBACK_COMPLETE state: {stack_status}")
    return stack_status


@retry(wait_fixed=seconds(30), stop_max_delay=minutes(30))
def _wait_for_head_node_rollback_complete(remote_command_executor):
    """
    Wait for head node rollback recipe to complete.

    CFN stack reaches UPDATE_ROLLBACK_COMPLETE before head node finishes rollback recipe.
    We check the last line of chef-client.log for check_cluster_ready.py output which indicates
    rollback completion.
    """
    result = remote_command_executor.run_remote_command("tail -1 /var/log/chef-client.log")
    last_line = result.stdout.strip()
    if "check_cluster_ready.py" not in last_line or "returned" not in last_line:
        raise Exception(f"Rollback recipe not yet complete. Last line: {last_line}")
    logger.info(f"Head node rollback recipe completed: {last_line}")
    return last_line


def _verify_clustermgtd_running(remote_command_executor):
    """Verify that clustermgtd is running."""
    logger.info("Verifying clustermgtd is running...")
    supervisorctl_path = _get_supervisorctl_path(remote_command_executor)
    result = remote_command_executor.run_remote_command(f"sudo {supervisorctl_path} status clustermgtd")
    assert_that(result.stdout).contains("RUNNING")
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


def _verify_metadata_db_updated(remote_command_executor):
    """Verify that metadata_db.json was updated (cfn-hup processed the change)."""
    logger.info("Verifying metadata_db.json is updated...")

    metadata_db_path = "/var/lib/cfn-hup/data/metadata_db.json"

    # Check file exists (use sudo in case of permission issues)
    result = remote_command_executor.run_remote_command(f"sudo ls -la {metadata_db_path}")
    logger.info(f"metadata_db.json: {result.stdout.strip()}")

    # Check the modification time is recent (within last 10 minutes)
    age_seconds = get_file_mtime_age_seconds(remote_command_executor, metadata_db_path)
    logger.info(f"metadata_db.json age: {age_seconds} seconds")
    # Should have been updated within the last 10 minutes
    assert_that(age_seconds).is_less_than(600)
    logger.info("metadata_db.json exists and was recently updated.")


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
