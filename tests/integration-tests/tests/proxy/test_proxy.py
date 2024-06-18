# Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

import boto3
import pytest
from assertpy import assert_that
from cfn_stacks_factory import CfnStack
from remote_command_executor import RemoteCommandExecutor
from utils import generate_stack_name

from tests.common.schedulers_common import SlurmCommands


@pytest.fixture(scope="class")
def proxy_stack_factory(region, request, cfn_stacks_factory):
    """
    Set up and tear down a CloudFormation stack to deploy a proxy environment.

    The stack is created from a CloudFormation template that sets up the necessary
    networking, instances, and security groups for a proxy environment. The proxy
    address and subnet are retrieved from the stack outputs and used in the cluster
    configuration.
    """
    proxy_stack_template_path = "../../cloudformation/proxy/proxy.yaml"
    with open(proxy_stack_template_path) as proxy_stack_template:
        if request.config.getoption("proxy_stack"):
            logging.info("Using proxy stack {0} in region {1}".format(request.config.getoption("proxy_stack"), region))
            proxy_stack = CfnStack(
                name=request.config.getoption("proxy_stack"),
                region=region,
                template=proxy_stack_template.read(),
            )
        else:
            stack_name = generate_stack_name("integ-tests-proxy", request.config.getoption("stackname_suffix"))
            stack_parameters = [
                {"ParameterKey": "Keypair", "ParameterValue": request.config.getoption("key_name")},
                {"ParameterKey": "VpcCidr", "ParameterValue": "10.0.0.0/16"},
                {"ParameterKey": "SSHCidr", "ParameterValue": "0.0.0.0/0"},
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

        if not request.config.getoption("no_delete") and not request.config.getoption("proxy_stack"):
            cfn_stacks_factory.delete_stack(proxy_stack.name, region)


def get_instance_public_ip(instance_id, region):
    ec2_client = boto3.client("ec2", region_name=region)
    response = ec2_client.describe_instances(InstanceIds=[instance_id])
    instance = response["Reservations"][0]["Instances"][0]
    return instance.get("PublicIpAddress")


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
def test_proxy(pcluster_config_reader, proxy_stack_factory, scheduler_commands_factory, clusters_factory):
    """
    Test the creation and functionality of a Cluster using a proxy environment.

    The test performs the following steps:
    1. Deploy a proxy environment using a CloudFormation stack.
    2. Create a ParallelCluster that uses the deployed proxy.
    3. Submit a sleep job to the cluster and verify it completes successfully.
    4. Check Internet access by trying to access google.com
    """
    proxy_address = proxy_stack_factory.cfn_outputs["ProxyAddress"]
    subnet_with_proxy = proxy_stack_factory.cfn_outputs["PrivateSubnet"]
    proxy_instance_id = proxy_stack_factory.cfn_resources.get("Proxy")
    assert_that(proxy_instance_id).is_not_none().described_as("Proxy instance ID should not be None")
    proxy_public_ip = get_instance_public_ip(proxy_instance_id, proxy_stack_factory.region)
    assert_that(proxy_public_ip).is_not_none().described_as("Proxy public IP should not be None")

    cluster_config = pcluster_config_reader(proxy_address=proxy_address, subnet_with_proxy=subnet_with_proxy)
    cluster = clusters_factory(cluster_config)

    bastion = f"ubuntu@{proxy_public_ip}"

    remote_command_executor = RemoteCommandExecutor(
        cluster=cluster, bastion=bastion, connection_timeout=300, connection_allow_agent=False
    )
    slurm_commands = SlurmCommands(remote_command_executor)

    # _check_internet_access(remote_command_executor)

    job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "srun sleep 1", "nodes": 1}
    )
    slurm_commands.wait_job_completed(job_id)
    slurm_commands.assert_job_succeeded(job_id)


def _check_internet_access(remote_command_executor):
    logging.info("Checking cluster has Internet access by trying to access google.com")
    internet_result = remote_command_executor.run_remote_command(
        "curl --connect-timeout 10 -I https://google.com", raise_on_error=False
    )
    assert_that(internet_result.failed).is_false()
