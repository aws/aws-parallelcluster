# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=W0613

from datetime import datetime

from pcluster.api.controllers.common import check_cluster_version, configure_aws_region, convert_errors
from pcluster.api.errors import BadRequestException, NotFoundException
from pcluster.api.models import (
    ComputeFleetStatus,
    DescribeComputeFleetStatusResponseContent,
    RequestedComputeFleetStatus,
    UpdateComputeFleetStatusRequestContent,
)
from pcluster.aws.common import StackNotFoundError
from pcluster.models.cluster import Cluster


@configure_aws_region()
def describe_compute_fleet_status(cluster_name, region=None):
    """
    Describe the status of the compute fleet.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region. Defaults to the region the API is deployed to.
    :type region: str

    :rtype: DescribeComputeFleetStatusResponseContent
    """
    return DescribeComputeFleetStatusResponseContent(
        last_updated_time=datetime.now(), status=ComputeFleetStatus.RUNNING
    )


@configure_aws_region()
@convert_errors()
def update_compute_fleet_status(cluster_name, update_compute_fleet_status_request_content, region=None):
    """
    Update the status of the cluster compute fleet.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param update_compute_fleet_status_request_content:
    :type update_compute_fleet_status_request_content: dict | bytes
    :param region: AWS Region. Defaults to the region the API is deployed to.
    :type region: str

    :rtype: None
    """
    try:
        update_compute_fleet_status_request_content = UpdateComputeFleetStatusRequestContent.from_dict(
            update_compute_fleet_status_request_content
        )
        cluster = Cluster(cluster_name)
        if not check_cluster_version(cluster, exact_match=True):
            raise BadRequestException(
                f"cluster '{cluster_name}' belongs to an incompatible ParallelCluster major version."
            )
        status = update_compute_fleet_status_request_content.status
        if cluster.stack.scheduler == "slurm":
            if status == RequestedComputeFleetStatus.START_REQUESTED:
                cluster.start()
            elif status == RequestedComputeFleetStatus.STOP_REQUESTED:
                cluster.stop()
            else:
                raise BadRequestException(
                    "the update compute fleet status can only be set to"
                    " `START_REQUESTED` or `STOP_REQUESTED` for Slurm clusters."
                )
        else:
            if cluster.stack.scheduler == "awsbatch":
                if status == RequestedComputeFleetStatus.ENABLED:
                    cluster.start()
                elif status == RequestedComputeFleetStatus.DISABLED:
                    cluster.stop()
                else:
                    raise BadRequestException(
                        "the update compute fleet status can only be set to"
                        " `ENABLED` or `DISABLED` for AWS Batch clusters."
                    )
    except StackNotFoundError:
        raise NotFoundException(
            f"cluster '{cluster_name}' does not exist or belongs to an incompatible ParallelCluster major version."
        )
