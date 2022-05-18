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
from cfn_stacks_factory import CfnStack
from remote_command_executor import RemoteCommandExecutor
from troposphere import Template
from troposphere.route53 import HostedZone, HostedZoneVPCs
from utils import generate_stack_name

from tests.common.mpi_common import _test_mpi
from tests.common.utils import fetch_instance_slots


@pytest.mark.usefixtures("os")
def test_hit_no_cluster_dns_mpi(
    scheduler, region, instance, pcluster_config_reader, clusters_factory, test_datadir, scheduler_commands_factory
):
    logging.info("Testing HIT cluster with cluster DNS disabled.")
    scaledown_idletime = 3
    max_queue_size = 3
    min_queue_size = 1
    slots_per_instance = fetch_instance_slots(region, instance)
    cluster_config = pcluster_config_reader(
        scaledown_idletime=scaledown_idletime, max_queue_size=max_queue_size, min_queue_size=min_queue_size
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    # Assert that compute hostname cannot be pinged directly
    compute_nodes = scheduler_commands.get_compute_nodes()
    result = remote_command_executor.run_remote_command("ping -c 3 {}".format(compute_nodes[0]), raise_on_error=False)
    assert_that(result.failed).is_true()

    # Assert compute hostname is the same as nodename
    _test_hostname_same_as_nodename(scheduler_commands, remote_command_executor, compute_nodes)

    # This verifies that the job completes correctly
    _test_mpi(
        remote_command_executor,
        slots_per_instance,
        scheduler,
        scheduler_commands,
        region=region,
        stack_name=cluster.cfn_name,
        scaledown_idletime=scaledown_idletime,
        verify_scaling=False,
    )


@pytest.mark.usefixtures("os", "instance")
def test_existing_hosted_zone(
    hosted_zone_factory,
    pcluster_config_reader,
    clusters_factory,
    vpc_stack,
    cfn_stacks_factory,
    key_name,
    scheduler,
    region,
    instance,
    scheduler_commands_factory,
):
    """Test hosted_zone_id is provided in the config file."""
    num_computes = 2
    hosted_zone_id, domain_name = hosted_zone_factory()
    cluster_config = pcluster_config_reader(existing_hosted_zone=hosted_zone_id, queue_size=num_computes)
    cluster = clusters_factory(cluster_config, upper_case_cluster_name=True)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    # Test run mpi job
    _test_mpi(
        remote_command_executor,
        slots_per_instance=fetch_instance_slots(region, instance),
        scheduler=scheduler,
        scheduler_commands=scheduler_commands,
        region=region,
        stack_name=cluster.cfn_name,
        scaledown_idletime=3,
        verify_scaling=False,
    )

    # Assert compute hostname is the same as nodename
    compute_nodes = scheduler_commands.get_compute_nodes()
    _test_hostname_same_as_nodename(scheduler_commands, remote_command_executor, compute_nodes)

    # Test domain name matches expected domain name
    resolv_conf = remote_command_executor.run_remote_command("cat /etc/resolv.conf").stdout
    assert_that(resolv_conf).contains(cluster.cfn_name.lower() + "." + domain_name)


@pytest.fixture(scope="class")
def hosted_zone_factory(vpc_stack, cfn_stacks_factory, request, region):
    """Create a hosted zone stack."""
    hosted_zone_stack_name = generate_stack_name(
        "integ-tests-hosted-zone", request.config.getoption("stackname_suffix")
    )
    domain_name = hosted_zone_stack_name + ".com"

    def create_hosted_zone():
        hosted_zone_template = Template()
        hosted_zone_template.set_version("2010-09-09")
        hosted_zone_template.set_description("Hosted zone stack created for testing existing DNS")
        hosted_zone_template.add_resource(
            HostedZone(
                "HostedZoneResource",
                Name=domain_name,
                VPCs=[HostedZoneVPCs(VPCId=vpc_stack.cfn_outputs["VpcId"], VPCRegion=region)],
            )
        )
        hosted_zone_stack = CfnStack(
            name=hosted_zone_stack_name,
            region=region,
            template=hosted_zone_template.to_json(),
        )
        cfn_stacks_factory.create_stack(hosted_zone_stack)
        return hosted_zone_stack.cfn_resources["HostedZoneResource"], domain_name

    yield create_hosted_zone

    if not request.config.getoption("no_delete"):
        cfn_stacks_factory.delete_stack(hosted_zone_stack_name, region)


def _test_hostname_same_as_nodename(scheduler_commands, remote_command_executor, compute_nodes):
    result = scheduler_commands.submit_command("hostname > /shared/compute_hostname")
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    hostname = remote_command_executor.run_remote_command("cat /shared/compute_hostname").stdout
    assert_that(compute_nodes).contains(hostname)
