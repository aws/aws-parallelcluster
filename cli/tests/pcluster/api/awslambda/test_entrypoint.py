#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import json

import pytest
from assertpy import assert_that

from pcluster.api.models import ListClustersResponseContent


@pytest.fixture(autouse=True)
def set_lambda_env(set_env):
    set_env("POWERTOOLS_TRACE_DISABLED", "1")
    # Pytest Live Log feature duplicates emitted log messages in order to style log statements according to their
    # levels, for this to work use POWERTOOLS_LOG_DEDUPLICATION_DISABLED env var.
    set_env("POWERTOOLS_LOG_DEDUPLICATION_DISABLED", "1")
    set_env("AWS_REGION", "eu-west-1")


@pytest.fixture
def apigw_event():
    return {
        "resource": "/v3/clusters",
        "path": "/v3/clusters",
        "httpMethod": "GET",
        "headers": None,
        "multiValueHeaders": None,
        "queryStringParameters": None,
        "multiValueQueryStringParameters": None,
        "pathParameters": None,
        "stageVariables": None,
        "requestContext": {
            "resourceId": "123456",
            "resourcePath": "/v3/clusters",
            "operationName": "ListClusters",
            "httpMethod": "GET",
            "extendedRequestId": "AAAA1Fy6DoEFskw=",
            "requestTime": "04/Oct/2021:10:46:09 +0000",
            "path": "/v3/clusters",
            "accountId": "1234567890",
            "protocol": "HTTP/1.1",
            "stage": "test-invoke-stage",
            "domainPrefix": "testPrefix",
            "requestTimeEpoch": 1633344369951,
            "requestId": "6dc86175-6615-4707-9690-8d7bd38af8aa",
            "identity": {
                "cognitoIdentityPoolId": None,
                "cognitoIdentityId": None,
                "apiKey": "test-invoke-api-key",
                "principalOrgId": None,
                "cognitoAuthenticationType": None,
                "userArn": "arn:aws:sts::1234567890:assumed-role/aaa/aaaa",
                "apiKeyId": "test-invoke-api-key-id",
                "userAgent": "aws-internal/3 aws-sdk-java/1.12.71 Linux/5.4.134-73.228.amzn2int.x86_64",
                "accountId": "1234567890",
                "caller": "xxx:aaaa",
                "sourceIp": "test-invoke-source-ip",
                "accessKey": "xxx",
                "cognitoAuthenticationProvider": None,
                "user": "xxx:aaaa",
            },
            "domainName": "testPrefix.testDomainName",
            "apiId": "aaaaaaa",
        },
        "body": None,
        "isBase64Encoded": False,
    }


@pytest.fixture
def lambda_context():
    class LambdaContext:
        function_name: str = "test"
        memory_limit_in_mb: int = 128
        invoked_function_arn: str = "arn:aws:lambda:eu-west-1:809313241:function:test"
        aws_request_id: str = "52fdfc07-2182-154f-163f-5f0f9a621d72"

    return LambdaContext()


def test_lambda_handler(apigw_event, lambda_context, mocker):
    from pcluster.api.awslambda import entrypoint

    mocker.patch(
        "pcluster.api.controllers.cluster_operations_controller.list_clusters",
        return_value=ListClustersResponseContent(clusters=[]),
    )

    ret = entrypoint.lambda_handler(apigw_event, lambda_context)
    data = json.loads(ret["body"])

    assert_that(ret["statusCode"]).is_equal_to(200)
    assert_that(data).contains_key("clusters")
