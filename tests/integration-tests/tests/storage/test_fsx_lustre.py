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
import os
import time

import boto3
import pytest
import utils
from assertpy import assert_that
from botocore.exceptions import ClientError
from cfn_stacks_factory import CfnStack, CfnVpcStack
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from troposphere.fsx import LustreConfiguration
from utils import is_fsx_lustre_deployment_type_supported

from tests.storage.storage_common import (
    assert_fsx_lustre_correctly_mounted,
    check_dra,
    check_fsx,
    create_fsx_ontap,
    create_fsx_open_zfs,
    get_fsx_ids,
)

BACKUP_NOT_YET_AVAILABLE_STATES = {"CREATING", "TRANSFERRING", "PENDING"}
# Maximum number of minutes to wait past when an file system's automatic backup is scheduled to start creating.
# If after this many minutes past the scheduled time backup creation has not started, the test will fail.
MAX_MINUTES_TO_WAIT_FOR_AUTOMATIC_BACKUP_START = 5
# Maximum number of minutes to wait for a file system's backup to finish being created.
MAX_MINUTES_TO_WAIT_FOR_BACKUP_COMPLETION = 7


@pytest.mark.parametrize(
    (
        "deployment_type",
        "per_unit_storage_throughput",
        "auto_import_policy",
        "storage_type",
        "drive_cache_type",
        "storage_capacity",
        "imported_file_chunk_size",
        "data_compression_type",
    ),
    [
        ("PERSISTENT_1", 200, "NEW_CHANGED", None, None, 1200, 1024, None),
        ("SCRATCH_1", None, "NEW", None, None, 1200, 1024, "LZ4"),
        ("SCRATCH_2", None, "NEW_CHANGED_DELETED", None, None, 1200, 1024, "LZ4"),
        ("PERSISTENT_1", 40, None, "HDD", None, 1800, 512, "LZ4"),
        ("PERSISTENT_1", 12, None, "HDD", "READ", 6000, 1024, "LZ4"),
        ("PERSISTENT_2", 250, None, "SSD", None, 1200, 2048, "LZ4"),
    ],
)
@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_fsx_lustre_configuration_options(
    deployment_type,
    per_unit_storage_throughput,
    auto_import_policy,
    region,
    pcluster_config_reader,
    s3_bucket_factory,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
    storage_type,
    drive_cache_type,
    data_compression_type,
    storage_capacity,
    imported_file_chunk_size,
):
    if not is_fsx_lustre_deployment_type_supported(region, deployment_type):
        pytest.skip(
            f"Skipping the test because the deployment type {deployment_type} is not supported in region {region}"
        )

    mount_dir = "/fsx_mount_dir"
    bucket_name = None
    if deployment_type != "PERSISTENT_2":
        # Association to S3 is currently not supported with Persistent 2 because it is not supported by CloudFormation.
        # FSx is working on supporting it through CloudFormation
        bucket_name = s3_bucket_factory()
        bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
        bucket.upload_file(str(test_datadir / "s3_test_file"), "s3_test_file")
    weekly_maintenance_start_time = (datetime.datetime.utcnow() + datetime.timedelta(minutes=60)).strftime("%u:%H:%M")
    cluster_config = pcluster_config_reader(
        bucket_name=bucket_name,
        mount_dir=mount_dir,
        deployment_type=deployment_type,
        per_unit_storage_throughput=per_unit_storage_throughput,
        auto_import_policy=auto_import_policy,
        storage_type=storage_type,
        drive_cache_type=drive_cache_type,
        data_compression_type=data_compression_type,
        storage_capacity=storage_capacity,
        imported_file_chunk_size=imported_file_chunk_size,
        weekly_maintenance_start_time=weekly_maintenance_start_time,
    )
    cluster = clusters_factory(cluster_config)
    _test_fsx_lustre_configuration_options(
        cluster,
        region,
        scheduler_commands_factory,
        mount_dir,
        bucket_name,
        storage_type,
        auto_import_policy,
        deployment_type,
        data_compression_type,
        weekly_maintenance_start_time,
        imported_file_chunk_size,
        storage_capacity,
    )


