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
from datetime import datetime

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.utils import isoformat_to_epoch


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
                f"at {self.start_time} and ending at {self.end_time}" +
                f", with log stream name prefix '{log_stream_prefix}'" if log_stream_prefix else ""
            )
