# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=W0613


from datetime import datetime
from typing import Dict, List

from pcluster.api.errors import CreateClusterBadRequestException
from pcluster.api.models import (
    CloudFormationStatus,
    ClusterConfigurationStructure,
    ClusterInfoSummary,
    ComputeFleetStatus,
    CreateClusterBadRequestExceptionResponseContent,
    CreateClusterRequestContent,
    CreateClusterResponseContent,
    DeleteClusterResponseContent,
    DescribeClusterResponseContent,
    EC2Instance,
    InstanceState,
    ListClustersResponseContent,
    UpdateClusterRequestContent,
    UpdateClusterResponseContent,
)
from pcluster.api.models.cluster_status import ClusterStatus


def create_cluster(
    create_cluster_request_content: Dict,
    suppress_validators: List[str] = None,
    validation_failure_level: Dict = None,
    dryrun: bool = None,
    rollback_on_failure: bool = None,
    client_token: str = None,
) -> CreateClusterResponseContent:
    """
    Create a ParallelCluster managed cluster in a given region.

    :param create_cluster_request_content:
    :param suppress_validators: Identifies one or more config validators to suppress. Format:
    ALL|id:$value|level:(info|error|warning)|type:$value
    :param validation_failure_level: Min validation level that will cause the cluster creation to fail.
    Defaults to &#39;ERROR&#39;.
    :param dryrun: Only perform request validation without creating any resource. It can be used to validate the cluster
    configuration. Response code: 200
    :param rollback_on_failure: When set it automatically initiates a cluster stack rollback on failures.
    Defaults to true.
    :param client_token: Idempotency token that can be set by the client so that retries for the same request are
    idempotent
    """
    create_cluster_request_content = CreateClusterRequestContent.from_dict(create_cluster_request_content)
    if create_cluster_request_content.cluster_configuration == "invalid":
        raise CreateClusterBadRequestException(
            CreateClusterBadRequestExceptionResponseContent(configuration_validation_errors=[], message="invalid")
        )

    return CreateClusterResponseContent(
        ClusterInfoSummary(
            cluster_name="nameeee",
            cloudformation_stack_status=CloudFormationStatus.CREATE_COMPLETE,
            cloudformation_stack_arn="arn",
            region="region",
            version="3.0.0",
            cluster_status=ClusterStatus.CREATE_COMPLETE,
        )
    )


def delete_cluster(cluster_name, region=None, retain_logs=None, client_token=None):
    """
    Initiate the deletion of a cluster.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region. Defaults to the region the API is deployed to.
    :type region: str
    :param retain_logs: Retain cluster logs on delete. Defaults to True.
    :type retain_logs: bool
    :param client_token: Idempotency token that can be set by the client so that retries for the same request are
    idempotent
    :type client_token: str

    :rtype: DeleteClusterResponseContent
    """
    return DeleteClusterResponseContent(
        cluster=ClusterInfoSummary(
            cluster_name="nameeee",
            cloudformation_stack_status=CloudFormationStatus.CREATE_COMPLETE,
            cloudformation_stack_arn="arn",
            region="region",
            version="3.0.0",
            cluster_status=ClusterStatus.CREATE_COMPLETE,
        )
    )


def describe_cluster(cluster_name, region=None):
    """
    Get detailed information about an existing cluster.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region. Defaults to the region the API is deployed to.
    :type region: str

    :rtype: DescribeClusterResponseContent
    """
    return DescribeClusterResponseContent(
        creation_time=datetime.now(),
        headnode=EC2Instance(
            instance_id="id2",
            launch_time=datetime.now(),
            public_ip_address="1.2.3.5",
            instance_type="c5.xlarge",
            state=InstanceState.RUNNING,
            private_ip_address="1.2.3.4",
        ),
        version="3.0.0",
        cluster_configuration=ClusterConfigurationStructure(s3_url="s3"),
        tags=[],
        cloud_formation_status=CloudFormationStatus.CREATE_COMPLETE,
        cluster_name="clustername",
        compute_fleet_status=ComputeFleetStatus.RUNNING,
        cloudformation_stack_arn="arn",
        last_updated_time=datetime.now(),
        region="region",
        cluster_status=ClusterStatus.CREATE_COMPLETE,
    )


def list_clusters(region=None, next_token=None, cluster_status=None):
    """
    Retrieve the list of existing clusters managed by the API. Deleted clusters are not listed by default.

    :param region: List clusters deployed to a given AWS Region. Defaults to the AWS region the API is deployed to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str
    :param cluster_status: Filter by cluster status.
    :type cluster_status: list | bytes

    :rtype: ListClustersResponseContent
    """
    return ListClustersResponseContent(items=[])


def update_cluster(
    update_cluster_request_content: Dict,
    cluster_name,
    suppress_validators=None,
    validation_failure_level=None,
    region=None,
    dryrun=None,
    force_update=None,
    client_token=None,
):
    """
    Update cluster.

    :param update_cluster_request_content:
    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param suppress_validators: Identifies one or more config validators to suppress.
    Format: ALL|id:$value|level:(info|error|warning)|type:$value
    :type suppress_validators: List[str]
    :param validation_failure_level: Min validation level that will cause the update to fail.
    Defaults to &#39;error&#39;.
    :type validation_failure_level: dict | bytes
    :param region: AWS Region. Defaults to the region the API is deployed to.
    :type region: str
    :param dryrun: Only perform request validation without creating any resource.
    It can be used to validate the cluster configuration and update requirements. Response code: 200
    :type dryrun: bool
    :param force_update: Force update by ignoring the update validation errors.
    :type force_update: bool
    :param client_token: Idempotency token that can be set by the client so that retries for the same request are
    idempotent
    :type client_token: str

    :rtype: UpdateClusterResponseContent
    """
    update_cluster_request_content = UpdateClusterRequestContent.from_dict(update_cluster_request_content)
    return UpdateClusterResponseContent(
        cluster=ClusterInfoSummary(
            cluster_name="nameeee",
            cloudformation_stack_status=CloudFormationStatus.CREATE_COMPLETE,
            cloudformation_stack_arn="arn",
            region="region",
            version="3.0.0",
            cluster_status=ClusterStatus.CREATE_COMPLETE,
        )
    )