def _test_fsx_lustre_configuration_options(
    cluster,
    region,
    scheduler_commands_factory,
    mount_dir,
    bucket_name,
    storage_type,
    auto_import_policy,
    deployment_type,
    data_compression_type,
    weekly_maintenance_start_time,
    imported_file_chunk_size,
    storage_capacity,
):
    check_fsx(cluster, region, scheduler_commands_factory, [mount_dir], bucket_name)
    remote_command_executor = RemoteCommandExecutor(cluster)
    fsx_fs_id = get_fsx_ids(cluster, region)[0]
    fsx = boto3.client("fsx", region_name=region).describe_file_systems(FileSystemIds=[fsx_fs_id])

    _test_storage_type(storage_type, fsx)
    _test_deployment_type(deployment_type, fsx)
    if bucket_name:
        _test_auto_import(auto_import_policy, remote_command_executor, mount_dir, bucket_name, region)
        _test_imported_file_chunch_size(imported_file_chunk_size, fsx)
    _test_storage_capacity(remote_command_executor, mount_dir, storage_capacity)
    _test_weekly_maintenance_start_time(weekly_maintenance_start_time, fsx)
    _test_data_compression_type(data_compression_type, fsx)


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_fsx_lustre(
    region,
    pcluster_config_reader,
    s3_bucket_factory,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
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
        storage_capacity=1200,
    )
    cluster = clusters_factory(cluster_config)
    check_fsx(
        cluster,
        region,
        scheduler_commands_factory,
        [mount_dir],
        bucket_name,
    )


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_fsx_lustre_dra(
    region,
    pcluster_config_reader,
    s3_bucket_factory,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
):
    """Test Data Respository Associations for a FSx Lustre file system."""
    mount_dir = "/fsx_mount_dir"
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "s3_test_file"), "test1/s3_test_file")
    cluster_config = pcluster_config_reader(
        bucket_name=bucket_name,
        mount_dir=mount_dir,
        storage_capacity=1200,
    )

    cluster = clusters_factory(cluster_config)

    check_dra(cluster, region, 1, "test1", mount_dir)

    # Add a second DRA
    cluster_update_config = pcluster_config_reader(
        config_file="pcluster.config.update.yaml",
        mount_dir=mount_dir,
        bucket_name=bucket_name,
        storage_capacity=1200,
    )

    bucket.upload_file(str(test_datadir / "s3_test_file"), "test2/s3_test_file")
    cluster.update(str(cluster_update_config))

    check_dra(cluster, region, 2, "test2", mount_dir)

    # Remove a DRA
    cluster.update(str(cluster_config))

    check_dra(cluster, region, 1, None, mount_dir)


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_fsx_lustre_backup(region, pcluster_config_reader, clusters_factory, scheduler_commands_factory):
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
    daily_automatic_backup_start_time = datetime.datetime.utcnow() + datetime.timedelta(minutes=15)
    logging.info(f"daily_automatic_backup_start_time: {daily_automatic_backup_start_time}")
    cluster_config = pcluster_config_reader(
        mount_dir=mount_dir, daily_automatic_backup_start_time=daily_automatic_backup_start_time.strftime("%H:%M")
    )

    # Create a cluster with automatic backup parameters.
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    fsx_fs_id = get_fsx_ids(cluster, region)[0]

    # Mount file system
    assert_fsx_lustre_correctly_mounted(remote_command_executor, mount_dir, region, fsx_fs_id)

    # Create a text file in the mount directory.
    create_backup_test_file(scheduler_commands, remote_command_executor, mount_dir)

    # Wait for the creation of automatic backup and assert if it is in available state.
    automatic_backup = monitor_automatic_backup_creation(fsx_fs_id, region, daily_automatic_backup_start_time)

    # Create a manual FSx Lustre backup using boto3 client.
    manual_backup = create_manual_fs_backup(fsx_fs_id, region)

    # Delete original cluster.
    cluster.delete()

    # Verify whether automatic backup is also deleted along with the cluster.
    _test_automatic_backup_deletion(automatic_backup, region)

    # Restore backup into a new cluster
    cluster_config_restore = pcluster_config_reader(
        config_file="pcluster_restore_fsx.config.yaml", mount_dir=mount_dir, fsx_backup_id=manual_backup.get("BackupId")
    )

    cluster_restore = clusters_factory(cluster_config_restore)
    remote_command_executor_restore = RemoteCommandExecutor(cluster_restore)
    fsx_fs_id_restore = get_fsx_ids(cluster_restore, region)[0]

    # Mount the restored file system
    assert_fsx_lustre_correctly_mounted(remote_command_executor_restore, mount_dir, region, fsx_fs_id_restore)

    # Validate whether text file created in the original file system is present in the restored file system.
    _test_restore_from_backup(remote_command_executor_restore, mount_dir)

    # Test deletion of manual backup
    _test_delete_manual_backup(manual_backup, region)


