#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import pytest
from assertpy import assert_that

from pcluster.aws.common import AWSClientError
from pcluster.constants import Operation
from pcluster.models.common import LogStream
from pcluster.utils import to_utc_datetime
from tests.pcluster.api.controllers.utils import mock_assert_supported_operation, verify_unsupported_operation


class TestGetImageLogEvents:
    method = "GET"

    @staticmethod
    def url(image_id: str, log_stream_name: str):
        return f"/v3/images/custom/{image_id}/logstreams/{log_stream_name}"

    def _send_test_request(
        self,
        client,
        image_id,
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
            self.url(image_id, log_stream_name),
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
    def test_successful_get_image_log_events_request(
        self, client, mocker, region, next_token, start_from_head, limit, start_time, end_time
    ):
        log_stream_name = "logstream"
        mock_log_events = [
            {
                "ingestionTime": 1627524017632,
                "message": "Jan 01 00:00:00 ip-10-0-0-1 event1.",
                "timestamp": 1609459200000,
            },
            {
                "ingestionTime": 1627524017632,
                "message": "Jan 01 00:00:00 ip-10-0-0-1 event2.",
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

        mock_log_stream = LogStream("image", log_stream_name, mock_log_events_response)

        get_log_events_mock = mocker.patch(
            "pcluster.models.imagebuilder.ImageBuilder.get_log_events",
            return_value=mock_log_stream,
        )

        response = self._send_test_request(
            client, "image", log_stream_name, region, next_token, start_from_head, limit, start_time, end_time
        )

        expected_args = {
            "start_time": start_time and to_utc_datetime(start_time),
            "end_time": end_time and to_utc_datetime(end_time),
            "limit": limit,
            "start_from_head": start_from_head,
            "next_token": next_token,
        }
        get_log_events_mock.assert_called_with(log_stream_name, **expected_args)

        expected = {
            "events": [
                {
                    "message": "Jan 01 00:00:00 ip-10-0-0-1 event1.",
                    "timestamp": "2021-01-01T00:00:00.000Z",
                },
                {
                    "message": "Jan 01 00:00:00 ip-10-0-0-1 event2.",
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
            client, "image", "logstream", "us-east-1", None, None, None, start_time, end_time
        )
        self._assert_invalid_response(response, expected_response)

    @pytest.mark.parametrize(
        "limit, expected_response",
        [("invalid", r"expected 'integer' for query parameter 'limit'"), (-1, r"'limit' must be a positive integer.")],
    )
    def test_invalid_limit(self, client, limit, expected_response):
        response = self._send_test_request(client, "image", "logstream", "us-east-1", None, None, limit, None, None)
        self._assert_invalid_response(response, expected_response)

    @pytest.mark.parametrize(
        "image_exists, log_group_exists, expected_response",
        [
            (False, True, r"Unable to find image logs.*"),
            (True, False, r"The specified log stream.*does not exist."),
        ],
    )
    def test_invalid_logs(self, client, mocker, image_exists, log_group_exists, expected_response):
        err_msg = "The specified %s doesn't exist." % ("log stream" if image_exists else "log group")
        mocker.patch(
            "pcluster.aws.logs.LogsClient.get_log_events",
            autospec=True,
            side_effect=AWSClientError("get_log_events", err_msg, 404),
        )
        response = self._send_test_request(client, "image", "logstream", "us-east-2", None, None, None, None, None)
        self._assert_invalid_response(response, expected_response, 404)

    def test_unsupported_operation_error(self, client, mocker):
        mocked_assert_supported_operation = mock_assert_supported_operation(
            mocker, "pcluster.api.controllers.image_logs_controller.assert_supported_operation"
        )
        response = self._send_test_request(client, "image", "logstream", "us-east-2", None, None, None, None, None)
        verify_unsupported_operation(
            mocked_assertion=mocked_assert_supported_operation,
            operation=Operation.GET_IMAGE_LOG_EVENTS,
            region="us-east-2",
            response=response,
        )

    @staticmethod
    def _assert_invalid_response(response, expected_response, response_code=400):
        assert_that(response.status_code).is_equal_to(response_code)
        out = response.get_json()
        assert_that(out).contains("message")
        assert_that(out["message"]).matches(expected_response)


class TestGetImageStackEvents:
    method = "GET"

    @staticmethod
    def url(image_id: str):
        return f"/v3/images/custom/{image_id}/stackevents"

    def _send_test_request(
        self,
        client,
        image_id,
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
            self.url(image_id),
            method=self.method,
            headers=headers,
            query_string=query_string,
        )

    @pytest.mark.parametrize(
        "region, next_token",
        [
            ("us-east-2", None),
            ("us-east-1", "next_token"),
        ],
    )
    def test_successful_get_image_log_events_request(self, client, mocker, mock_image_stack, region, next_token):
        uid = "00000000-dddd-4444-bbbb-555555555555"
        image_id = "image"
        account_id = "012345678999"
        mock_events = [
            {
                "eventId": uid,
                "physicalResourceId": f"arn:aws:cloudformation:us-east-2:{account_id}:stack/{image_id}/{uid}",
                "resourceStatus": "CREATE_IN_PROGRESS",
                "resourceStatusReason": "User Initiated",
                "stackId": f"arn:aws:cloudformation:us-east-2:{account_id}:stack/{image_id}/{uid}",
                "stackName": image_id,
                "logicalResourceId": image_id,
                "resourceType": "AWS::CloudFormation::Stack",
                "timestamp": "2021-01-01T00:00:00.000Z",
            }
        ]

        mock_response = {"StackEvents": mock_events}

        mocker.patch("pcluster.aws.cfn.CfnClient.stack_exists", return_value=True)
        mock_image_stack(image_id=image_id)
        get_stack_events_mock = mocker.patch("pcluster.aws.cfn.CfnClient.get_stack_events", return_value=mock_response)

        response = self._send_test_request(client, image_id, region, next_token)

        expected_args = {"next_token": next_token}
        get_stack_events_mock.assert_called_with(image_id, **expected_args)

        expected = {
            "events": [
                {
                    "eventId": "00000000-dddd-4444-bbbb-555555555555",
                    "logicalResourceId": image_id,
                    "physicalResourceId": f"arn:aws:cloudformation:us-east-2:{account_id}:stack/{image_id}/{uid}",
                    "resourceStatus": "CREATE_IN_PROGRESS",
                    "resourceStatusReason": "User Initiated",
                    "resourceType": "AWS::CloudFormation::Stack",
                    "stackId": f"arn:aws:cloudformation:us-east-2:{account_id}:stack/{image_id}/{uid}",
                    "stackName": image_id,
                    "timestamp": "2021-01-01T00:00:00.000Z",
                }
            ]
        }
        assert_that(response.status_code).is_equal_to(200)
        assert_that(response.get_json()).is_equal_to(expected)

    @pytest.mark.parametrize(
        "image_stack_found, expected_response",
        [
            (False, r"does not exist"),
        ],
    )
    def test_invalid_image(self, client, mock_image_stack, image_stack_found, expected_response):
        mock_image_stack(image_id="image", stack_exists=image_stack_found)
        response = self._send_test_request(client, "image", "us-east-2", None)
        self._assert_invalid_response(response, expected_response, 404)

    def test_unsupported_operation_error(self, client, mocker):
        mocked_assert_supported_operation = mock_assert_supported_operation(
            mocker, "pcluster.api.controllers.image_logs_controller.assert_supported_operation"
        )
        response = self._send_test_request(client, "image", "us-east-2", None)
        verify_unsupported_operation(
            mocked_assertion=mocked_assert_supported_operation,
            operation=Operation.GET_IMAGE_STACK_EVENTS,
            region="us-east-2",
            response=response,
        )

    @staticmethod
    def _assert_invalid_response(response, expected_response, response_code=400):
        assert_that(response.status_code).is_equal_to(response_code)
        out = response.get_json()
        assert_that(out).contains("message")
        assert_that(out["message"]).matches(expected_response)


class TestListImageLogStreams:
    method = "GET"

    @staticmethod
    def url(image_id: str):
        return f"/v3/images/custom/{image_id}/logstreams"

    def _send_test_request(
        self,
        client,
        image_id: str,
        region: str = None,
        next_token: str = None,
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
            self.url(image_id),
            method=self.method,
            headers=headers,
            query_string=query_string,
        )

    @pytest.mark.parametrize(
        "next_token, resp_next_token, expected_prefix",
        [
            (None, None, None),
            ("next_token", None, None),
            (None, "123", None),
        ],
    )
    def test_successful_list_image_log_streams_request(
        self, client, mocker, mock_image_stack, next_token, resp_next_token, expected_prefix
    ):
        image_id = "image"
        account_id = "012345678999"
        inst = "i-0fffffcccc3333aaa"
        mock_streams = [
            {
                "arn": (
                    f"arn:aws:logs:us-east-2:{account_id}:log-group:/aws/parallelimage/"
                    f"{image_id}-202101010000:log-stream:ip-10-0-0-100.{inst}.cfn-init"
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

        describe_log_streams_mock = mocker.patch(
            "pcluster.aws.logs.LogsClient.describe_log_streams", return_value=mock_response
        )
        mocker.patch("pcluster.aws.logs.LogsClient.log_group_exists", return_value=True)
        mock_image_stack(image_id=image_id)

        response = self._send_test_request(client, image_id, "us-east-1", next_token)

        expected_args = {
            "log_group_name": f"/aws/imagebuilder/ParallelClusterImage-{image_id}",
            "next_token": next_token,
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
                        "arn:aws:logs:us-east-2:012345678999:log-group:/aws/parallelimage/"
                        "image-202101010000:log-stream:ip-10-0-0-100.i-0fffffcccc3333aaa."
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
        "image_stack_found, expected_response",
        [
            (False, r"Unable to find image logs"),
        ],
    )
    def test_invalid_image(self, client, mocker, mock_image_stack, image_stack_found, expected_response):
        err_msg = "The specified %s doesn't exist." % "log stream" if image_stack_found else "log group"
        mock_image_stack(image_id="image", stack_exists=image_stack_found)
        mocker.patch(
            "pcluster.models.imagebuilder.ImageBuilder.get_log_events",
            autospec=True,
            side_effect=AWSClientError("get_log_events", err_msg, 404),
        )
        response = self._send_test_request(client, "image", "us-east-1", None)
        self._assert_invalid_response(response, expected_response, 404)

    def test_unsupported_operation_error(self, client, mocker):
        mocked_assert_supported_operation = mock_assert_supported_operation(
            mocker, "pcluster.api.controllers.image_logs_controller.assert_supported_operation"
        )
        response = self._send_test_request(client, "image", "us-east-1", None)
        verify_unsupported_operation(
            mocked_assertion=mocked_assert_supported_operation,
            operation=Operation.LIST_IMAGE_LOG_STREAMS,
            region="us-east-1",
            response=response,
        )

    @staticmethod
    def _assert_invalid_response(response, expected_response, response_code=400):
        assert_that(response.status_code).is_equal_to(response_code)
        out = response.get_json()
        assert_that(out).contains("message")
        assert_that(out["message"]).matches(expected_response)
