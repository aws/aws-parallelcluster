# Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from remote_command_executor import RemoteCommandExecutor

from tests.common.schedulers_common import SlurmCommands


@pytest.mark.usefixtures("region", "os", "instance", "scheduler", "scale_up_fleet")
def test_pyxis(pcluster_config_reader, clusters_factory, test_datadir, s3_bucket_factory, region, scale_up_fleet):
    """
    Test Pyxis and Enroot functionality after configuration.


    This test creates a cluster with the necessary custom actions to configure Pyxis and Enroot.
    It submits two consecutive containerized jobs and verifies that they run successfully,
    and the output contains the expected messages.
    """
    # Convert scale_up_fleet to boolean
    scale_up_fleet = scale_up_fleet.strip().lower() == "true"

    # Set max_queue_size based on scale_up_fleet
    max_queue_size = 1000 if scale_up_fleet else 3

    # Create an S3 bucket for custom action scripts
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)

    # Pre-upload custom scripts that set up pyxis to S3
    bucket.upload_file(str(test_datadir / "head_node_configure.sh"), "head_node_configure.sh")
    bucket.upload_file(str(test_datadir / "compute_node_start.sh"), "compute_node_start.sh")

    cluster_config = pcluster_config_reader(bucket_name=bucket_name, max_queue_size=max_queue_size)
    cluster = clusters_factory(cluster_config)

    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = SlurmCommands(remote_command_executor)

    if scale_up_fleet:
        job_id = slurm_commands.submit_command_and_assert_job_accepted(
            submit_command_args={"command": "srun hostname", "nodes": 1000}
        )
        slurm_commands.wait_job_completed(job_id, timeout=30)
        slurm_commands.assert_job_succeeded(job_id)

    # Submit the first containerized job
    logging.info("Submitting first containerized job")

    result = slurm_commands.submit_command(
        command="srun --container-image docker://ubuntu:22.04 hostname",
        nodes=3,
        other_options="-o slurm1.out",
    )
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    slurm_commands.assert_job_succeeded(job_id)

    # Fetch the job output and check for the expected messages
    logging.info("Checking output of the first job")
    slurm_out_1 = remote_command_executor.run_remote_command("cat slurm1.out").stdout

    logging.info("Checking for expected messages in first job output")
    assert_that(slurm_out_1).contains("pyxis: importing docker image: docker://ubuntu:22.04")

    # Submit the second containerized job after the first one completes
    logging.info("Submitting second containerized job")
    result = slurm_commands.submit_command(
        command="srun --container-image docker://ubuntu:22.04 hostname",
        nodes=3,
        other_options="-o slurm2.out",
    )
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    slurm_commands.assert_job_succeeded(job_id)

    # Fetch the job output and check for the expected messages
    logging.info("Checking output of the second job")
    slurm_out_2 = remote_command_executor.run_remote_command("cat slurm2.out").stdout

    logging.info("Checking for expected messages in second job output")
    assert_that(slurm_out_2).contains("pyxis: importing docker image: docker://ubuntu:22.04")
