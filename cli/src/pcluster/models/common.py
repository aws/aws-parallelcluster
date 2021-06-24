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
import gzip
import logging
import os
import tarfile
import time
from datetime import datetime

import yaml
from tabulate import tabulate

from pcluster import utils
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError, get_region
from pcluster.constants import STACK_EVENTS_LOG_STREAM_NAME_FORMAT
from pcluster.utils import isoformat_to_epoch

LOGGER = logging.getLogger(__name__)


class LimitExceeded(Exception):
    """Base exception type for errors caused by exceeding the limit of some underlying AWS service."""

    pass


class BadRequest(Exception):
    """Base exception type for errors caused by problems in the request."""

    pass


class Conflict(Exception):
    """Base exception type for errors caused by some conflict (such as a resource already existing)."""

    pass


def parse_config(config):
    """Parse a YAML configuration into a dictionary."""
    try:
        config_dict = yaml.safe_load(config)
        if not isinstance(config_dict, dict):
            LOGGER.error("Failed: parsed config is not a dict")
            raise Exception("parsed config is not a dict")
        return config_dict
    except Exception as e:
        LOGGER.error("Failed when parsing the configuration due to invalid YAML document: %s", e)
        raise BadRequest("configuration must be a valid YAML document")


class FiltersParserError(Exception):
    """Represent export logs filter errors."""

    def __init__(self, message: str):
        super().__init__(message)


class LogGroupTimeFiltersParser:
    """Class to manage start-time and end-time filters for a log group."""

    def __init__(self, log_group_name: str, start_time: str = None, end_time: str = None):
        self._log_group_name = log_group_name
        try:
            self._start_time = isoformat_to_epoch(start_time) if start_time else None
            self.end_time = isoformat_to_epoch(end_time) if end_time else int(datetime.now().timestamp() * 1000)
        except Exception as e:
            raise FiltersParserError(f"Unable to parse time. It must be in ISO8601 format. {e}")

    @property
    def start_time(self):
        """Get start time filter."""
        if not self._start_time:
            try:
                self._start_time = AWSApi.instance().logs.describe_log_group(self._log_group_name).get("creationTime")
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
            start_time=self.start_time,
            end_time=self.end_time,
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

        # If the default bucket prefix is being used and there's nothing underneath that prefix already
        # then we can delete everything under that prefix after downloading the data
        # (unless keep-s3-objects is specified)
        if bucket_prefix:
            self.bucket_prefix = bucket_prefix
            self.delete_everything_under_prefix = False
        else:
            self.bucket_prefix = f"{resource_id}-logs-{datetime.now().strftime('%Y%m%d%H%M')}"
            self.delete_everything_under_prefix = AWSApi.instance().s3_resource.is_empty(bucket, self.bucket_prefix)

    def execute(self, log_stream_prefix=None, start_time=None, end_time=None):
        """Start export task. Returns logs streams folder."""
        # Export logs to S3
        task_id = self._export_logs_to_s3(log_stream_prefix=log_stream_prefix, start_time=start_time, end_time=end_time)
        # Download exported S3 objects to output dir subfolder
        try:
            log_streams_dir = os.path.join(self.output_dir, self.bucket_prefix)
            self._download_s3_objects_with_prefix(task_id, log_streams_dir)
            LOGGER.debug("Archive of CloudWatch logs saved to %s", self.output_dir)
            return log_streams_dir
        except OSError:
            raise LogsExporterError("Unable to download archive logs from S3, double check your filters are correct.")
        finally:
            if not self.keep_s3_objects:
                if self.delete_everything_under_prefix:
                    delete_key = self.bucket_prefix
                else:
                    delete_key = "/".join((self.bucket_prefix, task_id))
                LOGGER.info("Cleaning up S3 bucket %s. Deleting all objects under %s", self.bucket, delete_key)
                AWSApi.instance().s3_resource.delete_objects(bucket_name=self.bucket, prefix=delete_key)

    def _export_logs_to_s3(self, log_stream_prefix=None, start_time=None, end_time=None):
        """Export the contents of a image's CloudWatch log group to an s3 bucket."""
        try:
            LOGGER.info("Starting export of logs from log group %s to s3 bucket %s", self.log_group_name, self.bucket)
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
            raise LogsExporterError(f"Unexpected error when starting export task: {e}")

    @staticmethod
    def _wait_for_task_completion(task_id):
        """Wait for the CloudWatch logs export task given by task_id to finish."""
        LOGGER.info("Waiting for export task with task ID=%s to finish...", task_id)
        status = "PENDING"
        still_running_statuses = ("PENDING", "PENDING_CANCEL", "RUNNING")
        while status in still_running_statuses:
            time.sleep(1)
            status = AWSApi.instance().logs.get_export_task_status(task_id)
        return status

    def _download_s3_objects_with_prefix(self, task_id, destdir):
        """Download all object in bucket with given prefix into destdir."""
        prefix = f"{self.bucket_prefix}/{task_id}"
        LOGGER.debug("Downloading exported logs from s3 bucket %s (under key %s) to %s", self.bucket, prefix, destdir)
        for archive_object in AWSApi.instance().s3_resource.get_objects(bucket_name=self.bucket, prefix=prefix):
            decompressed_path = os.path.dirname(os.path.join(destdir, archive_object.key))
            decompressed_path = decompressed_path.replace(
                r"{unwanted_path_segment}{sep}".format(unwanted_path_segment=prefix, sep=os.path.sep), ""
            )
            compressed_path = f"{decompressed_path}.gz"

            LOGGER.debug("Downloading object with key=%s to %s", archive_object.key, compressed_path)
            os.makedirs(os.path.dirname(compressed_path), exist_ok=True)
            AWSApi.instance().s3_resource.download_file(
                bucket_name=self.bucket, key=archive_object.key, output=compressed_path
            )

            # Create a decompressed copy of the downloaded archive and remove the original
            LOGGER.debug("Extracting object at %s to %s", compressed_path, decompressed_path)
            with gzip.open(compressed_path) as gfile, open(decompressed_path, "wb") as outfile:
                outfile.write(gfile.read())
            os.remove(compressed_path)


