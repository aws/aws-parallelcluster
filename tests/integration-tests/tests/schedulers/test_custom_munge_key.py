# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

import boto3
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from utils import wait_for_computefleet_changed


@pytest.mark.usefixtures("instance", "os")
def test_custom_munge_key(
    region,
    munge_key,
    pcluster_config_reader,
    clusters_factory,
    scheduler_commands_factory,
    store_secret_in_secret_manager,
    test_datadir,
    s3_bucket_factory,
):
    """
    Test custom munge key config, rotate, update, remove and roll back.

    This test is focused on the scenario with LoginNodes.
    Because this scenario covers all the logic covered by the test without login nodes。

    Test phases summary:
    1. Deployment verification: Confirm munge key is successfully shared across head, compute and login nodes, and jobs
       can be submitted.
    2. Rotation prep: Attempt munge key rotation without stopping compute and login nodes, expecting error messages.
    3. Compute fleet shutdown: Prepare for munge key rotation scenario.
    4. Key rotation without login node stop: Attempt rotation, checking for expected failure and error messages.
    5. Login node stoppage and munge key rotation: Update cluster to stop login nodes, then execute munge key rotation.
    6. Munge key removal: Update cluster to remove the custom munge key. Test Munge Key has been changed
    7. Roll back with failure: Update cluster to add back the custom munge key. But let the cluster update fail after
       the custom munge key has been added. Trigger cluster roll back. Test if munge key is fully functional.
    """
    encoded_custom_munge_key, custom_munge_key_arn = munge_key
    cluster_config = pcluster_config_reader(custom_munge_key_arn=custom_munge_key_arn)
    cluster = clusters_factory(cluster_config, upper_case_cluster_name=True)

    # 1. Deployment verification: Confirm munge key is successfully shared across head, compute and login nodes,
    # and jobs can be submitted.

    # Test if the munge key was successfully fetched, decoded and shared in HeadNode and LoginNodes
    remote_command_executor = RemoteCommandExecutor(cluster)
    _check_encoded_munge_key(remote_command_executor, encoded_custom_munge_key)
    _test_munge_key_shared(remote_command_executor)

    remote_command_executor_login = RemoteCommandExecutor(cluster, use_login_node=True)
    _check_encoded_munge_key(remote_command_executor_login, encoded_custom_munge_key)
    job_command_args = {
        "command": "srun sleep 1",
        "nodes": 2,
    }
    # Test if compute node can run jobs from LoginNodes and HeadNode, indicating the munge key was successfully fetched.
    scheduler_commands = scheduler_commands_factory(remote_command_executor_login)
    scheduler_commands.submit_command_and_assert_job_succeeded(job_command_args)
    remote_command_executor_login.close_connection()

    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    scheduler_commands.submit_command_and_assert_job_succeeded(job_command_args)

    # 2. Rotation prep: Attempt munge key rotation without stopping compute and login nodes, expecting error messages.
    _test_update_munge_key_without_stop_login_or_compute(remote_command_executor)

    # 3. Compute fleet shutdown: Prepare for munge key rotation scenario.
    cluster.stop()
    wait_for_computefleet_changed(cluster, "STOPPED")

    # 4. Key rotation without login node stop: Attempt rotation, checking for expected failure and error messages.
    _test_update_munge_key_without_stop_login_or_compute(remote_command_executor, compute_stopped=True)

    # 5. Login node stop and munge key rotation: Update cluster to stop login nodes, then execute munge key rotation.
    update_cluster_stop_login_config = pcluster_config_reader(
        config_file="pcluster.stop_login.config.yaml",
        custom_munge_key_arn=custom_munge_key_arn,
    )
    cluster.update(str(update_cluster_stop_login_config))

    # wait for LoginNodes gracetime_period
    _check_login_nodes_stopped(remote_command_executor)

    # Test rotation script runs successfully
    result = remote_command_executor.run_remote_command("sudo /opt/parallelcluster/scripts/slurm/update_munge_key.sh")
    exit_code = result.return_code
    assert_that(exit_code).is_equal_to(0)

    # 6. Munge key removal: Update cluster to remove the custom munge key. Test Munge Key has been changed.
    update_cluster_remove_custom_munge_key_config = pcluster_config_reader(
        config_file="pcluster.remove_custom_munge_key.config.yaml"
    )
    cluster.update(str(update_cluster_remove_custom_munge_key_config))
    _check_encoded_munge_key(remote_command_executor, encoded_custom_munge_key, use_custom_munge_key=False)

    # 7. Roll back with failure: Update cluster to add back the custom munge key. But let the cluster update fail after
    # the custom munge key has been added. Trigger cluster roll back. Test if munge key is fully functional.
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "fail-on-node-updated.sh"), "fail-on-node-updated.sh")
    update_cluster_fail_roll_back_config = pcluster_config_reader(
        config_file="pcluster.roll_back.config.yaml",
        custom_munge_key_arn=custom_munge_key_arn,
        bucket_name=bucket_name,
    )
    cluster.update(str(update_cluster_fail_roll_back_config), raise_on_error=False)

    cluster.start()
    wait_for_computefleet_changed(cluster, "RUNNING")
    scheduler_commands.submit_command_and_assert_job_succeeded(job_command_args)


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(15))
def _check_login_nodes_stopped(remote_command_executor):
    result = remote_command_executor.run_remote_command(
        "sudo /opt/parallelcluster/scripts/slurm/check_login_nodes_stopped.sh",
        raise_on_error=False,
    )
    exit_code = result.return_code
    assert_that(exit_code).is_equal_to(0)


def _check_encoded_munge_key(remote_command_executor, expected_encoded_munge_key, use_custom_munge_key=True):
    """Test encoded munge key in secret manager has been successfully fetched by cluster and decode."""
    result = remote_command_executor.run_remote_command("sudo cat /etc/munge/munge.key | base64")
    encoded_munge_key = result.stdout.strip().replace("\n", "")
    if use_custom_munge_key:
        assert_that(encoded_munge_key).is_equal_to(expected_encoded_munge_key)
    else:
        assert_that(encoded_munge_key).is_not_equal_to(expected_encoded_munge_key)


def _test_munge_key_shared(remote_command_executor):
    """Test munge key has been successfully shared to shared directory."""
    compute_node_munge_key_path = "/opt/parallelcluster/shared/.munge/.munge.key"
    head_node_munge_key_path = "/opt/parallelcluster/shared_login_nodes/.munge/.munge.key"

    assert_that(
        remote_command_executor.run_remote_command(f"sudo test -f {compute_node_munge_key_path}").return_code,
        f"File does not exist: {compute_node_munge_key_path}",
    ).is_equal_to(0)

    assert_that(
        remote_command_executor.run_remote_command(f"sudo test -f {head_node_munge_key_path}").return_code,
        f"File does not exist: {head_node_munge_key_path}",
    ).is_equal_to(0)


def _test_update_munge_key_without_stop_login_or_compute(remote_command_executor, compute_stopped=False):
    result = remote_command_executor.run_remote_command(
        "sudo /opt/parallelcluster/scripts/slurm/update_munge_key.sh",
        raise_on_error=False,
    )
    command_output = result.stdout.strip()
    exit_code = result.return_code
    assert_that(exit_code).is_equal_to(1)
    if compute_stopped:
        expected_message = "Login nodes are running."
    else:
        expected_message = "Compute fleet is not stopped."
    assert_that(command_output).contains(expected_message)
