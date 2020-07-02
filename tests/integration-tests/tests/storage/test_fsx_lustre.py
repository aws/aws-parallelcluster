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
from retrying import retry

import utils
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from tests.common.schedulers_common import SgeCommands
from time_utils import minutes, seconds


@pytest.mark.parametrize(
    "deployment_type, per_unit_storage_throughput", [("PERSISTENT_1", 200), ("SCRATCH_1", None), ("SCRATCH_2", None)]
)
@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5.xlarge", "m6g.xlarge"])
@pytest.mark.schedulers(["sge"])
@pytest.mark.usefixtures("os", "instance", "scheduler", "deployment_type")
# FSx is not supported on CentOS 6
@pytest.mark.skip_oss(["centos6"])
# FSx is only supported on ARM instances for Ubuntu 18.04 and Amazon Linux 2
@pytest.mark.skip_dimensions("*", "m6g.xlarge", "alinux", "*")
@pytest.mark.skip_dimensions("*", "m6g.xlarge", "centos7", "*")
@pytest.mark.skip_dimensions("*", "m6g.xlarge", "ubuntu1604", "*")
def test_fsx_lustre(
    deployment_type,
    per_unit_storage_throughput,
    region,
    pcluster_config_reader,
    clusters_factory,
    s3_bucket_factory,
    test_datadir,
    os,
):
    """
    Test all FSx Lustre related features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    mount_dir = "/fsx_mount_dir"
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "s3_test_file"), "s3_test_file")
    cluster_config = pcluster_config_reader(
        bucket_name=bucket_name,
        mount_dir=mount_dir,
        deployment_type=deployment_type,
        per_unit_storage_throughput=per_unit_storage_throughput,
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    fsx_fs_id = get_fsx_fs_id(cluster, region)

    _test_fsx_lustre_correctly_mounted(remote_command_executor, mount_dir, os, region, fsx_fs_id)
    _test_import_path(remote_command_executor, mount_dir)
    _test_fsx_lustre_correctly_shared(remote_command_executor, mount_dir)
    _test_export_path(remote_command_executor, mount_dir, bucket_name)
    _test_data_repository_task(remote_command_executor, mount_dir, bucket_name, fsx_fs_id, region)


def _test_fsx_lustre_correctly_mounted(remote_command_executor, mount_dir, os, region, fsx_fs_id):
    logging.info("Testing fsx lustre is correctly mounted")
    result = remote_command_executor.run_remote_command("df -h -t lustre | tail -n +2 | awk '{print $1, $2, $6}'")
    mount_name = get_mount_name(fsx_fs_id, region)
    assert_that(result.stdout).matches(
        r"[0-9\.]+@tcp:/{mount_name}\s+1\.[12]T\s+{mount_dir}".format(mount_name=mount_name, mount_dir=mount_dir)
    )

    result = remote_command_executor.run_remote_command("cat /etc/fstab")
    mount_options = {
        "default": "defaults,_netdev,flock,user_xattr,noatime,noauto,x-systemd.automount",
        "alinux": "defaults,_netdev,flock,user_xattr,noatime",
    }

    assert_that(result.stdout).matches(
        r"fs-[0-9a-z]+\.fsx\.[a-z1-9\-]+\.amazonaws\.com@tcp:/{mount_name}"
        r" {mount_dir} lustre {mount_options} 0 0".format(
            mount_name=mount_name, mount_dir=mount_dir, mount_options=mount_options.get(os, mount_options["default"])
        )
    )


def get_mount_name(fsx_fs_id, region):
    logging.info("Getting MountName from DescribeFilesystem API.")
    fsx = boto3.client("fsx", region_name=region)
    return (
        fsx.describe_file_systems(FileSystemIds=[fsx_fs_id])
        .get("FileSystems")[0]
        .get("LustreConfiguration")
        .get("MountName")
    )


def get_fsx_fs_id(cluster, region):
    fsx_stack = utils.get_substacks(cluster.cfn_name, region=region, sub_stack_name="FSXSubstack")[0]
    return utils.retrieve_cfn_outputs(fsx_stack, region).get("FileSystemId")


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


@retry(
    retry_on_result=lambda result: result.get("Lifecycle") in ["PENDING", "EXECUTING", "CANCELLING"],
    wait_fixed=seconds(5),
    stop_max_delay=minutes(7),
)
def poll_on_data_export(task, fsx):
    logging.info(
        "Data Export Task {task_id}: {status}".format(task_id=task.get("TaskId"), status=task.get("Lifecycle"))
    )
    return fsx.describe_data_repository_tasks(TaskIds=[task.get("TaskId")]).get("DataRepositoryTasks")[0]


def _test_data_repository_task(remote_command_executor, mount_dir, bucket_name, fsx_fs_id, region):
    logging.info("Testing fsx lustre data repository task")
    file_contents = "Exported by FSx Lustre"
    remote_command_executor.run_remote_command(
        "echo '{file_contents}' > {mount_dir}/file_to_export".format(file_contents=file_contents, mount_dir=mount_dir)
    )

    # set file permissions
    remote_command_executor.run_remote_command(
        "sudo chmod 777 {mount_dir}/file_to_export && sudo chown 6666:6666 {mount_dir}/file_to_export".format(
            mount_dir=mount_dir
        )
    )

    fsx = boto3.client("fsx", region_name=region)
    task = fsx.create_data_repository_task(
        FileSystemId=fsx_fs_id, Type="EXPORT_TO_REPOSITORY", Paths=["file_to_export"], Report={"Enabled": False}
    ).get("DataRepositoryTask")

    task = poll_on_data_export(task, fsx)

    assert_that(task.get("Lifecycle")).is_equal_to("SUCCEEDED")

    remote_command_executor.run_remote_command(
        "aws s3 cp s3://{bucket_name}/export_dir/file_to_export ./file_to_export".format(bucket_name=bucket_name)
    )
    result = remote_command_executor.run_remote_command("cat ./file_to_export")
    assert_that(result.stdout).is_equal_to(file_contents)

    # test s3 metadata
    s3 = boto3.client("s3", region_name=region)
    metadata = (
        s3.head_object(Bucket=bucket_name, Key="export_dir/file_to_export").get("ResponseMetadata").get("HTTPHeaders")
    )
    file_owner = metadata.get("x-amz-meta-file-owner")
    file_group = metadata.get("x-amz-meta-file-group")
    file_permissions = metadata.get("x-amz-meta-file-permissions")
    assert_that(file_owner).is_equal_to("6666")
    assert_that(file_group).is_equal_to("6666")
    assert_that(file_permissions).is_equal_to("0100777")