@pytest.mark.usefixtures("instance", "scheduler")
def test_multiple_fsx(
    os,
    region,
    fsx_factory,
    svm_factory,
    open_zfs_volume_factory,
    vpc_stack,
    pcluster_config_reader,
    s3_bucket_factory,
    clusters_factory,
    scheduler_commands_factory,
    test_datadir,
    request,
):
    """
    Test existing Fsx file system

    Check fsx_fs_id provided in config file can be mounted correctly
    """
    # Create s3 bucket and upload test_file
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "s3_test_file"), "s3_test_file")
    import_path, export_path = "s3://{0}".format(bucket_name), "s3://{0}/export_dir".format(bucket_name)

    partition = utils.get_arn_partition(region)
    num_new_fsx_lustre = 1
    num_existing_fsx_ontap_volumes = (
        2 if partition in ["aws", "aws-us-gov"] else 0
    )  # China and Isolated do not have Ontap
    num_existing_fsx_open_zfs_volumes = (
        2 if partition in ["aws"] else 0
    )  # China, GovCloud and Isolated do not have OpenZFS.
    # Minimal total existing FSx is the number of Ontap and OpenZFS plus one existing FSx Lustre
    num_existing_fsx = num_existing_fsx_ontap_volumes + num_existing_fsx_open_zfs_volumes + 1
    num_existing_fsx_lustre = num_existing_fsx - num_existing_fsx_ontap_volumes - num_existing_fsx_open_zfs_volumes
    fsx_lustre_mount_dirs = ["/shared"]
    for i in range(num_new_fsx_lustre + num_existing_fsx_lustre - 1):
        fsx_lustre_mount_dirs.append(f"/fsx_lustre_mount_dir{i}")

    fsx_ontap_mount_dirs = [f"/fsx_ontap_mount_dir{i}" for i in range(num_existing_fsx_ontap_volumes)]
    fsx_open_zfs_mount_dirs = [f"/fsx_open_zfs_mount_dir{i}" for i in range(num_existing_fsx_open_zfs_volumes)]

    existing_fsx_lustre_fs_ids = _create_fsx_lustre_volume_ids(
        num_existing_fsx_lustre, fsx_factory, import_path, export_path
    )
    fsx_on_tap_volume_ids = _create_fsx_on_tap_volume_ids(num_existing_fsx_ontap_volumes, fsx_factory, svm_factory)
    fsx_open_zfs_volume_ids = _create_fsx_open_zfs_volume_ids(
        num_existing_fsx_open_zfs_volumes, fsx_factory, open_zfs_volume_factory
    )

    cluster_config = pcluster_config_reader(
        bucket_name=bucket_name,
        fsx_lustre_mount_dirs=fsx_lustre_mount_dirs,
        existing_fsx_lustre_fs_ids=existing_fsx_lustre_fs_ids,
        fsx_open_zfs_volume_ids=fsx_open_zfs_volume_ids,
        fsx_open_zfs_mount_dirs=fsx_open_zfs_mount_dirs,
        fsx_ontap_volume_ids=fsx_on_tap_volume_ids,
        fsx_ontap_mount_dirs=fsx_ontap_mount_dirs,
    )
    cluster = clusters_factory(cluster_config)

    check_fsx(
        cluster,
        region,
        scheduler_commands_factory,
        fsx_lustre_mount_dirs + fsx_open_zfs_mount_dirs + fsx_ontap_mount_dirs,
        bucket_name,
    )


