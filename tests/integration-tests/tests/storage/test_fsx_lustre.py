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
import datetime
import logging

import boto3
import pytest
from botocore.exceptions import ClientError
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


@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5.xlarge", "m6g.xlarge"])
@pytest.mark.schedulers(["sge"])
@pytest.mark.usefixtures("os", "instance", "scheduler")
# FSx is not supported on CentOS 6
@pytest.mark.skip_oss(["centos6"])
# FSx is only supported on ARM instances for Ubuntu 18.04 and Amazon Linux 2
@pytest.mark.skip_dimensions("*", "m6g.xlarge", "alinux", "*")
@pytest.mark.skip_dimensions("*", "m6g.xlarge", "centos7", "*")
@pytest.mark.skip_dimensions("*", "m6g.xlarge", "ubuntu1604", "*")
def test_fsx_lustre_backup(
    region, pcluster_config_reader, clusters_factory, test_datadir, os,
):
    """
    Test FSx Lustre backup feature. As part of this test, following steps are performed
    1. Create a cluster with FSx automatic backups feature enabled.
    2. Mount the file system and create a test file in it.
    3. Wait for automatic backup to be created.
    4. Create a manual FSx Lustre backup of the file system.
    5. Delete the cluster.
    6. Verify whether automatic backup is deleted. NOTE: FSx team is planning to change this
       behavior to retain automatic backups upon filesystem deletion. The test case should
       be update when this change is in place.
    7. Restore a cluster from the manual backup taken in step 4. Verify whether test file
       created in step 2 exists in the restored file system.
    8. Delete manual backup created in step 4.

    """
    mount_dir = "/fsx_mount_dir"
    utc_now_plus_15 = datetime.datetime.utcnow() + datetime.timedelta(minutes=15)
    daily_automatic_backup_start_time = utc_now_plus_15.strftime("%H:%M")
    logging.info("daily_automatic_backup_start_time" + daily_automatic_backup_start_time)
    cluster_config = pcluster_config_reader(
        mount_dir=mount_dir, daily_automatic_backup_start_time=daily_automatic_backup_start_time
    )

    # Create a cluster with automatic backup parameters.
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    fsx_fs_id = get_fsx_fs_id(cluster, region)

    # Mount file system
    _test_fsx_lustre_correctly_mounted(remote_command_executor, mount_dir, os, region, fsx_fs_id)

    # Create a text file in the mount directory.
    create_backup_test_file(remote_command_executor, mount_dir)

    # Wait for the creation of automatic backup and assert if it is in available state.
    automatic_backup = monitor_automatic_backup_creation(remote_command_executor, fsx_fs_id, region)

    # Create a manual FSx Lustre backup using boto3 client.
    manual_backup = create_manual_fs_backup(remote_command_executor, fsx_fs_id, region)

    # Delete original cluster.
    cluster.delete()

    # Verify whether automatic backup is also deleted along with the cluster.
    _test_automatic_backup_deletion(remote_command_executor, automatic_backup, region)

    # Restore backup into a new cluster
    cluster_config_restore = pcluster_config_reader(
        config_file="pcluster_restore_fsx.config.ini", mount_dir=mount_dir, fsx_backup_id=manual_backup.get("BackupId"),
    )

    cluster_restore = clusters_factory(cluster_config_restore)
    remote_command_executor_restore = RemoteCommandExecutor(cluster_restore)
    fsx_fs_id_restore = get_fsx_fs_id(cluster_restore, region)

    # Mount the restored file system
    _test_fsx_lustre_correctly_mounted(remote_command_executor_restore, mount_dir, os, region, fsx_fs_id_restore)

    # Validate whether text file created in the original file system is present in the restored file system.
    _test_restore_from_backup(remote_command_executor_restore, mount_dir)

    # Test deletion of manual backup
    _test_delete_manual_backup(remote_command_executor, manual_backup, region)


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


