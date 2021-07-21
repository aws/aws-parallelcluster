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


import base64
import logging

import boto3
import pytest
from assertpy import assert_that
from botocore.config import Config
from pcluster_client import ApiException
from pcluster_client.api import (
    cluster_compute_fleet_api,
    cluster_instances_api,
    cluster_operations_api,
    image_operations_api,
)
from pcluster_client.exceptions import NotFoundException
from pcluster_client.model.build_image_request_content import BuildImageRequestContent
from pcluster_client.model.cloud_formation_stack_status import CloudFormationStackStatus
from pcluster_client.model.cluster_status import ClusterStatus
from pcluster_client.model.compute_fleet_status import ComputeFleetStatus
from pcluster_client.model.create_cluster_request_content import CreateClusterRequestContent
from pcluster_client.model.image_build_status import ImageBuildStatus
from pcluster_client.model.image_status_filtering_option import ImageStatusFilteringOption
from pcluster_client.model.instance_state import InstanceState
from pcluster_client.model.node_type import NodeType
from pcluster_client.model.requested_compute_fleet_status import RequestedComputeFleetStatus
from pcluster_client.model.update_cluster_request_content import UpdateClusterRequestContent
from pcluster_client.model.update_compute_fleet_request_content import UpdateComputeFleetRequestContent
from utils import generate_stack_name

from tests.common.utils import retrieve_latest_ami

LOGGER = logging.getLogger(__name__)


def _cloudformation_wait(region, stack_name, status):
    config = Config(region_name=region)
    cloud_formation = boto3.client("cloudformation", config=config)
    waiter = cloud_formation.get_waiter(status)
    waiter.wait(StackName=stack_name)


def _ec2_wait_terminated(region, instances):
    config = Config(region_name=region)
    ec2 = boto3.client("ec2", config=config)
    waiter = ec2.get_waiter("instance_terminated")
    waiter.wait(InstanceIds=instances)


@pytest.mark.usefixtures("os", "instance")
def test_cluster_slurm(request, scheduler, region, pcluster_config_reader, api_client):
    assert_that(scheduler).is_equal_to("slurm")
    _test_cluster_workflow(request, scheduler, region, pcluster_config_reader, api_client)


@pytest.mark.usefixtures("os", "instance")
def test_cluster_awsbatch(request, scheduler, region, pcluster_config_reader, api_client):
    assert_that(scheduler).is_equal_to("awsbatch")
    _test_cluster_workflow(request, scheduler, region, pcluster_config_reader, api_client)


def _test_cluster_workflow(request, scheduler, region, pcluster_config_reader, api_client):
    initial_config_file = pcluster_config_reader()
    updated_config_file = pcluster_config_reader("pcluster.config.update.yaml")

    # Create cluster with initial configuration
    with open(initial_config_file) as config_file:
        cluster_config = config_file.read()

    cluster_name = generate_stack_name("integ-tests", request.config.getoption("stackname_suffix"))
    cluster_operations_client = cluster_operations_api.ClusterOperationsApi(api_client)
    cluster_compute_fleet_client = cluster_compute_fleet_api.ClusterComputeFleetApi(api_client)
    cluster_instances_client = cluster_instances_api.ClusterInstancesApi(api_client)

    _test_create_cluster(cluster_operations_client, cluster_config, region, cluster_name)

    _test_list_clusters(cluster_operations_client, cluster_name, region, "CREATE_IN_PROGRESS")
    _test_describe_cluster(cluster_operations_client, cluster_name, region, "CREATE_IN_PROGRESS")

    _cloudformation_wait(region, cluster_name, "stack_create_complete")

    _test_list_clusters(cluster_operations_client, cluster_name, region, "CREATE_COMPLETE")
    _test_describe_cluster(cluster_operations_client, cluster_name, region, "CREATE_COMPLETE")

    # Update cluster with new configuration
    with open(updated_config_file) as config_file:
        updated_cluster_config = config_file.read()
    _test_update_cluster_dryrun(cluster_operations_client, updated_cluster_config, region, cluster_name)

    head_node = _test_describe_cluster_head_node(cluster_instances_client, cluster_name, region)
    compute_node_map = _test_describe_cluster_compute_nodes(cluster_instances_client, cluster_name, region)
    if scheduler == "slurm":
        _test_delete_cluster_instances(cluster_instances_client, cluster_name, head_node, compute_node_map, region)

    running_state = "RUNNING" if scheduler == "slurm" else "ENABLED"
    _test_describe_compute_fleet_status(cluster_compute_fleet_client, cluster_name, region, running_state)
    _test_stop_compute_fleet(cluster_compute_fleet_client, cluster_instances_client, cluster_name, region, scheduler)

    _test_delete_cluster(cluster_operations_client, cluster_name, region)


