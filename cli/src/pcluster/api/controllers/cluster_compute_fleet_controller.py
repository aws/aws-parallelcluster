# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=W0613

from pcluster.api.controllers.common import configure_aws_region, convert_errors, validate_cluster
from pcluster.api.errors import BadRequestException
from pcluster.api.models import (
    DescribeComputeFleetResponseContent,
    RequestedComputeFleetStatus,
    UpdateComputeFleetRequestContent,
    UpdateComputeFleetResponseContent,
)
from pcluster.models.cluster import Cluster
from pcluster.utils import to_utc_datetime


@configure_aws_region()
@convert_errors()
def describe_compute_fleet(cluster_name, region=None):
    """
    Describe the status of the compute fleet.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str

    :rtype: DescribeComputeFleetResponseContent
    """
    cluster = Cluster(cluster_name)
    validate_cluster(cluster)
    status, last_status_updated_time = cluster.compute_fleet_status_with_last_updated_time
    return DescribeComputeFleetResponseContent(
        last_status_updated_time=last_status_updated_time and to_utc_datetime(last_status_updated_time),
        status=status.value,
    )


@configure_aws_region()
@convert_errors()
def update_compute_fleet(update_compute_fleet_request_content, cluster_name, region=None):
    """
        Update the status of the cluster compute fleet.

    request_content:
        :type update_compute_fleet_request_content: dict | bytes
        :param cluster_name: Name of the cluster
        :type cluster_name: str
        :param region: AWS Region that the operation corresponds to.
        :type region: str

        :rtype: UpdateComputeFleetResponseContent
    """
    update_compute_fleet_request_content = UpdateComputeFleetRequestContent.from_dict(
        update_compute_fleet_request_content
    )
    cluster = Cluster(cluster_name)
    validate_cluster(cluster)

    status = update_compute_fleet_request_content.status
    if cluster.stack.scheduler == "awsbatch":
        if status == RequestedComputeFleetStatus.ENABLED:
            cluster.start()
        elif status == RequestedComputeFleetStatus.DISABLED:
            cluster.stop()
        else:
            raise BadRequestException(
                "the update compute fleet status can only be set to"
                " `ENABLED` or `DISABLED` for AWS Batch scheduler clusters."
            )
    else:
        if status == RequestedComputeFleetStatus.START_REQUESTED:
            cluster.start()
        elif status == RequestedComputeFleetStatus.STOP_REQUESTED:
            cluster.stop()
        else:
            raise BadRequestException(  # nosec
                "the update compute fleet status can only be set to"
                " `START_REQUESTED` or `STOP_REQUESTED` for %s scheduler clusters."
                % cluster.stack.scheduler.capitalize()
            )
    status, last_status_updated_time = cluster.compute_fleet_status_with_last_updated_time
    last_status_updated_time = last_status_updated_time and to_utc_datetime(last_status_updated_time)
    return UpdateComputeFleetResponseContent(last_status_updated_time=last_status_updated_time, status=status.value)
