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
import os
import subprocess

import boto3
import pytest
from assertpy import assert_that
from utils import describe_cluster_instances, retrieve_cfn_resources, wait_for_computefleet_changed


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

    # Apply patch to the repo
    logging.info("Applying patch to the repository")
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
    s3_bucket_file = os.path.join(repo_root, "cli/src/pcluster/models/s3_bucket.py")

    # Backup the original file
    with open(s3_bucket_file, "r") as f:
        original_content = f.read()

    try:
        # Apply the patch - inject the bug that replaces capacity reservation IDs
        with open(s3_bucket_file, "r") as f:
            content = f.read()

        # Add the bug injection line after the upload_config method definition
        modified_content = content.replace(
            "    def upload_config(self, config, config_name, format=S3FileFormat.YAML):\n"
            '        """Upload config file to S3 bucket."""',
            "    def upload_config(self, config, config_name, format=S3FileFormat.YAML):\n"
            '        """Upload config file to S3 bucket."""\n'
            '        if config_name == "cluster-config.yaml":\n'
            "            config = re.sub(r'cr-[0-9a-f]{17}', 'cr-11111111111111111', config)",
        )

        # Write the modified content back
        with open(s3_bucket_file, "w") as f:
            f.write(modified_content)

        # Install the CLI
        logging.info("Installing CLI from local repository")
        subprocess.run(["pip", "install", "./cli"], cwd=repo_root, check=True)

        # Create the cluster
        cluster = clusters_factory(cluster_config)
    finally:
        # Revert the patch by restoring the original file
        logging.info("Reverting patch from the repository")
        with open(s3_bucket_file, "w") as f:
            f.write(original_content)

        # Reinstall the CLI
        logging.info("Reinstalling CLI from local repository")
        subprocess.run(["pip", "install", "./cli"], cwd=repo_root, check=True)

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
    cluster.stop()
    wait_for_computefleet_changed(cluster, "STOPPED")
    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update.yaml",
        placement_group=placement_group_stack.cfn_resources["PlacementGroup"],
        open_capacity_reservation_id=odcr_resources["integTestsOpenOdcr"],
        open_capacity_reservation_arn=resource_group_arn,
        target_capacity_reservation_id=odcr_resources["integTestsTargetOdcr"],
        target_capacity_reservation_arn=resource_group_arn,
        pg_capacity_reservation_id=odcr_resources["integTestsPgOdcr"],
        pg_capacity_reservation_arn=resource_group_arn,
    )
    cluster.update(str(updated_config_file))


def _assert_instance_in_capacity_reservation(cluster, region, compute_resource_name, expected_reservation):
    instances = describe_cluster_instances(cluster.name, region, filter_by_compute_resource_name=compute_resource_name)
    if len(instances) == 1:
        assert_that(instances[0]["CapacityReservationId"]).is_equal_to(expected_reservation)
        logging.info(f"One instance launched in the {expected_reservation}")
    else:
        logging.error("Too many instances returned from describe_cluster_instances")
        pytest.fail(f"Too many instances found in the {expected_reservation}")
