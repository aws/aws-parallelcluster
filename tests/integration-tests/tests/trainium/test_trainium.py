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
import boto3
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor


@pytest.mark.usefixtures("os", "scheduler")
def test_trainium(
    region,
    pcluster_config_reader,
    test_datadir,
    clusters_factory,
    s3_bucket_factory,
    scheduler_commands_factory,
):
    # Post-install script to install Neuronx packages
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "neuron-installation.sh"), "neuron-installation.sh")

    cluster_config = pcluster_config_reader(bucket_name=bucket_name)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    # TODO uncomment allreduce test when bug fix in collective library
    # _test_allreduce_single_node(test_datadir, remote_command_executor, scheduler_commands)
    _test_ccl_two_nodes(test_datadir, remote_command_executor, scheduler_commands)


def _test_allreduce_single_node(test_datadir, remote_command_executor, scheduler_commands):
    result = scheduler_commands.submit_script(str(test_datadir / "neuron-allreduce.sh"), partition="queue-trn2")
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
    result = remote_command_executor.run_remote_command("cat output-allreduce.txt")

    print(result.stdout)
    assert_that(result.stdout).matches(".*PASSED.*")


def _test_ccl_two_nodes(test_datadir, remote_command_executor, scheduler_commands):
    result = scheduler_commands.submit_script(
        str(test_datadir / "neuron-ccl.sh"),
        nodes=2,
        partition="queue-trn32",
        other_options="--ntasks-per-node=1 --cpus-per-task=32",
    )
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
    result = remote_command_executor.run_remote_command("cat output-ccl.txt")

    print(result.stdout)
    assert_that(result.stdout).contains("CCL(1)", "CCL(50)", "CCL(99)", "CCL(100)")
