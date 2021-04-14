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
from cfn_stacks_factory import CfnStack
from fabric import Connection
from troposphere import Template
from troposphere.ec2 import EIP
from utils import generate_stack_name, get_compute_nodes_instance_ids, get_username_for_os


@pytest.mark.dimensions("us-west-2", "c5.xlarge", "alinux2", "slurm")
@pytest.mark.dimensions("eu-west-2", "c5.xlarge", "centos7", "slurm")
@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_cluster_in_private_subnet(region, pcluster_config_reader, clusters_factory):
    # This test just creates a cluster in the private subnet and just checks that no failures occur
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    assert_that(cluster).is_not_none()

    assert_that(len(get_compute_nodes_instance_ids(cluster.cfn_name, region))).is_equal_to(1)


@pytest.fixture(scope="class")
def existing_eip(region, request, cfn_stacks_factory):
    template = Template()
    template.set_version("2010-09-09")
    template.set_description("EIP stack for testing existing EIP")
    template.add_resource(EIP("ElasticIP", Domain="vpc"))
    stack = CfnStack(
        name=generate_stack_name("integ-tests-eip", request.config.getoption("stackname_suffix")),
        region=region,
        template=template.to_json(),
    )
    cfn_stacks_factory.create_stack(stack)

    yield stack.cfn_resources["ElasticIP"]

    if not request.config.getoption("no_delete"):
        cfn_stacks_factory.delete_stack(stack.name, region)


@pytest.mark.usefixtures("os", "scheduler", "instance", "region")
def test_existing_eip(existing_eip, pcluster_config_reader, clusters_factory):
    cluster_config = pcluster_config_reader(elastic_ip=existing_eip)
    cluster = clusters_factory(cluster_config)
    assert_that(cluster).is_not_none()
    username = get_username_for_os(cluster.os)
    connection = Connection(
        host=existing_eip,
        user=username,
        forward_agent=False,
        connect_kwargs={"key_filename": [cluster.ssh_key]},
    )
    # Run arbitrary command to test if we can use the elastic ip to log into the instance.
    connection.run("cat /var/log/cfn-init.log", timeout=60)
