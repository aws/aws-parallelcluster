# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from utils import describe_cluster_instances, retrieve_cfn_resources


@pytest.mark.usefixtures("os", "region")
def test_on_demand_capacity_reservation(
    region, pcluster_config_reader, placement_group_stack, odcr_stack, clusters_factory
):
    """Verify open, targeted and pg odcrs can be created and instances can be launched into them."""

    """This test is only for slurm."""

    resource_groups_client = boto3.client("resource-groups")
    odcr_resources = retrieve_cfn_resources(odcr_stack.name, region)
    resource_group_arn = resource_groups_client.get_group(Group=odcr_stack.cfn_resources["integTestsOdcrGroup"])[
        "Group"
    ]["GroupArn"]

    cluster_config = pcluster_config_reader(
        placement_group=placement_group_stack.cfn_resources["PlacementGroup"],
        open_capacity_reservation_id=odcr_resources["integTestsOpenOdcr"],
        open_capacity_reservation_arn=resource_group_arn,
        target_capacity_reservation_id=odcr_resources["integTestsTargetOdcr"],
        target_capacity_reservation_arn=resource_group_arn,
        pg_capacity_reservation_id=odcr_resources["integTestsPgOdcr"],
        pg_capacity_reservation_arn=resource_group_arn,
    )
    cluster = clusters_factory(cluster_config)

    _assert_instance_in_capacity_reservation(cluster, region, "open-odcr-id-cr", odcr_resources["integTestsOpenOdcr"])
    _assert_instance_in_capacity_reservation(cluster, region, "open-odcr-arn-cr", odcr_resources["integTestsOpenOdcr"])
    _assert_instance_in_capacity_reservation(
        cluster, region, "open-odcr-id-pg-cr", odcr_resources["integTestsOpenOdcr"]
    )
    _assert_instance_in_capacity_reservation(
        cluster, region, "open-odcr-arn-pg-cr", odcr_resources["integTestsOpenOdcr"]
    )
    _assert_instance_in_capacity_reservation(
        cluster, region, "target-odcr-id-cr", odcr_resources["integTestsTargetOdcr"]
    )
    _assert_instance_in_capacity_reservation(
        cluster, region, "target-odcr-arn-cr", odcr_resources["integTestsTargetOdcr"]
    )
    _assert_instance_in_capacity_reservation(
        cluster, region, "target-odcr-id-pg-cr", odcr_resources["integTestsTargetOdcr"]
    )
    _assert_instance_in_capacity_reservation(
        cluster, region, "target-odcr-arn-pg-cr", odcr_resources["integTestsTargetOdcr"]
    )
    _assert_instance_in_capacity_reservation(cluster, region, "pg-odcr-id-cr", odcr_resources["integTestsPgOdcr"])
    _assert_instance_in_capacity_reservation(cluster, region, "pg-odcr-arn-cr", odcr_resources["integTestsPgOdcr"])


def _assert_instance_in_capacity_reservation(cluster, region, compute_resource_name, expected_reservation):
    instances = describe_cluster_instances(cluster.name, region, filter_by_compute_resource_name=compute_resource_name)
    if len(instances) == 1:
        logging.info("One instance found!")
        assert_that(instances[0]["CapacityReservationId"]).is_equal_to(expected_reservation)
    else:
        logging.error("Too many instances returned from describe_cluster_instances")
        pytest.fail("Too many instances found")
