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
from tests.common.software_installer import (
    assert_slurm_controller_healthy,
    install_test_software_with_stopped_consumers,
)


@pytest.mark.parametrize("scale_up_fleet", [False])
@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
def test_pyxis(pcluster_config_reader, clusters_factory, test_datadir, s3_bucket_factory, region, scale_up_fleet):
    """
    Test Pyxis and Enroot functionality after configuration.


    This test creates a cluster with the necessary custom actions to configure Pyxis and Enroot.
    It submits two consecutive containerized jobs and verifies that they run successfully,
    and the output contains the expected messages.
    """
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

    _run_pyxis_job(
        remote_command_executor,
        slurm_commands,
        nodes=max_queue_size,
        job_description="first",
        timeout=30 if scale_up_fleet else 12,
    )
    _run_pyxis_job(remote_command_executor, slurm_commands, nodes=3, job_description="second")

    install_test_software_with_stopped_consumers(remote_command_executor, region, cluster)
    assert_slurm_controller_healthy(remote_command_executor)

    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = SlurmCommands(remote_command_executor)
    _run_pyxis_job(remote_command_executor, slurm_commands, nodes=3, job_description="post-install")


def _run_pyxis_job(remote_command_executor, slurm_commands, nodes, job_description, timeout=None):
    """Submit a containerized job and verify that Pyxis imported the expected image."""
    logging.info("Submitting %s containerized job", job_description)
    result = slurm_commands.submit_command(
        command="srun --container-image docker://ubuntu:22.04 hostname",
        nodes=nodes,
    )
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    if timeout is None:
        slurm_commands.wait_job_completed(job_id)
    else:
        slurm_commands.wait_job_completed(job_id, timeout=timeout)
    slurm_commands.assert_job_succeeded(job_id)

    logging.info("Checking output of the %s job", job_description)
    slurm_output = remote_command_executor.run_remote_command(f"cat slurm-{job_id}.out").stdout

    logging.info("Checking for expected messages in %s job output", job_description)
    assert_that(slurm_output).contains("pyxis: imported docker image: docker://ubuntu:22.04")