@pytest.mark.usefixtures("instance")
def test_file_cache(
    os,
    region,
    create_file_cache,
    pcluster_config_reader,
    s3_bucket_factory,
    clusters_factory,
    scheduler_commands_factory,
    test_datadir,
):
    """
    Test existing File Cache

    Check fsx_fc_id provided in config file can be mounted correctly
    """
    if utils.get_arn_partition(region) in ["aws"]:
        # China, GovCloud and Isolated do not have FileCache.
        # Create s3 bucket and upload test_file
        bucket_name = s3_bucket_factory()
        bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
        bucket.upload_file(str(test_datadir / "s3_test_file"), "s3_test_file")

        file_cache_id = _get_file_cache_id(
            create_file_cache,
            "/file-cache-path/",
            bucket_name,
        )
        cluster_config = pcluster_config_reader(file_cache_id=file_cache_id, bucket_name=bucket_name)
        cluster = clusters_factory(cluster_config)

        check_fsx(
            cluster,
            region,
            scheduler_commands_factory,
            ["/existing-file-cache-mount-1"],
            bucket_name,
            file_cache_path="/file-cache-path/",
        )


@pytest.mark.usefixtures("instance", "scheduler")
def test_multi_az_fsx(
    os,
    region,
    fsx_factory,
    svm_factory,
    open_zfs_volume_factory,
    vpc_stack,
    pcluster_config_reader,
    clusters_factory,
    s3_bucket_factory,
    scheduler_commands_factory,
    test_datadir,
):
    """Test that FSx FileSystem works in a MultiAZ Cluster."""
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "s3_test_file"), "s3_test_file")
    import_path = "s3://{0}".format(bucket_name)
    export_path = "s3://{0}/export_dir".format(bucket_name)

    existing_fsx_lustre_fs_id = _create_fsx_lustre_volume_ids(1, fsx_factory, import_path, export_path)[0]
    fsx_lustre_mount_dir = "/fsx_lustre_mount_dir"

    cluster_config = pcluster_config_reader(
        config_file="pcluster-unmanaged-fsx.config.yaml",
        bucket_name=bucket_name,
        fsx_lustre_mount_dir=fsx_lustre_mount_dir,
        existing_fsx_lustre_fs_id=existing_fsx_lustre_fs_id,
    )
    cluster = clusters_factory(cluster_config)

    check_fsx(
        cluster,
        region,
        scheduler_commands_factory,
        [fsx_lustre_mount_dir],
        bucket_name,
    )

    managed_fsx_config = pcluster_config_reader(config_file="pcluster-managed-fsx.config.yaml", bucket_name=bucket_name)

    response = cluster.update(managed_fsx_config, raise_on_error=False)
    assert_that(
        any(
            "Managed FSx storage created by ParallelCluster is not supported" in error["message"]
            for error in response["configurationValidationErrors"]
        )
    ).is_true()


def _create_fsx_on_tap_volume_ids(num_existing_fsx_ontap_volumes, fsx_factory, svm_factory):
    if num_existing_fsx_ontap_volumes > 0:
        fsx_ontap_fs_id = create_fsx_ontap(fsx_factory, num=1)[0]
        return svm_factory(fsx_ontap_fs_id, num_volumes=num_existing_fsx_ontap_volumes)
    return []


def _create_fsx_open_zfs_volume_ids(num_existing_fsx_open_zfs_volumes, fsx_factory, open_zfs_volume_factory):
    if num_existing_fsx_open_zfs_volumes > 0:
        fsx_open_zfs_root_volume_id = create_fsx_open_zfs(fsx_factory, num=1)[0]
        return open_zfs_volume_factory(fsx_open_zfs_root_volume_id, num_volumes=num_existing_fsx_open_zfs_volumes)
    return []


def _get_file_cache_id(create_file_cache, file_cache_path, bucket_name):
    return create_file_cache(file_cache_path, bucket_name)


