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
import logging

from assertpy import assert_that

from tests.common.assertions import assert_scaling_worked
from tests.common.schedulers_common import get_scheduler_commands


def assert_overscaling_when_job_submitted_during_scaledown(
    remote_command_executor, scheduler, region, stack_name, scaledown_idletime
):
    """Test that if a job gets submitted when a node is locked the cluster does not overscale"""
    logging.info("Testing cluster does not overscale when a job is submitted and a node is being terminated.")
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    if scheduler_commands.compute_nodes_count() == 0:
        result = scheduler_commands.submit_command("sleep 1")
        job_id = scheduler_commands.assert_job_submitted(result.stdout)
        scheduler_commands.wait_job_completed(job_id)
    assert_that(scheduler_commands.compute_nodes_count()).is_equal_to(1)

    scheduler_commands.wait_for_locked_node()

    result = scheduler_commands.submit_command("sleep 1")
    scheduler_commands.assert_job_submitted(result.stdout)
    # do not check scheduler scaling but only ASG.
    assert_scaling_worked(
        scheduler_commands,
        region,
        stack_name,
        scaledown_idletime,
        expected_max=1,
        expected_final=0,
        assert_scheduler=False,
    )
