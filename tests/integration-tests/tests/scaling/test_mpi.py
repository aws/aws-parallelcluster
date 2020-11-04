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


@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5.xlarge", "m6g.xlarge"])
@pytest.mark.schedulers(["slurm", "sge"])
@pytest.mark.usefixtures("os")
def test_mpi(scheduler, region, instance, pcluster_config_reader, clusters_factory):
    scaledown_idletime = 3
    max_queue_size = 3
    slots_per_instance = fetch_instance_slots(region, instance)
    cluster_config = pcluster_config_reader(scaledown_idletime=scaledown_idletime, max_queue_size=max_queue_size)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

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

    # This verifies that scaling worked
    _test_mpi(
        remote_command_executor,
        slots_per_instance,
        scheduler,
        region,
        cluster.cfn_name,
        scaledown_idletime,
        verify_scaling=True,
    )


@pytest.mark.regions(["eu-west-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm", "sge"])
@pytest.mark.usefixtures("region", "instance", "os")
def test_mpi_ssh(scheduler, pcluster_config_reader, clusters_factory, test_datadir):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_mpi_ssh(remote_command_executor, scheduler, test_datadir)


def _test_mpi_ssh(remote_command_executor, scheduler, test_datadir):
    logging.info("Testing mpi SSH")
    mpi_module = "openmpi"

    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    compute_node = scheduler_commands.get_compute_nodes()
    assert_that(len(compute_node)).is_equal_to(1)
    remote_host = compute_node[0]

    # Gets remote host ip from hostname
    remote_host_ip = remote_command_executor.run_remote_command(
        "getent hosts {0} | cut -d' ' -f1".format(remote_host), timeout=10
    ).stdout

    # Below job will timeout if the IP address is not in known_hosts
    mpirun_out_ip = remote_command_executor.run_remote_script(
        str(test_datadir / "mpi_ssh.sh"), args=[mpi_module, remote_host_ip], timeout=10
    ).stdout.splitlines()

    # mpirun_out_ip = ["Warning: Permanently added '192.168.60.89' (ECDSA) to the list of known hosts.",
    # '', 'ip-192-168-60-89']
    assert_that(len(mpirun_out_ip)).is_equal_to(3)
    assert_that(mpirun_out_ip[-1]).is_equal_to(remote_host)

    mpirun_out = remote_command_executor.run_remote_script(
        str(test_datadir / "mpi_ssh.sh"), args=[mpi_module, remote_host], timeout=10
    ).stdout.splitlines()

    # mpirun_out = ["Warning: Permanently added 'ip-192-168-60-89,192.168.60.89' (ECDSA) to the list of known hosts.",
    # '', 'ip-192-168-60-89']
    assert_that(len(mpirun_out)).is_equal_to(3)
    assert_that(mpirun_out[-1]).is_equal_to(remote_host)
