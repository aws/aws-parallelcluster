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
            LOGGER.error(
                "Failed when retrieving fleet status from DynamoDB with error %s, using fallback value %s", e, fallback
            )
            return fallback

    def update_status(self, current_status, next_status):
        """Set compute fleet status."""
        try:
            self._table.put_item(
                Item={"Id": self.COMPUTE_FLEET_STATUS_KEY, self.COMPUTE_FLEET_STATUS_ATTRIBUTE: str(next_status)},
                ConditionExpression=Attr(self.COMPUTE_FLEET_STATUS_ATTRIBUTE).eq(str(current_status)),
            )
        except self._ddb_resource.meta.client.exceptions.ConditionalCheckFailedException as e:
            raise ComputeFleetStatusManager.ConditionalStatusUpdateFailed(e)
