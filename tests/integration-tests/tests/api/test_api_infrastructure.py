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
from assertpy import assert_that, soft_assertions

LOGGER = logging.getLogger(__name__)


@pytest.mark.skip_regions(["cn-north-1", "cn-northwest-1"])  # No Lambda container support in China regions
def test_api_infrastructure_with_default_parameters(region, api_server_factory):
    """Test that creating the API Infrastructure stack with the defaults correctly sets up the Lambda and APIGateway API

    :param region: the region where the stack is run
    :api_server_factory: factory for deploying API servers on-demand to each region
    """
    stack = api_server_factory(region)

    lambda_client = boto3.client("lambda", region_name=region)
    apigateway_client = boto3.client("apigateway", region_name=region)

    parallelcluster_lambda_name = stack.cfn_resources["ParallelClusterFunction"]
    parallelcluster_lambda_arn = stack.cfn_outputs["ParallelClusterLambdaArn"]
    parallelcluster_api_copied_image_uri = stack.cfn_outputs["UriOfCopyOfPublicEcrImage"]

    parallelcluster_api_id = stack.cfn_resources["ApiGatewayApiWithoutCustomDomain"]
    parallelcluster_api_url = stack.cfn_outputs["ParallelClusterApiInvokeUrl"]

    with soft_assertions():
        _assert_parallelcluster_lambda(
            client=lambda_client,
            lambda_name=parallelcluster_lambda_name,
            lambda_arn=parallelcluster_lambda_arn,
            lambda_image_uri=parallelcluster_api_copied_image_uri,
        )

        _assert_parallelcluster_api(
            client=apigateway_client, api_id=parallelcluster_api_id, api_url=parallelcluster_api_url
        )

        _assert_can_call_list_clusters(region=region, api_url=parallelcluster_api_url)


def _assert_parallelcluster_lambda(client, lambda_name, lambda_arn, lambda_image_uri):
    """Check that the ParallelCluster Lambda is correctly configured

    :param client: the Lambda client
    :param lambda_name: the name of the ParallelCluster Lambda
    :param lambda_arn: the ARN of the ParallelCluster Lambda
    :param lambda_image_uri: the URI of the local copy of the ParallelCluster Lambda Docker image
    """
    lambda_resource = client.get_function(FunctionName=lambda_name)
    lambda_configuration = lambda_resource["Configuration"]
    assert_that(lambda_configuration["FunctionArn"]).is_equal_to(lambda_arn)
    assert_that(lambda_configuration["Timeout"]).is_equal_to(30)
    assert_that(lambda_configuration["MemorySize"]).is_equal_to(512)
    assert_that(lambda_configuration["TracingConfig"]["Mode"]).is_equal_to("Active")
    assert_that(lambda_resource["Tags"]).contains("parallelcluster:version")
    assert_that(lambda_resource["Code"]["ImageUri"]).is_equal_to(lambda_image_uri)


def _assert_parallelcluster_api(client, api_id, api_url):
    """Check that the ParallelCluster APIGateway API is correctly configured

    :param client: the APIGateway client
    :param api_id: the id of the ParallelCluster API
    :param api_url: the URL of the ParallelCluster API
    """
    apigateway_resource = client.get_rest_api(restApiId=api_id)
    assert_that(apigateway_resource["endpointConfiguration"]["types"]).is_equal_to(["REGIONAL"])

    api_id_from_url = _parse_api_url(api_url)["ApiId"]
    assert_that(api_url).ends_with("/prod")
    assert_that(api_id_from_url).is_equal_to(api_id)

    stage_resource = client.get_stage(restApiId=api_id, stageName="prod")
    assert_that(stage_resource["tags"]).contains("parallelcluster:version")
    assert_that(stage_resource["tracingEnabled"]).is_true()


def _assert_can_call_list_clusters(region, api_url):
    """Executed a SigV4 signed request to the ListClusters API

    :param region: the region where to execute the request
    :param api_url: the APIGateway API invoke url
    """
    session = botocore.session.Session()
    request = botocore.awsrequest.AWSRequest(method="GET", url="{}/v3/clusters".format(api_url))
    botocore.auth.SigV4Auth(session.get_credentials(), "execute-api", region).add_auth(request)
    prepared_request = request.prepare()
    response = requests.get(prepared_request.url, headers=prepared_request.headers, timeout=10)
    LOGGER.info(response.json())
    assert_that(response.status_code).is_equal_to(requests.codes.ok)


def _parse_api_url(url):
    """Parse an APIGateway URL

    :param url: the APIGateway API URL
    :return: a dictionary with two keys, ApiId and VpcEndpointId
    """
    url_pattern = "https://(?P<ApiId>[^-.]+)(-(?P<VpcEndpointId>[^.]+))?\\..+"
    return re.match(url_pattern, url).groupdict()