@pytest.fixture
def create_file_cache(request, region, vpc_stack: CfnVpcStack, cfn_stacks_factory):
    """Create a File Cache Stack with its required Networking resources."""
    file_cache_config_file = os.path.join("resources", "file-cache-storage-cfn.yaml")

    def _create_file_cache(file_cache_path, bucket_name):
        if request.config.getoption("external_shared_storage_stack_name"):
            stack = CfnStack(
                name=request.config.getoption("external_shared_storage_stack_name"), region=region, template=None
            )
        else:
            logging.info("Creating the stack for File Cache")
            params = [
                {"ParameterKey": "FileCachePath", "ParameterValue": file_cache_path},
                {"ParameterKey": "S3BucketName", "ParameterValue": bucket_name},
                {"ParameterKey": "VpcId", "ParameterValue": vpc_stack.cfn_outputs["VpcId"]},
                {"ParameterKey": "SubnetId", "ParameterValue": vpc_stack.get_public_subnet()},
            ]
            with open(file_cache_config_file, encoding="utf-8") as template_file:
                template = template_file.read()
            stack = CfnStack(
                name=utils.generate_stack_name(
                    "integ-tests-file-cache-storage", request.config.getoption("stackname_suffix")
                ),
                region=region,
                parameters=params,
                template=template,
                capabilities=["CAPABILITY_IAM"],
            )
            cfn_stacks_factory.create_stack(stack)
            logging.info("Created the FileCacheId {0}".format(stack.cfn_outputs["FileCacheId"]))
            # Immediately using the FileCacheId after its creation gives Error
            time.sleep(150)

        return stack.cfn_outputs["FileCacheId"]

    yield _create_file_cache


def _create_fsx_lustre_volume_ids(num_existing_fsx_lustre, fsx_factory, import_path, export_path):
    return fsx_factory(
        ports=[988],
        ip_protocols=["tcp"],
        num=num_existing_fsx_lustre,
        file_system_type="LUSTRE",
        StorageCapacity=1200,
        LustreConfiguration=LustreConfiguration(
            title="lustreConfiguration",
            ImportPath=import_path,
            ExportPath=export_path,
            DeploymentType="PERSISTENT_1",
            PerUnitStorageThroughput=200,
        ),
        FileSystemTypeVersion="2.15",
    )


def _get_storage_type(fsx):
    logging.info("Getting StorageType from DescribeFilesystem API.")
    return fsx.get("FileSystems")[0].get("StorageType")


def _test_storage_type(storage_type, fsx):
    if storage_type == "HDD":
        assert_that(_get_storage_type(fsx)).is_equal_to("HDD")
    else:
        assert_that(_get_storage_type(fsx)).is_equal_to("SSD")


def _get_deployment_type(fsx):
    deployment_type = fsx.get("FileSystems")[0].get("LustreConfiguration").get("DeploymentType")
    logging.info(f"Getting DeploymentType {deployment_type} from DescribeFilesystem API.")
    return deployment_type


def _test_deployment_type(deployment_type, fsx):
    logging.info("Test fsx deployment type")
    assert_that(_get_deployment_type(fsx)).is_equal_to(deployment_type)


