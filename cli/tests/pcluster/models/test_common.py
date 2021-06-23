# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import os
import time

import pytest
from assertpy import assert_that
from dateutil.parser import parse

from pcluster.aws.common import AWSClientError
from pcluster.models.common import (
    CloudWatchLogsExporter,
    FiltersParserError,
    LogGroupTimeFiltersParser,
    LogsExporterError,
)
from tests.pcluster.aws.dummy_aws_api import mock_aws_api


class TestLogGrouptimeFiltersParser:
    @pytest.fixture()
    def log_group_time_parser(self):
        return LogGroupTimeFiltersParser("log_group_name")

    @pytest.mark.parametrize(
        "params, expected_error",
        [
            ({"start_time": "1623071000"}, "Unable to parse time. It must be in ISO8601 format"),
            ({"end_time": "1623071000"}, "Unable to parse time. It must be in ISO8601 format"),
        ],
    )
    def test_initialization_error(self, mocker, params, expected_error):
        log_group_name = "log_group_name"
        creation_time_mock = 1623061001000
        mock_aws_api(mocker)
        mocker.patch(
            "pcluster.aws.logs.LogsClient.describe_log_group", return_value={"creationTime": creation_time_mock}
        )

        with pytest.raises(FiltersParserError, match=expected_error):
            LogGroupTimeFiltersParser(log_group_name, params.get("start_time", None), params.get("end_time", None))

    @pytest.mark.parametrize(
        "params, expected_attrs",
        [
            (
                {"start_time": "2012-07-09", "end_time": "2012-07-29"},
                {"start_time": 1341788400000, "end_time": 1343516400000},
            ),
        ],
    )
    def test_initialization_success(self, params, expected_attrs):
        os.environ["TZ"] = "Europe/London"
        time.tzset()
        log_group_name = "log_group_name"

        export_logs_filters = LogGroupTimeFiltersParser(
            log_group_name, params.get("start_time", None), params.get("end_time", None)
        )

        for attr in expected_attrs:
            assert_that(getattr(export_logs_filters, attr)).is_equal_to(expected_attrs.get(attr))

    @pytest.mark.parametrize(
        "attrs, event_in_window, log_stream_prefix, expected_error",
        [
            ({"end_time": "2020-06-02"}, True, "test", "Start time must be earlier than end time"),
            (
                {"start_time": "2021-06-07", "end_time": "2021-06-02"},
                True,
                "test",
                "Start time must be earlier than end time",
            ),
            ({"end_time": "2021-07-09T22:45:22+04:00"}, False, None, "No log events in the log group"),
        ],
    )
    def test_validate(self, mocker, attrs, event_in_window, log_stream_prefix, expected_error):
        log_group_name = "log_group_name"
        creation_time_mock = 1623061001000
        mock_aws_api(mocker)
        describe_log_group_mock = mocker.patch(
            "pcluster.aws.logs.LogsClient.describe_log_group", return_value={"creationTime": creation_time_mock}
        )
        filter_log_events_mock = mocker.patch(
            "pcluster.aws.logs.LogsClient.filter_log_events", return_value=event_in_window
        )

        export_logs_filters = LogGroupTimeFiltersParser(
            log_group_name, attrs.get("start_time", None), attrs.get("end_time", None)
        )

        if expected_error:
            with pytest.raises(FiltersParserError, match=expected_error):
                export_logs_filters.validate(log_stream_prefix)
        else:
            export_logs_filters.validate(log_stream_prefix)
            filter_log_events_mock.assert_called_with(
                log_group_name,
                log_stream_prefix,
                export_logs_filters.start_time,
                export_logs_filters.end_time,
            )

            if "start_time" not in attrs:
                describe_log_group_mock.assert_called_with(log_group_name)
                assert_that(export_logs_filters.start_time).is_equal_to(creation_time_mock)


