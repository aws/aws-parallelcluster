#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from typing import List

import pytest
from assertpy import assert_that

from pcluster.models.common import LogStream
from pcluster.utils import to_utc_datetime


class TestGetClusterLogEvents:
    method = "GET"

    @staticmethod
    def url(cluster_name: str, log_stream_name: str):
        return f"/v3/clusters/{cluster_name}/logstreams/{log_stream_name}"

    def _send_test_request(
        self,
        client,
        cluster_name,
        log_stream_name,
        region=None,
        next_token=None,
        start_from_head=None,
        limit=None,
        start_time=None,
        end_time=None,
    ):
        query_string = []
        if region:
            query_string.append(("region", region))
        if next_token:
            query_string.append(("nextToken", next_token))
        if start_from_head:
            query_string.append(("startFromHead", start_from_head))
        if limit:
            query_string.append(("limit", limit))
        if start_time:
            query_string.append(("startTime", start_time))
        if end_time:
            query_string.append(("endTime", end_time))
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        return client.open(
            self.url(cluster_name, log_stream_name),
            method=self.method,
            headers=headers,
            query_string=query_string,
        )

    @pytest.mark.parametrize(
        "region, next_token, start_from_head, limit, start_time, end_time",
        [
            ("us-east-1", None, None, None, None, None),
            ("us-east-1", "next_token", True, 3, "1984-09-15T19:20:30Z", "2025-01-01"),
        ],
    )
    def test_successful_get_cluster_log_events_request(
        self, client, mocker, mock_cluster_stack, region, next_token, start_from_head, limit, start_time, end_time
    ):
        cluster_name = "cluster"
        log_stream_name = "logstream"
        mock_log_events = [
            {
                "ingestionTime": 1627524017632,
                "message": "Jan 01 00:00:00 ip-10-0-0-1 systemd: Started Session c20325 of " "user root.",
                "timestamp": 1609459200000,
            },
            {
                "ingestionTime": 1627524017632,
                "message": "Jan 01 00:00:00 ip-10-0-0-1 systemd: Removed slice User Slice " "of root.",
                "timestamp": 1609459207000,
            },
        ]
        uid = "00000000-dddd-4444-bbbb-555555555555"
        mock_log_events_response = {
            "ResponseMetadata": {
                "HTTPHeaders": {
                    "content-length": "12345",
                    "content-type": "application/x-amz-json-1.1",
                    "date": "Fri, 01 Jan 2021 00:00:00 GMT",
                    "x-amzn-requestid": uid,
                },
                "HTTPStatusCode": 200,
                "RequestId": uid,
                "RetryAttempts": 0,
            },
            "events": mock_log_events,
            "nextBackwardToken": "b/123",
            "nextForwardToken": "f/456",
        }

        mock_log_stream = LogStream(cluster_name, log_stream_name, mock_log_events_response)

        get_log_events_mock = mocker.patch(
            "pcluster.models.cluster.Cluster.get_log_events",
            return_value=mock_log_stream,
        )

        mock_cluster_stack()

        response = self._send_test_request(
            client, cluster_name, log_stream_name, region, next_token, start_from_head, limit, start_time, end_time
        )

        expected_args = {
            "log_stream_name": log_stream_name,
            "start_time": start_time and to_utc_datetime(start_time),
            "end_time": end_time and to_utc_datetime(end_time),
            "limit": limit,
            "start_from_head": start_from_head,
            "next_token": next_token,
        }
        get_log_events_mock.assert_called_with(**expected_args)

        expected = {
            "events": [
                {
                    "message": "Jan 01 00:00:00 ip-10-0-0-1 systemd: Started Session c20325 of user root.",
                    "timestamp": "2021-01-01T00:00:00.000Z",
                },
                {
                    "message": "Jan 01 00:00:00 ip-10-0-0-1 systemd: Removed slice User Slice of root.",
                    "timestamp": "2021-01-01T00:00:07.000Z",
                },
            ],
            "nextToken": "f/456",
            "prevToken": "b/123",
        }
        assert_that(response.status_code).is_equal_to(200)
        assert_that(response.get_json()).is_equal_to(expected)

    @pytest.mark.parametrize(
        "start_time, end_time, expected_response",
        [
            ("invalid", None, r".*start_time filter must be in the ISO 8601.*"),
            (None, "invalid", r".*end_time filter must be in the ISO 8601.*"),
            ("2021-01-01", "1999-12-31", r"start_time filter must be earlier than end_time filter."),
            ("2021-01-01", "2021-01-01", r"start_time filter must be earlier than end_time filter."),
        ],
        ids=["invalid_start_date", "invalid_end_date", "start_after_end", "start_equal_end"],
    )
    def test_invalid_time(self, client, start_time, end_time, expected_response):
        response = self._send_test_request(
            client, "cluster", "logstream", "us-east-1", None, None, None, start_time, end_time
        )
        self._assert_invalid_response(response, expected_response)

    @pytest.mark.parametrize(
        "limit, expected_response",
        [("invalid", r"expected 'integer' for query parameter 'limit'"), (-1, r"'limit' must be a positive integer.")],
    )
    def test_invalid_limit(self, client, limit, expected_response):
        response = self._send_test_request(client, "cluster", "logstream", "us-east-1", None, None, limit, None, None)
        self._assert_invalid_response(response, expected_response)

    @pytest.mark.parametrize(
        "cluster_found, cluster_valid, logging_enabled, expected_response",
        [
            (False, True, True, r"does not exist"),
            (True, False, True, r"belongs to an incompatible"),
            (True, True, False, r"CloudWatch logging is not enabled"),
        ],
    )
    def test_invalid_logging(
        self, client, mock_cluster_stack, cluster_found, cluster_valid, logging_enabled, expected_response
    ):
        mock_cluster_stack(cluster_found=cluster_found, cluster_valid=cluster_valid, logging_enabled=logging_enabled)
        response = self._send_test_request(client, "cluster", "logstream", "us-east-1", None, None, None, None, None)
        self._assert_invalid_response(response, expected_response, 400 if cluster_found else 404)

    @staticmethod
    def _assert_invalid_response(response, expected_response, response_code=400):
        assert_that(response.status_code).is_equal_to(response_code)
        out = response.get_json()
        assert_that(out).contains("message")
        assert_that(out["message"]).matches(expected_response)


