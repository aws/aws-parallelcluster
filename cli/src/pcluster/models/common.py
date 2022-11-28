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
import json
import logging
import os
import os.path
import tarfile
import time
from typing import List

import configparser

from pcluster.api.encoder import JSONEncoder
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError, get_region
from pcluster.utils import datetime_to_epoch, to_utc_datetime, yaml_load

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
        # Export logs to S3
        task_id = self._export_logs_to_s3(log_stream_prefix=log_stream_prefix, start_time=start_time, end_time=end_time)
        LOGGER.info("Log export task id: %s", task_id)
        # Download exported S3 objects to output dir subfolder
        try:
            log_streams_dir = os.path.join(self.output_dir, "cloudwatch-logs")
            self._download_s3_objects_with_prefix(task_id, log_streams_dir)
            LOGGER.info("Archive of CloudWatch logs saved to %s", self.output_dir)
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
            raise LogsExporterError(f"Unexpected error when starting export task: {e}")

    @staticmethod
    def _wait_for_task_completion(task_id):
        """Wait for the CloudWatch logs export task given by task_id to finish."""
        LOGGER.debug("Waiting for export task with task ID=%s to finish...", task_id)
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
    stack_events = []
    chunk = AWSApi.instance().cfn.get_stack_events(stack_name)
    stack_events.append(chunk["StackEvents"])
    while chunk.get("nextToken"):
        chunk = AWSApi.instance().cfn.get_stack_events(stack_name, next_token=chunk["nextToken"])
        stack_events.append(chunk["StackEvents"])

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
