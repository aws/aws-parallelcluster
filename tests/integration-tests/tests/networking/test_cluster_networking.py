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
import time

import pytest
import utils
from assertpy import assert_that
from cfn_stacks_factory import CfnStack
from remote_command_executor import RemoteCommandExecutor
from troposphere import GetAtt, Output, Ref, Template, ec2
from utils import get_compute_nodes_instance_ids

from tests.common.schedulers_common import get_scheduler_commands
from tests.common.utils import retrieve_latest_ami
from tests.storage.test_fsx_lustre import (
    assert_fsx_lustre_correctly_mounted,
    assert_fsx_lustre_correctly_shared,
    get_fsx_fs_id,
)


@pytest.mark.dimensions("us-west-2", "c5.xlarge", "alinux2", "slurm")
@pytest.mark.dimensions("eu-west-2", "c5.xlarge", "centos7", "slurm")
@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_cluster_in_private_subnet(region, os, scheduler, pcluster_config_reader, clusters_factory, bastion_factory):
    # This test just creates a cluster in the private subnet and just checks that no failures occur
    fsx_mount_dir = "/fsx_mount"
    cluster_config = pcluster_config_reader(fsx_mount_dir=fsx_mount_dir)
    cluster = clusters_factory(cluster_config)
    assert_that(cluster).is_not_none()

    assert_that(len(get_compute_nodes_instance_ids(cluster.cfn_name, region))).is_equal_to(1)
    _test_fsx_in_private_subnet(cluster, os, region, scheduler, fsx_mount_dir, bastion_factory)


def _test_fsx_in_private_subnet(cluster, os, region, scheduler, fsx_mount_dir, bastion_factory):
    """Test FSx can be mounted in private subnet."""
    bastion_ip = bastion_factory()
    logging.info("Sleeping for 60 sec to wait for bastion ssh to become ready.")
    time.sleep(60)
    logging.info("Bastion_ip: {}".format(bastion_ip))
    remote_command_executor = RemoteCommandExecutor(cluster, bastion="ec2-user@{}".format(bastion_ip))
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    fsx_fs_id = get_fsx_fs_id(cluster, region)
    assert_fsx_lustre_correctly_mounted(remote_command_executor, fsx_mount_dir, os, region, fsx_fs_id)
    assert_fsx_lustre_correctly_shared(scheduler_commands, remote_command_executor, fsx_mount_dir)


@pytest.fixture()
def bastion_factory(vpc_stack, cfn_stacks_factory, request, region, key_name):
    """Class to create bastion instance used to execute commands on cluster in private subnet."""
    bastion_stack_name = utils.generate_stack_name(
        "integ-tests-networking-bastion", request.config.getoption("stackname_suffix")
    )

    def _bastion_factory():
        """Create bastion stack."""
        bastion_template = Template()
        bastion_template.set_version()
        bastion_template.set_description("Create Networking bastion stack")

        bastion_sg = ec2.SecurityGroup(
            "NetworkingTestBastionSG",
            GroupDescription="SecurityGroup for Bastion",
            SecurityGroupIngress=[
                ec2.SecurityGroupRule(
                    IpProtocol="tcp",
                    FromPort="22",
                    ToPort="22",
                    CidrIp="0.0.0.0/0",
                ),
            ],
            VpcId=vpc_stack.cfn_outputs["VpcId"],
        )

        bastion_instance = ec2.Instance(
            "NetworkingBastionInstance",
            InstanceType="c5.xlarge",
            ImageId=retrieve_latest_ami(region, "alinux2"),
            KeyName=key_name,
            SecurityGroupIds=[Ref(bastion_sg)],
            SubnetId=vpc_stack.cfn_outputs["PublicSubnetId"],
        )
        bastion_template.add_resource(bastion_sg)
        bastion_template.add_resource(bastion_instance)
        bastion_template.add_output(
            Output("BastionIP", Value=GetAtt(bastion_instance, "PublicIp"), Description="The Bastion Public IP")
        )
        bastion_stack = CfnStack(
            name=bastion_stack_name,
            region=region,
            template=bastion_template.to_json(),
        )
        cfn_stacks_factory.create_stack(bastion_stack)

        return bastion_stack.cfn_outputs.get("BastionIP")

    yield _bastion_factory
    cfn_stacks_factory.delete_stack(bastion_stack_name, region)
