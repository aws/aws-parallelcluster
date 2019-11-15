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

import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from tests.common.assertions import assert_no_errors_in_logs
from tests.common.schedulers_common import get_scheduler_commands
from tests.common.utils import fetch_instance_slots


# t2's do not support CpuOptions and hence do not support disable_hyperthreading
@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.skip_schedulers(["awsbatch"])
def test_disable_hyperthreading(region, scheduler, instance, os, pcluster_config_reader, clusters_factory):
    """Test Disable Hyperthreading"""
    slots_per_instance = fetch_instance_slots(region, instance)
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_disable_hyperthreading(remote_command_executor, scheduler_commands, slots_per_instance, scheduler)

    assert_no_errors_in_logs(remote_command_executor, ["/var/log/sqswatcher", "/var/log/jobwatcher"])


def _test_disable_hyperthreading(remote_command_executor, scheduler_commands, slots_per_instance, scheduler):
    # Test disable hyperthreading on Master
    logging.info("Test Disable Hyperthreading on Master")
    result = remote_command_executor.run_remote_command("lscpu")
    assert_that(result.stdout).matches(r"Thread\(s\) per core:\s+1")
    assert_that(result.stdout).matches(r"CPU\(s\):\s+{0}".format(slots_per_instance // 2))

    # Test disable hyperthreading on Compute
    logging.info("Test Disable Hyperthreading on Compute")
    result = scheduler_commands.submit_command("lscpu > /shared/lscpu.out")

    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    # Check compute has 1 thread per core
    result = remote_command_executor.run_remote_command("cat /shared/lscpu.out")
    assert_that(result.stdout).matches(r"Thread\(s\) per core:\s+1")
    assert_that(result.stdout).matches(r"CPU\(s\):\s+{0}".format(slots_per_instance // 2))

    # Check scheduler has correct number of cores
    result = scheduler_commands.get_node_cores()
    logging.info("{0} Cores: [{1}]".format(scheduler, result))
    assert_that(int(result)).is_equal_to(slots_per_instance // 2)

    # check scale up to 2 nodes
    result = scheduler_commands.submit_command(
        "hostname > /shared/hostname.out", nodes=2, slots=slots_per_instance // 2
    )
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
    assert_that(scheduler_commands.compute_nodes_count()).is_equal_to(2)
