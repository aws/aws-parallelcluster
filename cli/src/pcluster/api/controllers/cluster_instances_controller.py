# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=W0613

from datetime import datetime

from pcluster.api.models import DescribeClusterInstancesResponseContent, EC2Instance, InstanceState
from pcluster.api.validators import validate_region


@validate_region()
def delete_cluster_instances(cluster_name, region=None, force=None):
    """
    Initiate the forced termination of all cluster compute nodes. Does not work with AWS Batch clusters.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region. Defaults to the region the API is deployed to.
    :type region: str
    :param force: Force the deletion also when the cluster id is not found.
    :type force: bool

    :rtype: None
    """
    return None


@validate_region()
def describe_cluster_instances(cluster_name, region=None, next_token=None, node_type=None, queue_name=None):
    """
    Describe the instances belonging to a given cluster.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region. Defaults to the region the API is deployed to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str
    :param node_type:
    :type node_type: dict | bytes
    :param queue_name:
    :type queue_name: str

    :rtype: DescribeClusterInstancesResponseContent
    """
    return DescribeClusterInstancesResponseContent(
        [
            EC2Instance(
                instance_id="id",
                launch_time=datetime.now(),
                public_ip_address="1.2.3.4",
                instance_type="c5.xlarge",
                state=InstanceState.RUNNING,
                private_ip_address="1.2.3.4",
            )
        ]
    )
