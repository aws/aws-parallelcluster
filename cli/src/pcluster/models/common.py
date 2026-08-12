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
import concurrent.futures
import datetime
import gzip
import json
import logging
import os
import os.path
import re
import sys
import tarfile
import time
from typing import List

import configparser

from pcluster.api.encoder import JSONEncoder
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError, get_region
from pcluster.utils import datetime_to_epoch, to_utc_datetime, yaml_load

LOGGER = logging.getLogger(__name__)

# How often (seconds) to emit human-readable export/download progress to stderr. The status is polled
# more frequently than this; progress is throttled to this interval to keep the output readable and to
# avoid an S3 ListObjects call on every poll.
EXPORT_LOGS_PROGRESS_INTERVAL_SECONDS = 15

# Number of objects to download from S3 in parallel. An export can produce tens of thousands of small
# objects; downloading them serially is slow. Downloads are I/O-bound, so a thread pool helps a lot.
# Kept at botocore's default connection-pool size (10) so we don't exhaust the pool (which would serialize
# requests and emit "connection pool is full" warnings).
EXPORT_LOGS_DOWNLOAD_MAX_WORKERS = 10


def format_bytes(num_bytes: float) -> str:
    """Return a human-readable size string (e.g. '512 B', '4.2 KB', '1.3 GB') for a byte count."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class LimitExceeded(Exception):
    """Base exception type for errors caused by exceeding the limit of some underlying AWS service."""

    pass


class BadRequest(Exception):
    """Base exception type for errors caused by problems in the request."""

    pass


class Conflict(Exception):
    """Base exception type for errors caused by some conflict (such as a resource already existing)."""

    pass


class NotFound(Exception):
    """Base exception type for errors caused by resource not existing."""

    pass


def parse_config(config: str) -> dict:
    """Parse a YAML configuration into a dictionary."""
    try:
        config_dict = yaml_load(config)
        if not isinstance(config_dict, dict):
            LOGGER.error("Failed: parsed config is not a dict")
            raise Exception("Parsed config is not a dict")
        return config_dict
    except Exception as e:
        try:
            configparser.ConfigParser().read_string(config)
        except Exception:
            LOGGER.error("Failed when parsing the configuration due to invalid YAML document: %s", e)
            raise BadRequest("Configuration must be a valid YAML document. %s" % e)
        LOGGER.error("Please use pcluster3 configuration file format: %s", e)
        raise BadRequest(
            "ParallelCluster 3 requires configuration files to be valid YAML documents. "
            "To create a basic cluster configuration, you can run the `pcluster configure` command. "
            "To convert from ParallelCluster 2 configuration files, please run "
            "`pcluster3-config-converter --config-file <input_file> --output-file <output_file>`."
        )


class FiltersParserError(Exception):
    """Represent export logs filter errors."""

    def __init__(self, message: str):
        super().__init__(message)


class LogGroupTimeFiltersParser:
    """Class to manage start-time and end-time filters for a log group."""

    def __init__(self, log_group_name: str, start_time: datetime.datetime = None, end_time: datetime.datetime = None):
        self._log_group_name = log_group_name
        if (
            start_time and (not isinstance(start_time, datetime.datetime) or start_time.tzinfo != datetime.timezone.utc)
        ) or (end_time and (not isinstance(end_time, datetime.datetime) or end_time.tzinfo != datetime.timezone.utc)):
            raise FiltersParserError("Invalid time filter, must be of type 'datetime' with utc timezone.")
        self._start_time = start_time
        now_utc = datetime.datetime.now().astimezone(datetime.timezone.utc)
        self.end_time = end_time or now_utc

    @property
    def start_time(self):
        """Get start time filter."""
        if not self._start_time:
            try:
                creation_time = AWSApi.instance().logs.describe_log_group(self._log_group_name).get("creationTime")
                self._start_time = to_utc_datetime(creation_time)
            except AWSClientError as e:
                raise FiltersParserError(
                    f"Unable to retrieve creation time of log group {self._log_group_name}, {str(e)}"
                )
        return self._start_time

    def validate(self, log_stream_prefix=None):
        """Check filter consistency."""
        if self.start_time >= self.end_time:
            raise FiltersParserError("Start time must be earlier than end time.")

        event_in_window = AWSApi.instance().logs.filter_log_events(
            log_group_name=self._log_group_name,
            log_stream_name_prefix=log_stream_prefix,
            start_time=datetime_to_epoch(self.start_time),
            end_time=datetime_to_epoch(self.end_time),
        )
        if not event_in_window:
            raise FiltersParserError(
                f"No log events in the log group {self._log_group_name} in interval starting "
                f"at {self.start_time} and ending at {self.end_time}"
                + (f", with log stream name prefix '{log_stream_prefix}'" if log_stream_prefix else "")
            )


class LogsExporterError(Exception):
    """Represent logs coming from export tasks."""

    def __init__(self, message: str):
        super().__init__(message)


class CloudWatchLogsExporter:
    """Utility class used to export log group logs."""

    def __init__(self, resource_id, log_group_name, bucket, output_dir, bucket_prefix=None, keep_s3_objects=False):
        # check bucket
        bucket_region = AWSApi.instance().s3.get_bucket_region(bucket_name=bucket)
        if bucket_region != get_region():
            raise LogsExporterError(
                f"The bucket used for exporting logs must be in the same region as the {resource_id}. "
                f"The given resource is in {get_region()}, but the bucket's region is {bucket_region}."
            )
        self.bucket = bucket
        self.log_group_name = log_group_name
        self.output_dir = output_dir
        self.keep_s3_objects = keep_s3_objects

        if bucket_prefix:
            self.bucket_prefix = bucket_prefix
            self.delete_everything_under_prefix = False
        else:
            # If the default bucket prefix is being used and there's nothing underneath that prefix already
            # then we can delete everything under that prefix after downloading the data
            # (unless keep-s3-objects is specified)
            self.bucket_prefix = f"{resource_id}-logs-{datetime.datetime.now().strftime('%Y%m%d%H%M')}"
            self.delete_everything_under_prefix = AWSApi.instance().s3_resource.is_empty(bucket, self.bucket_prefix)

    def execute(self, log_stream_prefix=None, start_time: datetime.datetime = None, end_time: datetime.datetime = None):
        """Start export task. Returns logs streams folder."""
        self._operation_start_time = time.time()
        # Count and report the number of log streams to be exported
        stream_count = self._count_log_streams(log_stream_prefix)
        self._report_progress(
            f"Exporting {stream_count} log stream(s) from log group {self.log_group_name}..."
        )
        # Export logs to S3
        task_id = self._export_logs_to_s3(log_stream_prefix=log_stream_prefix, start_time=start_time, end_time=end_time)
        LOGGER.info("Log export task id: %s", task_id)
        # Download exported S3 objects to output dir subfolder
        try:
            log_streams_dir = os.path.join(self.output_dir, "cloudwatch-logs")
            self._download_s3_objects_with_prefix(task_id, log_streams_dir)
            LOGGER.info("Archive of CloudWatch logs saved to %s", self.output_dir)
            self._report_progress("CloudWatch logs export complete.")
        except OSError:
            raise LogsExporterError("Unable to download archive logs from S3, double check your filters are correct.")
        finally:
            if not self.keep_s3_objects:
                if self.delete_everything_under_prefix:
                    delete_key = self.bucket_prefix
                else:
                    delete_key = "/".join((self.bucket_prefix, task_id))
                LOGGER.debug("Cleaning up S3 bucket %s. Deleting all objects under %s", self.bucket, delete_key)
                AWSApi.instance().s3_resource.delete_objects(bucket_name=self.bucket, prefix=delete_key)

    def _export_logs_to_s3(
        self, log_stream_prefix=None, start_time: datetime.datetime = None, end_time: datetime.datetime = None
    ):
        """Export the contents of an image's CloudWatch log group to an s3 bucket."""
        # CloudWatch Logs allows only one active export task per account. If one is already running for
        # this same log group (e.g. the user interrupted a previous invocation, whose task keeps running
        # server-side, and reran), attach to it and track it to completion instead of failing.
        adopted_task_id = self._handle_active_export_tasks(self._get_active_export_tasks())
        if adopted_task_id:
            return adopted_task_id

        try:
            LOGGER.debug("Starting export of logs from log group %s to s3 bucket %s", self.log_group_name, self.bucket)
            task_id = AWSApi.instance().logs.create_export_task(
                log_group_name=self.log_group_name,
                log_stream_name_prefix=log_stream_prefix,
                bucket=self.bucket,
                bucket_prefix=self.bucket_prefix,
                start_time=start_time,
                end_time=end_time,
            )

            result_status = self._wait_for_task_completion(task_id)
            if result_status != "COMPLETED":
                raise LogsExporterError(f"CloudWatch logs export task {task_id} failed with status: {result_status}")
            return task_id
        except AWSClientError as e:
            # TODO use log type/class
            if "Please check if CloudWatch Logs has been granted permission to perform this operation." in str(e):
                raise LogsExporterError(
                    f"CloudWatch Logs needs GetBucketAcl and PutObject permission for the s3 bucket {self.bucket}. "
                    "See https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/S3ExportTasks.html#S3Permissions "
                    "for more details."
                )
            # A concurrent export task may have started between the pre-flight check and create_export_task
            # (or the pre-flight listing failed). Re-check: attach if it is ours, else give clear guidance.
            if "LimitExceededException" in str(e) or "Resource limit exceeded" in str(e):
                adopted_task_id = self._handle_active_export_tasks(self._get_active_export_tasks())
                if adopted_task_id:
                    return adopted_task_id
                raise LogsExporterError(
                    "A CloudWatch Logs export task is already running for this account. CloudWatch Logs allows "
                    "only one export task at a time; please wait for it to complete before retrying."
                )
            raise LogsExporterError(f"Unexpected error when starting export task: {e}")

    @staticmethod
    def _get_active_export_tasks():
        """Return the account's active (PENDING/RUNNING) export tasks; [] on any failure (best-effort)."""
        try:
            return AWSApi.instance().logs.get_active_export_tasks() or []
        except Exception as e:  # best-effort: never let this check block the export
            LOGGER.debug("Could not list in-progress export tasks: %s", e)
            return []

    def _handle_active_export_tasks(self, active_tasks):
        """Resolve what to do given the account's active export tasks.

        - No active task: return None (the caller starts a new export).
        - An active task for this same log group: attach to it, track it to completion, and return its
          task id (the caller then downloads its output).
        - An active task for a different log group: it holds the single account-wide export slot and its
          output is not ours to download, so raise a clear "please wait" error.
        """
        if not active_tasks:
            return None
        same_log_group_task = next(
            (task for task in active_tasks if task.get("logGroupName") == self.log_group_name), None
        )
        if same_log_group_task:
            return self._attach_to_in_progress_export(same_log_group_task)

        task = active_tasks[0]
        created = task.get("executionInfo", {}).get("creationTime")
        started_clause = f", started at {to_utc_datetime(created)}" if created else ""
        raise LogsExporterError(
            f"Another CloudWatch Logs export task is already running for this account "
            f"(task {task.get('taskId')}, log group '{task.get('logGroupName')}'{started_clause}). CloudWatch Logs "
            "allows only one export task at a time; please wait for it to complete before retrying."
        )

    def _attach_to_in_progress_export(self, task):
        """Attach to an already-running export task for this log group and track it to completion.

        The running task was created by an earlier invocation, so it writes to that invocation's S3
        destination. Adopt the task's destination bucket/prefix so progress reporting, download, and
        cleanup all target the right location, then wait for it with the same progress output as a task
        we started ourselves.
        """
        task_id = task.get("taskId")
        destination = task.get("destination")
        destination_prefix = task.get("destinationPrefix")
        if destination:
            self.bucket = destination
        if destination_prefix:
            self.bucket_prefix = destination_prefix
            # We did not create this prefix, so only clean up what belongs to this task, not the whole prefix.
            self.delete_everything_under_prefix = False

        created = task.get("executionInfo", {}).get("creationTime")
        started_clause = f", started at {to_utc_datetime(created)}" if created else ""
        self._report_progress(
            f"An export task for log group '{self.log_group_name}' is already running (task {task_id}"
            f"{started_clause}). Tracking it instead of starting a new one."
        )

        result_status = self._wait_for_task_completion(task_id, created_epoch_ms=created)
        if result_status != "COMPLETED":
            raise LogsExporterError(f"CloudWatch logs export task {task_id} failed with status: {result_status}")
        return task_id

    def _wait_for_task_completion(self, task_id, created_epoch_ms=None):
        """Wait for the CloudWatch logs export task given by task_id to finish.

        Emits human-readable progress to stderr on a fixed interval so the command does not appear hung.
        The CloudWatch DescribeExportTasks API exposes no progress/ETA, so progress is derived from the
        size of the objects the export has written to S3 so far (a real, monotonically increasing signal).

        ``created_epoch_ms`` is the task's CloudWatch creation time (epoch milliseconds). When provided,
        elapsed time is measured from it so it reflects the task's true age -- important when attaching to
        a task an earlier invocation started. When omitted, elapsed is measured from now.
        """
        LOGGER.debug("Waiting for export task with task ID=%s to finish...", task_id)
        status = "PENDING"
        still_running_statuses = ("PENDING", "PENDING_CANCEL", "RUNNING")
        start_time = created_epoch_ms / 1000 if created_epoch_ms else time.time()
        last_report_time = time.time()
        self._report_progress(
            f"Started CloudWatch Logs export task {task_id}. Waiting for it to complete... "
            "(CloudWatch buffers logs and usually writes them to S3 near the end of the task, so the "
            "exported size may stay at 0 for several minutes.)"
        )
        while status in still_running_statuses:
            time.sleep(1)
            status = AWSApi.instance().logs.get_export_task_status(task_id)
            now = time.time()
            if now - last_report_time >= EXPORT_LOGS_PROGRESS_INTERVAL_SECONDS:
                self._report_export_progress(task_id, elapsed_seconds=now - start_time)
                last_report_time = now
        self._report_progress(f"Export task {task_id} finished after {int(time.time() - start_time)}s.")
        return status

    def _report_export_progress(self, task_id, elapsed_seconds):
        """Emit a progress line for the export phase, including bytes exported to S3 so far when available.

        Until CloudWatch starts flushing objects to S3 the exported size is 0; showing "0 B" repeatedly
        looks stuck, so a plain "still exporting" heartbeat is emitted until the first bytes appear.
        """
        exported_bytes = self._exported_bytes_so_far(task_id)
        elapsed = int(elapsed_seconds)
        # exported_bytes is None (could not read) or 0 until CloudWatch starts flushing objects to S3.
        progress = f"{format_bytes(exported_bytes)} exported so far" if exported_bytes else "no data written to S3 yet"
        self._report_progress(f"Exporting logs from CloudWatch: {progress} (elapsed {elapsed}s)")

    def _exported_bytes_so_far(self, task_id):
        """Return the total size of objects the export task has written to S3 so far, or None on failure."""
        prefix = f"{self.bucket_prefix}/{task_id}"
        try:
            return sum(obj.size for obj in AWSApi.instance().s3_resource.get_objects(self.bucket, prefix))
        except Exception as e:  # best-effort progress signal; never fail the export because of it
            LOGGER.debug("Could not compute exported size so far for task %s: %s", task_id, e)
            return None

    @staticmethod
    def _report_progress(message):
        """Emit a user-facing progress line to stderr.

        The default CLI logger writes only to a rotating log file, so progress must go to stderr to be
        visible; stdout is left clean for the command's own output.
        """
        print(message, file=sys.stderr, flush=True)

    def _count_log_streams(self, log_stream_prefix=None):
        """Return the number of log streams in the log group matching the optional prefix."""
        count = 0
        next_token = None
        while True:
            response = AWSApi.instance().logs.describe_log_streams(
                log_group_name=self.log_group_name,
                log_stream_name_prefix=log_stream_prefix,
                next_token=next_token,
            )
            count += len(response.get("logStreams", []))
            next_token = response.get("nextToken")
            if not next_token:
                break
        return count

    def _download_s3_objects_with_prefix(self, task_id, destdir):
        """Download all objects in bucket with the given prefix into destdir, in parallel."""
        prefix = f"{self.bucket_prefix}/{task_id}"
        LOGGER.debug("Downloading exported logs from s3 bucket %s (under key %s) to %s", self.bucket, prefix, destdir)
        objects = list(AWSApi.instance().s3_resource.get_objects(bucket_name=self.bucket, prefix=prefix))

        # Group objects by their resolved local destination. Objects that map to the same file are handled
        # sequentially within one group (preserving the existing last-writer-wins behavior and avoiding
        # concurrent writes to the same path); distinct files are downloaded in parallel across groups.
        object_groups = {}
        for archive_object in objects:
            decompressed_path = self._resolve_local_path(archive_object.key, destdir, prefix)
            # Defend against path traversal: an S3 object key (derived from a CloudWatch log stream name) may
            # contain '..' path segments that would escape destdir and overwrite arbitrary local files. Verify
            # the resolved destination is still contained within destdir before writing anything to disk.
            if not self._is_path_contained(decompressed_path, destdir):
                LOGGER.warning(
                    "Skipping S3 object with key=%s: resolved path %s escapes the export directory %s",
                    archive_object.key,
                    decompressed_path,
                    destdir,
                )
                continue
            object_groups.setdefault(decompressed_path, []).append(archive_object)

        total_objects = sum(len(group) for group in object_groups.values())
        total_bytes = sum(archive_object.size for group in object_groups.values() for archive_object in group)
        if total_objects:
            self._report_progress(f"Downloading {total_objects} log object(s) ({format_bytes(total_bytes)}) from S3...")

        downloaded_objects = 0
        last_report_time = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=EXPORT_LOGS_DOWNLOAD_MAX_WORKERS) as executor:
            futures = [
                executor.submit(self._download_object_group, decompressed_path, group)
                for decompressed_path, group in object_groups.items()
            ]
            for future in concurrent.futures.as_completed(futures):
                downloaded_objects += future.result()
                now = time.time()
                if now - last_report_time >= EXPORT_LOGS_PROGRESS_INTERVAL_SECONDS:
                    elapsed = int(now - self._operation_start_time)
                    self._report_progress(
                        f"Downloaded {downloaded_objects}/{total_objects} log object(s)... (elapsed {elapsed}s)"
                    )
                    last_report_time = now

        if total_objects:
            elapsed = int(time.time() - self._operation_start_time)
            self._report_progress(
                f"Downloaded {downloaded_objects} of {total_objects} log object(s) "
                f"({format_bytes(total_bytes)}). (elapsed {elapsed}s)"
            )

    @staticmethod
    def _resolve_local_path(key, destdir, prefix):
        """Resolve the local file path an exported object maps to (the CloudWatch stream, minus the prefix)."""
        decompressed_path = os.path.dirname(os.path.join(destdir, key))
        return decompressed_path.replace(
            r"{unwanted_path_segment}{sep}".format(unwanted_path_segment=prefix, sep=os.path.sep), ""
        )

    def _download_object_group(self, decompressed_path, archive_objects):
        """Download and extract every object mapping to ``decompressed_path`` sequentially; return the count.

        Runs in a worker thread. Objects in the same group share a destination file, so they are processed
        in order (last writer wins, matching the previous serial behavior) to avoid corrupting the file.
        """
        compressed_path = f"{decompressed_path}.gz"
        os.makedirs(os.path.dirname(compressed_path), exist_ok=True)
        for archive_object in archive_objects:
            LOGGER.debug("Downloading object with key=%s to %s", archive_object.key, compressed_path)
            AWSApi.instance().s3_resource.download_file(
                bucket_name=self.bucket, key=archive_object.key, output=compressed_path
            )
            # Create a decompressed copy of the downloaded archive.
            LOGGER.debug("Extracting object at %s to %s", compressed_path, decompressed_path)
            with gzip.open(compressed_path) as gfile, open(decompressed_path, "wb") as outfile:
                outfile.write(gfile.read())
        if os.path.exists(compressed_path):
            os.remove(compressed_path)
        return len(archive_objects)

    @staticmethod
    def _is_path_contained(path, parent_dir):
        """Return True if path, once resolved, is located inside parent_dir (defends against '..' traversal)."""
        resolved_parent = os.path.realpath(parent_dir)
        resolved_path = os.path.realpath(path)
        # commonpath raises ValueError when the paths are on different drives (Windows); treat that as not contained.
        try:
            return os.path.commonpath([resolved_parent, resolved_path]) == resolved_parent
        except ValueError:
            return False


