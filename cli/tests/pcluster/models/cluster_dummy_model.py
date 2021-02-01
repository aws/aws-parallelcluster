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


from pcluster.models.cluster import HeadNode, HeadNodeNetworking, Image, QueueNetworking, Ssh
from pcluster.models.cluster_slurm import SlurmCluster, SlurmComputeResource, SlurmQueue, SlurmScheduling


def dummy_head_node():
    """Generate dummy head node."""
    image = Image(os="fakeos")
    head_node_networking = HeadNodeNetworking(subnet_id="test")
    ssh = Ssh(key_name="test")
    return HeadNode(instance_type="fake", networking=head_node_networking, ssh=ssh, image=image)


def dummy_cluster():
    """Generate dummy cluster."""
    image = Image(os="fakeos")
    head_node = dummy_head_node()
    compute_resources = [SlurmComputeResource(instance_type="test")]
    queue_networking = QueueNetworking(subnet_ids=["test"])
    queues = [SlurmQueue(name="test", networking=queue_networking, compute_resources=compute_resources)]
    scheduling = SlurmScheduling(queues=queues)
    return SlurmCluster(image=image, head_node=head_node, scheduling=scheduling)
