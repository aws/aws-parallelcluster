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
import datetime
import gzip
import os
import re
import time
from types import SimpleNamespace

import pytest
from assertpy import assert_that

from pcluster.aws.common import AWSClientError
from pcluster.models.common import (
    CloudWatchLogsExporter,
    FiltersParserError,
    LogGroupTimeFiltersParser,
    LogsExporterError,
    export_stack_events,
    format_bytes,
    sanitize_path_component,
)
from tests.pcluster.aws.dummy_aws_api import mock_aws_api


class TestLogGrouptimeFiltersParser:
    @pytest.fixture()
    def log_group_time_parser(self):
        return LogGroupTimeFiltersParser("log_group_name")

    @pytest.mark.parametrize(
        "params, expected_error",
        [
            ({"start_time": "1623071000"}, "Invalid time filter, must be of type 'datetime'"),
            ({"start_time": datetime.datetime(2012, 7, 9)}, "Invalid time filter, must be of type 'datetime'"),
            ({"end_time": "1623071000"}, "Invalid time filter, must be of type 'datetime'"),
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
                {
                    "start_time": datetime.datetime(2012, 7, 9, tzinfo=datetime.timezone.utc),
                    "end_time": datetime.datetime(2012, 7, 29, tzinfo=datetime.timezone.utc),
                },
                {
                    "start_time": datetime.datetime(2012, 7, 9, tzinfo=datetime.timezone.utc),
                    "end_time": datetime.datetime(2012, 7, 29, tzinfo=datetime.timezone.utc),
                },
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
            assert_that(getattr(export_logs_filters, attr)).is_equal_to(expected_attrs.get(attr))  # noqa: B038

    @pytest.mark.parametrize(
        "attrs, event_in_window, log_stream_prefix, expected_error",
        [
            (
                {"end_time": datetime.datetime(2020, 6, 2, tzinfo=datetime.timezone.utc)},
                True,
                "test",
                "Start time must be earlier than end time",
            ),
            (
                {
                    "start_time": datetime.datetime(2020, 6, 7, tzinfo=datetime.timezone.utc),
                    "end_time": datetime.datetime(2020, 6, 2, tzinfo=datetime.timezone.utc),
                },
                True,
                "test",
                "Start time must be earlier than end time",
            ),
            (
                {"end_time": datetime.datetime(2021, 7, 9, 22, 45, 22, tzinfo=datetime.timezone.utc)},
                False,
                None,
                "No log events in the log group",
            ),
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
            ({"start_time": "wrong"}, "Invalid time filter"),
            ({"end_time": "1622802790248"}, "Invalid time filter"),
            ({"end_time": "1622802790"}, "Invalid time filter"),
            (
                {
                    "start_time": datetime.datetime(2021, 6, 2, 15, 15, 10, tzinfo=datetime.timezone.utc),
                    "end_time": datetime.datetime(2021, 6, 2, 15, 15, 10, tzinfo=datetime.timezone.utc),
                },
                None,
            ),
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
            assert_that(time_parser.start_time).is_equal_to(args.get("start_time"))
            assert_that(time_parser.end_time).is_equal_to(args.get("end_time"))


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
                download_objects_mock.assert_called_with("task_id", os.path.join("output_dir", "cloudwatch-logs"))

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

    def test_export_logs_to_s3_attaches_to_same_log_group_export_in_progress(self, cw_logs_exporter, mocker, capsys):
        """A running export for the same log group is adopted and tracked, not restarted."""
        mock_aws_api(mocker)
        mocker.patch(
            "pcluster.aws.logs.LogsClient.get_active_export_tasks",
            return_value=[
                {
                    "taskId": "running-task",
                    "logGroupName": "groupname",
                    "destination": "previous-bucket",
                    "destinationPrefix": "previous-prefix",
                    "executionInfo": {"creationTime": 1700000000000},
                }
            ],
        )
        create_task_mock = mocker.patch("pcluster.aws.logs.LogsClient.create_export_task")
        wait_mock = mocker.patch(
            "pcluster.models.common.CloudWatchLogsExporter._wait_for_task_completion", return_value="COMPLETED"
        )

        task_id = cw_logs_exporter._export_logs_to_s3()

        # We attach to the existing task rather than starting a new one.
        create_task_mock.assert_not_called()
        assert_that(task_id).is_equal_to("running-task")
        # Elapsed must be measured from the existing task's creation time, so it is passed through.
        wait_mock.assert_called_with("running-task", created_epoch_ms=1700000000000)
        # The existing task's S3 destination is adopted so download/cleanup target the right location.
        assert_that(cw_logs_exporter.bucket).is_equal_to("previous-bucket")
        assert_that(cw_logs_exporter.bucket_prefix).is_equal_to("previous-prefix")
        assert_that(cw_logs_exporter.delete_everything_under_prefix).is_false()
        assert_that(capsys.readouterr().err).contains("Attaching to it")

    def test_export_logs_to_s3_attached_task_failure_raises(self, cw_logs_exporter, mocker):
        """If the adopted in-progress task ends in a non-COMPLETED state, surface it as an error."""
        mock_aws_api(mocker)
        mocker.patch(
            "pcluster.aws.logs.LogsClient.get_active_export_tasks",
            return_value=[{"taskId": "running-task", "logGroupName": "groupname", "destinationPrefix": "p"}],
        )
        mocker.patch("pcluster.models.common.CloudWatchLogsExporter._wait_for_task_completion", return_value="FAILED")

        with pytest.raises(LogsExporterError, match="export task running-task failed with status: FAILED"):
            cw_logs_exporter._export_logs_to_s3()

    def test_export_logs_to_s3_blocks_when_other_log_group_export_in_progress(self, cw_logs_exporter, mocker):
        """A running export for a different log group (account-wide limit) yields a clear message."""
        mock_aws_api(mocker)
        mocker.patch(
            "pcluster.aws.logs.LogsClient.get_active_export_tasks",
            return_value=[{"taskId": "other-task", "logGroupName": "another-cluster-group"}],
        )
        create_task_mock = mocker.patch("pcluster.aws.logs.LogsClient.create_export_task")

        with pytest.raises(LogsExporterError) as exc_info:
            cw_logs_exporter._export_logs_to_s3()

        message = str(exc_info.value)
        assert_that(message).contains("account")
        assert_that(message).contains("another-cluster-group")
        create_task_mock.assert_not_called()

    def test_export_logs_to_s3_translates_limit_exceeded_error(self, cw_logs_exporter, mocker):
        """A LimitExceededException from create_export_task becomes a friendly 'already running' message."""
        mock_aws_api(mocker)
        # No task detected at pre-flight (empty), but create_export_task races into the account limit.
        mocker.patch("pcluster.aws.logs.LogsClient.get_active_export_tasks", return_value=[])
        mocker.patch(
            "pcluster.aws.logs.LogsClient.create_export_task",
            side_effect=AWSClientError("create_export_task", "Resource limit exceeded (LimitExceededException)"),
        )

        with pytest.raises(LogsExporterError) as exc_info:
            cw_logs_exporter._export_logs_to_s3()

        assert_that(str(exc_info.value)).contains("only one export task at a time")

    def test_wait_for_task_completion_reports_size_progress(self, cw_logs_exporter, mocker, capsys):
        """While polling, progress lines (with exported size) are written to stderr on each interval."""
        mock_aws_api(mocker)
        mocker.patch("pcluster.models.common.time.sleep")
        # Report on every poll for the test.
        mocker.patch("pcluster.models.common.EXPORT_LOGS_PROGRESS_INTERVAL_SECONDS", 0)
        mocker.patch(
            "pcluster.aws.logs.LogsClient.get_export_task_status",
            side_effect=["RUNNING", "RUNNING", "COMPLETED"],
        )
        mocker.patch(
            "pcluster.aws.s3_resource.S3Resource.get_objects",
            return_value=[SimpleNamespace(key="k1", size=1024), SimpleNamespace(key="k2", size=1024)],
        )

        status = cw_logs_exporter._wait_for_task_completion("task_id")

        assert_that(status).is_equal_to("COMPLETED")
        err = capsys.readouterr().err
        assert_that(err).contains("Started CloudWatch Logs export task task_id")
        assert_that(err).contains("exported so far")
        assert_that(err).contains("2.0 KB")
        assert_that(err).contains("finished")

    def test_wait_for_task_completion_falls_back_to_elapsed_when_size_unavailable(
        self, cw_logs_exporter, mocker, capsys
    ):
        """When the exported size can't be read, progress still shows an elapsed-time heartbeat."""
        mock_aws_api(mocker)
        mocker.patch("pcluster.models.common.time.sleep")
        mocker.patch("pcluster.models.common.EXPORT_LOGS_PROGRESS_INTERVAL_SECONDS", 0)
        mocker.patch("pcluster.aws.logs.LogsClient.get_export_task_status", side_effect=["RUNNING", "COMPLETED"])
        mocker.patch(
            "pcluster.aws.s3_resource.S3Resource.get_objects",
            side_effect=AWSClientError("get_objects", "denied"),
        )

        cw_logs_exporter._wait_for_task_completion("task_id")

        assert_that(capsys.readouterr().err).contains("no data written to S3 yet")

    def test_wait_for_task_completion_shows_waiting_until_first_bytes(self, cw_logs_exporter, mocker, capsys):
        """Before CloudWatch writes anything to S3, show a waiting heartbeat rather than a misleading '0 B'."""
        mock_aws_api(mocker)
        mocker.patch("pcluster.models.common.time.sleep")
        mocker.patch("pcluster.models.common.EXPORT_LOGS_PROGRESS_INTERVAL_SECONDS", 0)
        mocker.patch("pcluster.aws.logs.LogsClient.get_export_task_status", side_effect=["RUNNING", "COMPLETED"])
        # CloudWatch has not flushed any objects yet -> 0 bytes exported.
        mocker.patch("pcluster.aws.s3_resource.S3Resource.get_objects", return_value=[])

        cw_logs_exporter._wait_for_task_completion("task_id")

        err = capsys.readouterr().err
        assert_that(err).contains("no data written to S3 yet")
        assert_that(err).does_not_contain("0 B")

    def test_wait_for_task_completion_measures_elapsed_from_creation_time(self, cw_logs_exporter, mocker, capsys):
        """When a task's creation time is supplied, elapsed reflects the task's true age, not our wait time."""
        mock_aws_api(mocker)
        mocker.patch("pcluster.models.common.time.sleep")
        mocker.patch("pcluster.models.common.EXPORT_LOGS_PROGRESS_INTERVAL_SECONDS", 0)
        mocker.patch("pcluster.aws.logs.LogsClient.get_export_task_status", side_effect=["RUNNING", "COMPLETED"])
        mocker.patch(
            "pcluster.aws.s3_resource.S3Resource.get_objects",
            return_value=[SimpleNamespace(key="k", size=1024)],
        )
        # Task was created 300 seconds ago.
        created_epoch_ms = int((time.time() - 300) * 1000)

        cw_logs_exporter._wait_for_task_completion("task_id", created_epoch_ms=created_epoch_ms)

        err = capsys.readouterr().err
        elapsed_values = [int(match) for match in re.findall(r"elapsed (\d+)s", err)]
        assert_that(elapsed_values).is_not_empty()
        # Every reported elapsed reflects the ~300s task age rather than the near-zero local wait.
        assert_that(min(elapsed_values)).is_greater_than_or_equal_to(300)
        finished_values = [int(match) for match in re.findall(r"finished after (\d+)s", err)]
        assert_that(finished_values[0]).is_greater_than_or_equal_to(300)

    def test_download_reports_progress(self, cw_logs_exporter, mocker, tmp_path, capsys):
        """The download phase reports the object count/size to stderr."""
        mock_aws_api(mocker)
        cw_logs_exporter.bucket_prefix = "test_prefix"

        def fake_download_file(bucket_name, key, output):
            with gzip.open(output, "wb") as gzipped:
                gzipped.write(b"log data")

        mocker.patch(
            "pcluster.aws.s3_resource.S3Resource.get_objects",
            return_value=[SimpleNamespace(key="test_prefix/task_id/ip-10-0-0-1/000000.gz", size=8)],
        )
        mocker.patch("pcluster.aws.s3_resource.S3Resource.download_file", side_effect=fake_download_file)

        cw_logs_exporter._download_s3_objects_with_prefix("task_id", str(tmp_path / "cloudwatch-logs"))

        err = capsys.readouterr().err
        assert_that(err).contains("Downloading 1 log object(s)")
        assert_that(err).contains("Downloaded 1 of 1 log object(s)")

    def test_download_parallelizes_distinct_objects(self, cw_logs_exporter, mocker, tmp_path, capsys):
        """Distinct objects are downloaded (in parallel) and all counted; every object is fetched once."""
        mock_aws_api(mocker)
        cw_logs_exporter.bucket_prefix = "test_prefix"

        def fake_download_file(bucket_name, key, output):
            with gzip.open(output, "wb") as gzipped:
                gzipped.write(b"log data")

        objects = [SimpleNamespace(key=f"test_prefix/task_id/ip-10-0-0-{i}/000000.gz", size=8) for i in range(1, 4)]
        mocker.patch("pcluster.aws.s3_resource.S3Resource.get_objects", return_value=objects)
        download_mock = mocker.patch(
            "pcluster.aws.s3_resource.S3Resource.download_file", side_effect=fake_download_file
        )

        destdir = str(tmp_path / "cloudwatch-logs")
        cw_logs_exporter._download_s3_objects_with_prefix("task_id", destdir)

        assert_that(download_mock.call_count).is_equal_to(3)
        assert_that(capsys.readouterr().err).contains("Downloaded 3 of 3 log object(s)")
        # Each distinct stream produced its own local file.
        for i in range(1, 4):
            assert_that(os.path.isfile(os.path.join(destdir, f"ip-10-0-0-{i}"))).is_true()

    def test_download_groups_objects_mapping_to_same_file(self, cw_logs_exporter, mocker, tmp_path):
        """Objects resolving to the same local path are handled in one group (no concurrent writes)."""
        mock_aws_api(mocker)
        cw_logs_exporter.bucket_prefix = "test_prefix"

        group_calls = {}

        original = CloudWatchLogsExporter._download_object_group

        def tracking_group(self, decompressed_path, archive_objects):
            group_calls[decompressed_path] = len(archive_objects)
            return original(self, decompressed_path, archive_objects)

        mocker.patch.object(CloudWatchLogsExporter, "_download_object_group", tracking_group)

        def fake_download_file(bucket_name, key, output):
            with gzip.open(output, "wb") as gzipped:
                gzipped.write(b"log data")

        # Two objects for the same stream must land in a single group of size 2.
        objects = [
            SimpleNamespace(key="test_prefix/task_id/ip-10-0-0-1/000000.gz", size=8),
            SimpleNamespace(key="test_prefix/task_id/ip-10-0-0-1/000001.gz", size=8),
        ]
        mocker.patch("pcluster.aws.s3_resource.S3Resource.get_objects", return_value=objects)
        mocker.patch("pcluster.aws.s3_resource.S3Resource.download_file", side_effect=fake_download_file)

        cw_logs_exporter._download_s3_objects_with_prefix("task_id", str(tmp_path / "cloudwatch-logs"))

        assert_that(list(group_calls.values())).is_equal_to([2])

    @pytest.mark.parametrize(
        "path_relative_to_parent, expected",
        [
            ("child", True),
            (os.path.join("nested", "child"), True),
            (".", True),
            ("foo..bar", True),  # embedded dots are a legitimate single component, not a traversal
            (os.path.join("..", "escape"), False),
            (os.path.join("a", "..", "..", "escape"), False),
            (os.path.join("..", "..", "..", "etc", "cron.d", "evil"), False),
        ],
    )
    def test_is_path_contained(self, tmp_path, path_relative_to_parent, expected):
        parent_dir = str(tmp_path)
        candidate = os.path.join(parent_dir, path_relative_to_parent)
        assert_that(CloudWatchLogsExporter._is_path_contained(candidate, parent_dir)).is_equal_to(expected)


@pytest.mark.parametrize(
    "num_bytes, expected",
    [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024 * 1024, "1.0 MB"),
        (5 * 1024 * 1024 * 1024, "5.0 GB"),
        (3 * 1024 * 1024 * 1024 * 1024, "3.0 TB"),
    ],
)
def test_format_bytes(num_bytes, expected):
    assert_that(format_bytes(num_bytes)).is_equal_to(expected)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("my-cluster", "my-cluster"),  # ordinary name is unchanged
        ("cluster_1.2", "cluster_1.2"),  # dots and underscores are preserved
        (
            "arn:aws:cloudformation:us-east-1:447714826191:stack/integ-tests-x/c8ea7a80",
            "arn_aws_cloudformation_us-east-1_447714826191_stack_integ-tests-x_c8ea7a80",
        ),  # ARN separators become safe underscores
    ],
)
def test_sanitize_path_component(name, expected):
    result = sanitize_path_component(name)
    assert_that(result).is_equal_to(expected)
    # The result never contains path separators or drive/colon markers.
    assert_that(result).does_not_contain("/")
    assert_that(result).does_not_contain(os.sep)
    assert_that(result).does_not_contain(":")


def test_export_stack_events_creates_missing_parent_dirs(mocker, tmp_path):
    """export_stack_events must create the parent directory before writing (defends against odd paths)."""
    mocker.patch("pcluster.models.common.get_all_stack_events", return_value=[{"event": 1}])
    output_file = str(tmp_path / "does" / "not" / "exist" / "events.json")

    export_stack_events("stack-name", output_file)

    assert_that(os.path.isfile(output_file)).is_true()