def _test_auto_import(auto_import_policy, remote_command_executor, mount_dir, bucket_name, region):
    s3 = boto3.client("s3", region_name=region)
    new_file_body = "New File AutoImported by FSx Lustre"
    modified_file_body = "File Modification AutoImported by FSx Lustre"
    filename = "fileToAutoImport"

    # Test new file
    s3.put_object(Bucket=bucket_name, Key=filename, Body=new_file_body)
    # AutoImport has a P99.9 of 1 min for new/changed files to be imported onto the filesystem
    remote_command_executor.run_remote_command("sleep 1m")
    if auto_import_policy in ("NEW", "NEW_CHANGED", "NEW_CHANGED_DELETED"):
        result = remote_command_executor.run_remote_command(f"cat {mount_dir}/{filename}")
        assert_that(result.stdout).is_equal_to(new_file_body)
    else:
        _assert_file_does_not_exist(remote_command_executor, filename, mount_dir)

    # Test modified file
    s3.put_object(Bucket=bucket_name, Key=filename, Body=modified_file_body)
    remote_command_executor.run_remote_command("sleep 1m")
    if auto_import_policy in ("NEW", "NEW_CHANGED", "NEW_CHANGED_DELETED"):
        result = remote_command_executor.run_remote_command(f"cat {mount_dir}/{filename}")
        assert_that(result.stdout).is_equal_to(
            modified_file_body if auto_import_policy in ["NEW_CHANGED", "NEW_CHANGED_DELETED"] else new_file_body
        )
    else:
        _assert_file_does_not_exist(remote_command_executor, filename, mount_dir)

    if auto_import_policy == "NEW_CHANGED_DELETED":
        # Test deleted file
        s3.delete_object(Bucket=bucket_name, Key=filename)
        remote_command_executor.run_remote_command("sleep 1m")
        _assert_file_does_not_exist(remote_command_executor, filename, mount_dir)


def _assert_file_does_not_exist(remote_command_executor, filename, mount_dir):
    result = remote_command_executor.run_remote_command(f"ls {mount_dir}/")
    assert_that(result.stdout).does_not_contain(filename)


def _test_storage_capacity(remote_command_executor, mount_dir, storage_capacity):
    logging.info("Test FSx storage capacity")
    # Get the storage size of mount_dir with GB, the storage size is slightly less than storage capacity defined,
    # here we set 0.1 as the difference ratio threshold
    result = remote_command_executor.run_remote_command(
        f"df -BG | grep {mount_dir}" + "| awk '{print$2}' | tr -d -c 0-9"
    )
    assert_that((storage_capacity - int(result.stdout)) / storage_capacity).is_less_than(0.1)


def _test_imported_file_chunch_size(imported_file_chunk_size, fsx):
    logging.info("Test FSx ImportedFileChunkSize setting")
    assert_that(get_imported_chunch_size(fsx)).is_equal_to(imported_file_chunk_size)


def _test_data_compression_type(compression_type, fsx):
    logging.info("Test FSx data compression type")
    if compression_type:
        actual_compression_type = fsx.get("FileSystems")[0].get("LustreConfiguration").get("DataCompressionType")
        assert_that(actual_compression_type).is_equal_to(compression_type)


def _test_weekly_maintenance_start_time(weekly_maintenance_start_time, fsx):
    logging.info("Test FSx weekly maintenance start time setting")
    assert_that(get_weekly_maintenance_start_time(fsx)).is_equal_to(weekly_maintenance_start_time)


def get_imported_chunch_size(fsx):
    logging.info("Getting ImportedFileChunkSize from DescribeFilesystem API.")
    return (
        fsx.get("FileSystems")[0]
        .get("LustreConfiguration")
        .get("DataRepositoryConfiguration")
        .get("ImportedFileChunkSize")
    )


def get_weekly_maintenance_start_time(fsx):
    logging.info("Getting WeeklyMaintenanceStartTime from DescribeFilesystem API.")
    return fsx.get("FileSystems")[0].get("LustreConfiguration").get("WeeklyMaintenanceStartTime")


def create_backup_test_file(scheduler_commands, remote_command_executor, mount_dir):
    logging.info("Creating a backup test file in fsx lustre mount directory")
    remote_command_executor.run_remote_command(
        "echo 'FSx Lustre Backup test file' > {mount_dir}/file_to_backup".format(mount_dir=mount_dir)
    )
    job_command = "cat {mount_dir}/file_to_backup ".format(mount_dir=mount_dir)
    result = scheduler_commands.submit_command(job_command)
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
    result = remote_command_executor.run_remote_command("cat {mount_dir}/file_to_backup".format(mount_dir=mount_dir))
    assert_that(result.stdout).is_equal_to("FSx Lustre Backup test file")


