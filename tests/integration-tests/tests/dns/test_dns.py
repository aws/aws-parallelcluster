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

from tests.common.mpi_common import _test_mpi
from tests.common.schedulers_common import get_scheduler_commands
from tests.common.utils import fetch_instance_slots


@pytest.mark.regions(["eu-west-2"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("os")
def test_hit_no_cluster_dns_mpi(scheduler, region, instance, pcluster_config_reader, clusters_factory, test_datadir):
    logging.info("Testing HIT cluster with cluster DNS disabled.")
    scaledown_idletime = 3
    max_queue_size = 3
    slots_per_instance = fetch_instance_slots(region, instance)
    cluster_config = pcluster_config_reader(scaledown_idletime=scaledown_idletime, max_queue_size=max_queue_size)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    # Assert that compute hostname cannot be pinged directly
    compute_nodes = scheduler_commands.get_compute_nodes()
    result = remote_command_executor.run_remote_command("ping -c 3 {}".format(compute_nodes[0]), raise_on_error=False)
    assert_that(result.failed).is_true()

    # Assert compute hostname is the same as nodename
    result = scheduler_commands.submit_command("hostname > /shared/compute_hostname")
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    hostname = remote_command_executor.run_remote_command("cat /shared/compute_hostname").stdout
    assert_that(compute_nodes).contains(hostname)

    # This verifies that the job completes correctly
    _test_mpi(
        remote_command_executor,
        slots_per_instance,
        scheduler,
        region,
        cluster.cfn_name,
        scaledown_idletime,
        verify_scaling=False,
    )