def get_all_stack_events(stack_name: str):
    """Retrieve all stack events."""
    stack_events = []
    chunk = AWSApi.instance().cfn.get_stack_events(stack_name)
    stack_events.append(chunk["StackEvents"])
    while chunk.get("nextToken"):
        chunk = AWSApi.instance().cfn.get_stack_events(stack_name, next_token=chunk["nextToken"])
        stack_events.append(chunk["StackEvents"])
    return stack_events


def sanitize_path_component(name: str) -> str:
    """Make ``name`` safe to use as a single local filesystem path component.

    A cluster/image identifier may be an ARN (e.g. when exporting logs from a deleted stack, which can
    only be referenced by ARN). ARNs contain '/' and ':', so using them verbatim in a file/dir name
    splits into unintended directories and breaks writes. Replace every character that is not
    alphanumeric or one of ``-._`` with '_'. Ordinary names (``[A-Za-z0-9-]``) are left unchanged.
    """
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def export_stack_events(stack_name: str, output_file: str):
    """Save CFN stack events into a file."""
    stack_events = get_all_stack_events(stack_name)

    # Ensure the parent directory exists before writing (defends against identifiers that expand paths).
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as cfn_events_file:
        cfn_events_file.write(json.dumps(stack_events, cls=JSONEncoder, indent=2))


