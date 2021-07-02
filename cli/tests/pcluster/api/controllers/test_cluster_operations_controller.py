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
from pcluster.config.update_policy import UpdatePolicy
from pcluster.models.cluster import (
    BadRequestClusterActionError,
    ClusterActionError,
    ClusterUpdateError,
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
        "create_cluster_request_content, errors, suppress_validators, validation_failure_level, rollback_on_failure",
        [
            pytest.param(
                {
                    "region": "us-east-1",
                    "name": "cluster",
                    "clusterConfiguration": BASE64_ENCODED_CONFIG,
                },
                [ValidationResult("message", FailureLevel.WARNING, "type")],
                None,
                None,
                None,
                id="test with all errors",
            ),
            pytest.param(
                {
                    "region": "us-east-1",
                    "name": "cluster",
                    "clusterConfiguration": BASE64_ENCODED_CONFIG,
                },
                [ValidationResult("message", FailureLevel.WARNING, "type")],
                ["type:type1", "type:type2"],
                ValidationLevel.WARNING,
                False,
                id="test with filtered errors",
            ),
            pytest.param(
                {
                    "region": "us-east-1",
                    "name": "cluster",
                    "clusterConfiguration": BASE64_ENCODED_CONFIG,
                },
                [],
                ["type:type1", "type:type2"],
                ValidationLevel.WARNING,
                False,
                id="test with no errors",
            ),
        ],
    )
    def test_successful_create_request(
        self,
        client,
        mocker,
        create_cluster_request_content,
        errors,
        suppress_validators,
        validation_failure_level,
        rollback_on_failure,
    ):
        cluster_create_mock = mocker.patch(
            "pcluster.models.cluster.Cluster.create",
            auto_spec=True,
            return_value=("id", errors),
        )

        response = self._send_test_request(
            client,
            create_cluster_request_content,
            suppress_validators,
            validation_failure_level,
            False,
            rollback_on_failure,
        )

        messages = [{"level": "WARNING", "message": "message", "type": "type"}] if errors else []

        expected_response = {
            "cluster": {
                "cloudformationStackArn": "id",
                "cloudformationStackStatus": "CREATE_IN_PROGRESS",
                "clusterName": create_cluster_request_content["name"],
                "clusterStatus": "CREATE_IN_PROGRESS",
                "region": create_cluster_request_content["region"],
                "version": "3.0.0",
            },
            "validationMessages": messages,
        }

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(202)
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
        "expected_response",
        [
            (None, None, None, None, None, {"message": "Bad Request: request body is required"}),
            ({}, None, None, None, None, {"message": "Bad Request: request body is required"}),
            (
                {"region": "us-east-1", "name": "cluster"},
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
                {"message": "Bad Request: invalid or unsupported region 'invalid'"},
            ),
            (
                {"clusterConfiguration": "config", "region": "us-east-1"},
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
                {"message": "Bad Request: 'ALLL' does not match '^(ALL|type:[A-Za-z0-9]+)$'"},
            ),
            (
                {"clusterConfiguration": "config", "name": "cluster", "region": "us-east-1"},
                ["type:"],
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
                {"message": "Bad Request: 'CRITICAL' is not one of ['INFO', 'WARNING', 'ERROR']"},
            ),
            (
                {"clusterConfiguration": "config", "name": "cluster", "region": "us-east-1"},
                None,
                None,
                "NO",
                None,
                {"message": "Bad Request: Wrong type, expected 'boolean' for query parameter 'dryrun'"},
            ),
            (
                {"clusterConfiguration": "config", "name": "cluster", "region": "us-east-1"},
                None,
                None,
                None,
                "NO",
                {"message": "Bad Request: Wrong type, expected 'boolean' for query parameter 'rollbackOnFailure'"},
            ),
            (
                {"clusterConfiguration": "config", "name": "cluster", "region": "us-east-1"},
                None,
                None,
                None,
                None,
                {"message": "Bad Request: invalid configuration. Please make sure the string is base64 encoded."},
            ),
            (
                {"clusterConfiguration": "aW52YWxpZA==", "name": "cluster", "region": "us-east-1"},
                None,
                None,
                None,
                None,
                {"message": "Bad Request: Configuration must be a valid YAML document"},
            ),
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
                {"message": "Bad Request: configuration is required and cannot be empty"},
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
            "invalid_config_format",
            "invalid_config_schema",
            "empty_config",
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
    url = "/v3/clusters/{cluster_name}"
    method = "DELETE"

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
        "cfn_stack_data, expected_response",
        [
            (
                cfn_describe_stack_mock_response(),
                {
                    "cluster": {
                        "cloudformationStackArn": "arn:aws:cloudformation:us-east-1:123:stack/pcluster3-2/123",
                        "cloudformationStackStatus": "DELETE_IN_PROGRESS",
                        "clusterName": "clustername",
                        "clusterStatus": "DELETE_IN_PROGRESS",
                        "region": "us-east-1",
                        "version": "3.0.0",
                    }
                },
            ),
            (
                cfn_describe_stack_mock_response({"StackStatus": "DELETE_IN_PROGRESS"}),
                {
                    "cluster": {
                        "cloudformationStackArn": "arn:aws:cloudformation:us-east-1:123:stack/pcluster3-2/123",
                        "cloudformationStackStatus": "DELETE_IN_PROGRESS",
                        "clusterName": "clustername",
                        "clusterStatus": "DELETE_IN_PROGRESS",
                        "region": "us-east-1",
                        "version": "3.0.0",
                    }
                },
            ),
        ],
        ids=["required", "cluster_delete_in_progress"],
    )
    def test_successful_request(self, mocker, client, cfn_stack_data, expected_response):
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", return_value=cfn_stack_data)
        cluster_delete_mock = mocker.patch(
            "pcluster.models.cluster.Cluster.delete",
            auto_spec=True,
        )
        response = self._send_test_request(client)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(202)
            assert_that(response.get_json()).is_equal_to(expected_response)

        if cfn_stack_data["StackStatus"] != "DELETE_IN_PROGRESS":
            cluster_delete_mock.assert_called_with(keep_logs=False)
        else:
            cluster_delete_mock.assert_not_called()

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
                    "message": "cluster 'clustername' does not exist or belongs to an incompatible ParallelCluster "
                    "major version. In case you have running instances belonging to a deleted cluster please"
                    " use the DeleteClusterInstances API."
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
                    "message": "Bad Request: cluster 'clustername' belongs to an incompatible ParallelCluster major"
                    " version."
                }
            )

    @pytest.mark.parametrize(
        "error_type, error_code",
        [
            (LimitExceededClusterActionError, 429),
            (BadRequestClusterActionError, 400),
            (ClusterActionError, 500),
        ],
    )
    def test_cluster_action_error(self, client, mocker, error_type, error_code):
        mocker.patch(
            "pcluster.aws.cfn.CfnClient.describe_stack",
            return_value=cfn_describe_stack_mock_response(),
        )
        mocker.patch(
            "pcluster.models.cluster.Cluster.delete",
            auto_spec=True,
            side_effect=error_type("error message"),
        )

        response = self._send_test_request(client)

        expected_response = {"message": "error message"}
        if error_type == BadRequestClusterActionError:
            expected_response["message"] = "Bad Request: " + expected_response["message"]

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(error_code)
            assert_that(response.get_json()).is_equal_to(expected_response)


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
                    "message": "cluster 'clustername' does not exist or belongs to an incompatible ParallelCluster "
                    "major version."
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
                    "message": "Bad Request: cluster 'clustername' belongs to an incompatible ParallelCluster major"
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
    url = "/v3/clusters/{cluster_name}"
    method = "PUT"

    BASE64_ENCODED_CONFIG = "SW1hZ2U6CiAgT3M6IGFsaW51eDIKSGVhZE5vZGU6CiAgSW5zdGFuY2VUeXBlOiB0Mi5taWNybw=="

    def _send_test_request(
        self,
        client,
        cluster_name,
        region="us-east-1",
        update_cluster_request_content=None,
        suppress_validators=None,
        validation_failure_level=None,
        dryrun=None,
        force_update=None,
    ):
        query_string = []
        if region:
            query_string.append(("region", region))
        if suppress_validators:
            query_string.extend([("suppressValidators", validator) for validator in suppress_validators])
        if validation_failure_level:
            query_string.append(("validationFailureLevel", validation_failure_level))
        if dryrun is not None:
            query_string.append(("dryrun", dryrun))
        if force_update is not None:
            query_string.append(("forceUpdate", force_update))

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        return client.open(
            self.url.format(cluster_name=cluster_name),
            method=self.method,
            headers=headers,
            query_string=query_string,
            data=json.dumps(update_cluster_request_content) if update_cluster_request_content else None,
        )

    @pytest.mark.parametrize(
        "update_cluster_request_content, errors, suppress_validators, validation_failure_level, force_update",
        [
            pytest.param(
                {
                    "clusterConfiguration": BASE64_ENCODED_CONFIG,
                },
                [ValidationResult("message", FailureLevel.WARNING, "type")],
                None,
                None,
                None,
                id="test with all errors",
            ),
            pytest.param(
                {
                    "clusterConfiguration": BASE64_ENCODED_CONFIG,
                },
                [ValidationResult("message", FailureLevel.WARNING, "type")],
                ["type:type1", "type:type2"],
                ValidationLevel.WARNING,
                False,
                id="test with filtered errors",
            ),
            pytest.param(
                {
                    "clusterConfiguration": BASE64_ENCODED_CONFIG,
                },
                [],
                ["type:type1", "type:type2"],
                ValidationLevel.WARNING,
                False,
                id="test with no errors",
            ),
        ],
    )
    def test_successful_update_request(
        self,
        client,
        mocker,
        update_cluster_request_content,
        errors,
        suppress_validators,
        validation_failure_level,
        force_update,
    ):
        change_set = [
            ["param_path", "parameter", "old value", "new value", "check", "reason", "action_needed"],
            [["toplevel", "subpath"], "param", "oldval", "newval", None, None, None],
        ]
        stack_data = cfn_describe_stack_mock_response()
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", return_value=stack_data)
        cluster_update_mock = mocker.patch(
            "pcluster.models.cluster.Cluster.update",
            auto_spec=True,
            return_value=(change_set, errors),
        )

        response = self._send_test_request(
            client,
            "clusterName",
            "us-east-1",
            update_cluster_request_content,
            suppress_validators,
            validation_failure_level,
            False,
            force_update,
        )

        messages = [{"level": "WARNING", "message": "message", "type": "type"}] if errors else []

        expected_response = {
            "cluster": {
                "cloudformationStackArn": stack_data["StackId"],
                "cloudformationStackStatus": "UPDATE_IN_PROGRESS",
                "clusterName": "clusterName",
                "clusterStatus": "UPDATE_IN_PROGRESS",
                "region": "us-east-1",
                "version": "3.0.0",
            },
            "validationMessages": messages,
            "changeSet": [
                {"parameter": "toplevel.subpath.param", "requestedValue": "newval", "currentValue": "oldval"}
            ],
        }

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(202)
            assert_that(response.get_json()).is_equal_to(expected_response)
        cluster_update_mock.assert_called_with(
            force=not (force_update or True),
            target_source_config="Image:\n  Os: alinux2\nHeadNode:\n  InstanceType: t2.micro",
            validator_suppressors=mocker.ANY,
            validation_failure_level=FailureLevel[validation_failure_level or ValidationLevel.ERROR],
        )
        cluster_update_mock.assert_called_once()
        if suppress_validators:
            _, kwargs = cluster_update_mock.call_args
            assert_that(kwargs["validator_suppressors"].pop()._validators_to_suppress).is_equal_to({"type1", "type2"})

    def test_dryrun(self, mocker, client):
        stack_data = cfn_describe_stack_mock_response()
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", return_value=stack_data)
        mocker.patch(
            "pcluster.models.cluster.Cluster.validate_update_request",
            auto_spec=True,
            return_value=([]),
        )

        update_cluster_request_content = {
            "region": "us-east-1",
            "name": "cluster",
            "clusterConfiguration": self.BASE64_ENCODED_CONFIG,
        }

        response = self._send_test_request(
            client=client,
            cluster_name="clusterName",
            update_cluster_request_content=update_cluster_request_content,
            dryrun=True,
        )

        expected_response = {"message": "Request would have succeeded, but DryRun flag is set."}
        with soft_assertions():
            assert_that(response.status_code).is_equal_to(412)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize(
        "changes, change_set, error",
        [
            pytest.param(
                [
                    ["param_path", "parameter", "old value", "new value", "check", "reason", "action_needed"],
                    [
                        ["toplevel", "subpath"],
                        "param",
                        "oldval",
                        "newval",
                        UpdatePolicy.CheckResult.SUCCEEDED,
                        None,
                        None,
                    ],
                ],
                [{"parameter": "toplevel.subpath.param", "requestedValue": "newval", "currentValue": "oldval"}],
                None,
                id="test with nested path",
            ),
            pytest.param(
                [
                    ["param_path", "parameter", "old value", "new value", "check", "reason", "action_needed"],
                    [
                        None,
                        "param",
                        "oldval",
                        "newval",
                        UpdatePolicy.CheckResult.SUCCEEDED,
                        None,
                        None,
                    ],
                ],
                [{"parameter": "param", "requestedValue": "newval", "currentValue": "oldval"}],
                None,
                id="test with top level path",
            ),
            pytest.param(
                [
                    ["param_path", "parameter", "old value", "new value", "check", "reason", "action_needed"],
                    [
                        None,
                        "param",
                        "oldval",
                        "newval",
                        UpdatePolicy.CheckResult.FAILED,
                        "Failure reason",
                        None,
                    ],
                    [
                        None,
                        "param2",
                        "oldval",
                        "newval",
                        UpdatePolicy.CheckResult.SUCCEEDED,
                        None,
                        None,
                    ],
                ],
                [
                    {"parameter": "param", "requestedValue": "newval", "currentValue": "oldval"},
                    {"parameter": "param2", "requestedValue": "newval", "currentValue": "oldval"},
                ],
                [
                    {
                        "parameter": "param",
                        "requestedValue": "newval",
                        "currentValue": "oldval",
                        "message": "Failure reason",
                    }
                ],
                id="test with failure",
            ),
            pytest.param(
                [
                    ["param_path", "parameter", "old value", "new value", "check", "reason", "action_needed"],
                    [
                        None,
                        "param",
                        "oldval",
                        "newval",
                        UpdatePolicy.CheckResult.ACTION_NEEDED,
                        None,
                        "Action needed",
                    ],
                    [
                        None,
                        "param2",
                        "oldval",
                        "newval",
                        UpdatePolicy.CheckResult.SUCCEEDED,
                        None,
                        None,
                    ],
                ],
                [
                    {"parameter": "param", "requestedValue": "newval", "currentValue": "oldval"},
                    {"parameter": "param2", "requestedValue": "newval", "currentValue": "oldval"},
                ],
                [
                    {
                        "parameter": "param",
                        "requestedValue": "newval",
                        "currentValue": "oldval",
                        "message": "Action needed",
                    }
                ],
                id="test with action needed",
            ),
            pytest.param(
                [
                    ["param_path", "parameter", "old value", "new value", "check", "reason", "action_needed"],
                    [
                        None,
                        "param",
                        "oldval",
                        "newval",
                        UpdatePolicy.CheckResult.FAILED,
                        "Failure reason",
                        "Action needed",
                    ],
                    [
                        None,
                        "param2",
                        "oldval",
                        "newval",
                        UpdatePolicy.CheckResult.SUCCEEDED,
                        None,
                        None,
                    ],
                ],
                [
                    {"parameter": "param", "requestedValue": "newval", "currentValue": "oldval"},
                    {"parameter": "param2", "requestedValue": "newval", "currentValue": "oldval"},
                ],
                [
                    {
                        "parameter": "param",
                        "requestedValue": "newval",
                        "currentValue": "oldval",
                        "message": "Failure reason. Action needed",
                    }
                ],
                id="test with failure with action needed",
            ),
            pytest.param(
                [
                    ["param_path", "parameter", "old value", "new value", "check", "reason", "action_needed"],
                    [
                        None,
                        "param",
                        "oldval",
                        "newval",
                        UpdatePolicy.CheckResult.FAILED,
                        None,
                        None,
                    ],
                    [
                        None,
                        "param2",
                        "oldval",
                        "newval",
                        UpdatePolicy.CheckResult.SUCCEEDED,
                        None,
                        None,
                    ],
                ],
                [
                    {"parameter": "param", "requestedValue": "newval", "currentValue": "oldval"},
                    {"parameter": "param2", "requestedValue": "newval", "currentValue": "oldval"},
                ],
                [
                    {
                        "parameter": "param",
                        "requestedValue": "newval",
                        "currentValue": "oldval",
                        "message": "Error during update",
                    }
                ],
                id="test with failure without reason or action needed",
            ),
            pytest.param(
                [
                    ["param_path", "parameter", "old value", "new value", "check", "reason", "action_needed"],
                ],
                [],
                [],
                id="test with empty changeset",
            ),
        ],
    )
    def test_handling_of_change_sets(self, client, mocker, changes, change_set, error):
        stack_data = cfn_describe_stack_mock_response()
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", return_value=stack_data)
        if error:
            mocker.patch(
                "pcluster.models.cluster.Cluster.update",
                side_effect=ClusterUpdateError(message="Update failure", update_changes=changes),
            )
        else:
            mocker.patch(
                "pcluster.models.cluster.Cluster.update",
                return_value=(changes, []),
            )

        response = self._send_test_request(
            client, "clusterName", "us-east-1", {"clusterConfiguration": self.BASE64_ENCODED_CONFIG}
        )

        with soft_assertions():
            assert_that(response.get_json()["changeSet"]).is_equal_to(change_set)
            if error:
                assert_that(response.get_json()["updateValidationErrors"]).is_equal_to(error)

    @pytest.mark.parametrize(
        "update_cluster_request_content, region, cluster_name, suppress_validators,"
        " validation_failure_level, dryrun, force, expected_response",
        [
            pytest.param(
                None,
                "us-east-1",
                "clusterName",
                None,
                None,
                None,
                None,
                {"message": "Bad Request: request body is required"},
                id="request without body",
            ),
            pytest.param(
                {},
                "us-east-1",
                "clusterName",
                None,
                None,
                None,
                None,
                {"message": "Bad Request: request body is required"},
                id="request with empty body",
            ),
            pytest.param(
                {"clusterConfiguration": BASE64_ENCODED_CONFIG},
                "invalid",
                "clusterName",
                None,
                None,
                None,
                None,
                {"message": "Bad Request: invalid or unsupported region 'invalid'"},
                id="request with invalid region",
            ),
            pytest.param(
                {"clusterConfiguration": BASE64_ENCODED_CONFIG},
                "us-east-1",
                "clu",
                None,
                None,
                None,
                None,
                {"message": "Bad Request: 'clu' is too short"},
                id="request with invalid name",
            ),
            pytest.param(
                {"clusterConfiguration": BASE64_ENCODED_CONFIG},
                "us-east-1",
                "clusterName",
                ["ALL", "ALLL"],
                None,
                None,
                None,
                {"message": "Bad Request: 'ALLL' does not match '^(ALL|type:[A-Za-z0-9]+)$'"},
                id="request with invalid validator",
            ),
            pytest.param(
                {"clusterConfiguration": BASE64_ENCODED_CONFIG},
                "us-east-1",
                "clusterName",
                ["type:"],
                None,
                None,
                None,
                {"message": "Bad Request: 'type:' does not match '^(ALL|type:[A-Za-z0-9]+)$'"},
                id="request with empty named validator",
            ),
            pytest.param(
                {"clusterConfiguration": BASE64_ENCODED_CONFIG},
                "us-east-1",
                "clusterName",
                None,
                "CRITICAL",
                None,
                None,
                {"message": "Bad Request: 'CRITICAL' is not one of ['INFO', 'WARNING', 'ERROR']"},
                id="request with invalid validation failure level",
            ),
            pytest.param(
                {"clusterConfiguration": BASE64_ENCODED_CONFIG},
                "us-east-1",
                "clusterName",
                None,
                None,
                "NO",
                None,
                {"message": "Bad Request: Wrong type, expected 'boolean' for query parameter 'dryrun'"},
                id="request with invalid dryrun value",
            ),
            pytest.param(
                {"clusterConfiguration": BASE64_ENCODED_CONFIG},
                "us-east-1",
                "clusterName",
                None,
                None,
                None,
                "NO",
                {"message": "Bad Request: Wrong type, expected 'boolean' for query parameter 'forceUpdate'"},
                id="request with invalid forceUpdate value",
            ),
            pytest.param(
                {"clusterConfiguration": "config"},
                "us-east-1",
                "clusterName",
                None,
                None,
                None,
                None,
                {"message": "Bad Request: invalid configuration. " "Please make sure the string is base64 encoded."},
                id="request with configuration not encoded",
            ),
            pytest.param(
                {"clusterConfiguration": "aW52YWxpZA=="},
                "us-east-1",
                "clusterName",
                None,
                None,
                None,
                None,
                {"message": "Bad Request: Cluster update failed.\nConfiguration must be a valid YAML document"},
                id="request with single string configuration",
            ),
            pytest.param(
                {"clusterConfiguration": "SW1hZ2U6CiAgSW52YWxpZEtleTogdGVzdA=="},
                "us-east-1",
                "clusterName",
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
                id="request with validation error",
            ),
            pytest.param(
                {"clusterConfiguration": ""},
                "us-east-1",
                "clusterName",
                None,
                None,
                None,
                None,
                {"message": "Bad Request: configuration is required and cannot be empty"},
                id="request with empty configuration",
            ),
        ],
    )
    def test_malformed_request(
        self,
        client,
        mocker,
        update_cluster_request_content,
        region,
        cluster_name,
        suppress_validators,
        validation_failure_level,
        dryrun,
        force,
        expected_response,
    ):
        stack_data = cfn_describe_stack_mock_response()
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", return_value=stack_data)

        response = self._send_test_request(
            client=client,
            cluster_name=cluster_name,
            region=region,
            update_cluster_request_content=update_cluster_request_content,
            suppress_validators=suppress_validators,
            validation_failure_level=validation_failure_level,
            dryrun=dryrun,
            force_update=force,
        )

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).is_equal_to(expected_response)

    def test_cluster_not_found(self, client, mocker):
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", side_effect=StackNotFoundError("func", "stack"))

        response = self._send_test_request(
            client,
            update_cluster_request_content={"clusterConfiguration": self.BASE64_ENCODED_CONFIG},
            cluster_name="clusterName",
        )

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(404)
            assert_that(response.get_json()).is_equal_to(
                {
                    "message": "cluster 'clusterName' does not exist or belongs to "
                    "an incompatible ParallelCluster major version."
                }
            )

    @pytest.mark.parametrize(
        "error_type, error_code",
        [
            (LimitExceededClusterActionError, 429),
            (BadRequestClusterActionError, 400),
            (ConflictClusterActionError, 409),
            (ClusterActionError, 500),
            (ClusterUpdateError, 400),
        ],
    )
    def test_error_conversion(self, client, mocker, error_type, error_code):
        mocker.patch(
            "pcluster.aws.cfn.CfnClient.describe_stack",
            return_value=cfn_describe_stack_mock_response(),
        )

        if error_type == ClusterUpdateError:
            change_set = [
                ["param_path", "parameter", "old value", "new value", "check", "reason", "action_needed"],
                [
                    ["toplevel", "subpath"],
                    "param",
                    "oldval",
                    "newval",
                    UpdatePolicy.CheckResult.FAILED,
                    "reason",
                    "action",
                ],
                [["toplevel", "subpath"], "param2", "oldval", "newval", UpdatePolicy.CheckResult.SUCCEEDED, None, None],
                [
                    ["toplevel", "subpath"],
                    "param3",
                    "oldval",
                    "newval",
                    UpdatePolicy.CheckResult.FAILED,
                    "other reason",
                    None,
                ],
            ]
            error = error_type("error message", change_set)
        else:
            error = error_type("error message")

        mocker.patch(
            "pcluster.models.cluster.Cluster.update",
            auto_spec=True,
            side_effect=error,
        )

        response = self._send_test_request(
            client,
            update_cluster_request_content={"clusterConfiguration": self.BASE64_ENCODED_CONFIG},
            cluster_name="clusterName",
        )

        expected_response = {"message": "error message"}
        if error_type == BadRequestClusterActionError:
            expected_response["message"] = "Bad Request: " + expected_response["message"]
        elif error_type == ClusterUpdateError:
            expected_response["changeSet"] = [
                {"parameter": "toplevel.subpath.param", "requestedValue": "newval", "currentValue": "oldval"},
                {"parameter": "toplevel.subpath.param2", "requestedValue": "newval", "currentValue": "oldval"},
                {"parameter": "toplevel.subpath.param3", "requestedValue": "newval", "currentValue": "oldval"},
            ]
            expected_response["updateValidationErrors"] = [
                {
                    "parameter": "toplevel.subpath.param",
                    "requestedValue": "newval",
                    "currentValue": "oldval",
                    "message": "reason. action",
                },
                {
                    "parameter": "toplevel.subpath.param3",
                    "requestedValue": "newval",
                    "currentValue": "oldval",
                    "message": "other reason",
                },
            ]

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(error_code)
            assert_that(response.get_json()).is_equal_to(expected_response)


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