def monitor_automatic_backup_creation(fsx_fs_id, region, backup_start_time):
    logging.info("Monitoring automatic backup for FSx Lustre file system: {fs_id}".format(fs_id=fsx_fs_id))
    fsx = boto3.client("fsx", region_name=region)
    sleep_until_automatic_backup_creation_start_time(fsx_fs_id, backup_start_time)
    logging.info(
        f"Waiting up to {MAX_MINUTES_TO_WAIT_FOR_AUTOMATIC_BACKUP_START} minutes for automatic backup creation "
        "to start"
    )
    backup = poll_on_automatic_backup_creation_start(fsx_fs_id, fsx)
    backup = poll_on_backup_creation(backup, fsx)
    assert_that(backup.get("Lifecycle")).is_equal_to("AVAILABLE")
    return backup


def sleep_until_automatic_backup_creation_start_time(fsx_fs_id, backup_start_time):
    """Wait for the automatic backup of the given file system to start."""
    logging.info(f"Sleeping until time when {fsx_fs_id}'s backup creation should start at {backup_start_time}")
    remaining_time = (backup_start_time - datetime.datetime.utcnow()).total_seconds()
    if remaining_time > 0:
        time.sleep(remaining_time)


def log_backup_state(backup):
    """Log the ID and status of the given backup."""
    logging.info(
        "Backup {backup_id}: {status}".format(backup_id=backup.get("BackupId"), status=backup.get("Lifecycle"))
    )


@retry(
    retry_on_result=lambda result: result.get("Lifecycle") == "NOT_STARTED",
    wait_fixed=seconds(5),
    stop_max_delay=minutes(MAX_MINUTES_TO_WAIT_FOR_AUTOMATIC_BACKUP_START),
)
def poll_on_automatic_backup_creation_start(fsx_fs_id, fsx):
    backups = fsx.describe_backups(Filters=[{"Name": "file-system-id", "Values": [fsx_fs_id]}]).get("Backups")
    backup = backups[0] if len(backups) > 0 else {"BackupId": "NA", "Lifecycle": "NOT_STARTED"}
    log_backup_state(backup)
    return backup


def _test_automatic_backup_deletion(automatic_backup, region):
    backup_id = automatic_backup.get("BackupId")
    logging.info("Verifying whether automatic backup '{0}' was deleted".format(backup_id))
    error_message = "Backup '{backup_id}' does not exist.".format(backup_id=backup_id)
    fsx = boto3.client("fsx", region_name=region)
    with pytest.raises(ClientError, match=error_message):
        return fsx.describe_backups(BackupIds=[backup_id])


def create_manual_fs_backup(fsx_fs_id, region):
    logging.info("Create manual backup for FSx Lustre file system: {fs_id}".format(fs_id=fsx_fs_id))
    fsx = boto3.client("fsx", region_name=region)
    backup = fsx.create_backup(FileSystemId=fsx_fs_id).get("Backup")
    backup = poll_on_backup_creation(backup, fsx)
    assert_that(backup.get("Lifecycle")).is_equal_to("AVAILABLE")
    return backup


@retry(
    retry_on_result=lambda result: result.get("Lifecycle") in BACKUP_NOT_YET_AVAILABLE_STATES,
    wait_fixed=seconds(5),
    stop_max_delay=minutes(MAX_MINUTES_TO_WAIT_FOR_BACKUP_COMPLETION),
)
def poll_on_backup_creation(backup, fsx):
    log_backup_state(backup)
    return fsx.describe_backups(BackupIds=[backup.get("BackupId")]).get("Backups")[0]


def _test_restore_from_backup(remote_command_executor, mount_dir):
    logging.info("Testing fsx lustre correctly restored from backup")
    result = remote_command_executor.run_remote_command("cat {mount_dir}/file_to_backup".format(mount_dir=mount_dir))
    assert_that(result.stdout).is_equal_to("FSx Lustre Backup test file")


def _test_delete_manual_backup(backup, region):
    backup_id = backup.get("BackupId")
    logging.info("Testing deletion of manual backup {0}".format(backup_id))
    fsx = boto3.client("fsx", region_name=region)
    response = fsx.delete_backup(BackupId=backup_id)
    assert_that(response.get("Lifecycle")).is_equal_to("DELETED")
