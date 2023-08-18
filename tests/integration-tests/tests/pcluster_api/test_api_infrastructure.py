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
import json
import logging
import re

import boto3
import botocore
import pytest
import requests
from assertpy import assert_that
from botocore.exceptions import ClientError
from troposphere import Template, Parameter, Equals, Ref

import cfn_stacks_factory
from cfn_stacks_factory import CfnStack, CfnStacksFactory
from framework.credential_providers import sts_credential_provider
from retrying import retry

from tests.iam.test_iam import _create_permission_boundary
from time_utils import minutes, seconds
from utils import generate_stack_name, retrieve_cfn_resources

from tests.common.utils import get_installed_parallelcluster_version

LOGGER = logging.getLogger(__name__)


@pytest.fixture(scope="class")
def api_with_default_settings(
        api_infrastructure_s3_uri, api_definition_s3_uri, policies_uri, request, region, resource_bucket
):
    factory = CfnStacksFactory(request.config.getoption("credential"))

    def create_stack(custom_parameters={}):

        params = []
        if api_definition_s3_uri:
            params.append({"ParameterKey": "ApiDefinitionS3Uri", "ParameterValue": api_definition_s3_uri})
        if policies_uri:
            params.append({"ParameterKey": "PoliciesTemplateUri", "ParameterValue": policies_uri})
        if resource_bucket:
            params.append({"ParameterKey": "CustomBucket", "ParameterValue": resource_bucket})
        params.append(custom_parameters)

        template = (
                api_infrastructure_s3_uri
                or f"https://{resource_bucket}.s3.{region}.amazonaws.com{'.cn' if region.startswith('cn') else ''}"
                   f"/parallelcluster/{get_installed_parallelcluster_version()}/api/parallelcluster-api.yaml"
        )
        logging.info(f"Creating API Server stack in {region} with template {template}")
        stack = CfnStack(
            name=generate_stack_name("integ-tests-api", request.config.getoption("stackname_suffix")),
            region=region,
            parameters=params,
            capabilities=["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
            template=template,
        )
        factory.create_stack(stack)
        return stack

    yield create_stack
    factory.delete_all_stacks()


@pytest.fixture()
def create_permission_boundary(region, request, cfn_stacks_factory):
    permission_boundary_name = "test"
    iam_client = boto3.client("iam", region)
    template = Template()
    template.add_parameter(Parameter(
        "Region",
        Description="(Optional) The zone in which you want to create your subnet(s)",
        Type="String",
        Default="*",
    ))
    template.add_parameter(Parameter(
        "CustomIamNamePrefix",
        Description="(Optional) The zone in which you want to create your subnet(s)",
        Type="String",
        Default="parallelcluster",
    ))
    template.add_parameter(Parameter(
        "CustomIamPathPrefix",
        Description="(Optional) The zone in which you want to create your subnet(s)",
        Type="String",
        Default="parallelcluster",
    ))
    template.add_condition("IsMultiRegion", Equals(Ref("Region"), "*"))
    permission_boundary_policy = _create_permission_boundary(permission_boundary_name)
    template.add_resource(permission_boundary_policy)
    logging.info(f"Output: {template.to_json()}")
    stack = CfnStack(
        name=generate_stack_name("integ-tests-odcr", request.config.getoption("stackname_suffix")),
        region=region,
        capabilities=["CAPABILITY_IAM"],
        template=template.to_json(),
    )
    cfn_stacks_factory.create_stack(stack)
    yield stack.cfn_resources[permission_boundary_name]
    iam_client.delete_policy(PolicyArn=stack.cfn_resources[permission_boundary_name])


def test_api_infrastructure_with_default_parameters(region, api_with_default_settings, create_permission_boundary):
    """Test that creating the API Infrastructure stack with the defaults correctly sets up the Lambda and APIGateway API

    :param region: the region where the stack is run
    :api_server_factory: factory for deploying API servers on-demand to each region
    """
    ex_stack = api_with_default_settings()
    parallelcluster_lambda_name = ex_stack.cfn_resources["ParallelClusterFunction"]
    parallelcluster_lambda_arn = ex_stack.cfn_outputs["ParallelClusterLambdaArn"]

    parallelcluster_api_id = ex_stack.cfn_resources["ApiGatewayApiWithoutCustomDomain"]
    parallelcluster_api_url = ex_stack.cfn_outputs["ParallelClusterApiInvokeUrl"]
    parallelcluster_user_role = ex_stack.cfn_outputs["ParallelClusterApiUserRole"]

    _assert_parallelcluster_lambda(lambda_name=parallelcluster_lambda_name, lambda_arn=parallelcluster_lambda_arn)
    _assert_parallelcluster_api(api_id=parallelcluster_api_id, api_url=parallelcluster_api_url)
    _test_auth(region, parallelcluster_user_role, parallelcluster_api_url)
    _test_api_deletion(api_with_default_settings)

    cfn_client = boto3.client("cloudformation", region)
    iam_client = boto3.client("iam", region)
    prefix = ""
    permission_boundary_arn = create_permission_boundary(region=region)
    custom_params = {}
    ex_stack.create_stack(custom_params)

    try:
        stacks = cfn_client.describe_stack_resources(StackName=ex_stack.name)["StackResources"]
        stack_ids = [stack["StackId"] for stack in stacks]
        nested_stacks = cfn_client.describe_stack_resources(StackName=ex_stack.name)

        for nested_stack in nested_stacks:
            if nested_stack["ResourceType"] == "AWS::CloudFormation::Stack":
                nested_stack_id = nested_stack["PhysicalResourceId"]
                stack_ids.append(nested_stack_id)

        for stack_id in stack_ids:
            resources = cfn_client.describe_stack_resources(StackName=stack_id)["StackResources"]

            for resource in resources:
                resource_type = resource["ResourceType"]
                resource_logical_id = resource["LogicalResourceId"]

                if resource_type == "AWS::IAM::Role":
                    role_name = resource["PhysicalResourceId"]
                    try:
                        role = iam_client.get_role(RoleName=role_name)
                        assert_that(role_name.starts_with(prefix)).is_false()
                        assert_that("PermissionsBoundary" in role).is_false()
                    except ClientError as e:
                        print(f"Error getting role {role_name}: {e}")
                if resource_type == "AWS::IAM::Policy":
                    policy_name = resource["PhysicalResourceId"]
                    try:
                        policy_name = iam_client.get_policy(PolicyArn=policy_name)
                        assert_that(policy_name.startswith(prefix)).is_false()
                    except ClientError as e:
                        print(f"Error getting policy {policy_name}: {e}")
    except ClientError as e:
        print(f"Error: {e}")


def _assert_parallelcluster_lambda(lambda_name, lambda_arn):
    """Check that the ParallelCluster Lambda is correctly configured

    :param client: the Lambda client
    :param lambda_name: the name of the ParallelCluster Lambda
    :param lambda_arn: the ARN of the ParallelCluster Lambda
    """
    logging.info("Checking Lambda configuration")

    client = boto3.client("lambda")
    lambda_resource = client.get_function(FunctionName=lambda_name)
    lambda_configuration = lambda_resource["Configuration"]
    assert_that(lambda_configuration["FunctionArn"]).is_equal_to(lambda_arn)
    assert_that(lambda_configuration["Timeout"]).is_equal_to(30)
    assert_that(lambda_configuration).contains("Layers")
    assert_that(len(lambda_configuration["Layers"])).is_equal_to(1)
    assert_that(lambda_configuration["Layers"][0]).contains("Arn")
    if "TracingConfig" in lambda_configuration:
        # When executed in GovCloud get_function does not return TracingConfig
        assert_that(lambda_configuration["TracingConfig"]["Mode"]).is_equal_to("Active")
    assert_that(lambda_configuration["MemorySize"]).is_equal_to(2048)
    assert_that(lambda_resource["Tags"]).contains("parallelcluster:version")
    assert_that(lambda_resource["Tags"]).contains("parallelcluster:resource")


def _assert_parallelcluster_api(api_id, api_url):
    """Check that the ParallelCluster APIGateway API is correctly configured

    :param client: the APIGateway client
    :param api_id: the id of the ParallelCluster API
    :param api_url: the URL of the ParallelCluster API
    """
    logging.info("Checking Api Gateway configuration")
    client = boto3.client("apigateway")

    apigateway_resource = client.get_rest_api(restApiId=api_id)
    assert_that(apigateway_resource["endpointConfiguration"]["types"]).is_equal_to(["REGIONAL"])

    api_id_from_url = _parse_api_url(api_url)["ApiId"]
    assert_that(api_url).ends_with("/prod")
    assert_that(api_id_from_url).is_equal_to(api_id)

    stage_resource = client.get_stage(restApiId=api_id, stageName="prod")
    assert_that(stage_resource["tags"]).contains("parallelcluster:version")
    assert_that(stage_resource["tracingEnabled"]).is_true()


def _call_list_clusters(region, api_url, enable_sigv4=True):
    session = botocore.session.Session()
    request = botocore.awsrequest.AWSRequest(method="GET", url="{}/v3/clusters".format(api_url))
    if enable_sigv4:
        botocore.auth.SigV4Auth(session.get_credentials(), "execute-api", region).add_auth(request)
    prepared_request = request.prepare()
    response = requests.get(prepared_request.url, headers=prepared_request.headers, timeout=30)
    LOGGER.info(response.json())
    return response


def _test_auth(region, parallelcluster_user_role, parallelcluster_api_url):
    logging.info("Testing API auth")
    with sts_credential_provider(region, parallelcluster_user_role):
        assert_that(_call_list_clusters(region, parallelcluster_api_url).status_code).is_equal_to(requests.codes.ok)
    assert_that(_call_list_clusters(region, parallelcluster_api_url).status_code).is_equal_to(requests.codes.forbidden)
    assert_that(_call_list_clusters(region, parallelcluster_api_url, enable_sigv4=False).status_code).is_equal_to(
        requests.codes.forbidden
    )


def _parse_api_url(url):
    """Parse an APIGateway URL

    :param url: the APIGateway API URL
    :return: a dictionary with two keys, ApiId and VpcEndpointId
    """
    url_pattern = "https://(?P<ApiId>[^-.]+)(-(?P<VpcEndpointId>[^.]+))?\\..+"
    return re.match(url_pattern, url).groupdict()


def _test_api_deletion(api_stack):
    logging.info("Testing API deletion")

    cfn = boto3.client("cloudformation")
    cfn.delete_stack(StackName=api_stack.name)
    cfn.get_waiter("stack_delete_complete").wait(StackName=api_stack.name)


@retry(
    retry_on_result=lambda result: result["state"]["status"] not in {"AVAILABLE", "CANCELLED", "FAILED", "DELETED"},
    wait_fixed=seconds(10),
    stop_max_delay=minutes(15),
)
def _wait_for_image_build(image_builder_pipeline):
    image_builder = boto3.client("imagebuilder")
    return image_builder.list_image_pipeline_images(
        imagePipelineArn=image_builder_pipeline,
    )[
        "imageSummaryList"
    ][0]
