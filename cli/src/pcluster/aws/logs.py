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
import json

from pcluster.aws.common import AWSClientError, AWSExceptionHandler, Boto3Client
from pcluster.utils import datetime_to_epoch


class LogsClient(Boto3Client):
    """Logs Boto3 client."""

    def __init__(self):
        super().__init__("logs")

    def log_group_exists(self, log_group_name):
        """Return true if log group exists, false otherwise."""
        try:
            self.describe_log_group(log_group_name)
            return True
        except AWSClientError:
            return False

    @AWSExceptionHandler.handle_client_exception
    def delete_log_group(self, log_group_name):
        """Delete log group by given log group name."""
        self._client.delete_log_group(logGroupName=log_group_name)

    @AWSExceptionHandler.handle_client_exception
    def describe_log_groups(self, log_group_name_prefix=None):
        """Return a list of log groups ."""
        return list(self._paginate_results(self._client.describe_log_groups, logGroupNamePrefix=log_group_name_prefix))

    @AWSExceptionHandler.handle_client_exception
    def describe_log_group(self, log_group_name):
        """Return log group identified by the given log group name."""
        for group in self.describe_log_groups(log_group_name_prefix=log_group_name):
            if group.get("logGroupName") == log_group_name:
                return group
        raise AWSClientError(function_name="describe_log_groups", message=f"Log Group {log_group_name} not found")

    @AWSExceptionHandler.handle_client_exception
    def filter_log_events(self, log_group_name, start_time=None, end_time=None, log_stream_name_prefix=None):
        """Return the list of events included in a specific time window for a given group name."""
        kwargs = {"logGroupName": log_group_name, "limit": 1}
        if start_time:
            kwargs["startTime"] = start_time
        if end_time:
            kwargs["endTime"] = end_time
        if log_stream_name_prefix:
            kwargs["logStreamNamePrefix"] = log_stream_name_prefix
        return self._client.filter_log_events(**kwargs).get("events")

    @AWSExceptionHandler.handle_client_exception
    def get_log_events(
        self,
        log_group_name,
        log_stream_name,
        start_time=None,
        end_time=None,
        limit=None,
        start_from_head=None,
        next_token=None,
    ):
        """Return the list of events included in a specific time window for a given log stream."""
        kwargs = {"logGroupName": log_group_name, "logStreamName": log_stream_name}
        if start_time:
            kwargs["startTime"] = start_time
        if end_time:
            kwargs["endTime"] = end_time
        if limit:
            kwargs["limit"] = limit
        if start_from_head is not None:
            kwargs["startFromHead"] = start_from_head
        if next_token:
            kwargs["nextToken"] = next_token
        return self._client.get_log_events(**kwargs)

    @AWSExceptionHandler.handle_client_exception
    def create_export_task(
        self,
        log_group_name,
        bucket,
        bucket_prefix=None,
        log_stream_name_prefix=None,
        start_time: datetime.datetime = None,
        end_time: datetime.datetime = None,
    ):
        """Start the task that will export a log group name to an s3 bucket, and return the task ID."""
        kwargs = {
            "logGroupName": log_group_name,
            "fromTime": start_time and datetime_to_epoch(start_time),
            "to": end_time and datetime_to_epoch(end_time),
            "destination": bucket,
            "destinationPrefix": bucket_prefix,
        }
        if log_stream_name_prefix:
            kwargs["logStreamNamePrefix"] = log_stream_name_prefix
        return self._client.create_export_task(**kwargs).get("taskId")

    @AWSExceptionHandler.handle_client_exception
    def get_export_task_status(self, task_id):
        """Get the status for the CloudWatch export task with the given task_id."""
        tasks = self._client.describe_export_tasks(taskId=task_id).get("exportTasks", None)
        if not tasks:
            raise AWSClientError(function_name="describe_export_tasks", message=f"Log export task {task_id} not found")
        if len(tasks) > 2:
            raise AWSClientError(
                function_name="describe_export_tasks",
                message="More than one CloudWatch logs export task with ID={task_id}:\n{tasks}".format(
                    task_id=task_id, tasks=json.dumps(tasks, indent=2)
                ),
            )
        return tasks[0].get("status").get("code")

    @AWSExceptionHandler.handle_client_exception
    def describe_log_streams(self, log_group_name, log_stream_name_prefix=None, next_token=None):
        """Return a list of log streams in the given log group, filtered by the given prefix."""
        kwargs = {"logGroupName": log_group_name}
        if log_stream_name_prefix:
            kwargs["logStreamNamePrefix"] = log_stream_name_prefix
        if next_token:
            kwargs["nextToken"] = next_token
        return self._client.describe_log_streams(**kwargs)
