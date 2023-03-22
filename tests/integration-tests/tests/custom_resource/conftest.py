# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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


from pathlib import Path
import pkg_resources
import pytest
import boto3
from cfn_stacks_factory import CfnStack, CfnStacksFactory
from utils import generate_stack_name


@pytest.fixture(scope="class", name="cfn")
def cfn_fixture(region):
    """Create a CloudFormation Boto3 client."""
    client = boto3.client("cloudformation", region_name=region)
    return client


@pytest.fixture(scope="session", name="resources_dir")
def resources_dir_fixture():
    return Path(pkg_resources.resource_filename(__name__, "/../../resources"))


@pytest.fixture(scope="session", name="cluster_custom_resource_template")
def cluster_custom_resource_template_fixture(resources_dir):
    return resources_dir / "cluster_custom_resource.yaml"


@pytest.fixture(scope="session", name="cluster_custom_resource_provider_template")
def cluster_custom_resource_provider_template_fixture(resources_dir):
    return resources_dir / ".." / ".." / ".." / "cloudformation" / "custom_resource" / "cluster.yaml"


@pytest.fixture(scope="class", name="cluster_custom_resource_provider")
def cluster_custom_resource_provider_fixture(
    request, region, resource_bucket, cluster_custom_resource_service_token, cluster_custom_resource_provider_template
):
    """Create the cluster custom resource stack."""
    factory = CfnStacksFactory(request.config.getoption("credential"))
    if cluster_custom_resource_service_token:
        yield cluster_custom_resource_service_token
        return

    parameters = {"CustomBucket": resource_bucket}
    with open(cluster_custom_resource_provider_template, encoding="utf-8") as cfn_file:
        template_data = cfn_file.read()

    stack = CfnStack(
        name=generate_stack_name("custom-resource-provider", request.config.getoption("stackname_suffix")),
        region=region,
        template=template_data,
        parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in parameters.items()],
        capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
    )

    try:
        factory.create_stack(stack, True)
        yield stack.cfn_outputs.get("ServiceToken")
    finally:
        factory.delete_all_stacks()


@pytest.fixture(scope="class", name="cluster_custom_resource_factory")
def cluster_custom_resource_factory_fixture(
    request, region, cluster_custom_resource_template, cluster_custom_resource_provider, vpc_stack
):
    factory = CfnStacksFactory(request.config.getoption("credential"))

    def _produce_cluster_custom_resource_stack(parameters=None):
        cluster_name = generate_stack_name("custom-resource-c", request.config.getoption("stackname_suffix"))

        parameters = {
            "ClusterName": cluster_name,
            "HeadNodeSubnet": vpc_stack.get_public_subnet(),
            "ComputeNodeSubnet": vpc_stack.get_private_subnet(),
            "ServiceToken": cluster_custom_resource_provider,
            **(parameters or {}),
        }

        with open(cluster_custom_resource_template, encoding="utf-8") as cfn_file:
            template_data = cfn_file.read()

        stack = CfnStack(
            name=generate_stack_name("custom-resource", request.config.getoption("stackname_suffix")),
            region=region,
            template=template_data,
            parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in parameters.items()],
            capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
        )

        factory.create_stack(stack, True)
        stack.factory = factory
        return stack

    return _produce_cluster_custom_resource_stack

    factory.delete_all_stacks()
