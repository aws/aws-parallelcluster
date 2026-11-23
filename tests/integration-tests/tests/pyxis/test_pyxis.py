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
from tests.common.slurm_upgrade import (
    assert_shared_slurm_version,
    get_slurm_version,
    roll_back_slurm,
    select_slurm_upgrade_target,
    slurm_release,
    stopped_compute_nodes,
    upgrade_slurm,
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
    bucket.upload_file(str(test_datadir / "compute_node_configured.sh"), "compute_node_configured.sh")

    cluster_config = pcluster_config_reader(bucket_name=bucket_name, max_queue_size=max_queue_size)
    cluster = clusters_factory(cluster_config)

    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = SlurmCommands(remote_command_executor)

    # Submit the first containerized job with dynamic 3 or 1000 nodes
    logging.info("Submitting first containerized job")

    result = slurm_commands.submit_command(
        command="srun --container-image docker://ubuntu:22.04 hostname",
        nodes=max_queue_size,
    )
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id, timeout=30 if scale_up_fleet else 12)
    slurm_commands.assert_job_succeeded(job_id)

    # Fetch the job output and check for the expected messages
    logging.info("Checking output of the first job")
    slurm_out_1 = remote_command_executor.run_remote_command("cat slurm-1.out").stdout

    logging.info("Checking for expected messages in first job output")
    assert_that(slurm_out_1).contains("pyxis: imported docker image: docker://ubuntu:22.04")

    # Submit the second containerized job with fixed 3 nodes after the first one completes
    logging.info("Submitting second containerized job")
    result = slurm_commands.submit_command(
        command="srun --container-image docker://ubuntu:22.04 hostname",
        nodes=3,
    )
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    slurm_commands.assert_job_succeeded(job_id)

    # Fetch the job output and check for the expected messages
    logging.info("Checking output of the second job")
    slurm_out_2 = remote_command_executor.run_remote_command("cat slurm-2.out").stdout

    logging.info("Checking for expected messages in second job output")
    assert_that(slurm_out_2).contains("pyxis: imported docker image: docker://ubuntu:22.04")

    target = select_slurm_upgrade_target(remote_command_executor)
    if not target:
        return
    slurm_version_before = get_slurm_version(remote_command_executor)
    with stopped_compute_nodes(cluster):
        upgrade_slurm(remote_command_executor, target)
        slurm_version_after = get_slurm_version(remote_command_executor)
        # Appendix B, while no compute node is up to load a stale plugin.
        _rebuild_pyxis_if_slurm_major_changed(
            remote_command_executor, test_datadir, bucket, slurm_version_before, slurm_version_after
        )
    remote_command_executor = RemoteCommandExecutor(cluster)

    logging.info("Submitting third containerized job")
    _test_containerized_job(remote_command_executor)

    # /opt/slurm is on the internal EFS here, and Appendix D.5 reverts the plugin.
    with stopped_compute_nodes(cluster):
        roll_back_slurm(remote_command_executor, expected_version=slurm_version_before)
        _rebuild_pyxis_if_slurm_major_changed(
            remote_command_executor, test_datadir, bucket, slurm_version_after, slurm_version_before
        )
    remote_command_executor = RemoteCommandExecutor(cluster)
    assert_shared_slurm_version(
        remote_command_executor, SlurmCommands(remote_command_executor), slurm_version_before, partition="queue-0"
    )
    logging.info("Submitting fourth containerized job")
    _test_containerized_job(remote_command_executor)


def _test_containerized_job(remote_command_executor):
    slurm_commands = SlurmCommands(remote_command_executor)
    result = slurm_commands.submit_command(
        command="srun --container-image docker://ubuntu:22.04 hostname",
        nodes=3,
    )
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    slurm_commands.assert_job_succeeded(job_id)
    slurm_out = remote_command_executor.run_remote_command(f"cat slurm-{job_id}.out").stdout
    assert_that(slurm_out).contains("pyxis: imported docker image: docker://ubuntu:22.04")


def _rebuild_pyxis_if_slurm_major_changed(remote_command_executor, test_datadir, bucket, version_before, version_after):
    """Appendix B.2 and D.5 of the upgrade wiki page: rebuild the Pyxis SPANK plugin when Slurm crossed a major release.

    Slurm refuses a plugin stamped with another major release, which breaks every srun and sbatch. The plugin is on
    the root volume of each node, so it is rebuilt on the head node now and, through the OnNodeConfigured script of the
    compute queue, on every compute node at boot. Within a major release the plugin of the AMI is left alone.
    """
    if slurm_release(version_before)[:2] == slurm_release(version_after)[:2]:
        logging.info(
            "Slurm stayed on its major release (%s -> %s), keeping the Pyxis plugin", version_before, version_after
        )
        return

    logging.info(
        "Slurm crossed a major release (%s -> %s), rebuilding the Pyxis SPANK plugin", version_before, version_after
    )
    remote_command_executor.run_remote_script(
        str(test_datadir / "rebuild_pyxis.sh"), run_as_root=True, timeout=1800, pty=False
    )
    bucket.upload_file(str(test_datadir / "rebuild_pyxis.sh"), "compute_node_configured.sh")
