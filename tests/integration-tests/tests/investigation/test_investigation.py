# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from remote_command_executor import RemoteCommandExecutor


@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_investigation(
    region,
    scheduler,
    pcluster_config_reader,
    vpc_stack,
    s3_bucket_factory,
    test_datadir,
    clusters_factory,
    scheduler_commands_factory,
):
    """Create a cluster with custom actions on all node types and verify a job succeeds."""
    logging.info("Starting investigation test")

    # Create S3 bucket and upload custom action scripts
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "on_node_start.sh"), "scripts/on_node_start.sh")
    bucket.upload_file(str(test_datadir / "on_node_configured.sh"), "scripts/on_node_configured.sh")

    # Create the cluster
    on_node_start_script = f"s3://{bucket_name}/scripts/on_node_start.sh"
    on_node_configured_script = f"s3://{bucket_name}/scripts/on_node_configured.sh"
    cluster_config = pcluster_config_reader(
        bucket_name=bucket_name,
        on_node_start_script=on_node_start_script,
        on_node_configured_script=on_node_configured_script,
    )
    cluster = clusters_factory(cluster_config)

    # Submit a dummy job and assert it succeeds
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    _assert_dummy_job_succeeds(scheduler_commands)

    logging.info("Investigation test completed successfully")


def _assert_dummy_job_succeeds(scheduler_commands):
    """Submit a dummy job and assert it completes successfully."""
    result = scheduler_commands.submit_command("hostname", nodes=1)
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
