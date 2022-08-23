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
import pytest
from assertpy import assert_that
from botocore.exceptions import ClientError
from utils import create_hash_suffix, get_compute_nodes_instance_ids, get_root_volume_id, get_stack_id_tag_filter


@pytest.mark.usefixtures("instance", "scheduler")
def test_retain_on_deletion(pcluster_config_reader, clusters_factory, region, os):
    ebs_name = "ebs0"
    cluster_config = pcluster_config_reader(ebs_name=ebs_name)
    cluster = clusters_factory(cluster_config)

    stack_arn = cluster.cfn_stack_arn
    retained_volume = cluster.cfn_resources[f"EBS{create_hash_suffix(ebs_name)}"]
    head_node_root_volume = get_root_volume_id(cluster.head_node_instance_id, region, os)
    compute_node_instance_ids = get_compute_nodes_instance_ids(cluster.name, region)
    logging.info("Checking at least one compute node is running")
    assert_that(len(compute_node_instance_ids)).is_greater_than_or_equal_to(1)
    compute_root_volumes = []
    for compute_node in compute_node_instance_ids:
        compute_root_volumes.append(get_root_volume_id(compute_node, region, os))
    logging.info("Compute root volume %s", compute_root_volumes)

    ec2_client = boto3.client("ec2")
    logging.info("Checking no snapshot with the tag of stack id is created before stack deletion")
    snapshots = _get_snapshots(ec2_client, stack_arn)
    assert_that(snapshots).is_length(0)

    cluster.delete()

    logging.info("Checking a snapshot with the tag of stack id is created after stack deletion")
    snapshots = _get_snapshots(ec2_client, stack_arn)
    assert_that(snapshots).is_length(1)

    logging.info("Checking retained volume after stack deletion")
    _check_volume(ec2_client, retained_volume)

    logging.info("Checking retained head node root volume after stack deletion")
    _check_volume(ec2_client, head_node_root_volume)

    logging.info("Checking compute node root volumes are deleted after stack deletion")
    with pytest.raises(ClientError, match="InvalidVolume.NotFound"):
        ec2_client.describe_volumes(VolumeIds=compute_root_volumes)["Volumes"]


def _get_snapshots(ec2_client, stack_arn):
    return ec2_client.describe_snapshots(Filters=[get_stack_id_tag_filter(stack_arn)])["Snapshots"]


def _check_volume(ec2_client, volume_id):
    volumes = ec2_client.describe_volumes(VolumeIds=[volume_id])["Volumes"]
    assert_that(volumes).is_length(1)
