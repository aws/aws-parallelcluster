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


import logging

import boto3
import pytest
from assertpy import assert_that
from benchmarks.common.util import get_instance_vcpus
from botocore.config import Config
from clusters_factory import Cluster, ClustersFactory
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
from pcluster_client.model.node_type import NodeType
from pcluster_client.model.requested_compute_fleet_status import RequestedComputeFleetStatus
from pcluster_client.model.update_cluster_request_content import UpdateClusterRequestContent
from pcluster_client.model.update_compute_fleet_request_content import UpdateComputeFleetRequestContent
from utils import generate_stack_name

from tests.common.assertions import wait_for_num_instances_in_cluster
from tests.common.utils import retrieve_latest_ami

LOGGER = logging.getLogger(__name__)
NUM_OF_COMPUTE_INSTANCES = 2


@pytest.fixture()
def build_image(region):
    """Create a build image process."""
    image_id_post_test = None
    client_post_test = None

    def _build_image(client, image_id, config):
        nonlocal image_id_post_test
        nonlocal client_post_test
        image_id_post_test = image_id
        client_post_test = client

        body = BuildImageRequestContent(image_id=image_id, image_configuration=config)
        return client.build_image(body, region=region)

    yield _build_image

    if image_id_post_test:
        try:
            response = client_post_test.delete_image(image_id_post_test, region=region)
            LOGGER.info("Build image post process. Delete image result: %s", response)
        except NotFoundException:
            logging.info("Build image post process. Nothing to do, image %s was already deleted.", image_id_post_test)


@pytest.fixture()
def create_cluster(region, request):
    """A fixture to create clusters via the API client, and clean them up in case of test failure."""
    factory = ClustersFactory(delete_logs_on_success=request.config.getoption("delete_logs_on_success"))

    def _create_cluster(client, cluster_name, config):
        # Create cluster with initial configuration
        with open(config) as config_file:
            config_contents = config_file.read()
        body = CreateClusterRequestContent(cluster_name=cluster_name, cluster_configuration=config_contents)
        response = client.create_cluster(body, region=region)
        cluster = Cluster(
            name=cluster_name, config_file=config, ssh_key=request.config.getoption("key_path"), region=region
        )
        factory.register_cluster(cluster)
        return cluster, response

    yield _create_cluster
    if not request.config.getoption("no_delete"):
        try:
            test_passed = request.node.rep_call.passed
        except AttributeError:
            test_passed = False
        factory.destroy_all_clusters(test_passed=test_passed)


def _cloudformation_wait(region, stack_name, status):
    config = Config(region_name=region)
    cloud_formation = boto3.client("cloudformation", config=config)
    waiter = cloud_formation.get_waiter(status)
    # 180 attempts, one every 30 seconds, times out after 90 minutes
    waiter.wait(StackName=stack_name, WaiterConfig={"MaxAttempts": 180})


def _ec2_wait_running(region, instances):
    _ec2_wait(region, instances, "instance_running")


def _ec2_wait_terminated(region, instances):
    _ec2_wait(region, instances, "instance_terminated")


def _ec2_wait(region, instances, waiter_type):
    config = Config(region_name=region)
    ec2 = boto3.client("ec2", config=config)
    waiter = ec2.get_waiter(waiter_type)
    waiter.wait(InstanceIds=instances)


@pytest.mark.usefixtures("os", "instance")
def test_cluster_slurm(region, api_client, create_cluster, request, pcluster_config_reader, scheduler, instance):
    assert_that(scheduler).is_equal_to("slurm")
    _test_cluster_workflow(region, api_client, create_cluster, request, pcluster_config_reader, scheduler, instance)


@pytest.mark.usefixtures("os", "instance")
def test_cluster_awsbatch(region, api_client, create_cluster, request, pcluster_config_reader, scheduler, instance):
    assert_that(scheduler).is_equal_to("awsbatch")
    _test_cluster_workflow(region, api_client, create_cluster, request, pcluster_config_reader, scheduler, instance)


