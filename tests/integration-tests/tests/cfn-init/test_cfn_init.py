# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from remote_command_executor import RemoteCommandExecutor
from utils import check_status

from tests.common.assertions import wait_for_num_instances_in_cluster, wait_instance_replaced_or_terminating


@pytest.mark.usefixtures("os", "instance")
def test_replace_compute_on_failure(
    region, pcluster_config_reader, s3_bucket_factory, clusters_factory, test_datadir, scheduler_commands_factory
):
    """
    Test that compute nodes get replaced on userdata failures and logs get saved in shared directory.

    The failure is caused by a post_install script that exits with errors on compute nodes.
    """
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "failing_post_install.sh"), "failing_post_install.sh")
    cluster_config = pcluster_config_reader(bucket_name=bucket_name)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # submit a job to spin up a compute node that will fail due to post_install script
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    scheduler_commands.submit_command("sleep 1")

    # Wait for the instance to become running
    instances = wait_for_num_instances_in_cluster(cluster.cfn_name, cluster.region, desired=1)

    wait_instance_replaced_or_terminating(instances[0], region)


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_install_args_quotes(region, pcluster_config_reader, s3_bucket_factory, clusters_factory, test_datadir):
    """
    Test pre/post install args with single quote and double quotes.

    The cluster should be created and running.
    """
    # Create S3 bucket for pre/post install scripts
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "pre_install.sh"), "scripts/pre_install.sh")
    bucket.upload_file(str(test_datadir / "post_install.sh"), "scripts/post_install.sh")

    # Create cluster with initial configuration
    init_config_file = pcluster_config_reader(bucket_name=bucket_name)
    cluster = clusters_factory(init_config_file)

    # Check head node and compute node status
    _assert_server_status(cluster)


def _assert_server_status(cluster):
    check_status(cluster, "CREATE_COMPLETE", "running", "RUNNING")