def create_backup_test_file(remote_command_executor, mount_dir):
    logging.info("Creating a backup test file in fsx lustre mount directory")
    sge_commands = SgeCommands(remote_command_executor)
    remote_command_executor.run_remote_command(
        "echo 'FSx Lustre Backup test file' > {mount_dir}/file_to_backup".format(mount_dir=mount_dir)
    )
    job_command = "cat {mount_dir}/file_to_backup ".format(mount_dir=mount_dir)
    result = sge_commands.submit_command(job_command)
    job_id = sge_commands.assert_job_submitted(result.stdout)
    sge_commands.wait_job_completed(job_id)
    sge_commands.assert_job_succeeded(job_id)
    result = remote_command_executor.run_remote_command("cat {mount_dir}/file_to_backup".format(mount_dir=mount_dir))
    assert_that(result.stdout).is_equal_to("FSx Lustre Backup test file")


def monitor_automatic_backup_creation(remote_command_executor, fsx_fs_id, region):
    logging.info("Monitoring automatic backup for FSx Lustre file system: {fs_id}".format(fs_id=fsx_fs_id))
    fsx = boto3.client("fsx", region_name=region)
    backup = poll_on_automatic_backup_creation(fsx_fs_id, fsx)
    assert_that(backup.get("Lifecycle")).is_equal_to("AVAILABLE")
    return backup


@retry(
    retry_on_result=lambda result: result.get("Lifecycle") in ["CREATING", "NOT_STARTED"],
    wait_fixed=seconds(5),
    stop_max_delay=minutes(7),
)
def poll_on_automatic_backup_creation(fsx_fs_id, fsx):
    backups = fsx.describe_backups(Filters=[{"Name": "file-system-id", "Values": [fsx_fs_id]}]).get("Backups")
    backup = backups[0] if len(backups) > 0 else {"BackupId": "NA", "Lifecycle": "NOT_STARTED"}
    logging.info(
        "Backup {backup_id}: {status}".format(backup_id=backup.get("BackupId"), status=backup.get("Lifecycle"))
    )

    return backup


def _test_automatic_backup_deletion(remote_command_executor, automatic_backup, region):
    backup_id = automatic_backup.get("BackupId")
    logging.info("Verifying whether automatic backup '{0}' was deleted".format(backup_id))
    error_message = "Backup '{backup_id}' does not exist.".format(backup_id=backup_id)
    fsx = boto3.client("fsx", region_name=region)
    with pytest.raises(ClientError, match=error_message):
        return fsx.describe_backups(BackupIds=[backup_id])


def create_manual_fs_backup(remote_command_executor, fsx_fs_id, region):
    logging.info("Create manual backup for FSx Lustre file system: {fs_id}".format(fs_id=fsx_fs_id))
    fsx = boto3.client("fsx", region_name=region)
    backup = fsx.create_backup(FileSystemId=fsx_fs_id).get("Backup")
    backup = poll_on_manual_backup_creation(backup, fsx)
    assert_that(backup.get("Lifecycle")).is_equal_to("AVAILABLE")
    return backup


@retry(
    retry_on_result=lambda result: result.get("Lifecycle") in ["CREATING"],
    wait_fixed=seconds(5),
    stop_max_delay=minutes(7),
)
def poll_on_manual_backup_creation(backup, fsx):
    logging.info(
        "Backup {backup_id}: {status}".format(backup_id=backup.get("BackupId"), status=backup.get("Lifecycle"))
    )
    return fsx.describe_backups(BackupIds=[backup.get("BackupId")]).get("Backups")[0]


def _test_restore_from_backup(remote_command_executor, mount_dir):
    logging.info("Testing fsx lustre correctly restored from backup")
    result = remote_command_executor.run_remote_command("cat {mount_dir}/file_to_backup".format(mount_dir=mount_dir))
    assert_that(result.stdout).is_equal_to("FSx Lustre Backup test file")


def _test_delete_manual_backup(remote_command_executor, backup, region):
    backup_id = backup.get("BackupId")
    logging.info("Testing deletion of manual backup {0}".format(backup_id))
    fsx = boto3.client("fsx", region_name=region)
    response = fsx.delete_backup(BackupId=backup_id)
    assert_that(response.get("Lifecycle")).is_equal_to("DELETED")
