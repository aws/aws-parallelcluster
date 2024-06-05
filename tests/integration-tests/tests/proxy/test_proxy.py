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
from cfn_stacks_factory import CfnStack
from remote_command_executor import RemoteCommandExecutor
from utils import generate_stack_name


@pytest.fixture(scope="class")
def proxy_stack(region, request, cfn_stacks_factory):
    """
    Set up and tear down a CloudFormation stack to deploy a proxy environment.

    The stack is created from a CloudFormation template that sets up the necessary
    networking, instances, and security groups for a proxy environment. The proxy
    address and subnet are retrieved from the stack outputs and used in the cluster
    configuration.
    """
    proxy_stack_template_path = "../../cloudformation/proxy/proxy.yaml"
    with open(proxy_stack_template_path) as proxy_stack_template:
        stack_name = generate_stack_name("integ-tests-proxy", request.config.getoption("stackname_suffix"))
        stack_parameters = [
            {"ParameterKey": "Keypair", "ParameterValue": request.config.getoption("key_name")},
            {"ParameterKey": "VpcCidr", "ParameterValue": "10.0.0.0/16"},
        ]
        capabilities = ["CAPABILITY_IAM"]
        tags = [{"Key": "parallelcluster:integ-tests-proxy-stack", "Value": "proxy"}]

        proxy_stack = CfnStack(
            name=stack_name,
            region=region,
            template=proxy_stack_template.read(),
            parameters=stack_parameters,
            capabilities=capabilities,
            tags=tags,
        )

    cfn_stacks_factory.create_stack(proxy_stack)
    yield proxy_stack

    if not request.config.getoption("no_delete"):
        cfn_stacks_factory.delete_stack(proxy_stack.name, region)


@pytest.mark.usefixtures("os", "instance")
def test_proxy(scheduler, pcluster_config_reader, clusters_factory, proxy_stack, scheduler_commands_factory):
    """
    Test the creation and functionality of a ParallelCluster using a proxy environment.

    The test performs the following steps:
    1. Deploy a proxy environment using a CloudFormation stack.
    2. Create a ParallelCluster that uses the deployed proxy.
    3. Submit a sleep job to the cluster and verify it completes successfully.
    """
    proxy_address = proxy_stack.cfn_outputs["ProxyAddress"]
    subnet_with_proxy = proxy_stack.cfn_outputs["PrivateSubnet"]

    cluster_config = pcluster_config_reader(proxy_address=proxy_address, subnet_with_proxy=subnet_with_proxy)
    cluster = clusters_factory(cluster_config)

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 5", "nodes": 2}
    )
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
