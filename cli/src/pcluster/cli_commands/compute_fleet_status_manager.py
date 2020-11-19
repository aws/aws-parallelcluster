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
from enum import Enum

import boto3
from boto3.dynamodb.conditions import Attr

LOGGER = logging.getLogger(__name__)


class ComputeFleetStatus(Enum):
    """Represents the status of the cluster compute fleet."""

    STOPPED = "STOPPED"  # Fleet is stopped, partitions are inactive.
    RUNNING = "RUNNING"  # Fleet is running, partitions are active.
    STOPPING = "STOPPING"  # clustermgtd is handling the stop request.
    STARTING = "STARTING"  # clustermgtd is handling the start request.
    STOP_REQUESTED = "STOP_REQUESTED"  # A request to stop the fleet has been submitted.
    START_REQUESTED = "START_REQUESTED"  # A request to start the fleet has been submitted.

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


class ComputeFleetStatusManager:
    """Implement functionalities to retrieve and update the compute fleet status."""

    COMPUTE_FLEET_STATUS_KEY = "COMPUTE_FLEET"
    COMPUTE_FLEET_STATUS_ATTRIBUTE = "Status"

    class ConditionalStatusUpdateFailed(Exception):
        """Raised when there is a failure in updating the status due to a change occurred after retrieving its value."""

        pass

    def __init__(self, cluster_name):
        self._table_name = "parallelcluster-" + cluster_name
        self._ddb_resource = boto3.resource("dynamodb")
        self._table = self._ddb_resource.Table(self._table_name)

    def get_status(self, fallback=None):
        """Get compute fleet status."""
        try:
            compute_fleet_status = self._table.get_item(ConsistentRead=True, Key={"Id": self.COMPUTE_FLEET_STATUS_KEY})
            if not compute_fleet_status or "Item" not in compute_fleet_status:
                raise Exception("COMPUTE_FLEET status not found in db table")
            return ComputeFleetStatus(compute_fleet_status["Item"][self.COMPUTE_FLEET_STATUS_ATTRIBUTE])
        except Exception as e:
            LOGGER.error("Failed when retrieving fleet status from DynamoDB with error %s", e)
            return fallback

    def put_status(self, current_status, next_status):
        """Set compute fleet status."""
        try:
            self._table.put_item(
                Item={"Id": self.COMPUTE_FLEET_STATUS_KEY, self.COMPUTE_FLEET_STATUS_ATTRIBUTE: str(next_status)},
                ConditionExpression=Attr(self.COMPUTE_FLEET_STATUS_ATTRIBUTE).eq(str(current_status)),
            )
        except self._ddb_resource.meta.client.exceptions.ConditionalCheckFailedException as e:
            raise ComputeFleetStatusManager.ConditionalStatusUpdateFailed(e)

    def update_status(self, request_status, in_progress_status, final_status, wait_transition=False):
        """
        Update the status of the compute fleet and wait for a status transition.

        It updates the status of the fleet to request_status and then waits for it to be updated to final_status,
        by eventually transitioning through in_progress_status
        """
        compute_fleet_status = self.get_status()
        if not compute_fleet_status:
            raise Exception("Could not retrieve compute fleet status.")

        if compute_fleet_status == final_status:
            LOGGER.info("Compute fleet already in %s status.", final_status)
            return

        LOGGER.info("Compute fleet status is: %s. Submitting status change request.", compute_fleet_status)
        if compute_fleet_status not in {request_status, in_progress_status, final_status}:
            self.put_status(current_status=compute_fleet_status, next_status=request_status)

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
        else:
            LOGGER.info("Compute fleet status updated successfully.")

    def _wait_for_status_transition(self, wait_on_status, timeout=300, retry_every_seconds=15):
        current_status = self.get_status()
        start_time = time.time()
        while current_status == wait_on_status and not self._timeout_expired(start_time, timeout):
            current_status = self.get_status()
            time.sleep(retry_every_seconds)

        if current_status == wait_on_status:
            raise TimeoutError("Timeout expired while waiting for status transition.")

        return current_status

    @staticmethod
    def _timeout_expired(start_time, timeout):
        return (time.time() - start_time) > timeout
