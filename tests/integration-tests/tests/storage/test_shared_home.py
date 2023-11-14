# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from tests.storage.storage_common import (
    check_fsx,
    create_fsx_ontap,
    create_fsx_open_zfs,
    test_directory_correctly_shared_between_ln_and_hn,
    test_efs_correctly_mounted,
    verify_directory_correctly_shared,
)
from tests.storage.test_fsx_lustre import create_file_cache  # noqa  # pylint: disable=unused-import

# flake8: noqa


@pytest.mark.parametrize(
    "storage_type",
    ["Efs", "FsxLustre", "FsxOpenZfs", "FsxOntap", "Ebs"],
    # TODO full test ["Efs", "FsxLustre", "FsxOpenZfs", "FsxOntap", "FileCache", "Ebs"]
)
@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_shared_home(
    region,
    scheduler,
    pcluster_config_reader,
    create_file_cache,
    vpc_stack,
    scheduler_commands_factory,
    storage_type,
    fsx_factory,
    svm_factory,
    open_zfs_volume_factory,
    s3_bucket_factory,
    test_datadir,
    clusters_factory,
):
    """Verify the shared /home storage fs is available when set"""
    mount_dir = "/home"
    bucket_name = None
    if storage_type == "FileCache":
        bucket_name = s3_bucket_factory()
        bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
        bucket.upload_file(str(test_datadir / "s3_test_file"), "s3_test_file")
    file_cache_path = "/slurm/" if storage_type == "FileCache" else None
    if storage_type == "FsxOpenZfs":
        fsx_open_zfs_root_volume_id = create_fsx_open_zfs(fsx_factory, num=1)[0]
        fsx_open_zfs_volume_id = open_zfs_volume_factory(fsx_open_zfs_root_volume_id, num_volumes=1)[0]
        cluster_config = pcluster_config_reader(
            mount_dir=mount_dir, storage_type=storage_type, volume_id=fsx_open_zfs_volume_id
        )
    elif storage_type == "FsxOntap":
        fsx_ontap_fs_id = create_fsx_ontap(fsx_factory, num=1)[0]
        fsx_on_tap_volume_id = svm_factory(fsx_ontap_fs_id, num_volumes=1)[0]
        cluster_config = pcluster_config_reader(
            mount_dir=mount_dir, storage_type=storage_type, volume_id=fsx_on_tap_volume_id
        )
    elif storage_type == "FileCache":
        file_cache_id = create_file_cache(file_cache_path, bucket_name)
        cluster_config = pcluster_config_reader(
            mount_dir=mount_dir, storage_type=storage_type, file_cache_id=file_cache_id
        )
    else:
        cluster_config = pcluster_config_reader(mount_dir=mount_dir, storage_type=storage_type)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    remote_command_executor_login_node = RemoteCommandExecutor(cluster, use_login_node=True)

    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    if storage_type == "Efs":
        test_efs_correctly_mounted(remote_command_executor, mount_dir)
        logging.info("Testing efs correctly mounted on compute nodes")
        verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands, run_sudo=True)
        test_efs_correctly_mounted(remote_command_executor_login_node, mount_dir)
        test_directory_correctly_shared_between_ln_and_hn(
            remote_command_executor, remote_command_executor_login_node, mount_dir, run_sudo=True
        )
    elif storage_type in ["FsxLustre", "FsxOpenZfs", "FsxOntap", "FileCache"]:
        check_fsx(
            cluster,
            region,
            scheduler_commands_factory,
            [mount_dir],
            bucket_name,
            file_cache_path=file_cache_path,
            run_sudo=True,
        )
    elif storage_type == "Ebs":
        _test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size=40)
        _test_ebs_correctly_mounted(remote_command_executor_login_node, mount_dir, volume_size=40)
        # Test ebs correctly shared between HeadNode and ComputeNodes
        logging.info("Testing ebs correctly mounted on compute nodes")
        verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


def _test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size):
    logging.info("Testing ebs {0} is correctly mounted on login".format(mount_dir))
    result = remote_command_executor.run_remote_command("df -h | grep {0}".format(mount_dir))
    assert_that(result.stdout).matches(r"{size}G.*{mount_dir}".format(size=volume_size, mount_dir=mount_dir))

    result = remote_command_executor.run_remote_command("cat /etc/fstab")
    assert_that(result.stdout).matches(r"{mount_dir}.*_netdev".format(mount_dir=mount_dir))