class TestGetClusterStackEvents:
    method = "GET"

    @staticmethod
    def url(cluster_name: str):
        return f"/v3/clusters/{cluster_name}/stackevents"

    def _send_test_request(
        self,
        client,
        cluster_name,
        region=None,
        next_token=None,
    ):
        query_string = []
        if region:
            query_string.append(("region", region))
        if next_token:
            query_string.append(("nextToken", next_token))
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        return client.open(
            self.url(cluster_name),
            method=self.method,
            headers=headers,
            query_string=query_string,
        )

    @pytest.mark.parametrize(
        "region, next_token",
        [
            ("us-east-1", None),
            ("us-east-1", "next_token"),
        ],
    )
    def test_successful_get_cluster_log_events_request(self, client, mocker, region, next_token):

        uid = "00000000-dddd-4444-bbbb-555555555555"
        cluster_name = "cluster"
        account_id = "012345678999"
        mock_events = [
            {
                "eventId": uid,
                "physicalResourceId": f"arn:aws:cloudformation:us-east-2:{account_id}:stack/{cluster_name}/{uid}",
                "resourceStatus": "CREATE_IN_PROGRESS",
                "resourceStatusReason": "User Initiated",
                "stackId": f"arn:aws:cloudformation:us-east-2:{account_id}:stack/{cluster_name}/{uid}",
                "stackName": cluster_name,
                "logicalResourceId": cluster_name,
                "resourceType": "AWS::CloudFormation::Stack",
                "timestamp": "2021-01-01T00:00:00.000Z",
            }
        ]

        mock_response = {"StackEvents": mock_events}

        validate_cluster = mocker.patch(
            "pcluster.api.controllers.cluster_logs_controller.validate_cluster",
            autospec=True,
            return_value=True,
        )

        mocker.patch("pcluster.aws.cfn.CfnClient.stack_exists", return_value=True)
        get_stack_events_mock = mocker.patch("pcluster.aws.cfn.CfnClient.get_stack_events", return_value=mock_response)

        response = self._send_test_request(client, cluster_name, region, next_token)

        expected_args = {"next_token": next_token}
        get_stack_events_mock.assert_called_with(cluster_name, **expected_args)
        validate_cluster.assert_called_once()

        expected = {
            "events": [
                {
                    "eventId": "00000000-dddd-4444-bbbb-555555555555",
                    "logicalResourceId": "cluster",
                    "physicalResourceId": f"arn:aws:cloudformation:us-east-2:{account_id}:stack/{cluster_name}/{uid}",
                    "resourceStatus": "CREATE_IN_PROGRESS",
                    "resourceStatusReason": "User Initiated",
                    "resourceType": "AWS::CloudFormation::Stack",
                    "stackId": f"arn:aws:cloudformation:us-east-2:{account_id}:stack/{cluster_name}/{uid}",
                    "stackName": "cluster",
                    "timestamp": "2021-01-01T00:00:00.000Z",
                }
            ]
        }
        assert_that(response.status_code).is_equal_to(200)
        assert_that(response.get_json()).is_equal_to(expected)

    @pytest.mark.parametrize(
        "cluster_found, cluster_valid, expected_response",
        [
            (False, True, r"does not exist"),
            (True, False, r"belongs to an incompatible"),
        ],
    )
    def test_invalid_cluster(self, client, mock_cluster_stack, cluster_found, cluster_valid, expected_response):
        mock_cluster_stack(cluster_found=cluster_found, cluster_valid=cluster_valid)
        response = self._send_test_request(client, "cluster", "us-east-1", None)
        self._assert_invalid_response(response, expected_response, 400 if cluster_found else 404)

    @staticmethod
    def _assert_invalid_response(response, expected_response, response_code=400):
        assert_that(response.status_code).is_equal_to(response_code)
        out = response.get_json()
        assert_that(out).contains("message")
        assert_that(out["message"]).matches(expected_response)


