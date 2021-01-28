# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
# import logging

import json
import logging
import subprocess as sp

import boto3
import pytest
from assertpy import assert_that


@pytest.mark.regions(["ap-southeast-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.oss(["alinux2"])
@pytest.mark.schedulers(["slurm", "torque", "awsbatch"])
@pytest.mark.usefixtures("region", "instance")
def test_tag_propagation(pcluster_config_reader, clusters_factory, scheduler, os):
    """
    Verify tags from various sources are propagated to the expected resources.

    The following resources are checked for tags:
    - main CFN stack
    - head node substack
    - head node
    - head node's root EBS volume
    - compute node (traditional schedulers)
    - compute node's root EBS volume (traditional schedulers)
    - shared EBS volume
    """
    config_file_tags = {"ConfigFileTag": "ConfigFileTagValue"}
    command_line_tags = {"CommandLineTag": "CommandLineTagValue"}
    version_tags = {"Version": get_pcluster_version()}
    cluster_config = pcluster_config_reader(tags=json.dumps(config_file_tags))
    cluster = clusters_factory(cluster_config, extra_args=["--tags", json.dumps(command_line_tags)])
    cluster_name_tags = {"ClusterName": cluster.name}

    test_cases = [
        {
            "resource": "Main CloudFormation Stack",
            "tag_getter": get_main_stack_tags,
            "expected_tags": (version_tags, config_file_tags, command_line_tags),
        },
        {
            "resource": "Head Node CloudFormation Stack",
            "tag_getter": get_head_node_substack_tags,
            "expected_tags": (version_tags, config_file_tags, command_line_tags),
        },
        {
            "resource": "ComputeFleet CloudFormation Stack",
            "tag_getter": get_compute_fleet_substack_tags,
            "tag_getter_kwargs": {"cluster": cluster, "scheduler": scheduler},
            "expected_tags": (version_tags, config_file_tags, command_line_tags),
        },
        {
            "resource": "Head Node",
            "tag_getter": get_head_node_tags,
            "expected_tags": (cluster_name_tags, {"Name": "Master", "aws-parallelcluster-node-type": "Master"}),
        },
        {
            "resource": "Head Node Root Volume",
            "tag_getter": get_head_node_root_volume_tags,
            "expected_tags": (cluster_name_tags, {"aws-parallelcluster-node-type": "Master"}),
            "tag_getter_kwargs": {"cluster": cluster, "os": os},
        },
        {
            "resource": "Compute Node",
            "tag_getter": get_compute_node_tags,
            "expected_tags": (
                cluster_name_tags,
                {"Name": "Compute", "aws-parallelcluster-node-type": "Compute"},
                config_file_tags,
                command_line_tags,
            ),
            "skip": scheduler == "awsbatch",
        },
        {
            "resource": "Compute Node Root Volume",
            "tag_getter": get_compute_node_root_volume_tags,
            "expected_tags": (
                cluster_name_tags,
                {"aws-parallelcluster-node-type": "Compute"},
                config_file_tags if scheduler == "slurm" else {},
                command_line_tags if scheduler == "slurm" else {},
            ),
            "tag_getter_kwargs": {"cluster": cluster, "os": os},
            "skip": scheduler == "awsbatch",
        },
        {
            "resource": "Shared EBS Volume",
            "tag_getter": get_shared_volume_tags,
            "expected_tags": (version_tags, config_file_tags, command_line_tags),
        },
    ]
    for test_case in test_cases:
        if test_case.get("skip"):
            continue
        logging.info("Verifying tags were propagated to %s", test_case.get("resource"))
        tag_getter = test_case.get("tag_getter")
        # Assume tag getters use lone cluster object arg if none explicitly given
        tag_getter_args = test_case.get("tag_getter_kwargs", {"cluster": cluster})
        observed_tags = tag_getter(**tag_getter_args)
        expected_tags = test_case["expected_tags"]
        assert_that(observed_tags).contains(*convert_tags_dicts_to_tags_list(expected_tags))


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


def get_head_node_substack_name(cluster):
    """Return the name of the given cluster's head node's substack."""
    return cluster.cfn_resources.get("MasterServerSubstack")


def get_head_node_substack_tags(cluster):
    """Return the tags for the given cluster's head node's CFN stack."""
    return get_cloudformation_tags(cluster.region, get_head_node_substack_name(cluster))


def get_compute_fleet_substack_name(cluster, scheduler):
    """Return the name of the given cluster's compute fleet substack."""
    scheduler_to_compute_fleet_logical_stack_name = {
        "slurm": "ComputeFleetHITSubstack",
        "sge": "ComputeFleetSubstack",
        "torque": "ComputeFleetSubstack",
        "awsbatch": "AWSBatchStack",
    }
    return cluster.cfn_resources.get(scheduler_to_compute_fleet_logical_stack_name[scheduler])


def get_compute_fleet_substack_tags(cluster, scheduler):
    """Return the tags for the given cluster's compute fleet CFN stack."""
    return get_cloudformation_tags(cluster.region, get_compute_fleet_substack_name(cluster, scheduler))


def get_head_node_instance_id(cluster):
    """Return the given cluster's head node's instance ID."""
    return cluster.head_node_substack_cfn_resources.get("MasterServer")


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


def get_root_volume_id(instance_id, region, os):
    """Return the root EBS volume's ID for the given EC2 instance."""
    logging.info("Getting root volume for instance %s", instance_id)
    os_to_root_volume_device = {
        # These are taken from the main CFN template
        "centos7": "/dev/sda1",
        "centos8": "/dev/sda1",
        "alinux": "/dev/xvda",
        "alinux2": "/dev/xvda",
        "ubuntu1604": "/dev/sda1",
        "ubuntu1804": "/dev/sda1",
    }
    block_device_mappings = (
        boto3.client("ec2", region_name=region)
        .describe_instances(InstanceIds=[instance_id])
        .get("Reservations")[0]
        .get("Instances")[0]
        .get("BlockDeviceMappings")
    )
    matching_devices = [
        device_mapping
        for device_mapping in block_device_mappings
        if device_mapping.get("DeviceName") == os_to_root_volume_device[os]
    ]
    assert_that(matching_devices).is_length(1)
    return matching_devices[0].get("Ebs").get("VolumeId")


def get_tags_for_volume(volume_id, region):
    """Return the tags attached to the given EBS volume."""
    logging.info("Getting tags for volume %s", volume_id)
    return boto3.client("ec2", region_name=region).describe_volumes(VolumeIds=[volume_id]).get("Volumes")[0].get("Tags")


def get_head_node_root_volume_tags(cluster, os):
    """Return the given cluster's head node's root volume's tags."""
    head_node_instance_id = get_head_node_instance_id(cluster)
    root_volume_id = get_root_volume_id(head_node_instance_id, cluster.region, os)
    return get_tags_for_volume(root_volume_id, cluster.region)


def get_head_node_tags(cluster):
    """Return the given cluster's head node's tags."""
    head_node_instance_id = get_head_node_instance_id(cluster)
    return get_ec2_instance_tags(head_node_instance_id, cluster.region)


def get_compute_node_root_volume_tags(cluster, os):
    """Return the given cluster's compute node's root volume's tags."""
    compute_nodes = cluster.instances(desired_instance_role="ComputeFleet")
    assert_that(compute_nodes).is_length(1)
    root_volume_id = get_root_volume_id(compute_nodes[0], cluster.region, os)
    return get_tags_for_volume(root_volume_id, cluster.region)


def get_compute_node_tags(cluster):
    """Return the given cluster's compute node's tags."""
    compute_nodes = cluster.instances(desired_instance_role="ComputeFleet")
    assert_that(compute_nodes).is_length(1)
    return get_ec2_instance_tags(compute_nodes[0], cluster.region)


def get_ebs_volume_tags(volume_id, region):
    """Return the tags associated with the given EBS volume."""
    return boto3.client("ec2", region_name=region).describe_volumes(VolumeIds=[volume_id]).get("Volumes")[0].get("Tags")


def get_shared_volume_tags(cluster):
    """Return the given cluster's EBS volume's tags."""
    shared_volume = cluster.ebs_substack_cfn_resources.get("Volume1")
    return get_ebs_volume_tags(shared_volume, cluster.region)


def get_pcluster_version():
    """Return the installed version of the pclsuter CLI."""
    return sp.check_output("pcluster version".split()).decode().strip()
