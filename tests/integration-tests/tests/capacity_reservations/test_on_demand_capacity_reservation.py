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
import json
import logging
import os
import shutil
import subprocess
import tempfile
import venv

import boto3
import pytest
from assertpy import assert_that
from clusters_factory import Cluster
from utils import describe_cluster_instances, random_alphanumeric, retrieve_cfn_resources, wait_for_computefleet_changed


def _run_pcluster_command_in_venv(pcluster_path, args, timeout=7200):
    """Run pcluster command using the specified pcluster executable."""
    command = [pcluster_path] + args
    logging.info("Executing command: %s", " ".join(command))
    result = subprocess.run(
        command,
        capture_output=True,
        universal_newlines=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if result.returncode != 0:
        logging.error("Command failed with error:\n%s\nand output:\n%s", result.stderr, result.stdout)
    return result


def _create_cluster_with_custom_pcluster(pcluster_path, cluster_name, config_file, region):
    """Create a cluster using a custom pcluster executable."""
    logging.info("Creating cluster %s with config %s using custom pcluster", cluster_name, config_file)
    args = [
        "create-cluster",
        "--rollback-on-failure", "false",
        "--cluster-configuration", config_file,
        "--cluster-name", cluster_name,
        "--region", region,
        "--wait",
    ]
    result = _run_pcluster_command_in_venv(pcluster_path, args)
    response = json.loads(result.stdout)
    if response.get("cloudFormationStackStatus") != "CREATE_COMPLETE":
        raise Exception(f"Cluster creation failed for {cluster_name}: {result.stdout}")
    logging.info("Cluster %s created successfully", cluster_name)
    return response


@pytest.mark.usefixtures("os", "region")
def test_on_demand_capacity_reservation(
    region, pcluster_config_reader, placement_group_stack, odcr_stack, request
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

    # Create an isolated virtual environment for the patched CLI
    # This avoids affecting other parallel tests that share the same Python environment
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
    s3_bucket_file = os.path.join(repo_root, "cli/src/pcluster/models/s3_bucket.py")

    # Backup the original file
    with open(s3_bucket_file, "r") as f:
        original_content = f.read()

    venv_dir = tempfile.mkdtemp(prefix="pcluster_test_odcr_")
    cluster_name = f"integ-tests-{random_alphanumeric()}"
    cluster = None
    pcluster_path = None

    try:
        # Create isolated virtual environment
        logging.info("Creating isolated virtual environment at %s", venv_dir)
        venv.create(venv_dir, with_pip=True)

        pip_path = os.path.join(venv_dir, "bin", "pip")
        pcluster_path = os.path.join(venv_dir, "bin", "pcluster")

        # Apply the patch - inject the bug that replaces capacity reservation IDs
        logging.info("Applying patch to the repository")
        modified_content = original_content.replace(
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

        # Install the patched CLI into the isolated environment
        logging.info("Installing patched CLI into isolated virtual environment")
        subprocess.run([pip_path, "install", "./cli"], cwd=repo_root, check=True)

        # Revert the patch by restoring the original file
        logging.info("Reverting patch from the repository")
        with open(s3_bucket_file, "w") as f:
            f.write(original_content)

        # Create the cluster using the patched pcluster from isolated environment
        _create_cluster_with_custom_pcluster(pcluster_path, cluster_name, str(cluster_config), region)

        # Create a Cluster object for the rest of the test (uses system pcluster for other operations)
        cluster = Cluster(
            name=cluster_name,
            config_file=str(cluster_config),
            ssh_key=request.config.getoption("key_path"),
            region=region,
        )
        cluster.mark_as_created()

        _assert_instance_in_capacity_reservation(
            cluster, region, "open-odcr-id-cr", odcr_resources["integTestsOpenOdcr"]
        )
        _assert_instance_in_capacity_reservation(
            cluster, region, "open-odcr-arn-cr", odcr_resources["integTestsOpenOdcr"]
        )
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
        _assert_instance_in_capacity_reservation(
            cluster, region, "pg-odcr-id-cr", odcr_resources["integTestsPgOdcr"]
        )
        _assert_instance_in_capacity_reservation(
            cluster, region, "pg-odcr-arn-cr", odcr_resources["integTestsPgOdcr"]
        )

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

    finally:
        # Ensure original file is restored
        with open(s3_bucket_file, "w") as f:
            f.write(original_content)

        # Clean up the cluster
        if cluster and not request.config.getoption("no_delete"):
            try:
                cluster.delete()
            except Exception as e:
                logging.error("Failed to delete cluster: %s", e)

        # Clean up the isolated virtual environment
        logging.info("Cleaning up isolated virtual environment")
        shutil.rmtree(venv_dir, ignore_errors=True)


def _assert_instance_in_capacity_reservation(cluster, region, compute_resource_name, expected_reservation):
    instances = describe_cluster_instances(cluster.name, region, filter_by_compute_resource_name=compute_resource_name)
    if len(instances) == 1:
        assert_that(instances[0]["CapacityReservationId"]).is_equal_to(expected_reservation)
        logging.info(f"One instance launched in the {expected_reservation}")
    else:
        logging.error("Too many instances returned from describe_cluster_instances")
        pytest.fail(f"Too many instances found in the {expected_reservation}")
