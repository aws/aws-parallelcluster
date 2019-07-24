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
import threading

import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from tests.common.mpi_common import OS_TO_OPENMPI_MODULE_MAP, _test_mpi
from tests.common.schedulers_common import get_scheduler_commands
from tests.common.utils import _fetch_instance_slots


@pytest.mark.regions(["us-west-2"])
@pytest.mark.instances(["c5.xlarge", "c5n.18xlarge"])
@pytest.mark.schedulers(["slurm", "sge"])
@pytest.mark.oss(["alinux", "centos7", "centos6", "ubuntu1604", "ubuntu1804"])
def test_mpi(scheduler, region, os, instance, pcluster_config_reader, clusters_factory):
    scaledown_idletime = 3
    max_queue_size = 3
    slots_per_instance = _fetch_instance_slots(region, instance)
    cluster_config = pcluster_config_reader(scaledown_idletime=scaledown_idletime, max_queue_size=max_queue_size)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # This verifies that the job completes correctly
    _test_mpi(
        remote_command_executor,
        slots_per_instance,
        scheduler,
        os,
        region,
        cluster.cfn_name,
        scaledown_idletime,
        verify_scaling=False,
    )

    # This verifies that scaling worked
    _test_mpi(
        remote_command_executor,
        slots_per_instance,
        scheduler,
        os,
        region,
        cluster.cfn_name,
        scaledown_idletime,
        verify_scaling=True,
    )


@pytest.mark.regions(["eu-west-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm", "sge", "torque"])
@pytest.mark.usefixtures("region", "instance")
def test_mpi_ssh(scheduler, os, pcluster_config_reader, clusters_factory):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    mpi_module = OS_TO_OPENMPI_MODULE_MAP[os]
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    compute_node = scheduler_commands.get_compute_nodes()
    assert_that(len(compute_node)).is_equal_to(1)
    remote_host = compute_node[0]

    # Calls the test in a new thread and wait for its completion within a 5sec timeout
    # Setting the thread as daemon allows the main program to exit also if daemon thread is still running
    t = threading.Thread(target=_test_mpi_ssh, args=(remote_command_executor, mpi_module, remote_host))
    t.daemon = True
    t.start()
    t.join(5.0)
    assert_that(t.isAlive()).is_equal_to(False)


def _test_mpi_ssh(remote_command_executor, mpi_module, remote_host):
    logging.info("Testing mpi SSH")

    mpirun_out = remote_command_executor.run_remote_command(
        "module load {0} && mpirun --host {1} hostname".format(mpi_module, remote_host), raise_on_error=False
    ).stdout.splitlines()

    # mpirun_out =
    # "Warning: Permanently added the RSA host key for IP address '10.0.127.71' to the list of known hosts.\n
    # ip-10-0-127-71"
    assert_that(len(mpirun_out)).is_greater_than_or_equal_to(1)
    assert_that(mpirun_out[-1]).is_equal_to(remote_host)
