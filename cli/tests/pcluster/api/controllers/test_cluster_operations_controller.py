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
from pcluster.aws.common import AWSClientError, StackNotFoundError
from pcluster.cli_commands.compute_fleet_status_manager import ComputeFleetStatus
from pcluster.models.cluster import ClusterActionError


def cfn_describe_stack_mock_response(edits=None):
    stack_data = {
        "StackId": "arn:aws:cloudformation:us-east-1:123:stack/pcluster3-2/123",
        "StackName": "pcluster3-2",
        "CreationTime": datetime(2021, 4, 30),
        "StackStatus": "CREATE_COMPLETE",
        "Outputs": [],
        "Tags": [
            {"Key": "Version", "Value": "3.0.0"},
            {"Key": "parallelcluster:s3_bucket", "Value": "bucket_name"},
            {
                "Key": "parallelcluster:cluster_dir",
                "Value": "parallelcluster/3.0.0/clusters/pcluster3-2-smkloc964uzpm12m",
            },
        ],
    }
    if edits:
        stack_data.update(edits)
    return stack_data


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
    url = "/v3/clusters/{cluster_name}"
    method = "GET"

    def _send_test_request(self, client, cluster_name="clustername", region="us-east-1"):
        query_string = [
            ("region", region),
        ]
        headers = {
            "Accept": "application/json",
        }
        return client.open(
            self.url.format(cluster_name=cluster_name), method=self.method, headers=headers, query_string=query_string
        )

    @pytest.mark.parametrize(
        "cfn_stack_data, headnode_data, fail_on_bucket_check, expected_response",
        [
            (
                cfn_describe_stack_mock_response(),
                {
                    "InstanceId": "i-020c2ec1b6d550000",
                    "InstanceType": "t2.micro",
                    "LaunchTime": datetime(2021, 5, 10, 13, 55, 48),
                    "PrivateIpAddress": "192.168.61.109",
                    "PublicIpAddress": "34.251.236.164",
                    "State": {"Code": 16, "Name": "running"},
                },
                False,
                {
                    "cloudFormationStatus": "CREATE_COMPLETE",
                    "cloudformationStackArn": "arn:aws:cloudformation:us-east-1:123:stack/pcluster3-2/123",
                    "clusterConfiguration": {"s3Url": "presigned-url"},
                    "clusterName": "clustername",
                    "clusterStatus": "CREATE_COMPLETE",
                    "computeFleetStatus": "RUNNING",
                    "creationTime": "2021-04-30 00:00:00",
                    "lastUpdatedTime": "2021-04-30 00:00:00",
                    "region": "us-east-1",
                    "tags": [
                        {"key": "Version", "value": "3.0.0"},
                        {"key": "parallelcluster:s3_bucket", "value": "bucket_name"},
                        {
                            "key": "parallelcluster:cluster_dir",
                            "value": "parallelcluster/3.0.0/clusters/pcluster3-2-smkloc964uzpm12m",
                        },
                    ],
                    "version": "3.0.0",
                    "headnode": {
                        "instanceId": "i-020c2ec1b6d550000",
                        "instanceType": "t2.micro",
                        "launchTime": "2021-05-10T13:55:48Z",
                        "privateIpAddress": "192.168.61.109",
                        "publicIpAddress": "34.251.236.164",
                        "state": "running",
                    },
                },
            ),
            (
                cfn_describe_stack_mock_response(),
                None,
                False,
                {
                    "cloudFormationStatus": "CREATE_COMPLETE",
                    "cloudformationStackArn": "arn:aws:cloudformation:us-east-1:123:stack/pcluster3-2/123",
                    "clusterConfiguration": {"s3Url": "presigned-url"},
                    "clusterName": "clustername",
                    "clusterStatus": "CREATE_COMPLETE",
                    "computeFleetStatus": "RUNNING",
                    "creationTime": "2021-04-30 00:00:00",
                    "lastUpdatedTime": "2021-04-30 00:00:00",
                    "region": "us-east-1",
                    "tags": [
                        {"key": "Version", "value": "3.0.0"},
                        {"key": "parallelcluster:s3_bucket", "value": "bucket_name"},
                        {
                            "key": "parallelcluster:cluster_dir",
                            "value": "parallelcluster/3.0.0/clusters/pcluster3-2-smkloc964uzpm12m",
                        },
                    ],
                    "version": "3.0.0",
                },
            ),
            (
                cfn_describe_stack_mock_response(),
                None,
                True,
                {
                    "cloudFormationStatus": "CREATE_COMPLETE",
                    "cloudformationStackArn": "arn:aws:cloudformation:us-east-1:123:stack/pcluster3-2/123",
                    "clusterConfiguration": {"s3Url": "NOT_AVAILABLE"},
                    "clusterName": "clustername",
                    "clusterStatus": "CREATE_COMPLETE",
                    "computeFleetStatus": "RUNNING",
                    "creationTime": "2021-04-30 00:00:00",
                    "lastUpdatedTime": "2021-04-30 00:00:00",
                    "region": "us-east-1",
                    "tags": [
                        {"key": "Version", "value": "3.0.0"},
                        {"key": "parallelcluster:s3_bucket", "value": "bucket_name"},
                        {
                            "key": "parallelcluster:cluster_dir",
                            "value": "parallelcluster/3.0.0/clusters/pcluster3-2-smkloc964uzpm12m",
                        },
                    ],
                    "version": "3.0.0",
                },
            ),
            (
                cfn_describe_stack_mock_response(
                    {"LastUpdatedTime": datetime(2021, 5, 30), "StackStatus": "ROLLBACK_IN_PROGRESS"}
                ),
                None,
                False,
                {
                    "cloudFormationStatus": "ROLLBACK_IN_PROGRESS",
                    "cloudformationStackArn": "arn:aws:cloudformation:us-east-1:123:stack/pcluster3-2/123",
                    "clusterConfiguration": {"s3Url": "presigned-url"},
                    "clusterName": "clustername",
                    "clusterStatus": "CREATE_FAILED",
                    "computeFleetStatus": "RUNNING",
                    "creationTime": "2021-04-30 00:00:00",
                    "lastUpdatedTime": "2021-05-30 00:00:00",
                    "region": "us-east-1",
                    "tags": [
                        {"key": "Version", "value": "3.0.0"},
                        {"key": "parallelcluster:s3_bucket", "value": "bucket_name"},
                        {
                            "key": "parallelcluster:cluster_dir",
                            "value": "parallelcluster/3.0.0/clusters/pcluster3-2-smkloc964uzpm12m",
                        },
                    ],
                    "version": "3.0.0",
                },
            ),
            (
                cfn_describe_stack_mock_response(),
                {
                    "InstanceId": "i-020c2ec1b6d550000",
                    "InstanceType": "t2.micro",
                    "LaunchTime": datetime(2021, 5, 10, 13, 55, 48),
                    "PrivateIpAddress": "192.168.61.109",
                    "State": {"Code": 16, "Name": "running"},
                },
                False,
                {
                    "cloudFormationStatus": "CREATE_COMPLETE",
                    "cloudformationStackArn": "arn:aws:cloudformation:us-east-1:123:stack/pcluster3-2/123",
                    "clusterConfiguration": {"s3Url": "presigned-url"},
                    "clusterName": "clustername",
                    "clusterStatus": "CREATE_COMPLETE",
                    "computeFleetStatus": "RUNNING",
                    "creationTime": "2021-04-30 00:00:00",
                    "lastUpdatedTime": "2021-04-30 00:00:00",
                    "region": "us-east-1",
                    "tags": [
                        {"key": "Version", "value": "3.0.0"},
                        {"key": "parallelcluster:s3_bucket", "value": "bucket_name"},
                        {
                            "key": "parallelcluster:cluster_dir",
                            "value": "parallelcluster/3.0.0/clusters/pcluster3-2-smkloc964uzpm12m",
                        },
                    ],
                    "version": "3.0.0",
                    "headnode": {
                        "instanceId": "i-020c2ec1b6d550000",
                        "instanceType": "t2.micro",
                        "launchTime": "2021-05-10T13:55:48Z",
                        "privateIpAddress": "192.168.61.109",
                        "state": "running",
                    },
                },
            ),
        ],
        ids=["all", "no_head_node", "no_bucket", "mix", "no_head_public_ip"],
    )
    def test_successful_request(
        self, mocker, client, cfn_stack_data, headnode_data, fail_on_bucket_check, expected_response
    ):
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", return_value=cfn_stack_data)
        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.describe_instances", return_value=[headnode_data] if headnode_data else []
        )
        mocker.patch(
            "pcluster.models.cluster.Cluster.compute_fleet_status", new_callable=mocker.PropertyMock
        ).return_value = ComputeFleetStatus.RUNNING
        if not fail_on_bucket_check:
            mocker.patch(
                "pcluster.models.cluster.Cluster.config_presigned_url", new_callable=mocker.PropertyMock
            ).return_value = "presigned-url"
        else:
            mocker.patch(
                "pcluster.models.cluster.Cluster.config_presigned_url", new_callable=mocker.PropertyMock
            ).side_effect = ClusterActionError("failed")

        response = self._send_test_request(client)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize(
        "region, cluster_name, expected_response",
        [
            (
                "us-east-",
                "clustername",
                {"message": "Bad Request: invalid or unsupported region 'us-east-'"},
            ),
            (
                "us-east-1",
                "a",
                {"message": "Bad Request: 'a' is too short"},
            ),
            (
                "us-east-1",
                "aaaaa.aaa",
                {"message": "Bad Request: 'aaaaa.aaa' does not match '^[a-zA-Z][a-zA-Z0-9-]+$'"},
            ),
        ],
        ids=["bad_region", "short_cluster_name", "invalid_cluster_name"],
    )
    def test_malformed_request(self, client, region, cluster_name, expected_response):
        response = self._send_test_request(client, cluster_name=cluster_name, region=region)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).is_equal_to(expected_response)

    def test_cluster_not_found(self, client, mocker):
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", side_effect=StackNotFoundError("func", "stack"))

        response = self._send_test_request(client)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(404)
            assert_that(response.get_json()).is_equal_to(
                {
                    "message": "cluster clustername does not exist or belongs to an incompatible ParallelCluster major "
                    "version."
                }
            )

    def test_incompatible_version(self, client, mocker):
        mocker.patch(
            "pcluster.aws.cfn.CfnClient.describe_stack",
            return_value=cfn_describe_stack_mock_response({"Tags": [{"Key": "Version", "Value": "2.0.0"}]}),
        )

        response = self._send_test_request(client)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).is_equal_to(
                {
                    "message": "Bad Request: cluster clustername belongs to an incompatible ParallelCluster major"
                    " version."
                }
            )


