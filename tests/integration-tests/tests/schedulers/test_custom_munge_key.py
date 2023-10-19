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
from time import sleep

import pytest
from assertpy import assert_that
from constants import ENCODE_CUSTOM_MUNGE_KEY
from remote_command_executor import RemoteCommandExecutor
from utils import wait_for_computefleet_changed


@pytest.mark.usefixtures("instance", "os")
@pytest.mark.parametrize("use_login_node", [True, False])
def test_custom_munge_key(
    region,
    pcluster_config_reader,
    clusters_factory,
    scheduler_commands_factory,
    store_secret_in_secret_manager,
    use_login_node,
):
    """
    Test custom munge key config, rotate, update and remove.

    This test contains two case: with LoginNodes and without LoginNodes section.
    """
    custom_munge_key_arn = store_secret_in_secret_manager(
        region,
        secret_string=ENCODE_CUSTOM_MUNGE_KEY,
    )
    cluster_config = pcluster_config_reader(use_login_node=use_login_node, custom_munge_key_arn=custom_munge_key_arn)
    cluster = clusters_factory(cluster_config, upper_case_cluster_name=True)
    remote_command_executor = RemoteCommandExecutor(cluster)
    _test_custom_munge_key_fetch_and_decode(remote_command_executor)
    _test_munge_key_shared(remote_command_executor)

    # Test if compute node can run jobs, which means its munge key fetched successfully.
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "srun sleep 1",
            "nodes": 2,
        }
    )
    # Test error message when both compute and login nodes are not stopped.
    _test_update_munge_key_without_stop_login_or_compute(remote_command_executor)

    if use_login_node:
        remote_command_executor_login = RemoteCommandExecutor(cluster, use_login_node=True)
        _test_custom_munge_key_fetch_and_decode(remote_command_executor_login)
        remote_command_executor_login.close_connection()

    # Stop compute fleets
    cluster.stop()
    wait_for_computefleet_changed(cluster, "STOPPED")

    if use_login_node:
        # Test error message when login nodes are not stopped.
        _test_update_munge_key_without_stop_login_or_compute(remote_command_executor, compute_stopped=True)

        # Update cluster with pcluster.stop_login.config.yaml to stop login nodes.
        update_cluster_stop_login_config = pcluster_config_reader(
            config_file="pcluster.stop_login.config.yaml",
            custom_munge_key_arn=custom_munge_key_arn,
        )
        cluster.update(str(update_cluster_stop_login_config))

    # wait for LoginNodes gracetime_period
    for _i in range(5):
        result = remote_command_executor.run_remote_command(
            "sudo /opt/parallelcluster/scripts/slurm/check_login_nodes_stopped.sh",
            raise_on_error=False,
        )
        exit_code = result.return_code
        if exit_code == 0:
            break
        else:
            sleep(180)

    # Test rotation script run successfully
    result = remote_command_executor.run_remote_command("sudo /opt/parallelcluster/scripts/slurm/update_munge_key.sh")
    exit_code = result.return_code
    assert_that(exit_code).is_equal_to(0)

    update_cluster_remove_custom_munge_key_config = pcluster_config_reader(
        config_file="pcluster.remove_custom_munge_key.config.yaml",
        use_login_node=use_login_node,
    )
    cluster.update(str(update_cluster_remove_custom_munge_key_config))
    # Test Munge Key has been changed
    _test_custom_munge_key_fetch_and_decode(remote_command_executor, use_custom_munge_key=False)


def _test_custom_munge_key_fetch_and_decode(remote_command_executor, use_custom_munge_key=True):
    """Test encoded munge key in secret manager has been successfully fetched by cluster and decode."""
    result = remote_command_executor.run_remote_command("sudo cat /etc/munge/munge.key | base64")
    encode_munge_key = result.stdout.strip().replace("\n", "")
    if use_custom_munge_key:
        assert_that(encode_munge_key).is_equal_to(ENCODE_CUSTOM_MUNGE_KEY)
    else:
        assert_that(encode_munge_key).is_not_equal_to(ENCODE_CUSTOM_MUNGE_KEY)


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