def export_stack_events(stack_name: str, output_file: str):
    """Save CFN stack events into a file."""
    stack_events = AWSApi.instance().cfn.get_stack_events(stack_name)
    with open(output_file, "w") as cfn_events_file:
        for event in stack_events:
            cfn_events_file.write("%s\n" % AWSApi.instance().cfn.format_event(event))


def create_logs_archive(files_to_archive: list, archive_file_path: str):
    LOGGER.debug("Creating archive of logs and saving it to %s", archive_file_path)
    with tarfile.open(archive_file_path, "w:gz") as tar:
        for file_name in files_to_archive:
            tar.add(file_name, arcname=os.path.basename(file_name))


class Logs:
    """Class to manage list of logs, for both CW logs and Stack logs."""

    def __init__(self, stack_log_streams: dict = None, cw_log_streams: dict = None):
        self.stack_log_streams = stack_log_streams
        self.cw_log_streams = cw_log_streams

    def print_stack_log_streams(self):
        """Print Stack Log streams."""
        if not self.stack_log_streams:
            print("No Stack logs available.\n")
        else:
            print("{}\n".format(tabulate(self.stack_log_streams, headers="keys", tablefmt="plain")))

    def print_cw_log_streams(self):
        """Print CloudWatch log streams."""
        if not self.cw_log_streams:
            print("No logs saved in CloudWatch.")
        else:
            # List CW log streams
            output_headers = {
                "logStreamName": "Log Stream Name",
                "firstEventTimestamp": "First Event",
                "lastEventTimestamp": "Last Event",
            }
            filtered_result = []
            for item in self.cw_log_streams.get("logStreams", []):
                filtered_item = {}
                for key, output_key in output_headers.items():
                    value = item.get(key)
                    if key.endswith("Timestamp"):
                        value = utils.timestamp_to_isoformat(value)
                    filtered_item[output_key] = value
                filtered_result.append(filtered_item)
            print(tabulate(filtered_result, headers="keys", tablefmt="plain"))
            if self.cw_log_streams.get("nextToken", None):
                print("\nnextToken is: %s", self.cw_log_streams["nextToken"])


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

    def print_events(self):
        """Print log stream events."""
        if self.log_stream_name == STACK_EVENTS_LOG_STREAM_NAME_FORMAT.format(self.resource_id):
            # Print CFN stack events
            for event in self.events:
                print(AWSApi.instance().cfn.format_event(event))
        else:
            # Print CW log stream events
            if not self.events:
                print("No events found.")
            else:
                for event in self.events:
                    print("{0}: {1}".format(utils.timestamp_to_isoformat(event["timestamp"]), event["message"]))

    def print_next_tokens(self):
        """Print next tokens."""
        if self.next_btoken:
            LOGGER.info("\nnextBackwardToken is: %s", self.next_btoken)
        if self.next_ftoken:
            LOGGER.info("nextForwardToken is: %s", self.next_ftoken)
