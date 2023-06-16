# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import logging
import time
from abc import ABCMeta, abstractmethod
from datetime import datetime, timezone
from enum import Enum

from boto3.dynamodb.conditions import Attr
from pkg_resources import packaging

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.constants import PCLUSTER_DYNAMODB_PREFIX

LOGGER = logging.getLogger(__name__)


class ComputeFleetStatus(Enum):
    """Represents the status of the cluster compute fleet."""

    STOPPED = "STOPPED"  # Fleet is stopped, partitions are inactive.
    RUNNING = "RUNNING"  # Fleet is running, partitions are active.
    STOPPING = "STOPPING"  # clustermgtd is handling the stop request.
    STARTING = "STARTING"  # clustermgtd is handling the start request.
    STOP_REQUESTED = "STOP_REQUESTED"  # A request to stop the fleet has been submitted.
    START_REQUESTED = "START_REQUESTED"  # A request to start the fleet has been submitted.
    ENABLED = "ENABLED"  # AWS Batch only. The compute environment is enabled
    DISABLED = "DISABLED"  # AWS Batch only. The compute environment is disabled
    UNKNOWN = "UNKNOWN"  # Cannot determine fleet status
    # PROTECTED indicates that some partitions have consistent bootstrap failures. Affected partitions are inactive.
    PROTECTED = "PROTECTED"

    def __str__(self):
        return str(self.value)

    @staticmethod
    def is_start_in_progress(status):
        """Return True if start is requested or in progress."""
        return status in {ComputeFleetStatus.START_REQUESTED, ComputeFleetStatus.STARTING}

    @staticmethod
    def is_stop_in_progress(status):
        """Return True if stop is requested or in progress."""
        return status in {ComputeFleetStatus.STOP_REQUESTED, ComputeFleetStatus.STOPPING}

    @staticmethod
    def is_stop_status(status):
        """Return True if status is any of the stop ones."""
        return status in {ComputeFleetStatus.STOP_REQUESTED, ComputeFleetStatus.STOPPING, ComputeFleetStatus.STOPPED}

    @staticmethod
    def is_start_status(status):
        """Return True if status is any of the start ones."""
        return status in {ComputeFleetStatus.START_REQUESTED, ComputeFleetStatus.STARTING, ComputeFleetStatus.RUNNING}


