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
import json
import logging
from datetime import datetime
from typing import List

import yaml

from pcluster import utils
from pcluster.api.encoder import JSONEncoder
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
        raise BadRequest("Configuration must be a valid YAML document")


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

    def __init__(self, resource_id, log_group_name, bucket, bucket_prefix=None):
        # check bucket
        bucket_region = AWSApi.instance().s3.get_bucket_region(bucket_name=bucket)
        if bucket_region != get_region():
            raise LogsExporterError(
                f"The bucket used for exporting logs must be in the same region as the {resource_id}. "
                f"The given resource is in {get_region()}, but the bucket's region is {bucket_region}."
            )
        self.bucket = bucket
        self.log_group_name = log_group_name

        default_prefix = f"{resource_id}-logs-{datetime.now().strftime('%Y%m%d%H%M')}"
        self.bucket_prefix = bucket_prefix if bucket_prefix else default_prefix

    def execute(self, log_stream_prefix=None, start_time=None, end_time=None):
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


def export_stack_events(stack_name: str, bucket: str, bucket_prefix: str = None):
    """Save CFN stack events into a file."""
    # check bucket
    bucket_region = AWSApi.instance().s3.get_bucket_region(bucket_name=bucket)
    if bucket_region != get_region():
        raise LogsExporterError(
            f"The bucket used for exporting logs must be in the same region as the stack {stack_name}. "
            f"The given resource is in {get_region()}, but the bucket's region is {bucket_region}."
        )

    stack_events = AWSApi.instance().cfn.get_stack_events(stack_name)
    stack_events_str = json.dumps(stack_events, cls=JSONEncoder, indent=2)
    key = "cfn_stack_events"
    AWSApi.instance().s3.put_object(bucket, stack_events_str, f"{bucket_prefix}/{key}")
    return f"s3://{bucket}/{bucket_prefix}/{key}"


class Logs:
    """Class to manage list of logs, for both CW logs and Stack logs."""

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