class TestListClusterLogStreams:
    method = "GET"

    @staticmethod
    def url(cluster_name: str):
        return f"/v3/clusters/{cluster_name}/logstreams"

    def _send_test_request(
        self,
        client,
        cluster_name: str,
        region: str = None,
        next_token: str = None,
        filters: List[str] = None,
    ):
        query_string = []
        if region:
            query_string.append(("region", region))
        if next_token:
            query_string.append(("nextToken", next_token))
        if filters:
            query_string.extend([("filters", filter_) for filter_ in filters])
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        return client.open(
            self.url(cluster_name),
            method=self.method,
            headers=headers,
            query_string=query_string,
        )

    @pytest.mark.parametrize(
        "next_token, filters, resp_next_token, expected_prefix",
        [
            (None, None, None, None),
            ("next_token", None, None, None),
            (None, None, "123", None),
            (None, ["Name=node-type,Values=HeadNode"], None, "dns"),
            (None, ["Name=private-dns-name,Values=ip-10-0-0-101"], None, "ip-10-0-0-101"),
        ],
    )
    def test_successful_list_cluster_log_streams_request(
        self, client, mocker, mock_cluster_stack, next_token, filters, resp_next_token, expected_prefix
    ):
        cluster_name = "cluster"
        account_id = "012345678999"
        inst = "i-0fffffcccc3333aaa"
        mock_streams = [
            {
                "arn": (
                    f"arn:aws:logs:us-east-2:{account_id}:log-group:/aws/parallelcluster/"
                    f"{cluster_name}-202101010000:log-stream:ip-10-0-0-100.{inst}.cfn-init"
                ),
                "creationTime": 1609459207000,
                "firstEventTimestamp": 1609459214000,
                "lastEventTimestamp": 1609459249000,
                "lastIngestionTime": 1609459254000,
                "logStreamName": f"ip-10-0-0-100.{inst}.cfn-init",
                "storedBytes": 0,
                "uploadSequenceToken": "123",
            },
        ]

        mock_response = {"logStreams": mock_streams}
        if resp_next_token:
            mock_response["nextToken"] = resp_next_token

        mock_cluster_stack()
        describe_log_streams_mock = mocker.patch(
            "pcluster.aws.logs.LogsClient.describe_log_streams", return_value=mock_response
        )

        class MockHeadNode:
            private_dns_name_short = "dns"

        mocker.patch(
            "pcluster.models.cluster.Cluster.head_node_instance",
            new_callable=mocker.PropertyMock,
            return_value=MockHeadNode(),
        )

        mocker.patch("pcluster.models.cluster_resources.ListClusterLogsFiltersParser.validate", return_value=True)

        response = self._send_test_request(client, cluster_name, "us-east-1", next_token, filters)

        expected_args = {
            "log_group_name": "log_group",
            "next_token": next_token,
            "log_stream_name_prefix": expected_prefix,
        }
        describe_log_streams_mock.assert_called_with(**expected_args)

        expected = {
            "logStreams": [
                {
                    "creationTime": "2021-01-01T00:00:07.000Z",
                    "firstEventTimestamp": "2021-01-01T00:00:14.000Z",
                    "lastEventTimestamp": "2021-01-01T00:00:49.000Z",
                    "lastIngestionTime": "2021-01-01T00:00:54.000Z",
                    "logStreamArn": (
                        "arn:aws:logs:us-east-2:012345678999:log-group:/aws/parallelcluster/"
                        "cluster-202101010000:log-stream:ip-10-0-0-100.i-0fffffcccc3333aaa."
                        "cfn-init"
                    ),
                    "logStreamName": "ip-10-0-0-100.i-0fffffcccc3333aaa.cfn-init",
                    "uploadSequenceToken": "123",
                }
            ]
        }

        if resp_next_token:
            expected["nextToken"] = resp_next_token

        assert_that(response.status_code).is_equal_to(200)
        assert_that(response.get_json()).is_equal_to(expected)

    @pytest.mark.parametrize(
        "filters, expected_response",
        [
            (["Name=private-dns-name,Values=ip-10-0-0-101,ip-10-0-0-102"], "Filter.*doesn't accept comma separated"),
            (
                ["Name=node-type,Values=HeadNode", "Name=private-dns-name,Values=ip-10-0-0-101"],
                "Private DNS Name and Node Type filters cannot be set at the same time.",
            ),
            (
                ["Name=private-dns-name,Values=ip-10-0-0-101,ip-10-0-0-102", "Name=node-type,Value=HeadNode"],
                "provided filters parameter 'Name=node-type,Value=HeadNode' must be in the form",
            ),
        ],
    )
    def test_invalid_filters(self, client, mock_cluster_stack, filters, expected_response):
        mock_cluster_stack()
        response = self._send_test_request(client, "cluster", "us-east-1", None, filters)
        self._assert_invalid_response(response, expected_response)

    @pytest.mark.parametrize(
        "cluster_found, cluster_valid, expected_response",
        [
            (False, True, r"does not exist"),
            (True, False, r"belongs to an incompatible"),
        ],
    )
    def test_invalid_cluster(self, client, mock_cluster_stack, cluster_found, cluster_valid, expected_response):
        mock_cluster_stack(cluster_found=cluster_found, cluster_valid=cluster_valid)
        response = self._send_test_request(client, "cluster", "us-east-1", None)
        self._assert_invalid_response(response, expected_response, 400 if cluster_found else 404)

    @staticmethod
    def _assert_invalid_response(response, expected_response, response_code=400):
        assert_that(response.status_code).is_equal_to(response_code)
        out = response.get_json()
        assert_that(out).contains("message")
        assert_that(out["message"]).matches(expected_response)
