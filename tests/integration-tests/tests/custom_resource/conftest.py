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

import boto3
import cfn_tools
import pkg_resources
import pytest
from cfn_stacks_factory import CfnStack, CfnStacksFactory
from troposphere import Output, Ref
from troposphere.iam import ManagedPolicy
from troposphere.template_generator import TemplateGenerator
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


@pytest.fixture(scope="session", name="policies_template_path")
def policies_template_path_fixture(resources_dir):
    return resources_dir / ".." / ".." / ".." / "cloudformation" / "policies" / "parallelcluster-policies.yaml"


def cluster_custom_resource_provider_generator(credentials, region, stack_name, parameters, template):
    factory = CfnStacksFactory(credentials)
    with open(template, encoding="utf-8") as cfn_file:
        template_data = cfn_file.read()

    stack = CfnStack(
        name=stack_name,
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


@pytest.fixture(scope="class", name="cluster_custom_resource_provider")
def cluster_custom_resource_provider_fixture(
    request, region, resource_bucket, cluster_custom_resource_service_token, cluster_custom_resource_provider_template
):
    """Create the cluster custom resource stack."""
    if cluster_custom_resource_service_token:
        yield cluster_custom_resource_service_token
        return

    parameters = {"CustomBucket": resource_bucket}
    yield from cluster_custom_resource_provider_generator(
        request.config.getoption("credential"),
        region,
        generate_stack_name("custom-resource-provider", request.config.getoption("stackname_suffix")),
        parameters,
        cluster_custom_resource_provider_template,
    )


@pytest.fixture(scope="class", name="cluster_custom_resource_factory")
def cluster_custom_resource_factory_fixture(
    request, region, os, cluster_custom_resource_template, cluster_custom_resource_provider, vpc_stack
):
    factory = CfnStacksFactory(request.config.getoption("credential"))

    def _produce_cluster_custom_resource_stack(parameters=None):
        cluster_name = generate_stack_name("custom-resource-c", request.config.getoption("stackname_suffix"))

        parameters = {
            "ClusterName": cluster_name,
            "HeadNodeSubnet": vpc_stack.get_public_subnet(),
            "ComputeNodeSubnet": vpc_stack.get_private_subnet(),
            "ServiceToken": cluster_custom_resource_provider,
            "Os": os,
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

    yield _produce_cluster_custom_resource_stack

    factory.delete_all_stacks()


@pytest.fixture(scope="class", name="resource_bucket_cluster_template")
def resource_bucket_cluster_template_fixture(policies_template_path, resource_bucket):
    bucket_policy = ManagedPolicy(
        title="ResourceBucketAccess",
        Description="Policy to access resource bucket",
        PolicyDocument={
            "Statement": [
                {
                    "Action": ["s3:GetObject"],
                    "Effect": "Allow",
                    "Resource": {"Fn::Sub": f"arn:${{AWS::Partition}}:s3:::{resource_bucket}/*"},
                },
                {
                    "Action": ["events:PutRule", "events:DeleteRule", "events:PutTargets", "events:RemoveTargets"],
                    "Effect": "Allow",
                    "Resource": {"Fn::Sub": "arn:${AWS::Partition}:events:${AWS::Region}:${AWS::AccountId}:rule/*"},
                },
            ],
            "Version": "2012-10-17",
        },
    )

    with open(policies_template_path, "r", encoding="utf-8") as f:
        policies_template = TemplateGenerator(cfn_tools.load_yaml(f.read()))

    policies_template.add_resource(bucket_policy)
    policies_template.add_output(Output("ResourceBucketAccess", Value=Ref("ResourceBucketAccess")))
    managed_policies = policies_template.resources.get("ParallelClusterLambdaRole").properties["ManagedPolicyArns"]
    managed_policies.append(Ref("ResourceBucketAccess"))
    return policies_template.to_yaml()


@pytest.fixture(scope="class", name="resource_bucket_policies")
def resource_bucket_policies_fixture(request, region, resource_bucket_cluster_template):
    factory = CfnStacksFactory(request.config.getoption("credential"))

    parameters = {"EnableIamAdminAccess": "true"}
    stack = CfnStack(
        name=generate_stack_name("resource-bucket-policies", request.config.getoption("stackname_suffix")),
        region=region,
        template=resource_bucket_cluster_template,
        capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM"],
        parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in parameters.items()],
    )

    try:
        factory.create_stack(stack, True)
        yield stack
    finally:
        factory.delete_all_stacks()
