# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

from pcluster.api.controllers.common import (
    check_cluster_version,
    configure_aws_region,
    convert_errors,
    http_success_status_code,
)
from pcluster.api.converters import api_node_type_to_cluster_node_type
from pcluster.api.errors import BadRequestException, NotFoundException
from pcluster.api.models import ClusterInstance, DescribeClusterInstancesResponseContent
from pcluster.api.models import NodeType as ApiNodeType
from pcluster.aws.common import StackNotFoundError
from pcluster.models.cluster import Cluster, NodeType
from pcluster.utils import to_utc_datetime

# pylint: disable=W0613


@configure_aws_region()
@convert_errors()
@http_success_status_code(202)
def delete_cluster_instances(cluster_name, region=None, force=None):
    """
    Initiate the forced termination of all cluster compute nodes. Does not work with AWS Batch clusters.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param force: Force the deletion also when the cluster with the given name is not found. (Defaults to 'false'.)
    :type force: bool

    :rtype: None
    """
    cluster = Cluster(cluster_name)
    try:
        if not check_cluster_version(cluster):
            raise BadRequestException(
                f"Cluster '{cluster_name}' belongs to an incompatible ParallelCluster major version."
            )
        if cluster.stack.scheduler == "awsbatch":
            raise BadRequestException("the delete cluster instances operation does not support AWS Batch clusters.")
    except StackNotFoundError:
        if not force:
            raise NotFoundException(
                f"Cluster '{cluster_name}' does not exist or belongs to an incompatible ParallelCluster major version. "
                "To force the deletion of all compute nodes, please use the `force` param."
            )
    cluster.terminate_nodes()


@configure_aws_region()
@convert_errors()
def describe_cluster_instances(cluster_name, region=None, next_token=None, node_type=None, queue_name=None):
    """
    Describe the instances belonging to a given cluster.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str
    :param node_type: Filter the instances by node type.
    :type node_type: dict | bytes
    :param queue_name: Filter the instances by queue name.
    :type queue_name: str

    :rtype: DescribeClusterInstancesResponseContent
    """
    cluster = Cluster(cluster_name)
    node_type = api_node_type_to_cluster_node_type(node_type)
    instances, next_token = cluster.describe_instances(
        next_token=next_token, node_type=node_type, queue_name=queue_name
    )
    ec2_instances = []
    for instance in instances:
        node_type = ApiNodeType.COMPUTENODE
        if instance.node_type == NodeType.HEAD_NODE.value:
            node_type = ApiNodeType.HEADNODE
        elif instance.node_type == NodeType.LOGIN_NODE.value:
            node_type = ApiNodeType.LOGINNODE
        ec2_instances.append(
            ClusterInstance(
                instance_id=instance.id,
                launch_time=to_utc_datetime(instance.launch_time),
                public_ip_address=instance.public_ip,
                instance_type=instance.instance_type,
                state=instance.state,
                private_ip_address=instance.private_ip,
                node_type=node_type,
                queue_name=instance.queue_name,
            )
        )
    return DescribeClusterInstancesResponseContent(instances=ec2_instances, next_token=next_token)