def _test_cluster_workflow(region, api_client, create_cluster, request, pcluster_config_reader, scheduler, instance):
    if scheduler == "slurm":
        initial_config_file = pcluster_config_reader()
        updated_config_file = pcluster_config_reader("pcluster.config.update.yaml")
    else:
        vcpus = get_instance_vcpus(region, instance) * NUM_OF_COMPUTE_INSTANCES
        initial_config_file = pcluster_config_reader(vcpus=vcpus)
        updated_config_file = pcluster_config_reader("pcluster.config.update.yaml", vcpus=vcpus)

    cluster_name = generate_stack_name("integ-tests", request.config.getoption("stackname_suffix"))
    cluster_operations_client = cluster_operations_api.ClusterOperationsApi(api_client)
    cluster_compute_fleet_client = cluster_compute_fleet_api.ClusterComputeFleetApi(api_client)
    cluster_instances_client = cluster_instances_api.ClusterInstancesApi(api_client)

    cluster = _test_create_cluster(cluster_operations_client, create_cluster, cluster_name, initial_config_file)

    _test_list_clusters(region, cluster_operations_client, cluster_name, "CREATE_IN_PROGRESS")
    _test_describe_cluster(region, cluster_operations_client, cluster_name, "CREATE_IN_PROGRESS")

    _cloudformation_wait(region, cluster_name, "stack_create_complete")

    cluster.mark_as_created()

    _test_list_clusters(region, cluster_operations_client, cluster_name, "CREATE_COMPLETE")
    _test_describe_cluster(region, cluster_operations_client, cluster_name, "CREATE_COMPLETE")

    # We wait for instances to be ready before transitioning stack to CREATE_COMPLETE only when using Slurm
    if scheduler == "awsbatch":
        wait_for_num_instances_in_cluster(region=region, cluster_name=cluster_name, desired=NUM_OF_COMPUTE_INSTANCES)

    # Update cluster with new configuration
    with open(updated_config_file) as config_file:
        updated_cluster_config = config_file.read()
    _test_update_cluster_dryrun(region, cluster_operations_client, cluster_name, updated_cluster_config)

    head_node = _test_describe_cluster_head_node(region, cluster_instances_client, cluster_name)
    compute_node_map = _test_describe_cluster_compute_nodes(region, cluster_instances_client, cluster_name)
    if scheduler == "slurm":
        _test_delete_cluster_instances(region, cluster_instances_client, cluster_name, head_node, compute_node_map)

    running_state = "RUNNING" if scheduler == "slurm" else "ENABLED"
    _test_describe_compute_fleet(region, cluster_compute_fleet_client, cluster_name, running_state)
    _test_stop_compute_fleet(region, cluster_compute_fleet_client, cluster_instances_client, cluster_name, scheduler)

    _test_delete_cluster(region, cluster_operations_client, cluster_name)


def _test_describe_cluster_head_node(region, client, cluster_name):
    response = client.describe_cluster_instances(cluster_name=cluster_name, node_type=NodeType("HEAD"), region=region)
    assert_that(response.instances).is_length(1)
    return response.instances[0].instance_id


def _test_describe_cluster_compute_nodes(region, client, cluster_name, all_terminated=False):
    compute_nodes_map = dict()

    response = client.describe_cluster_instances(
        cluster_name=cluster_name, node_type=NodeType("COMPUTE"), region=region
    )
    _add_compute_nodes(response.instances, compute_nodes_map)

    while "next_token" in response:
        response = client.describe_cluster_instances(
            cluster_name=cluster_name, node_type=NodeType("COMPUTE"), region=region, next_token=response.next_token
        )
        _add_compute_nodes(response.instances, compute_nodes_map)

    for instances in compute_nodes_map.values():
        if all_terminated:
            assert_that(instances).is_empty()
        else:
            assert_that(instances).is_not_empty()

    return compute_nodes_map


def _add_compute_nodes(instances, compute_node_map):
    for instance in instances:
        # The AWS Batch queue name is not populated
        queue_name = instance.get("queue_name", "awsbatch_queue")
        if queue_name not in compute_node_map:
            compute_node_map[queue_name] = set()
        compute_node_map[queue_name].add(instance.instance_id)


