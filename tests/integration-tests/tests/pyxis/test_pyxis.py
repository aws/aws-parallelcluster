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

import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor

from tests.common.schedulers_common import SlurmCommands


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
def test_pyxis(pcluster_config_reader, clusters_factory, test_datadir):
    """
    Test Enroot and Pyxis failure due to concurrent sed operations on internal shared filesystem.

    This test creates a cluster with EFS as internal shared storage and 2000 dynamic compute nodes.
    It submits a simple job to scale up the cluster, and then submits a Pyxis job which should fail
    due to the known issue in version 3.11.0.

    The test checks that the expected error messages appear in the job output.
    """
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)

    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = SlurmCommands(remote_command_executor)

    # Submit a simple job to scale up to 2000 nodes
    logging.info("Submitting job to scale up to 2000 nodes")
    job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "srun hostname", "nodes": 2000}
    )
    slurm_commands.wait_job_completed(job_id, timeout=30)
    slurm_commands.assert_job_succeeded(job_id)

    # Submit the Pyxis job which is expected to fail
    logging.info("Submitting Pyxis job which should fail")
    result = slurm_commands.submit_script(
        script=str(test_datadir / "test.sh"),
        other_options="--wait -o slurm.out",
    )

    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)

    # Fetch the job output and check for the expected error messages
    logging.info("Fetching job output")
    slurm_out = remote_command_executor.run_remote_command("cat slurm.out").stdout

    logging.info("Checking for expected error messages in job output")
    assert_that(slurm_out).contains("Failed to open /opt/slurm/etc/plugstack.conf.d/")
    assert_that(slurm_out).contains("Permission denied")
    assert_that(slurm_out).contains("Plug-in initialization failed")