class TestLogGroupTimeFiltersParser:
    @pytest.mark.parametrize(
        "args, error_message",
        [
            ({"start_time": "wrong"}, "Unable to parse time"),
            ({"end_time": "1622802790248"}, "Unable to parse time"),
            ({"end_time": "1622802790"}, "Unable to parse time"),
            ({"start_time": "2021-06-02T15:55:10+02:00", "end_time": "2021-06-02T15:55:10+02:00"}, None),
        ],
    )
    def test_initialization(self, args, error_message, run_cli, capsys):
        kwargs = {"log_group_name": "log_group"}
        kwargs.update(args)
        if error_message:
            with pytest.raises(FiltersParserError, match=error_message):
                LogGroupTimeFiltersParser(**kwargs)
        else:
            time_parser = LogGroupTimeFiltersParser(**kwargs)
            assert_that(time_parser.start_time).is_equal_to(int(parse(args.get("start_time")).timestamp() * 1000))
            assert_that(time_parser.end_time).is_equal_to(int(parse(args.get("end_time")).timestamp() * 1000))


class TestCloudWatchLogsExporter:
    @pytest.fixture()
    def cw_logs_exporter(self, mocker, set_env):
        mocker.patch("pcluster.aws.s3.S3Client.get_bucket_region", return_value="us-east-2")
        mocker.patch("pcluster.aws.s3_resource.S3Resource.is_empty", return_value=True)
        set_env("AWS_DEFAULT_REGION", "us-east-2")
        kwargs = {
            "resource_id": "clustername",
            "log_group_name": "groupname",
            "bucket": "bucket_name",
            "output_dir": "output_dir",
        }
        return CloudWatchLogsExporter(**kwargs)

    @pytest.mark.parametrize(
        "params, bucket_region, is_bucket_empty, expected_error",
        [
            ({}, "eu-west-1", True, "The bucket used for exporting logs must be in the same region"),
            ({}, "us-east-2", True, None),
            ({}, "us-east-2", False, None),
            ({"bucket_prefix": "test_prefix"}, "us-east-2", False, None),
        ],
    )
    def test_initialization(self, mocker, set_env, params, bucket_region, is_bucket_empty, expected_error):
        mock_aws_api(mocker)
        set_env("AWS_DEFAULT_REGION", "us-east-2")
        bucket_region_mock = mocker.patch("pcluster.aws.s3.S3Client.get_bucket_region", return_value=bucket_region)
        bucket_empty_mock = mocker.patch("pcluster.aws.s3_resource.S3Resource.is_empty", return_value=is_bucket_empty)

        kwargs = {
            "resource_id": "clustername",
            "log_group_name": "groupname",
            "bucket": "bucket_name",
            "output_dir": "output_dir",
        }
        kwargs.update(params)

        if expected_error:
            with pytest.raises(LogsExporterError, match=expected_error):
                CloudWatchLogsExporter(**kwargs)
        else:
            cw_logs_exporter = CloudWatchLogsExporter(**kwargs)

            bucket_region_mock.assert_called_with(bucket_name=kwargs.get("bucket"))
            bucket_prefix = kwargs.get("bucket_prefix", None)
            if bucket_prefix:
                assert_that(cw_logs_exporter.bucket_prefix).is_equal_to(bucket_prefix)
                assert_that(cw_logs_exporter.delete_everything_under_prefix).is_equal_to(False)
                bucket_empty_mock.assert_not_called()
            else:
                bucket_empty_mock.assert_called()
                assert_that(cw_logs_exporter.bucket_prefix).matches("clustername-logs-.*")
                assert_that(cw_logs_exporter.delete_everything_under_prefix).is_equal_to(is_bucket_empty)

    @pytest.mark.parametrize(
        "params, is_bucket_empty, client_error, expected_error",
        [
            ({}, False, False, None),
            ({}, True, False, None),
            ({"bucket_prefix": "test_prefix"}, False, False, None),
            ({"keep_s3_objects": True}, False, False, None),
            ({"keep_s3_objects": False}, False, False, None),
            ({"bucket_prefix": "test_prefix", "keep_s3_objects": True}, False, False, None),
            ({}, False, True, "error"),
        ],
    )
    def test_execute(self, mocker, set_env, params, is_bucket_empty, client_error, expected_error):
        mock_aws_api(mocker)
        set_env("AWS_DEFAULT_REGION", "us-east-2")
        mocker.patch("pcluster.aws.s3.S3Client.get_bucket_region", return_value="us-east-2")
        mocker.patch("pcluster.aws.s3_resource.S3Resource.is_empty", return_value=is_bucket_empty)

        kwargs = {
            "resource_id": "clustername",
            "log_group_name": "groupname",
            "bucket": "bucket_name",
            "output_dir": "output_dir",
        }
        kwargs.update(params)
        cw_logs_exporter = CloudWatchLogsExporter(**kwargs)

        mocker.patch("pcluster.models.common.CloudWatchLogsExporter._export_logs_to_s3", return_value="task_id")
        download_objects_mock = mocker.patch(
            "pcluster.models.common.CloudWatchLogsExporter._download_s3_objects_with_prefix"
        )
        delete_objects_mock = mocker.patch(
            "pcluster.aws.s3_resource.S3Resource.delete_objects",
            side_effect=AWSClientError("delete_objects", "error") if client_error else None,
        )
        mocker.patch("pcluster.aws.s3_resource.S3Resource.is_empty", return_value=is_bucket_empty)

        if expected_error or client_error:
            with pytest.raises(AWSClientError, match=expected_error):
                cw_logs_exporter.execute(
                    {"log_stream_prefix": "log_stream_prefix", "start_time": None, "end_time": None}
                )
        else:
            cw_logs_exporter.execute({"log_stream_prefix": "log_stream_prefix", "start_time": None, "end_time": None})
            download_objects_mock.assert_called()
            bucket_prefix = params.get("bucket_prefix", None)

            if bucket_prefix:
                download_objects_mock.assert_called_with("task_id", os.path.join("output_dir", bucket_prefix))

            if not params.get("keep_s3_objects", False):
                delete_objects_mock.assert_called()

                if bucket_prefix:
                    prefix = "/".join((bucket_prefix, "task_id"))
                    delete_objects_mock.assert_called_with(bucket_name="bucket_name", prefix=prefix)
            else:
                delete_objects_mock.assert_not_called()

    @pytest.mark.parametrize(
        "task_statuses",
        [
            [
                "PENDING",
                "PENDING",
                "PENDING",
                "RUNNING",
                "COMPLETE",
            ],
            [
                "PENDING_CANCEL",
                "RUNNING",
                "any value other than PENDING, PENDING_CANCEL or RUNNING",
            ],
        ],
    )
    def test_wait_for_task_completion(self, cw_logs_exporter, mocker, task_statuses):
        """
        Verify that _wait_for_task_completion behaves as expected.

        _wait_for_task_completion should call updated_status until the StackStatus is anything besides
        ("PENDING", "PENDING_CANCEL", "RUNNING") use that to get expected call count for updated_status
        """
        mock_aws_api(mocker)
        wait_for_task_mock = mocker.patch(
            "pcluster.aws.logs.LogsClient.get_export_task_status", side_effect=task_statuses
        )

        expected_call_count = len(task_statuses)
        mocker.patch("pcluster.models.cluster.time.sleep")  # so we don't actually have to wait

        cw_logs_exporter._wait_for_task_completion("task_id")
        assert_that(wait_for_task_mock.call_count).is_equal_to(expected_call_count)

    @pytest.mark.parametrize("task_result", ["COMPLETED", "ERROR"])
    def test_export_logs_to_s3(self, cw_logs_exporter, mocker, task_result):
        """Verify that _export_logs_to_s3 behaves as expected."""
        mock_aws_api(mocker)
        wait_for_completion_mock = mocker.patch(
            "pcluster.models.common.CloudWatchLogsExporter._wait_for_task_completion",
            return_value=task_result,
        )
        mocker.patch("pcluster.aws.logs.LogsClient.create_export_task", return_value="task_id")

        if task_result != "COMPLETED":
            with pytest.raises(LogsExporterError, match=f"export task task_id failed with status: {task_result}"):
                cw_logs_exporter._export_logs_to_s3("log_group_name", "bucket")
        else:
            task_id = cw_logs_exporter._export_logs_to_s3("log_group_name", "bucket")
            wait_for_completion_mock.assert_called_with(task_id)