class ComputeFleetStatusManager(metaclass=ABCMeta):
    """Implement functionalities to retrieve and update the compute fleet status."""

    class ConditionalStatusUpdateFailed(Exception):
        """Raised when there is a failure in updating the status due to a change occurred after retrieving its value."""

        pass

    def __init__(self, table_name):
        self._table_name = table_name

    def get_status(self, fallback=ComputeFleetStatus.UNKNOWN):
        """Get compute fleet status."""
        status, _ = self.get_status_with_last_updated_time(status_fallback=fallback)
        return status

    def _wait_for_status_transition(self, wait_on_status, timeout=300, retry_every_seconds=15):
        current_status = self.get_status()
        start_time = time.time()
        while current_status == wait_on_status and not self._timeout_expired(start_time, timeout):
            current_status = self.get_status()
            time.sleep(retry_every_seconds)

        if current_status == wait_on_status:
            raise TimeoutError("Timeout expired while waiting for status transition.")

        return current_status

    def update_status(self, request_status, in_progress_status, final_status, wait_transition=False):
        """
        Update the status of the compute fleet and wait for a status transition.

        It updates the status of the fleet to request_status and then waits for it to be updated to final_status,
        by eventually transitioning through in_progress_status
        """
        compute_fleet_status = self.get_status()
        if compute_fleet_status == ComputeFleetStatus.UNKNOWN:
            raise Exception("Could not retrieve compute fleet status.")

        if compute_fleet_status == final_status:
            LOGGER.info("Compute fleet already in %s status.", final_status)
            return

        LOGGER.info("Compute fleet status is: %s. Submitting status change request.", compute_fleet_status)
        if compute_fleet_status not in {request_status, in_progress_status, final_status}:
            self._put_status(current_status=compute_fleet_status, next_status=request_status)

        if not wait_transition:
            LOGGER.info("Request submitted successfully. It might take a while for the transition to complete.")
            LOGGER.info("Please run 'pcluster status' if you need to check compute fleet status")
            return

        LOGGER.info("Submitted compute fleet status transition request. Waiting for status update to start...")
        compute_fleet_status = self._wait_for_status_transition(wait_on_status=request_status, timeout=180)
        if compute_fleet_status == in_progress_status:
            LOGGER.info(
                "Compute fleet status transition is in progress. This operation might take a while to complete..."
            )
            compute_fleet_status = self._wait_for_status_transition(wait_on_status=in_progress_status, timeout=600)

        if compute_fleet_status != final_status:
            raise Exception(
                "Unexpected final state {} probably due to a concurrent status update request.".format(
                    compute_fleet_status
                )
            )
        LOGGER.info("Compute fleet status updated successfully.")

    @abstractmethod
    def _put_status(self, current_status, next_status):
        """Set compute fleet status on DB."""
        pass

    @abstractmethod
    def get_status_with_last_updated_time(
        self, status_fallback=ComputeFleetStatus.UNKNOWN, last_updated_time_fallback=None
    ):
        """Get compute fleet status and the last compute fleet status updated time."""
        pass

    @staticmethod
    def get_manager(cluster_name, version):
        """Return compute fleet status manager based on version and plugin."""
        if packaging.version.parse(version) < packaging.version.parse("3.2.0a0"):
            return PlainTextComputeFleetStatusManager(cluster_name)
        else:
            return JsonComputeFleetStatusManager(cluster_name)

    @staticmethod
    def _timeout_expired(start_time, timeout):
        return (time.time() - start_time) > timeout


class JsonComputeFleetStatusManager(ComputeFleetStatusManager):
    """
    Implement functionalities to retrieve and update the compute fleet status.

    The value stored in the table is a json in the following form
    {
        "status": "STOPPING",
        "lastStatusUpdatedTime": "2021-12-21 18:12:07.485674+00:00",
    }
    """

    DB_KEY = "COMPUTE_FLEET"
    DB_DATA = "Data"

    COMPUTE_FLEET_STATUS_ATTRIBUTE = "status"
    COMPUTE_FLEET_LAST_UPDATED_TIME_ATTRIBUTE = "lastStatusUpdatedTime"

    QUEUES_ATTRIBUTE = "queues"
    QUEUE_STATUS_ATTRIBUTE = "status"
    QUEUE_LAST_UPDATED_TIME_ATTRIBUTE = "lastStatusUpdatedTime"

    def __init__(self, cluster_name):
        super().__init__(PCLUSTER_DYNAMODB_PREFIX + cluster_name)

    def get_status_with_last_updated_time(
        self, status_fallback=ComputeFleetStatus.UNKNOWN, last_updated_time_fallback=None
    ):
        """Get compute fleet status and the last compute fleet status updated time."""
        try:
            compute_fleet_item = AWSApi.instance().ddb_resource.get_item(self._table_name, {"Id": self.DB_KEY})
            if not compute_fleet_item or "Item" not in compute_fleet_item:
                raise Exception("COMPUTE_FLEET data not found in db table")
            return (
                ComputeFleetStatus(
                    compute_fleet_item["Item"].get(self.DB_DATA).get(self.COMPUTE_FLEET_STATUS_ATTRIBUTE)
                ),
                compute_fleet_item["Item"].get(self.DB_DATA).get(self.COMPUTE_FLEET_LAST_UPDATED_TIME_ATTRIBUTE),
            )
        except Exception as e:
            LOGGER.warning(
                "Failed when retrieving fleet status from DynamoDB with error %s. "
                "This is expected if cluster creation/deletion is in progress",
                e,
            )
            return status_fallback, last_updated_time_fallback

    def _put_status(self, current_status, next_status):
        """Set compute fleet status on DB."""
        try:
            AWSApi.instance().ddb_resource.update_item(
                self._table_name,
                key={"Id": self.DB_KEY},
                update_expression="set #dt.#st=:s, #dt.#lut=:t",
                expression_attribute_names={
                    "#dt": self.DB_DATA,
                    "#st": self.COMPUTE_FLEET_STATUS_ATTRIBUTE,
                    "#lut": self.COMPUTE_FLEET_LAST_UPDATED_TIME_ATTRIBUTE,
                },
                expression_attribute_values={
                    ":s": str(next_status),
                    ":t": str(datetime.now(tz=timezone.utc)),
                },
                condition_expression=Attr(f"{self.DB_DATA}.{self.COMPUTE_FLEET_STATUS_ATTRIBUTE}").eq(
                    str(current_status)
                ),
            )
        except AWSClientError as e:
            if e.error_code == AWSClientError.ErrorCode.CONDITIONAL_CHECK_FAILED_EXCEPTION.value:
                raise ComputeFleetStatusManager.ConditionalStatusUpdateFailed(e)
            LOGGER.error("Failed when updating fleet status with error: %s", e)
            raise


