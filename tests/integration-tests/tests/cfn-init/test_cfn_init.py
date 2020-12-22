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
import time

import boto3
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor

from tests.common.assertions import assert_instance_replaced_or_terminating
from tests.common.compute_logs_common import wait_compute_log
from tests.common.schedulers_common import get_scheduler_commands


@pytest.mark.regions(["eu-central-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm", "sge"])
@pytest.mark.oss(["centos7", "centos8", "alinux2", "ubuntu1804"])
@pytest.mark.usefixtures("os", "instance")
def test_replace_compute_on_failure(
    region, scheduler, pcluster_config_reader, clusters_factory, s3_bucket_factory, test_datadir
):
    """
    Test that compute nodes get replaced on userdata failures and logs get saved in shared directory.

    The failure is caused by a post_install script that exits with errors on compute nodes.
    """
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "post_install.sh"), "post_install.sh")
    cluster_config = pcluster_config_reader(bucket_name=bucket_name)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # submit a job to spin up a compute node that will fail due to post_install script
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    scheduler_commands.submit_command("sleep 1")
    instance_id = wait_compute_log(remote_command_executor)[0]

    # extract logs and check one of them
    _assert_compute_logs(remote_command_executor, instance_id)

    # check that instance got already replaced or is marked as Unhealthy
    time.sleep(15)  # Instance waits for 10 seconds before terminating to allow logs to propagate to CloudWatch
    assert_instance_replaced_or_terminating(instance_id, region)


@pytest.mark.dimensions("us-west-1", "c5.xlarge", "centos7", "slurm")
@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_install_args_quotes(region, pcluster_config_reader, clusters_factory, s3_bucket_factory, test_datadir):
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


def _assert_compute_logs(remote_command_executor, instance_id):
    remote_command_executor.run_remote_command(
        "tar -xf /home/logs/compute/{0}.tar.gz --directory /tmp".format(instance_id)
    )
    remote_command_executor.run_remote_command("test -f /tmp/var/log/cloud-init-output.log")
    output = remote_command_executor.run_remote_command(
        'find /tmp/var/log -type f | xargs grep "Reporting instance as unhealthy and dumping logs to"',
        hide=True,
        login_shell=False,
    ).stdout
    assert_that(output).is_not_empty()


def _assert_server_status(cluster):
    expected_status = ["Status: CREATE_COMPLETE", "MasterServer: RUNNING", "ComputeFleetStatus: RUNNING"]
    cluster_status = cluster.status()
    for detail in expected_status:
        assert_that(cluster_status).contains(detail)