def _test_delete_cluster_instances(region, client, cluster_name, head_node, compute_node_map):
    instances_to_terminate = _get_instances_to_terminate(compute_node_map)
    client.delete_cluster_instances(cluster_name=cluster_name, region=region)
    _ec2_wait_terminated(region, instances_to_terminate)
    wait_for_num_instances_in_cluster(region=region, cluster_name=cluster_name, desired=NUM_OF_COMPUTE_INSTANCES)

    new_head_node = _test_describe_cluster_head_node(region, client, cluster_name)
    new_compute_node_map = _test_describe_cluster_compute_nodes(region, client, cluster_name)

    assert_that(new_head_node).is_equal_to(head_node)
    assert_that(new_compute_node_map.keys()).is_equal_to(compute_node_map.keys())
    for queue in new_compute_node_map.keys():
        assert_that(new_compute_node_map[queue]).is_not_equal_to(compute_node_map[queue])


def _test_describe_compute_fleet(region, client, cluster_name, status):
    response = client.describe_compute_fleet(cluster_name=cluster_name, region=region)
    LOGGER.info("Compute fleet status response: %s", response)
    assert_that(response.status).is_equal_to(ComputeFleetStatus(status))


def _test_stop_compute_fleet(region, cluster_compute_fleet_client, cluster_instances_client, cluster_name, scheduler):
    stop_status = "STOP_REQUESTED" if scheduler == "slurm" else "DISABLED"
    terminal_state = "STOPPED" if scheduler == "slurm" else "DISABLED"

    head_node = _test_describe_cluster_head_node(region, cluster_instances_client, cluster_name)
    compute_node_map = _test_describe_cluster_compute_nodes(region, cluster_instances_client, cluster_name)
    instances_to_terminate = _get_instances_to_terminate(compute_node_map)

    # EC2 instances in "pending" or "stopping" state cannot be terminated, so we will wait for the instances we
    # intend to terminate to go in the "running" state before terminating them.
    _ec2_wait_running(region, instances_to_terminate)

    cluster_compute_fleet_client.update_compute_fleet(
        cluster_name=cluster_name,
        update_compute_fleet_request_content=UpdateComputeFleetRequestContent(RequestedComputeFleetStatus(stop_status)),
        region=region,
    )

    if scheduler == "slurm":
        # AWS Batch does not terminate all compute nodes, it just resizes the compute fleet down to a number
        # of instances equal to MinvCpus. For AWS Batch we simply check that the compute fleet status has been
        # updated, while for the Slurm case we wait for the previous compute instances to have been terminated.
        _ec2_wait_terminated(region, instances_to_terminate)

    response = cluster_compute_fleet_client.describe_compute_fleet(cluster_name=cluster_name, region=region)
    assert_that(response.status).is_equal_to(ComputeFleetStatus(terminal_state))

    if scheduler == "slurm":
        new_head_node = _test_describe_cluster_head_node(region, cluster_instances_client, cluster_name)
        assert_that(new_head_node).is_equal_to(head_node)
        _test_describe_cluster_compute_nodes(region, cluster_instances_client, cluster_name, all_terminated=True)


def _get_instances_to_terminate(compute_node_map):
    instances_to_terminate = []
    for instances in compute_node_map.values():
        instances_to_terminate.extend(instances)
    return instances_to_terminate


def _test_list_clusters(region, client, cluster_name, status):
    response = client.list_clusters(region=region)
    target_cluster = _get_cluster(cluster_name, response.items)

    while "next_token" in response and not target_cluster:
        response = client.list_clusters(region=region, next_token=response.next_token)
        target_cluster = _get_cluster(cluster_name, response.items)

    assert_that(target_cluster).is_not_none()
    assert_that(target_cluster.cluster_name).is_equal_to(cluster_name)
    assert_that(target_cluster.cluster_status).is_equal_to(ClusterStatus(status))
    assert_that(target_cluster.cloudformation_stack_status).is_equal_to(CloudFormationStackStatus(status))


def _get_cluster(cluster_name, clusters):
    for cluster in clusters:
        if cluster.cluster_name == cluster_name:
            return cluster
    return None


