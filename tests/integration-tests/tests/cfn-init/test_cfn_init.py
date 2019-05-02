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
from retrying import retry

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from tests.common.schedulers_common import SlurmCommands
from time_utils import minutes, seconds


@pytest.mark.regions(["eu-central-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_replace_compute_on_failure(region, pcluster_config_reader, clusters_factory, s3_bucket_factory, test_datadir):
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
    sge_commands = SlurmCommands(remote_command_executor)
    sge_commands.submit_command("sleep 1")
    instance_id = _wait_compute_log(remote_command_executor)

    # extract logs and check one of them
    remote_command_executor.run_remote_command(
        "tar -xf /home/logs/compute/{0}.tar.gz --directory /tmp".format(instance_id)
    )
    remote_command_executor.run_remote_command("test -f /tmp/var/log/nodewatcher")
    messages_log = remote_command_executor.run_remote_command("cat /tmp/var/log/messages", hide=True).stdout
    assert_that(messages_log).contains(
        "Reporting instance as unhealthy and dumping logs to /home/logs/compute/{0}.tar.gz".format(instance_id)
    )

    # check that instance got already replaced or is marked as Unhealthy
    response = boto3.client("autoscaling", region_name=region).describe_auto_scaling_instances(
        InstanceIds=[instance_id]
    )
    assert_that(
        not response["AutoScalingInstances"] or response["AutoScalingInstances"][0]["HealthStatus"] == "UNHEALTHY"
    ).is_true()


@retry(
    retry_on_exception=lambda exception: isinstance(exception, RemoteCommandExecutionError),
    wait_fixed=seconds(30),
    stop_max_delay=minutes(10),
)
def _wait_compute_log(remote_command_executor):
    remote_command_executor.run_remote_command("test -d /home/logs/compute", log_error=False)
    # return instance-id
    return remote_command_executor.run_remote_command(
        "find /home/logs/compute/ -type f -printf '%f\n' -quit  | head -1 | cut -d. -f1", log_error=False
    ).stdout