def create_logs_archive(directory: str, output_file: str = None):
    base_directory = os.path.dirname(directory)
    base_name = os.path.basename(directory)
    output_file = output_file or f"{os.path.join(base_directory, base_name)}.tar.gz"
    LOGGER.debug("Creating archive of logs and saving it to %s", output_file)
    with tarfile.open(output_file, "w:gz") as tar:
        tar.add(directory, arcname=base_name)
    return output_file


def upload_archive(bucket: str, bucket_prefix: str, archive_path: str):
    archive_filename = os.path.basename(archive_path)
    with open(archive_path, "rb") as archive_file:
        archive_data = archive_file.read()
    bucket_path = f"{bucket_prefix}/{archive_filename}" if bucket_prefix else archive_filename
    AWSApi.instance().s3.put_object(bucket, archive_data, bucket_path)
    return f"s3://{bucket}/{bucket_path}"


class LogStreams:
    """Class to manage list of logs along with next_token."""

    def __init__(self, log_streams: List[dict] = None, next_token: str = None):
        self.log_streams = log_streams
        self.next_token = next_token


class LogStream:
    """Class to manage log events, for both CW logs and Stack logs."""

    def __init__(self, resource_id: str, log_stream_name: str, log_events_response: dict):
        """Initialize log events starting from a dict with the form {"events": ..., "nextForwardToken": ..., }."""
        self.resource_id = resource_id
        self.log_stream_name = log_stream_name
        self.events = log_events_response.get("events", [])
        # The next_tokens are not present when the log stream is the Stack Events log stream
        self.next_ftoken = log_events_response.get("nextForwardToken", None)
        self.next_btoken = log_events_response.get("nextBackwardToken", None)