def _test_describe_cluster(region, client, cluster_name, status):
    response = client.describe_cluster(cluster_name, region=region)
    LOGGER.info("Describe cluster response: %s", response)
    assert_that(response.cluster_name).is_equal_to(cluster_name)
    assert_that(response.cluster_status).is_equal_to(ClusterStatus(status))
    assert_that(response.cloud_formation_stack_status).is_equal_to(CloudFormationStackStatus(status))


def _test_create_cluster(client, create_cluster, cluster_name, config):
    cluster, response = create_cluster(client, cluster_name, config)
    LOGGER.info("Create cluster response: %s", response)
    assert_that(response.cluster.cluster_name).is_equal_to(cluster_name)
    return cluster


def _test_update_cluster_dryrun(region, client, cluster_name, config):
    body = UpdateClusterRequestContent(config)
    error_message = "Request would have succeeded, but DryRun flag is set."
    with pytest.raises(ApiException, match=error_message):
        client.update_cluster(cluster_name, body, region=region, dryrun=True)


def _test_delete_cluster(region, client, cluster_name):
    client.delete_cluster(cluster_name, region=region)

    _cloudformation_wait(region, cluster_name, "stack_delete_complete")

    error_message = (
        f"Cluster '{cluster_name}' does not exist or belongs to an incompatible ParallelCluster major version."
    )
    with pytest.raises(NotFoundException, match=error_message):
        client.describe_cluster(cluster_name, region=region)


def test_official_images(region, api_client):
    client = image_operations_api.ImageOperationsApi(api_client)
    response = client.describe_official_images(region=region)
    assert_that(response.items).is_not_empty()


@pytest.mark.usefixtures("instance")
def test_custom_image(region, api_client, build_image, os, request, pcluster_config_reader):
    base_ami = retrieve_latest_ami(region, os)

    config_file = pcluster_config_reader(config_file="image.config.yaml", parent_image=base_ami)
    with open(config_file) as config_file:
        config = config_file.read()

    image_id = generate_stack_name("integ-tests-build-image", request.config.getoption("stackname_suffix"))
    client = image_operations_api.ImageOperationsApi(api_client)

    _test_build_image(client, build_image, image_id, config)

    _test_describe_image(region, client, image_id, "BUILD_IN_PROGRESS")
    _test_list_images(region, client, image_id, "PENDING")

    # CFN stack is deleted as soon as image is available
    _cloudformation_wait(region, image_id, "stack_delete_complete")

    _test_describe_image(region, client, image_id, "BUILD_COMPLETE")
    _test_list_images(region, client, image_id, "AVAILABLE")

    _delete_image(region, client, image_id)


def _test_build_image(client, build_image, image_id, config):
    response = build_image(client, image_id, config)
    LOGGER.info("Build image response: %s", response)
    assert_that(response.image.image_id).is_equal_to(image_id)


def _test_describe_image(region, client, image_id, status):
    response = client.describe_image(image_id, region=region)
    LOGGER.info("Describe image response: %s", response)
    assert_that(response.image_id).is_equal_to(image_id)
    assert_that(response.image_build_status).is_equal_to(ImageBuildStatus(status))


def _test_list_images(region, client, image_id, status):
    response = client.list_images(image_status=ImageStatusFilteringOption(status), region=region)
    target_image = _get_image(image_id, response.items)

    while "next_token" in response and not target_image:
        response = client.list_images(
            image_status=ImageStatusFilteringOption(status), region=region, next_token=response.next_token
        )
        target_image = _get_image(image_id, response.items)

    LOGGER.info("Target image in ListImages response is: %s", target_image)

    assert_that(target_image).is_not_none()


def _get_image(image_id, images):
    for image in images:
        if image.image_id == image_id:
            return image
    return None


def _delete_image(region, client, image_id):
    client.delete_image(image_id, region=region)

    error_message = f"No image or stack associated with ParallelCluster image id: {image_id}."
    with pytest.raises(NotFoundException, match=error_message):
        client.describe_image(image_id, region=region)
