# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import random
import time

import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor


@pytest.mark.usefixtures("os", "scheduler")
def test_capacity_blocks(pcluster_config_reader, clusters_factory, test_datadir, scheduler_commands_factory):
    """
    Test that clustermgtd and the system works as expected when using Capacity Blocks.

    The Capacity Blocks behaviour is totally simulated, with some mocking and overrides.

    Fleet-config and describe-capacity-reservations output will be mocked in the following way:
    - static nodes initially will be created because standard on-demand instances,
    - fleet-config.json will be modified to simulate there is a CB,
    - the describe_capacity_reservations will be mocked to return a pending/active CB to simulate state transition
    The test will verify that Slurm reservations are created/deleted accordingly and job in pending will start.
    """
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    # fake capacity block id
    capacity_block_id = "cr-123456abc12345abc"
    reservation_name = f"pcluster-{capacity_block_id}"

    # override describe-capacity-reservations output
    remote_command_executor = RemoteCommandExecutor(cluster)
    remote_command_executor.run_remote_script(
        script_file=str(test_datadir / "override_capacity_blocks.sh"), args=[capacity_block_id]
    )
    logging.info("Restart clustermgtd to load the overrides module")
    remote_command_executor.run_remote_command(command="sudo systemctl restart supervisord")
    # wait 1 minute for clustermgtd execution
    time.sleep(60)
    _check_slurm_reservation_existence(remote_command_executor, capacity_block_id, reservation_name)

    # submit a job that will remain in pending because CB is not active
    logging.info("Submitted a job in a pending CB")
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    result = scheduler_commands.submit_command("sleep 1")
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.assert_job_state(job_id, "PENDING")

    # Simulate active CB and check slurm reservations are removed
    _modify_capacity_block_override_status(remote_command_executor, previous_status="pending", new_status="active")
    # Verify slurm reservation has been removed
    logging.info("Checking slurm reservation for CB %s has been removed", capacity_block_id)
    result = remote_command_executor.run_remote_command(
        command=f"scontrol show ReservationName={reservation_name}", raise_on_error=False
    )
    assert_that(result.stdout).contains(f"Reservation {reservation_name} not found")

    # Verify job is completed
    scheduler_commands.wait_job_completed(job_id)
    logging.info(f"Job {job_id} that was pending in the inactive CB, is now completed")

    # Move CB back to pending and check slurm reservations are restored
    _modify_capacity_block_override_status(remote_command_executor, previous_status="active", new_status="pending")
    _check_slurm_reservation_existence(remote_command_executor, capacity_block_id, reservation_name)


def _check_slurm_reservation_existence(remote_command_executor, capacity_block_id, reservation_name):
    """Verify slurm reservation containing both static and dynamic nodes for the CB exists."""
    logging.info("Verifying slurm reservation for CB %s exists", capacity_block_id)
    result = remote_command_executor.run_remote_command(command=f"scontrol show ReservationName={reservation_name}")
    assert_that(result.stdout).matches(
        r"Nodes=queue1-dy-cr1-\[1-2\],queue1-st-cr1-\[1-2\] NodeCnt=4 .*Flags=MAINT,SPEC_NODES"
    )


def _modify_capacity_block_override_status(remote_command_executor, previous_status, new_status):
    """Replace strings in the capacity-reservations-data.json file and re-initialize clustermgtd."""
    logging.info("Changing status of CB from %s to %s", previous_status, new_status)
    remote_command_executor.run_remote_command(
        command=f"sudo sed -i 's/{previous_status}/{new_status}/g' /tmp/capacity-reservations-data.json",
    )
    _trigger_capacity_block_manager_execution(remote_command_executor)


def _trigger_capacity_block_manager_execution(remote_command_executor):
    """
    Modify a random parameter in clustermgtd configuration to trigger a new execution of the CB management loop.

    ClusterManager object (and so CapacityBlockManager) is re-initialized every time the clustermgd config is modified.
    """
    logging.info(
        "Triggering capacity block manager execution after modification of describe-capacity-reservations overrides"
    )
    new_timeout_value = random.randint(400, 800)
    remote_command_executor.run_remote_command(
        command=(
            f"sudo sed -i 's/insufficient_capacity_timeout = .*/insufficient_capacity_timeout = {new_timeout_value}/g'"
            " /etc/parallelcluster/slurm_plugin/parallelcluster_clustermgtd.conf"
        )
    )
    # wait 2 minutes to be sure clustermgtd does another round of checks
    time.sleep(120)
