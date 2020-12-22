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
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from utils import get_compute_nodes_instance_ids

from tests.common.schedulers_common import get_scheduler_commands


@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["p4d.24xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_multiple_nics(scheduler, region, pcluster_config_reader, clusters_factory):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    _test_head_node_nics(remote_command_executor, region)
    _test_compute_node_nics(cluster, region, remote_command_executor, scheduler_commands)


def _get_private_ip_addresses(instance_id, region, remote_command_executor):
    result = remote_command_executor.run_remote_command(
        "aws ec2 describe-instances --instance-id {0} --region {1} "
        '--query "Reservations[0].Instances[0].NetworkInterfaces[*].PrivateIpAddresses[*].PrivateIpAddress" '
        "--output text".format(instance_id, region)
    )
    return result.stdout.strip().split("\n")


def _test_head_node_nics(remote_command_executor, region):
    # On the head node we just check that all the private IPs have been assigned to NICs
    head_node_instance_id = remote_command_executor.run_remote_command(
        "curl http://169.254.169.254/latest/meta-data/instance-id"
    ).stdout

    head_node_ip_addresses = _get_private_ip_addresses(head_node_instance_id, region, remote_command_executor)
    ip_a_result = remote_command_executor.run_remote_command("ip a").stdout

    for ip_address in head_node_ip_addresses:
        assert_that(ip_a_result).matches(".* inet {0}.*".format(ip_address))


def _test_compute_node_nics(cluster, region, remote_command_executor, scheduler_commands):
    compute_instance_id = get_compute_nodes_instance_ids(cluster.cfn_name, region)[0]
    # Get compute node's IP addresses
    compute_ip_addresses = _get_private_ip_addresses(compute_instance_id, region, remote_command_executor)
    for ip_address in compute_ip_addresses:
        _test_compute_node_nic(ip_address, remote_command_executor, scheduler_commands)


def _test_compute_node_nic(ip_address, remote_command_executor, scheduler_commands):
    # ping test from head node
    result = remote_command_executor.run_remote_command("ping -c 5 {0}".format(ip_address))
    assert_that(result.stdout).matches(".*5 packets transmitted, 5 received, 0% packet loss,.*")
    # ssh test from head node
    result = remote_command_executor.run_remote_command(
        "ssh -o StrictHostKeyChecking=no -q {0} echo Hello".format(ip_address)
    )
    assert_that(result.stdout).matches("Hello")
    # ping test from compute node
    result = scheduler_commands.submit_command("ping -I {0} -c 5 amazon.com > /shared/ping_{0}.out".format(ip_address))
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
    result = remote_command_executor.run_remote_command("cat /shared/ping_{0}.out".format(ip_address))
    assert_that(result.stdout).matches(".*5 packets transmitted, 5 received, 0% packet loss,.*")