class TestListClusters:
    url = "/v3/clusters"
    method = "GET"

    def _send_test_request(self, client, region="us-east-1", next_token=None, cluster_status_list=None):
        query_string = []
        if region:
            query_string.append(("region", region))
        if next_token:
            query_string.append(("nextToken", next_token))
        if cluster_status_list:
            query_string.extend([("clusterStatus", status) for status in cluster_status_list])
        headers = {
            "Accept": "application/json",
        }
        return client.open(self.url, method=self.method, headers=headers, query_string=query_string)

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

        response = self._send_test_request(client, region, next_token, cluster_status)

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
                "DELETE_COMPLETE",
                {
                    "message": "Bad Request: 'DELETE_COMPLETE' is not one of ['CREATE_IN_PROGRESS', 'CREATE_FAILED', "
                    "'CREATE_COMPLETE', 'DELETE_IN_PROGRESS', 'DELETE_FAILED', "
                    "'UPDATE_IN_PROGRESS', 'UPDATE_COMPLETE', 'UPDATE_FAILED']"
                },
            ),
        ],
        ids=["bad_region", "unset_region", "invalid_status_filter"],
    )
    def test_malformed_request(self, client, region, next_token, cluster_status, expected_response):
        response = self._send_test_request(client, region, next_token, [cluster_status])

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

        response = self._send_test_request(client, "us-east-1")

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