class PlainTextComputeFleetStatusManager(ComputeFleetStatusManager):
    """Implement functionalities to retrieve and update the compute fleet status for Slurm.

    The value stored in the table is a plain text value, e.g.
    STOPPING
    """

    COMPUTE_FLEET_STATUS_KEY = "COMPUTE_FLEET"
    COMPUTE_FLEET_STATUS_ATTRIBUTE = "Status"
    LAST_UPDATED_TIME_ATTRIBUTE = "LastUpdatedTime"

    def __init__(self, cluster_name):
        super().__init__(PCLUSTER_DYNAMODB_PREFIX + cluster_name)

    def get_status_with_last_updated_time(
        self, status_fallback=ComputeFleetStatus.UNKNOWN, last_updated_time_fallback=None
    ):
        """Get compute fleet status and the last compute fleet status updated time."""
        try:
            compute_fleet_status = AWSApi.instance().ddb_resource.get_item(
                self._table_name, {"Id": self.COMPUTE_FLEET_STATUS_KEY}
            )
            if not compute_fleet_status or "Item" not in compute_fleet_status:
                raise Exception("COMPUTE_FLEET status not found in db table")
            return (
                ComputeFleetStatus(compute_fleet_status["Item"][self.COMPUTE_FLEET_STATUS_ATTRIBUTE]),
                compute_fleet_status["Item"].get(self.LAST_UPDATED_TIME_ATTRIBUTE),
            )
        except Exception as e:
            LOGGER.warning(
                "Failed when retrieving fleet status from DynamoDB with error %s. "
                "This is expected if cluster creation/deletion is in progress",
                e,
            )
            return status_fallback, last_updated_time_fallback

    def _put_status(self, current_status, next_status):
        """Set compute fleet status on DB."""
        try:
            AWSApi.instance().ddb_resource.put_item(
                self._table_name,
                item={
                    "Id": self.COMPUTE_FLEET_STATUS_KEY,
                    self.COMPUTE_FLEET_STATUS_ATTRIBUTE: str(next_status),
                    self.LAST_UPDATED_TIME_ATTRIBUTE: str(datetime.now(tz=timezone.utc)),
                },
                condition_expression=Attr(self.COMPUTE_FLEET_STATUS_ATTRIBUTE).eq(str(current_status)),
            )
        except AWSClientError as e:
            if e.error_code == AWSClientError.ErrorCode.CONDITIONAL_CHECK_FAILED_EXCEPTION.value:
                raise ComputeFleetStatusManager.ConditionalStatusUpdateFailed(e)
            LOGGER.error("Failed when updating fleet status with error: %s", e)
            raise
