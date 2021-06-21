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

from pcluster.api.controllers.common import get_validator_suppressors
from pcluster.api.models import CloudFormationStatus
from pcluster.api.models.cluster_status import ClusterStatus
from pcluster.api.models.validation_level import ValidationLevel
from pcluster.aws.common import AWSClientError, StackNotFoundError
from pcluster.cli_commands.compute_fleet_status_manager import ComputeFleetStatus
from pcluster.config.common import AllValidatorsSuppressor, TypeMatchValidatorsSuppressor
from pcluster.models.cluster import (
    BadRequestClusterActionError,
    ClusterActionError,
    ConflictClusterActionError,
    LimitExceededClusterActionError,
)
from pcluster.validators.common import FailureLevel, ValidationResult


def cfn_describe_stack_mock_response(edits=None):
    stack_data = {
        "StackId": "arn:aws:cloudformation:us-east-1:123:stack/pcluster3-2/123",
        "StackName": "pcluster3-2",
        "CreationTime": datetime(2021, 4, 30),
        "StackStatus": "CREATE_COMPLETE",
        "Outputs": [],
        "Tags": [
            {"Key": "parallelcluster:version", "Value": "3.0.0"},
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
    url = "/v3/clusters"
    method = "POST"

    BASE64_ENCODED_CONFIG = "SW1hZ2U6CiAgT3M6IGFsaW51eDIKSGVhZE5vZGU6CiAgSW5zdGFuY2VUeXBlOiB0Mi5taWNybw=="

    def _send_test_request(
        self,
        client,
        create_cluster_request_content=None,
        suppress_validators=None,
        validation_failure_level=None,
        dryrun=None,
        rollback_on_failure=None,
        client_token=None,
    ):
        query_string = []
        if suppress_validators:
            query_string.extend([("suppressValidators", validator) for validator in suppress_validators])
        if validation_failure_level:
            query_string.append(("validationFailureLevel", validation_failure_level))
        if dryrun is not None:
            query_string.append(("dryrun", dryrun))
        if rollback_on_failure is not None:
            query_string.append(("rollbackOnFailure", rollback_on_failure))
        if client_token:
            query_string.append(("clientToken", client_token))
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        return client.open(
            self.url,
            method=self.method,
            headers=headers,
            query_string=query_string,
            data=json.dumps(create_cluster_request_content) if create_cluster_request_content else None,
        )

    @pytest.mark.parametrize(
        "create_cluster_request_content, suppress_validators, validation_failure_level, rollback_on_failure",
        [
            (
                {
                    "region": "us-east-1",
                    "name": "cluster",
                    "clusterConfiguration": BASE64_ENCODED_CONFIG,
                },
                None,
                None,
                None,
            ),
            (
                {
                    "region": "us-east-1",
                    "name": "cluster",
                    "clusterConfiguration": BASE64_ENCODED_CONFIG,
                },
                ["type:type1", "type:type2"],
                ValidationLevel.WARNING,
                False,
            ),
        ],
        ids=["required", "all"],
    )
    def test_successful_create_request(
        self,
        client,
        mocker,
        create_cluster_request_content,
        suppress_validators,
        validation_failure_level,
        rollback_on_failure,
    ):
        cluster_create_mock = mocker.patch(
            "pcluster.models.cluster.Cluster.create",
            auto_spec=True,
            return_value=("id", [ValidationResult("message", FailureLevel.WARNING, "type")]),
        )

        response = self._send_test_request(
            client,
            create_cluster_request_content,
            suppress_validators,
            validation_failure_level,
            False,
            rollback_on_failure,
        )

        expected_response = {
            "cluster": {
                "cloudformationStackArn": "id",
                "cloudformationStackStatus": "CREATE_IN_PROGRESS",
                "clusterName": create_cluster_request_content["name"],
                "clusterStatus": "CREATE_IN_PROGRESS",
                "region": create_cluster_request_content["region"],
                "version": "3.0.0",
            },
            "validationMessages": [{"level": "WARNING", "message": "message", "type": "type"}],
        }

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)
        cluster_create_mock.assert_called_with(
            disable_rollback=not (rollback_on_failure or True),
            validator_suppressors=mocker.ANY,
            validation_failure_level=FailureLevel[validation_failure_level or ValidationLevel.ERROR],
        )
        cluster_create_mock.assert_called_once()
        if suppress_validators:
            _, kwargs = cluster_create_mock.call_args
            assert_that(kwargs["validator_suppressors"].pop()._validators_to_suppress).is_equal_to({"type1", "type2"})

    def test_dryrun(self, client, mocker):
        mocker.patch(
            "pcluster.models.cluster.Cluster.validate_create_request",
            auto_spec=True,
            return_value=([]),
        )

        create_cluster_request_content = {
            "region": "us-east-1",
            "name": "cluster",
            "clusterConfiguration": self.BASE64_ENCODED_CONFIG,
        }

        response = self._send_test_request(
            client,
            create_cluster_request_content=create_cluster_request_content,
            dryrun=True,
        )

        expected_response = {"message": "Request would have succeeded, but DryRun flag is set."}
        with soft_assertions():
            assert_that(response.status_code).is_equal_to(412)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize(
        "create_cluster_request_content, suppress_validators, validation_failure_level, dryrun, rollback_on_failure, "
        "client_token, expected_response",
        [
            (None, None, None, None, None, None, {"message": "Bad Request: request body is required"}),
            ({}, None, None, None, None, None, {"message": "Bad Request: request body is required"}),
            (
                {"region": "us-east-1", "name": "cluster"},
                None,
                None,
                None,
                None,
                None,
                {"message": "Bad Request: 'clusterConfiguration' is a required property"},
            ),
            (
                {"clusterConfiguration": "config", "name": "cluster", "region": "invalid"},
                None,
                None,
                None,
                None,
                None,
                {"message": "Bad Request: invalid or unsupported region 'invalid'"},
            ),
            (
                {"clusterConfiguration": "config", "region": "us-east-1"},
                None,
                None,
                None,
                None,
                None,
                {"message": "Bad Request: 'name' is a required property"},
            ),
            (
                {"clusterConfiguration": "config", "name": "cluster", "region": "us-east-1"},
                ["ALL", "ALLL"],
                None,
                None,
                None,
                None,
                {"message": "Bad Request: 'ALLL' does not match '^(ALL|type:[A-Za-z0-9]+)$'"},
            ),
            (
                {"clusterConfiguration": "config", "name": "cluster", "region": "us-east-1"},
                ["type:"],
                None,
                None,
                None,
                None,
                {"message": "Bad Request: 'type:' does not match '^(ALL|type:[A-Za-z0-9]+)$'"},
            ),
            (
                {"clusterConfiguration": "config", "name": "cluster", "region": "us-east-1"},
                None,
                "CRITICAL",
                None,
                None,
                None,
                {"message": "Bad Request: 'CRITICAL' is not one of ['INFO', 'WARNING', 'ERROR']"},
            ),
            (
                {"clusterConfiguration": "config", "name": "cluster", "region": "us-east-1"},
                None,
                None,
                "NO",
                None,
                None,
                {"message": "Bad Request: Wrong type, expected 'boolean' for query parameter 'dryrun'"},
            ),
            (
                {"clusterConfiguration": "config", "name": "cluster", "region": "us-east-1"},
                None,
                None,
                None,
                "NO",
                None,
                {"message": "Bad Request: Wrong type, expected 'boolean' for query parameter 'rollbackOnFailure'"},
            ),
            (
                {"clusterConfiguration": "config", "name": "cluster", "region": "us-east-1"},
                None,
                None,
                None,
                None,
                None,
                {"message": "Bad Request: invalid configuration. " "Please make sure the string is base64 encoded."},
            ),
            # (
            #     {"clusterConfiguration": "aW52YWxpZA==", "name": "cluster", "region": "us-east-1"},
            #     None,
            #     None,
            #     None,
            #     None,
            #     None,
            #     {"message": "Bad Request: configuration must be a valid base64-encoded YAML document"},
            # ),
            (
                {
                    "clusterConfiguration": "SW1hZ2U6CiAgSW52YWxpZEtleTogdGVzdA==",
                    "name": "cluster",
                    "region": "us-east-1",
                },
                None,
                None,
                None,
                None,
                None,
                {
                    "configurationValidationErrors": [
                        {
                            "level": "ERROR",
                            "message": "[('HeadNode', ['Missing data for required field.']), "
                            "('Image', {'Os': ['Missing data for required field.'], 'InvalidKey': "
                            "['Unknown field.']}), ('Scheduling', ['Missing data for required field.'])]",
                            "type": "ConfigSchemaValidator",
                        }
                    ],
                    "message": "Invalid cluster configuration",
                },
            ),
            (
                {"clusterConfiguration": "", "name": "cluster", "region": "us-east-1"},
                None,
                None,
                None,
                None,
                None,
                {"message": "Bad Request: configuration is required and cannot be empty"},
            ),
            (
                {"clusterConfiguration": "", "name": "cluster", "region": "us-east-1"},
                None,
                None,
                None,
                None,
                "token",
                {"message": "Bad Request: clientToken is currently not supported for this operation"},
            ),
        ],
        ids=[
            "no_body",
            "empty_body",
            "missing_config",
            "invalid_region",
            "missing_name",
            "invalid_suppress_validators",
            "invalid_suppress_validators",
            "invalid_failure_level",
            "invalid_dryrun",
            "invalid_rollback",
            "invalid_config_encoding",
            # "invalid_config_format",
            "invalid_config_schema",
            "empty_config",
            "client_token",
        ],
    )
    def test_malformed_request(
        self,
        client,
        mocker,
        create_cluster_request_content,
        suppress_validators,
        validation_failure_level,
        dryrun,
        rollback_on_failure,
        client_token,
        expected_response,
    ):
        mocker.patch("pcluster.aws.cfn.CfnClient.stack_exists", return_value=False)

        response = self._send_test_request(
            client,
            create_cluster_request_content,
            suppress_validators,
            validation_failure_level,
            dryrun,
            rollback_on_failure,
            client_token,
        )

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize(
        "error_type, error_code",
        [
            (LimitExceededClusterActionError, 429),
            (BadRequestClusterActionError, 400),
            (ConflictClusterActionError, 409),
            (ClusterActionError, 500),
        ],
    )
    def test_cluster_action_error(self, client, mocker, error_type, error_code):
        mocker.patch(
            "pcluster.models.cluster.Cluster.create",
            auto_spec=True,
            side_effect=error_type("error message"),
        )

        response = self._send_test_request(
            client,
            create_cluster_request_content={
                "region": "us-east-1",
                "name": "clustername",
                "clusterConfiguration": self.BASE64_ENCODED_CONFIG,
            },
        )

        expected_response = {"message": "error message"}
        if error_type == BadRequestClusterActionError:
            expected_response["message"] = "Bad Request: " + expected_response["message"]

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(error_code)
            assert_that(response.get_json()).is_equal_to(expected_response)


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
                        {"key": "parallelcluster:version", "value": "3.0.0"},
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
                        {"key": "parallelcluster:version", "value": "3.0.0"},
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
                        {"key": "parallelcluster:version", "value": "3.0.0"},
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
                        {"key": "parallelcluster:version", "value": "3.0.0"},
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
                        {"key": "parallelcluster:version", "value": "3.0.0"},
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
            return_value=cfn_describe_stack_mock_response(
                {"Tags": [{"Key": "parallelcluster:version", "Value": "2.0.0"}]}
            ),
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
                        "Tags": [{"Key": "parallelcluster:version", "Value": "3.0.0"}],
                    },
                    {
                        "StackName": "name2",
                        "StackId": "arn:id2",
                        "CreationTime": datetime(2021, 5, 30),
                        "StackStatus": CloudFormationStatus.UPDATE_ROLLBACK_COMPLETE,
                        "Tags": [{"Key": "parallelcluster:version", "Value": "3.1.0"}],
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
                        "Tags": [{"Key": "parallelcluster:version", "Value": "3.0.0"}],
                    },
                    {
                        "StackName": "name2",
                        "StackId": "arn:id2",
                        "CreationTime": datetime(2021, 5, 30),
                        "StackStatus": CloudFormationStatus.UPDATE_ROLLBACK_COMPLETE,
                        "Tags": [{"Key": "parallelcluster:version", "Value": "3.1.0"}],
                    },
                    {
                        "StackName": "name3",
                        "StackId": "arn:id3",
                        "CreationTime": datetime(2021, 5, 30),
                        "StackStatus": CloudFormationStatus.DELETE_IN_PROGRESS,
                        "Tags": [{"Key": "parallelcluster:version", "Value": "3.1.0"}],
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
                        "Tags": [{"Key": "parallelcluster:version", "Value": "3.0.0"}],
                    },
                    {
                        "StackName": "name2",
                        "StackId": "arn:id2",
                        "CreationTime": datetime(2021, 5, 30),
                        "StackStatus": CloudFormationStatus.UPDATE_ROLLBACK_COMPLETE,
                        "Tags": [{"Key": "parallelcluster:version", "Value": "3.1.0"}],
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
            ("suppressValidators", "ALL"),
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


@pytest.mark.parametrize(
    "suppress_validators_list, expected_suppressors",
    [
        (None, set()),
        ([], set()),
        (["ALL"], {AllValidatorsSuppressor()}),
        (["type:type1", "type:type2"], {TypeMatchValidatorsSuppressor({"type1", "type2"})}),
        (["type:type1", "ALL"], {AllValidatorsSuppressor(), TypeMatchValidatorsSuppressor({"type1"})}),
    ],
)
def test_get_validator_suppressors(suppress_validators_list, expected_suppressors):
    result = get_validator_suppressors(suppress_validators_list)
    assert_that(result).is_equal_to(expected_suppressors)
