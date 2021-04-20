# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=W0613

from datetime import datetime

from pcluster.api.models import (
    ComputeFleetStatus,
    DescribeComputeFleetStatusResponseContent,
    UpdateComputeFleetStatusRequestContent,
)


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
    update_compute_fleet_status_request_content = UpdateComputeFleetStatusRequestContent.from_dict(
        update_compute_fleet_status_request_content
    )
