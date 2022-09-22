# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import logging

import boto3
from assertpy import assert_that
from utils import create_hash_suffix, get_root_volume_id


def convert_tags_dicts_to_tags_list(tags_dicts):
    """Convert dicts of the form {key: value} to a list like [{"Key": key, "Value": value}]."""
    tags_list = []
    for tags_dict in tags_dicts:
        tags_list.extend([{"Key": key, "Value": value} for key, value in tags_dict.items()])
    return tags_list


def get_cloudformation_tags(region, stack_name):
    """
    Return the tags for the CFN stack with the given name

    The returned values is a list like the following:
    [
        {'Key': 'Key2', 'Value': 'Value2'},
        {'Key': 'Key1', 'Value': 'Value1'},
    ]
    """
    cfn_client = boto3.client("cloudformation", region_name=region)
    response = cfn_client.describe_stacks(StackName=stack_name)
    return response["Stacks"][0]["Tags"]


def get_main_stack_tags(cluster):
    """Return the tags for the cluster's main CFN stack."""
    return get_cloudformation_tags(cluster.region, cluster.cfn_name)


def get_ec2_instance_tags(instance_id, region):
    """Return a list of tags associated with the given EC2 instance."""
    logging.info("Getting tags for instance %s", instance_id)
    return (
        boto3.client("ec2", region_name=region)
        .describe_instances(InstanceIds=[instance_id])
        .get("Reservations")[0]
        .get("Instances")[0]
        .get("Tags")
    )


def get_tags_for_volume(volume_id, region):
    """Return the tags attached to the given EBS volume."""
    logging.info("Getting tags for volume %s", volume_id)
    return boto3.client("ec2", region_name=region).describe_volumes(VolumeIds=[volume_id]).get("Volumes")[0].get("Tags")


def get_head_node_root_volume_tags(cluster, os):
    """Return the given cluster's head node's root volume's tags."""
    root_volume_id = get_root_volume_id(cluster.head_node_instance_id, cluster.region, os)
    return get_tags_for_volume(root_volume_id, cluster.region)


def get_head_node_tags(cluster):
    """Return the given cluster's head node's tags."""
    return get_ec2_instance_tags(cluster.head_node_instance_id, cluster.region)


def get_compute_node_root_volume_tags(cluster, os):
    """Return the given cluster's compute node's root volume's tags."""
    compute_nodes = cluster.get_cluster_instance_ids(node_type="Compute")
    assert_that(compute_nodes).is_length(1)
    root_volume_id = get_root_volume_id(compute_nodes[0], cluster.region, os)
    return get_tags_for_volume(root_volume_id, cluster.region)


def get_compute_node_tags(cluster, queue_name=None):
    """Return the given cluster's compute node's tags."""
    compute_nodes = cluster.get_cluster_instance_ids(node_type="Compute", queue_name=queue_name)
    assert_that(compute_nodes).is_length(1)
    return get_ec2_instance_tags(compute_nodes[0], cluster.region)


def get_ebs_volume_tags(volume_id, region):
    """Return the tags associated with the given EBS volume."""
    return boto3.client("ec2", region_name=region).describe_volumes(VolumeIds=[volume_id]).get("Volumes")[0].get("Tags")


def get_shared_volume_tags(cluster, volume_name):
    """Return the given cluster's EBS volume's tags."""
    shared_volume = cluster.cfn_resources.get(f"EBS{create_hash_suffix(volume_name)}")
    return get_ebs_volume_tags(shared_volume, cluster.region)
