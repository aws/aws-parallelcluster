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
import utils
from assertpy import assert_that


@pytest.mark.usefixtures("os", "instance", "scheduler", "region")
def test_placement_group(region, pcluster_config_reader, placement_group_stack, clusters_factory, instance):
    """Test the case when placement_group is in queue section. This test is only for slurm."""
    existing_placement_group = placement_group_stack.cfn_resources["PlacementGroup"]
    cluster_config = pcluster_config_reader(placement_group=existing_placement_group)
    cluster = clusters_factory(cluster_config)

    dynamic_placement_group = _get_slurm_placement_group_from_stack(cluster, region)
    _assert_placement_group(cluster, region, dynamic_placement_group, "dynamic", "compute-resource-0")
    _assert_placement_group(cluster, region, existing_placement_group, "existing", "compute-resource-1")

    # need to delete the cluster before deleting placement group
    cluster.delete()


def _assert_placement_group(cluster, region, placement_group, queue_name, compute_resource):
    logging.info("Checking placement group")
    actual_placement_group = _get_placement_group(region, cluster, queue_name, compute_resource)
    assert_that(actual_placement_group).is_equal_to(placement_group)


def _get_placement_group(region, cluster, queue_name, compute_resource):
    """For slurm, the information of placement group can be retrieved from launch template."""
    ec2_client = boto3.client("ec2", region_name=region)
    launch_template_name = _get_launch_template_name(cluster, queue_name, compute_resource)
    launch_template_data = ec2_client.describe_launch_template_versions(
        LaunchTemplateName=launch_template_name, Versions=["$Latest"]
    )["LaunchTemplateVersions"][0]["LaunchTemplateData"]
    placement_group_name = launch_template_data["Placement"]["GroupName"]
    return placement_group_name


def _get_launch_template_name(cluster, queue_name, compute_resource):
    if not queue_name:
        # get launch template name for cluster section
        launch_template_name = f"{cluster.name}-compute-{compute_resource}"
    else:
        # get launch template name for queue section
        launch_template_name = f"{cluster.name}-{queue_name}-{compute_resource}"
    return launch_template_name


def _get_slurm_placement_group_from_stack(cluster, region):
    stack_resources = utils.retrieve_cfn_resources(cluster.cfn_name, region)
    placement_group = next(v for k, v in stack_resources.items() if k.startswith("PlacementGroup"))
    return placement_group