def _test_describe_cluster_head_node(client, cluster_name, region):
    response = client.describe_cluster_instances(cluster_name=cluster_name, node_type=NodeType("HEAD"), region=region)
    assert_that(response.instances).is_length(1)
    return response.instances[0].instance_id


def _test_describe_cluster_compute_nodes(client, cluster_name, region, all_terminated=False):
    compute_nodes_map = dict()

    response = client.describe_cluster_instances(
        cluster_name=cluster_name, node_type=NodeType("COMPUTE"), region=region
    )
    _add_non_terminated_compute_nodes(response.instances, compute_nodes_map)

    while "next_token" in response:
        response = client.describe_cluster_instances(
            cluster_name=cluster_name, node_type=NodeType("COMPUTE"), region=region, next_token=response.next_token
        )
        _add_non_terminated_compute_nodes(response.instances, compute_nodes_map)

    for instances in compute_nodes_map.values():
        if all_terminated:
            assert_that(instances).is_empty()
        else:
            assert_that(instances).is_not_empty()

    return compute_nodes_map


def _add_non_terminated_compute_nodes(instances, compute_node_map):
    for instance in instances:
        if instance.state == InstanceState("terminated"):
            continue

        if instance.queue_name not in compute_node_map:
            compute_node_map[instance.queue_name] = set()

        compute_node_map[instance.queue_name].add(instance.instance_id)


def _test_delete_cluster_instances(client, cluster_name, head_node, compute_node_map, region):
    instances_to_terminate = _get_instances_to_terminate(compute_node_map)
    client.delete_cluster_instances(cluster_name=cluster_name, region=region)
    _ec2_wait_terminated(region, instances_to_terminate)

    new_head_node = _test_describe_cluster_head_node(client, cluster_name, region)
    new_compute_node_map = _test_describe_cluster_compute_nodes(client, cluster_name, region)

    assert_that(new_head_node).is_equal_to(head_node)
    assert_that(new_compute_node_map.keys()).is_equal_to(compute_node_map.keys())
    for queue in new_compute_node_map.keys():
        assert_that(new_compute_node_map[queue]).is_not_equal_to(compute_node_map[queue])


def _test_describe_compute_fleet_status(client, cluster_name, region, status):
    response = client.describe_compute_fleet_status(cluster_name=cluster_name, region=region)
    LOGGER.info("Compute fleet status response: %s", response)
    assert_that(response.status).is_equal_to(ComputeFleetStatus(status))


def _test_stop_compute_fleet(cluster_compute_fleet_client, cluster_instances_client, cluster_name, region, scheduler):
    stop_status = "STOP_REQUESTED" if scheduler == "slurm" else "DISABLED"
    terminal_state = "STOPPED" if scheduler == "slurm" else "DISABLED"

    head_node = _test_describe_cluster_head_node(cluster_instances_client, cluster_name, region)
    compute_node_map = _test_describe_cluster_compute_nodes(cluster_instances_client, cluster_name, region)
    instances_to_terminate = _get_instances_to_terminate(compute_node_map)

    cluster_compute_fleet_client.update_compute_fleet_status(
        cluster_name=cluster_name,
        update_compute_fleet_status_request_content=UpdateComputeFleetRequestContent(
            RequestedComputeFleetStatus(stop_status)
        ),
        region=region,
    )

    if scheduler == "slurm":
        # AWS Batch does not terminate all compute nodes, it just resizes the compute fleet down to a number
        # of instances equal to MinvCpus. For AWS Batch we simply check that the compute fleet status has been
        # updated, while for the Slurm case we wait for the previous compute instances to have been terminated.
        _ec2_wait_terminated(region, instances_to_terminate)

    response = cluster_compute_fleet_client.describe_compute_fleet_status(cluster_name=cluster_name, region=region)
    assert_that(response.status).is_equal_to(ComputeFleetStatus(terminal_state))

    if scheduler == "slurm":
        new_head_node = _test_describe_cluster_head_node(cluster_instances_client, cluster_name, region)
        assert_that(new_head_node).is_equal_to(head_node)
        _test_describe_cluster_compute_nodes(cluster_instances_client, cluster_name, region, all_terminated=True)


def _get_instances_to_terminate(compute_node_map):
    instances_to_terminate = []
    for instances in compute_node_map.values():
        instances_to_terminate.extend(instances)
    return instances_to_terminate


def _test_list_clusters(client, cluster_name, region, status):
    response = client.list_clusters(region=region)
    target_cluster = _get_cluster(response.items, cluster_name)

    while "next_token" in response and not target_cluster:
        response = client.list_clusters(region=region, next_token=response.next_token)
        target_cluster = _get_cluster(response.items, cluster_name)

    assert_that(target_cluster).is_not_none()
    assert_that(target_cluster.cluster_name).is_equal_to(cluster_name)
    assert_that(target_cluster.cluster_status).is_equal_to(ClusterStatus(status))
    assert_that(target_cluster.cloudformation_stack_status).is_equal_to(CloudFormationStackStatus(status))


