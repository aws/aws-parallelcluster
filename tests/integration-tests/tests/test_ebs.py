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
import logging

import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from tests.common.schedulers_common import get_scheduler_commands


@pytest.mark.regions(["us-east-1", "eu-west-1", "cn-north-1", "us-gov-west-1"])
@pytest.mark.instances(["c4.xlarge", "c5.xlarge"])
@pytest.mark.schedulers(["sge", "awsbatch"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_ebs_single(scheduler, pcluster_config_reader, clusters_factory):
    mount_dir = "ebs_mount_dir"
    cluster_config = pcluster_config_reader(mount_dir=mount_dir)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    mount_dir = "/" + mount_dir
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size=20)
    _test_ebs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


@pytest.mark.regions(["us-east-1", "eu-west-1", "cn-north-1", "us-gov-west-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["sge", "awsbatch"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_ebs_multiple(scheduler, pcluster_config_reader, clusters_factory):
    mount_dirs = ["/ebs_mount_dir_{0}".format(i) for i in range(0, 5)]
    volume_sizes = [15 + 5 * i for i in range(0, 5)]
    cluster_config = pcluster_config_reader(mount_dirs=mount_dirs, volume_sizes=volume_sizes)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    for mount_dir, volume_size in zip(mount_dirs, volume_sizes):
        _test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size)
        _test_ebs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


def _test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size):
    logging.info("Testing ebs {0} is correctly mounted".format(mount_dir))
    result = remote_command_executor.run_remote_command(
        "df -h -t ext4 | tail -n +2 | awk '{{print $2, $6}}' | grep '{0}'".format(mount_dir)
    )
    assert_that(result.stdout).matches(r"{size}G {mount_dir}".format(size=volume_size, mount_dir=mount_dir))

    result = remote_command_executor.run_remote_command("cat /etc/fstab")
    assert_that(result.stdout).matches(
        r"/dev/disk/by-ebs-volumeid/vol-[a-z0-9]{{17}} {mount_dir} ext4 _netdev 0 0".format(mount_dir=mount_dir)
    )


def _test_ebs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands):
    logging.info("Testing ebs correctly mounted on compute nodes")
    remote_command_executor.run_remote_command("touch {mount_dir}/test_file".format(mount_dir=mount_dir))
    job_command = "cat {mount_dir}/test_file " "&& touch {mount_dir}/compute_output".format(mount_dir=mount_dir)

    result = scheduler_commands.submit_command(job_command)
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
    remote_command_executor.run_remote_command("cat {mount_dir}/compute_output".format(mount_dir=mount_dir))
