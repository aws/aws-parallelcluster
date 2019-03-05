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

import boto3
import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from tests.common.schedulers_common import SgeCommands


@pytest.mark.regions(["us-east-1", "eu-west-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.oss(["centos7"])
@pytest.mark.schedulers(["sge"])
@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_fsx_lustre(region, pcluster_config_reader, clusters_factory, s3_bucket_factory, test_datadir):
    """
    Test all FSx Lustre related features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    mount_dir = "/fsx_mount_dir"
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "s3_test_file"), "s3_test_file")
    cluster_config = pcluster_config_reader(bucket_name=bucket_name, mount_dir=mount_dir)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_fsx_lustre_correctly_mounted(remote_command_executor, mount_dir)
    _test_import_path(remote_command_executor, mount_dir)
    _test_fsx_lustre_correctly_shared(remote_command_executor, mount_dir)
    _test_export_path(remote_command_executor, mount_dir, bucket_name)


def _test_fsx_lustre_correctly_mounted(remote_command_executor, mount_dir):
    logging.info("Testing fsx lustre is correctly mounted")
    result = remote_command_executor.run_remote_command("df -h -t lustre | tail -n +2 | awk '{print $1, $2, $6}'")
    assert_that(result.stdout).matches(r"[0-9\.]+@tcp:/fsx\s+3\.4T\s+{mount_dir}".format(mount_dir=mount_dir))

    result = remote_command_executor.run_remote_command("cat /etc/fstab")
    assert_that(result.stdout).matches(
        r"fs-[0-9a-z]+\.fsx\.[a-z1-9\-]+\.amazonaws\.com@tcp:/fsx {mount_dir} lustre defaults,_netdev 0 0".format(
            mount_dir=mount_dir
        )
    )


def _test_import_path(remote_command_executor, mount_dir):
    logging.info("Testing fsx lustre import path")
    result = remote_command_executor.run_remote_command("cat {mount_dir}/s3_test_file".format(mount_dir=mount_dir))
    assert_that(result.stdout).is_equal_to("Downloaded by FSx Lustre")


def _test_fsx_lustre_correctly_shared(remote_command_executor, mount_dir):
    logging.info("Testing fsx lustre correctly mounted on compute nodes")
    sge_commands = SgeCommands(remote_command_executor)
    remote_command_executor.run_remote_command("touch {mount_dir}/test_file".format(mount_dir=mount_dir))
    job_command = (
        "cat {mount_dir}/s3_test_file "
        "&& cat {mount_dir}/test_file "
        "&& touch {mount_dir}/compute_output".format(mount_dir=mount_dir)
    )
    result = sge_commands.submit_command(job_command)
    job_id = sge_commands.assert_job_submitted(result.stdout)
    sge_commands.wait_job_completed(job_id)
    sge_commands.assert_job_succeeded(job_id)
    remote_command_executor.run_remote_command("cat {mount_dir}/compute_output".format(mount_dir=mount_dir))


def _test_export_path(remote_command_executor, mount_dir, bucket_name):
    logging.info("Testing fsx lustre export path")
    remote_command_executor.run_remote_command(
        "echo 'Exported by FSx Lustre' > {mount_dir}/file_to_export".format(mount_dir=mount_dir)
    )
    remote_command_executor.run_remote_command(
        "sudo lfs hsm_archive {mount_dir}/file_to_export && sleep 5".format(mount_dir=mount_dir)
    )
    remote_command_executor.run_remote_command(
        "aws s3 cp s3://{bucket_name}/export_dir/file_to_export ./file_to_export".format(bucket_name=bucket_name)
    )
    result = remote_command_executor.run_remote_command("cat ./file_to_export")
    assert_that(result.stdout).is_equal_to("Exported by FSx Lustre")
