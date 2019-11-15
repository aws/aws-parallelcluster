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


@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5n.18xlarge"])
@pytest.mark.oss(["centos7"])
@pytest.mark.schedulers(["sge"])
def test_intel_hpc(region, scheduler, instance, os, pcluster_config_reader, clusters_factory, test_datadir):
    """Test Intel Cluster Checker"""
    slots_per_instance = fetch_instance_slots(region, instance)
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_intel_clck(remote_command_executor, scheduler_commands, slots_per_instance, test_datadir)

    assert_no_errors_in_logs(remote_command_executor, ["/var/log/sqswatcher", "/var/log/jobwatcher"])


def _test_intel_clck(remote_command_executor, scheduler_commands, slots_per_instance, test_datadir):
    # Install Intel Cluster Checker CLCK Master
    logging.info("Installing Intel Cluster Checker")
    remote_command_executor.run_remote_script(str(test_datadir / "install_clck.sh"), hide=False)

    # Create nodefile
    # ip-172-31-15-31  # role: head
    # ip-172-31-12-237  # role: compute
    # ip-172-31-8-49  # role: compute
    remote_command_executor.run_remote_command("echo $HOSTNAME | awk '{print $1 \" # role: head\" }' > nodefile")
    remote_command_executor.run_remote_command(
        "qhost | tail -n +4 | awk '{print $1 \" # role: compute\" }' >> nodefile"
    )
    result = remote_command_executor.run_remote_command("cat nodefile | wc -l")
    assert_that(result.stdout).contains("3")

    # Setup network interface
    # <!-- This tag can be used to set the network interface used for
    #      accumulating data collected on-demand.
    # -->
    # <!--
    # <network_interface>ens5</network_interface>
    # -->
    # /opt/intel/clck/2019.3.5/etc/clck.xml
    remote_command_executor.run_remote_command(
        "sudo cp ~/clck.xml /opt/intel/clck/2019.3.5/etc/clck.xml", additional_files=[str(test_datadir / "clck.xml")]
    )

    # Load modules in ~/.bashrc
    remote_command_executor.run_remote_command(
        "echo 'PATH=/opt/intel/intelpython2/bin/:$PATH\nPATH=/opt/intel/intelpython3/bin/:$PATH\n"
        "source /opt/intel/psxe_runtime/linux/bin/psxevars.sh' >> ~/.bashrc"
    )

    # Run Cluster Checker
    result = remote_command_executor.run_remote_script(str(test_datadir / "run_clck.sh"))
    try:
        assert_that(result.stdout).contains("Overall Result: PASS")
    except AssertionError as e:
        logging.error(remote_command_executor.run_remote_command("cat clck_results.log").stdout)
        raise e
