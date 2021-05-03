#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import json
from datetime import datetime

import pytest
from assertpy import assert_that, soft_assertions

from pcluster.api.models import CloudFormationStatus
from pcluster.api.models.cluster_status import ClusterStatus
from pcluster.api.models.validation_level import ValidationLevel
from pcluster.aws.common import AWSClientError


class TestCreateCluster:
    def test_create_cluster(self, client):
        create_cluster_request_content = {
            "name": "clustername",
            "region": "eu-west-1",
            "clusterConfiguration": "clusterConfiguration",
        }
        query_string = [
            ("suppressValidators", ["suppress_validators_example"]),
            ("validationFailureLevel", ValidationLevel.INFO),
            ("dryrun", True),
            ("rollbackOnFailure", True),
            ("clientToken", "client_token_example"),
        ]
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        response = client.open(
            "/v3/clusters",
            method="POST",
            headers=headers,
            data=json.dumps(create_cluster_request_content),
            content_type="application/json",
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(200)


class TestDeleteCluster:
    def test_delete_cluster(self, client):
        query_string = [("region", "eu-west-1"), ("retainLogs", True), ("clientToken", "client_token_example")]
        headers = {
            "Accept": "application/json",
        }
        response = client.open(
            "/v3/clusters/{cluster_name}".format(cluster_name="clustername"),
            method="DELETE",
            headers=headers,
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(200)


class TestDescribeCluster:
    def test_describe_cluster(self, client):
        query_string = [("region", "eu-west-1")]
        headers = {
            "Accept": "application/json",
        }
        response = client.open(
            "/v3/clusters/{cluster_name}".format(cluster_name="clustername"),
            method="GET",
            headers=headers,
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(200)


class TestListClusters:
    url = "/v3/clusters"
    method = "GET"

    @pytest.mark.parametrize(
        "region, next_token, cluster_status, existing_stacks, expected_response",
        [
            (
                "us-east-1",
                None,
                [],
                [
                    {
                        "StackName": "name1",
                        "StackId": "arn:id",
                        "CreationTime": datetime(2021, 4, 30),
                        "StackStatus": CloudFormationStatus.CREATE_IN_PROGRESS,
                        "Tags": [{"Key": "Version", "Value": "3.0.0"}],
                    },
                    {
                        "StackName": "name2",
                        "StackId": "arn:id2",
                        "CreationTime": datetime(2021, 5, 30),
                        "StackStatus": CloudFormationStatus.UPDATE_ROLLBACK_COMPLETE,
                        "Tags": [{"Key": "Version", "Value": "3.1.0"}],
                    },
                ],
                {
                    "items": [
                        {
                            "cloudformationStackArn": "arn:id",
                            "cloudformationStackStatus": CloudFormationStatus.CREATE_IN_PROGRESS,
                            "clusterName": "name1",
                            "clusterStatus": ClusterStatus.CREATE_IN_PROGRESS,
                            "region": "us-east-1",
                            "version": "3.0.0",
                        },
                        {
                            "cloudformationStackArn": "arn:id2",
                            "cloudformationStackStatus": CloudFormationStatus.UPDATE_ROLLBACK_COMPLETE,
                            "clusterName": "name2",
                            "clusterStatus": ClusterStatus.UPDATE_FAILED,
                            "region": "us-east-1",
                            "version": "3.1.0",
                        },
                    ]
                },
            ),
            (
                "eu-west-1",
                None,
                [ClusterStatus.CREATE_IN_PROGRESS, ClusterStatus.UPDATE_FAILED],
                [
                    {
                        "StackName": "name1",
                        "StackId": "arn:id",
                        "CreationTime": datetime(2021, 4, 30),
                        "StackStatus": CloudFormationStatus.CREATE_IN_PROGRESS,
                        "Tags": [{"Key": "Version", "Value": "3.0.0"}],
                    },
                    {
                        "StackName": "name2",
                        "StackId": "arn:id2",
                        "CreationTime": datetime(2021, 5, 30),
                        "StackStatus": CloudFormationStatus.UPDATE_ROLLBACK_COMPLETE,
                        "Tags": [{"Key": "Version", "Value": "3.1.0"}],
                    },
                    {
                        "StackName": "name3",
                        "StackId": "arn:id3",
                        "CreationTime": datetime(2021, 5, 30),
                        "StackStatus": CloudFormationStatus.DELETE_IN_PROGRESS,
                        "Tags": [{"Key": "Version", "Value": "3.1.0"}],
                    },
                ],
                {
                    "items": [
                        {
                            "cloudformationStackArn": "arn:id",
                            "cloudformationStackStatus": CloudFormationStatus.CREATE_IN_PROGRESS,
                            "clusterName": "name1",
                            "clusterStatus": ClusterStatus.CREATE_IN_PROGRESS,
                            "region": "eu-west-1",
                            "version": "3.0.0",
                        },
                        {
                            "cloudformationStackArn": "arn:id2",
                            "cloudformationStackStatus": CloudFormationStatus.UPDATE_ROLLBACK_COMPLETE,
                            "clusterName": "name2",
                            "clusterStatus": ClusterStatus.UPDATE_FAILED,
                            "region": "eu-west-1",
                            "version": "3.1.0",
                        },
                    ]
                },
            ),
            (
                "eu-west-1",
                "token",
                [ClusterStatus.CREATE_IN_PROGRESS],
                [
                    {
                        "StackName": "name1",
                        "StackId": "arn:id",
                        "CreationTime": datetime(2021, 4, 30),
                        "StackStatus": CloudFormationStatus.CREATE_IN_PROGRESS,
                        "Tags": [{"Key": "Version", "Value": "3.0.0"}],
                    },
                    {
                        "StackName": "name2",
                        "StackId": "arn:id2",
                        "CreationTime": datetime(2021, 5, 30),
                        "StackStatus": CloudFormationStatus.UPDATE_ROLLBACK_COMPLETE,
                        "Tags": [{"Key": "Version", "Value": "3.1.0"}],
                    },
                ],
                {
                    "items": [
                        {
                            "cloudformationStackArn": "arn:id",
                            "cloudformationStackStatus": CloudFormationStatus.CREATE_IN_PROGRESS,
                            "clusterName": "name1",
                            "clusterStatus": ClusterStatus.CREATE_IN_PROGRESS,
                            "region": "eu-west-1",
                            "version": "3.0.0",
                        },
                    ],
                    "nextToken": "token",
                },
            ),
        ],
        ids=["all", "filter_by_status", "next_token"],
    )
    def test_successful_request(
        self, mocker, client, region, next_token, cluster_status, existing_stacks, expected_response
    ):
        mocker.patch("pcluster.aws.cfn.CfnClient.list_pcluster_stacks", return_value=(existing_stacks, next_token))

        query_string = [
            ("region", region),
            ("nextToken", next_token),
        ]
        query_string.extend([("clusterStatus", status) for status in cluster_status])
        headers = {
            "Accept": "application/json",
        }
        response = client.open(self.url, method=self.method, headers=headers, query_string=query_string)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize(
        "region, next_token, cluster_status, expected_response",
        [
            (
                "us-east-",
                None,
                None,
                {"message": "Bad Request: invalid or unsupported region 'us-east-'"},
            ),
            (
                None,
                None,
                None,
                {"message": "Bad Request: region needs to be set"},
            ),
            (
                "us-east-1",
                None,
                "invalid",
                {
                    "message": "Bad Request: 'invalid' is not one of ['CREATE_IN_PROGRESS', 'CREATE_FAILED', "
                    "'CREATE_COMPLETE', 'DELETE_IN_PROGRESS', 'DELETE_FAILED', 'DELETE_COMPLETE', "
                    "'UPDATE_IN_PROGRESS', 'UPDATE_COMPLETE', 'UPDATE_FAILED']"
                },
            ),
        ],
        ids=["bad_region", "unset_region", "invalid_status_filter"],
    )
    def test_malformed_request(self, client, region, next_token, cluster_status, expected_response):
        query_string = [
            ("region", region),
            ("nextToken", next_token),
            ("clusterStatus", cluster_status),
        ]
        headers = {
            "Accept": "application/json",
        }
        response = client.open(self.url, method=self.method, headers=headers, query_string=query_string)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).is_equal_to(expected_response)

    def test_aws_api_errors(self, client, mocker):
        # Generic AWSClientError error handling is tested in test_flask_app
        error = (
            AWSClientError(
                "list_pcluster_stacks", "Testing validation error", AWSClientError.ErrorCode.VALIDATION_ERROR.value
            ),
        )
        mocker.patch("pcluster.aws.cfn.CfnClient.list_pcluster_stacks", side_effect=error)

        query_string = [
            ("region", "us-east-1"),
        ]
        headers = {
            "Accept": "application/json",
        }
        response = client.open(self.url, method=self.method, headers=headers, query_string=query_string)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).is_equal_to({"message": "Bad Request: Testing validation error"})


class TestUpdateCluster:
    def test_update_cluster(self, client):
        update_cluster_request_content = {"clusterConfiguration": "clusterConfiguration"}
        query_string = [
            ("suppressValidators", ["suppress_validators_example"]),
            ["validationFailureLevel", ValidationLevel.INFO],
            ("region", "eu-west-1"),
            ("dryrun", True),
            ("forceUpdate", True),
            ("clientToken", "client_token_example"),
        ]
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        response = client.open(
            "/v3/clusters/{cluster_name}".format(cluster_name="clustername"),
            method="PUT",
            headers=headers,
            data=json.dumps(update_cluster_request_content),
            content_type="application/json",
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(200)