def _get_cluster(clusters, cluster_name):
    for cluster in clusters:
        if cluster.cluster_name == cluster_name:
            return cluster
    return None


def _test_describe_cluster(client, cluster_name, region, status):
    response = client.describe_cluster(cluster_name, region=region)
    LOGGER.info("Describe cluster response: %s", response)
    assert_that(response.cluster_name).is_equal_to(cluster_name)
    assert_that(response.cluster_status).is_equal_to(ClusterStatus(status))
    assert_that(response.cloud_formation_status).is_equal_to(CloudFormationStackStatus(status))


def _test_create_cluster(client, cluster_config, region, cluster_name):
    cluster_config_data = base64.b64encode(cluster_config.encode("utf-8")).decode("utf-8")
    body = CreateClusterRequestContent(cluster_name, cluster_config_data)
    response = client.create_cluster(body, region=region)
    assert_that(response.cluster.cluster_name).is_equal_to(cluster_name)


def _test_update_cluster_dryrun(client, cluster_config, region, cluster_name):
    cluster_config_data = base64.b64encode(cluster_config.encode("utf-8")).decode("utf-8")
    body = UpdateClusterRequestContent(cluster_config_data)
    error_message = "Request would have succeeded, but DryRun flag is set."
    with pytest.raises(ApiException, match=error_message):
        client.update_cluster(cluster_name, body, region=region, dryrun=True)


def _test_delete_cluster(client, cluster_name, region):
    client.delete_cluster(cluster_name, region=region)

    _cloudformation_wait(region, cluster_name, "stack_delete_complete")

    error_message = (
        f"cluster '{cluster_name}' does not exist or belongs" f" to an incompatible ParallelCluster major version."
    )
    with pytest.raises(NotFoundException, match=error_message):
        client.describe_cluster(cluster_name, region=region)


def test_official_images(region, api_client):
    client = image_operations_api.ImageOperationsApi(api_client)
    response = client.describe_official_images(region=region)
    assert_that(response.items).is_not_empty()


@pytest.mark.usefixtures("instance")
def test_custom_image(request, region, os, pcluster_config_reader, api_client):
    base_ami = retrieve_latest_ami(region, os)

    config_file = pcluster_config_reader(config_file="image.config.yaml", parent_image=base_ami)
    with open(config_file) as config_file:
        config = config_file.read()

    image_id = generate_stack_name("integ-tests-build-image", request.config.getoption("stackname_suffix"))
    client = image_operations_api.ImageOperationsApi(api_client)

    _test_build_image(client, image_id, region, config)

    _test_describe_image(client, image_id, region, "BUILD_IN_PROGRESS")
    _test_list_images(client, image_id, region, "PENDING")

    # CFN stack is deleted as soon as image is available
    _cloudformation_wait(region, image_id, "stack_delete_complete")

    _test_describe_image(client, image_id, region, "BUILD_COMPLETE")
    _test_list_images(client, image_id, region, "AVAILABLE")

    _delete_image(client, image_id, region)


def _test_build_image(client, image_id, region, config):
    image_config_data = base64.b64encode(config.encode("utf-8")).decode("utf-8")
    body = BuildImageRequestContent(image_config_data, image_id)
    response = client.build_image(body, region=region)
    LOGGER.info("Build image response: %s", response)
    assert_that(response.image.image_id).is_equal_to(image_id)


def _test_describe_image(client, image_id, region, status):
    response = client.describe_image(image_id, region=region)
    LOGGER.info("Describe image response: %s", response)
    assert_that(response.image_id).is_equal_to(image_id)
    assert_that(response.image_build_status).is_equal_to(ImageBuildStatus(status))


def _test_list_images(client, image_id, region, status):
    response = client.list_images(image_status=ImageStatusFilteringOption(status), region=region)
    target_image = _get_image(response.items, image_id)

    while "next_token" in response and not target_image:
        response = client.list_images(
            image_status=ImageStatusFilteringOption(status), region=region, next_token=response.next_token
        )
        target_image = _get_image(response.items, image_id)

    LOGGER.info("Target image in ListImages response is: %s", target_image)

    assert_that(target_image).is_not_none()


def _get_image(images, image_id):
    for image in images:
        if image.image_id == image_id:
            return image
    return None


def _delete_image(client, image_id, region):
    client.delete_image(image_id, region=region)

    error_message = f"No image or stack associated to parallelcluster image id {image_id}."
    with pytest.raises(NotFoundException, match=error_message):
        client.describe_image(image_id, region=region)
