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
from cfn_stacks_factory import CfnStack
from remote_command_executor import RemoteCommandExecutor
from troposphere import Template
from troposphere.ec2 import PlacementGroup
from utils import generate_stack_name


@pytest.mark.regions(["af-south-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.oss(["alinux2"])
@pytest.mark.usefixtures("os", "instance", "scheduler", "region")
def test_existing_placement_group_in_cluster(
    region, scheduler, pcluster_config_reader, clusters_factory, placement_group_stack, instance
):
    """Test the case when placement_group is provided. This test is not for awsbatch scheduler."""
    placement_group = placement_group_stack.cfn_resources["PlacementGroup"]
    placement = "compute"
    cluster_config = pcluster_config_reader(placement_group=placement_group, placement=placement)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _assert_placement_group(cluster, scheduler, region, placement_group, None, instance)
    _check_head_node_placement_group(remote_command_executor, region, None)
    # need to delete the cluster before deleting placement group
    cluster.delete()


@pytest.mark.regions(["eu-north-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.oss(["alinux2"])
@pytest.mark.usefixtures("os", "instance", "scheduler", "region")
def test_dynamic_placement_group_in_cluster(region, scheduler, pcluster_config_reader, clusters_factory, instance):
    """Test the case when placement_group is set to DYNAMIC. This test is not for awsbatch scheduler."""
    cluster_config = pcluster_config_reader(placement="cluster")
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # For tratitional scheduler, the placement group name can be retrieved from main stack, for slurm, it can be
    # retrieved from ComputeFleetHITSubstack
    if scheduler == "slurm":
        placement_group = _get_slurm_placement_group_from_stack(cluster, region)
        # for slurm, the placement type can only be compute
        _check_head_node_placement_group(remote_command_executor, region, None)
    else:
        placement_group = utils.retrieve_cfn_resources(cluster.cfn_name, region)["DynamicPlacementGroup"]
        _check_head_node_placement_group(remote_command_executor, region, placement_group)
    # check the placement_group of compute nodes
    _assert_placement_group(cluster, scheduler, region, placement_group, None, instance)

    # need to delete the cluster before deleting placement group
    cluster.delete()


@pytest.mark.regions(["eu-central-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.oss(["alinux2"])
@pytest.mark.usefixtures("os", "instance", "scheduler", "region")
def test_placement_group_in_queue(
    region, scheduler, pcluster_config_reader, clusters_factory, placement_group_stack, instance
):
    """Test the case when placement_group is in queue section. This test is only for slurm."""
    existing_placement_group = placement_group_stack.cfn_resources["PlacementGroup"]
    cluster_config = pcluster_config_reader(placement_group=existing_placement_group)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    dynamic_placement_group = _get_slurm_placement_group_from_stack(cluster, region)
    _assert_placement_group(cluster, scheduler, region, dynamic_placement_group, "dynamic", instance)
    _assert_placement_group(cluster, scheduler, region, existing_placement_group, "existing", instance)
    _check_head_node_placement_group(remote_command_executor, region, None)

    # need to delete the cluster before deleting placement group
    cluster.delete()


def _assert_placement_group(cluster, scheduler, region, placement_group, queue_name, instance):
    logging.info("Checking placement group")
    actual_placement_group = _get_placement_group(scheduler, region, cluster, queue_name, instance)
    assert_that(actual_placement_group).is_equal_to(placement_group)


def _get_placement_group(scheduler, region, cluster, queue_name, instance):
    """
    For slurm, the information of placement group can be retrieved from launch template, for traditional scheduler,
    the information of placement group can be retrieved from auto-scaling group.
    """
    ec2_client = boto3.client("ec2", region_name=region)
    launch_template_name = _get_launch_template_name(cluster, queue_name, instance)
    launch_template_data = ec2_client.describe_launch_template_versions(
        LaunchTemplateName=launch_template_name, Versions=["$Latest"]
    )["LaunchTemplateVersions"][0]["LaunchTemplateData"]
    placement_group_name = launch_template_data["Placement"]["GroupName"]
    return placement_group_name


def _get_launch_template_name(cluster, queue_name, instance):
    if not queue_name:
        # get launch template name for cluster section
        launch_template_name = f"{cluster.name}-compute-{instance}"
    else:
        # get launch template name for queue section
        launch_template_name = f"{cluster.name}-{queue_name}-{instance}"
    return launch_template_name


def _get_slurm_placement_group_from_stack(cluster, region):
    compute_fleet_substack = utils.get_substacks(
        cluster.cfn_name, region=region, sub_stack_name="ComputeFleetHITSubstack"
    )[0]
    compute_fleet_substack_resources = utils.retrieve_cfn_resources(compute_fleet_substack, region)
    placement_group = next(v for k, v in compute_fleet_substack_resources.items() if k.startswith("PlacementGroup"))
    return placement_group


def _check_head_node_placement_group(remote_command_executor, region, expected_placement_group=None):
    logging.info("Checking placement group for head node")

    token = remote_command_executor.run_remote_command(
        "curl --retry 3 --retry-delay 0 --fail -s -X "
        "PUT 'http://169.254.169.254/latest/api/token' -H 'X-aws-ec2-metadata-token-ttl-seconds: 300'"
    ).stdout
    head_node_instance_id = remote_command_executor.run_remote_command(
        "curl --retry 3 --retry-delay 0 --fail -s "
        f'-H "X-aws-ec2-metadata-token: {token}" http://169.254.169.254/latest/meta-data/instance-id'
    ).stdout
    head_node_placement_group = boto3.client("ec2", region_name=region).describe_instances(
        InstanceIds=[head_node_instance_id]
    )["Reservations"][0]["Instances"][0]["Placement"]["GroupName"]

    if expected_placement_group:
        # if the placement type is cluster, for traditional scheduler, make sure the head node also inside the
        # placement group
        assert_that(head_node_placement_group).is_equal_to(expected_placement_group)
    else:
        # if the placement type is compute,  make sure the head node is not inside the placement group
        assert_that(head_node_placement_group).is_equal_to("")


@pytest.fixture(scope="class")
def placement_group_stack(cfn_stacks_factory, request, region):
    """Placement group stack contains a placement group."""
    placement_group_template = Template()
    placement_group_template.set_version()
    placement_group_template.set_description("Placement group stack created for testing existing placement group")
    placement_group_template.add_resource(PlacementGroup("PlacementGroup", Strategy="cluster"))
    stack = CfnStack(
        name=generate_stack_name("integ-tests-placement-group", request.config.getoption("stackname_suffix")),
        region=region,
        template=placement_group_template.to_json(),
    )
    cfn_stacks_factory.create_stack(stack)

    yield stack

    cfn_stacks_factory.delete_stack(stack.name, region)
