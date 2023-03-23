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
import re

import boto3
import botocore
import pytest
import requests
from assertpy import assert_that
from cfn_stacks_factory import CfnStack, CfnStacksFactory
from framework.credential_providers import sts_credential_provider
from retrying import retry
from time_utils import minutes, seconds
from utils import generate_stack_name

from tests.common.utils import get_installed_parallelcluster_version

LOGGER = logging.getLogger(__name__)


@pytest.fixture()
def api_with_default_settings(
    api_infrastructure_s3_uri, api_definition_s3_uri, policies_uri, request, region, resource_bucket
):
    factory = CfnStacksFactory(request.config.getoption("credential"))

    params = []
    if api_definition_s3_uri:
        params.append({"ParameterKey": "ApiDefinitionS3Uri", "ParameterValue": api_definition_s3_uri})
    if policies_uri:
        params.append({"ParameterKey": "PoliciesTemplateUri", "ParameterValue": policies_uri})
    if resource_bucket:
        params.append({"ParameterKey": "CustomBucket", "ParameterValue": resource_bucket})

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
    try:
        factory.create_stack(stack)
        yield stack
    finally:
        factory.delete_all_stacks()


def test_api_infrastructure_with_default_parameters(region, api_with_default_settings):
    """Test that creating the API Infrastructure stack with the defaults correctly sets up the Lambda and APIGateway API

    :param region: the region where the stack is run
    :api_server_factory: factory for deploying API servers on-demand to each region
    """
    parallelcluster_lambda_name = api_with_default_settings.cfn_resources["ParallelClusterFunction"]
    parallelcluster_lambda_arn = api_with_default_settings.cfn_outputs["ParallelClusterLambdaArn"]

    parallelcluster_api_id = api_with_default_settings.cfn_resources["ApiGatewayApiWithoutCustomDomain"]
    parallelcluster_api_url = api_with_default_settings.cfn_outputs["ParallelClusterApiInvokeUrl"]
    parallelcluster_user_role = api_with_default_settings.cfn_outputs["ParallelClusterApiUserRole"]

    _assert_parallelcluster_lambda(lambda_name=parallelcluster_lambda_name, lambda_arn=parallelcluster_lambda_arn)
    _assert_parallelcluster_api(api_id=parallelcluster_api_id, api_url=parallelcluster_api_url)
    _test_auth(region, parallelcluster_user_role, parallelcluster_api_url)
    _test_api_deletion(api_with_default_settings)


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
