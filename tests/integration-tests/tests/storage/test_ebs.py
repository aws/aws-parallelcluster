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
import utils
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor

from tests.common.schedulers_common import get_scheduler_commands
from tests.storage.kms_key_factory import KMSKeyFactory
from tests.storage.snapshots_factory import EBSSnapshotsFactory
from tests.storage.storage_common import verify_directory_correctly_shared


@pytest.mark.regions(["eu-west-3", "cn-north-1", "us-gov-west-1"])
@pytest.mark.instances(["c4.xlarge", "c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("instance")
def test_ebs_single(scheduler, pcluster_config_reader, clusters_factory, kms_key_factory, region, os):
    mount_dir = "ebs_mount_dir"
    kms_key_id = kms_key_factory.create_kms_key(region)
    cluster_config = pcluster_config_reader(
        mount_dir=mount_dir, ec2_iam_role=kms_key_factory.iam_role, ebs_kms_key_id=kms_key_id
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    mount_dir = "/" + mount_dir
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    volume_id = get_ebs_volume_ids(cluster, region)[0]

    _test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size=35)
    _test_ebs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)
    _test_ebs_encrypted_with_kms(volume_id, region, encrypted=True, kms_key_id=kms_key_id)

    _test_root_volume_encryption(cluster, os, region, scheduler, encrypted=True)


@pytest.mark.dimensions("ap-northeast-2", "c5.xlarge", "alinux2", "slurm")
@pytest.mark.dimensions("cn-northwest-1", "c4.xlarge", "ubuntu1804", "slurm")
@pytest.mark.dimensions("eu-west-1", "c5.xlarge", "slurm")
@pytest.mark.usefixtures("os", "instance")
def test_ebs_snapshot(
    request, vpc_stacks, region, scheduler, pcluster_config_reader, snapshots_factory, clusters_factory
):
    logging.info("Testing ebs snapshot")
    mount_dir = "ebs_mount_dir"
    volume_size = 21
    # This volume_size is set to be larger than snapshot size(10G), to test create volumes larger than its snapshot size

    logging.info("Creating snapshot")

    snapshot_id = snapshots_factory.create_snapshot(request, vpc_stacks[region].cfn_outputs["PublicSubnetId"], region)

    logging.info("Snapshot id: %s" % snapshot_id)
    cluster_config = pcluster_config_reader(mount_dir=mount_dir, volume_size=volume_size, snapshot_id=snapshot_id)

    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    mount_dir = "/" + mount_dir
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    _test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size="9.8")
    _test_ebs_resize(remote_command_executor, mount_dir, volume_size=volume_size)
    _test_ebs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)

    # Checks for test data
    result = remote_command_executor.run_remote_command("cat {}/test.txt".format(mount_dir))
    assert_that(result.stdout.strip()).is_equal_to("hello world")


# cn-north-1 does not support KMS
@pytest.mark.dimensions("ca-central-1", "c5.xlarge", "alinux2", "awsbatch")
@pytest.mark.dimensions("ca-central-1", "c5.xlarge", "ubuntu1804", "slurm")
@pytest.mark.dimensions("eu-west-2", "c5.xlarge", "slurm")
@pytest.mark.usefixtures("instance")
def test_ebs_multiple(scheduler, pcluster_config_reader, clusters_factory, region, os):
    mount_dirs = ["/ebs_mount_dir_{0}".format(i) for i in range(0, 5)]
    volume_sizes = [15 + 5 * i for i in range(0, 5)]

    # for volume type sc1 and st1, the minimum volume sizes are 500G
    volume_sizes[3] = 500
    volume_sizes[4] = 500
    cluster_config = pcluster_config_reader(mount_dirs=mount_dirs, volume_sizes=volume_sizes)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    for mount_dir, volume_size in zip(mount_dirs, volume_sizes):
        # for volume size equal to 500G, the filesystem size is only about 492G
        # This is because the file systems use some of the total space available on a device for storing internal
        # structures and data (the file system's metadata). The overhead of the XFS filesystem is around 0.5%.
        # If we test with small volume size(eg: 40G), the number is not large enough to show the gap between the
        # partition size and the filesystem size. For sc1 and st1, the minimum size is 500G, so there will be a size
        # difference.
        _test_ebs_correctly_mounted(
            remote_command_executor, mount_dir, volume_size if volume_size != 500 else "49[0-9]"
        )
        _test_ebs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)

    volume_ids = get_ebs_volume_ids(cluster, region)
    for i in range(len(volume_ids)):
        # test different volume types
        volume_id = volume_ids[i]
        ebs_settings = _get_ebs_settings_by_name(cluster.config, f"ebs{i+1}")
        volume_type = ebs_settings["VolumeType"]
        volume = describe_volume(volume_id, region)
        assert_that(volume[0]).is_equal_to(volume_type)
        encrypted = ebs_settings.get("Encrypted")
        if encrypted is None:
            # Default encryption if not specified
            encrypted = True
        _test_ebs_encrypted_with_kms(volume_id, region, encrypted=encrypted, kms_key_id=ebs_settings.get("KmsKeyId"))
        # test different iops
        # only io1, io2, gp3 can configure iops
        if volume_type in ["io1", "io2", "gp3"]:
            volume_iops = ebs_settings["Iops"]
            assert_that(volume[1]).is_equal_to(int(volume_iops))

    _test_root_volume_encryption(cluster, os, region, scheduler, encrypted=False)
    _assert_root_volume_configuration(cluster, os, region, scheduler)


def _get_ebs_settings_by_name(config, name):
    for shared_storage in config["SharedStorage"]:
        if shared_storage["Name"] == name:
            return shared_storage["EbsSettings"]


@pytest.mark.dimensions("ap-northeast-2", "c5.xlarge", "centos7", "slurm")
@pytest.mark.usefixtures("os", "instance")
def test_ebs_existing(
    request, vpc_stacks, region, scheduler, pcluster_config_reader, snapshots_factory, clusters_factory
):
    logging.info("Testing ebs existing")
    existing_mount_dir = "existing_mount_dir"

    logging.info("Creating volume")

    volume_id = snapshots_factory.create_existing_volume(
        request, vpc_stacks[region].cfn_outputs["PublicSubnetId"], region
    )

    logging.info("Existing Volume id: %s" % volume_id)
    cluster_config = pcluster_config_reader(
        volume_id=volume_id,
        existing_mount_dir=existing_mount_dir,
    )

    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    existing_mount_dir = "/" + existing_mount_dir
    _test_ebs_correctly_mounted(remote_command_executor, existing_mount_dir, volume_size="9.8")
    _test_ebs_correctly_shared(remote_command_executor, existing_mount_dir, scheduler_commands)
    # Checks for test data
    result = remote_command_executor.run_remote_command("cat {}/test.txt".format(existing_mount_dir))
    assert_that(result.stdout.strip()).is_equal_to("hello world")

    # delete the cluster before detaching the EBS volume
    cluster.delete()
    # check the volume still exists after deleting the cluster
    _assert_volume_exist(volume_id, region)


def _test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size):
    logging.info("Testing ebs {0} is correctly mounted".format(mount_dir))
    result = remote_command_executor.run_remote_command(
        "df -h -t ext4 | tail -n +2 | awk '{{print $2, $6}}' | grep '{0}'".format(mount_dir)
    )
    assert_that(result.stdout).matches(r"{size}G {mount_dir}".format(size=volume_size, mount_dir=mount_dir))

    result = remote_command_executor.run_remote_command("cat /etc/fstab")
    assert_that(result.stdout).matches(r"UUID=.* {mount_dir} ext4 _netdev 0 0".format(mount_dir=mount_dir))


def _test_ebs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands):
    logging.info("Testing ebs correctly mounted on compute nodes")
    verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


def _test_home_correctly_shared(remote_command_executor, scheduler_commands):
    logging.info("Testing home dir correctly mounted on compute nodes")
    verify_directory_correctly_shared(remote_command_executor, "/home", scheduler_commands)


def _test_ebs_resize(remote_command_executor, mount_dir, volume_size):
    """
    This test verifies the following case:

    If the volume is created from a snapshot with a size larger than the snapshot, the size of the volume is correct.
    """
    logging.info("Testing ebs has correct volume size")

    # get the filesystem that the shared_dir is mounted on
    # example output of "df -h -t ext4"
    #     Filesystem      Size  Used Avail Use% Mounted on
    # /dev/nvme1n1p1  9.8G   37M  9.3G   1% /ebs_mount_dir
    # /dev/nvme2n1p1  9.8G   37M  9.3G   1% /existing_mount_dir
    filesystem_name = remote_command_executor.run_remote_command(
        "df -h -t ext4 | tail -n +2 |grep '{mount_dir}' | awk '{{print $1}}'".format(mount_dir=mount_dir)
    ).stdout

    # get the volume name given the filesystem name
    # example input: /dev/nvme1n1p1
    # example output: nvme1n1
    volume_name = remote_command_executor.run_remote_command(
        "lsblk -no pkname {filesystem_name}".format(filesystem_name=filesystem_name)
    ).stdout

    # get the volume size of the volume
    # example output of "lsblk"
    # NAME          MAJ:MIN RM SIZE RO TYPE MOUNTPOINT
    # nvme0n1       259:0    0  25G  0 disk
    # ├─nvme0n1p1   259:1    0  25G  0 part /
    # └─nvme0n1p128 259:2    0   1M  0 part
    # nvme1n1       259:3    0  21G  0 disk
    # └─nvme1n1p1   259:4    0  10G  0 part /ebs_mount_dir
    # nvme2n1       259:5    0  10G  0 disk
    # └─nvme2n1p1   259:6    0  10G  0 part /existing_mount_dir
    result = remote_command_executor.run_remote_command(
        "lsblk | tail -n +2 | grep {volume_name}| awk '{{print $4}}' | sed -n '1p'''".format(volume_name=volume_name)
    )

    assert_that(result.stdout).matches(r"{size}G".format(size=volume_size))


def get_ebs_volume_ids(cluster, region):
    # get the list of configured ebs volume ids
    # example output: ['vol-000', 'vol-001', 'vol-002']
    return utils.retrieve_cfn_outputs(cluster.cfn_name, region).get("EBSIds").split(",")


def describe_volume(volume_id, region):
    volume = boto3.client("ec2", region_name=region).describe_volumes(VolumeIds=[volume_id]).get("Volumes")[0]
    volume_type = volume.get("VolumeType")
    volume_iops = volume.get("Iops")
    return volume_type, volume_iops


def _assert_volume_exist(volume_id, region):
    volume_status = (
        boto3.client("ec2", region_name=region).describe_volumes(VolumeIds=[volume_id]).get("Volumes")[0].get("State")
    )
    assert_that(volume_status).is_equal_to("available")


def _test_ebs_encrypted_with_kms(volume_id, region, encrypted, kms_key_id=None):
    logging.info("Getting Encrypted information from DescribeVolumes API.")
    volume_info = boto3.client("ec2", region_name=region).describe_volumes(VolumeIds=[volume_id]).get("Volumes")[0]
    assert_that(volume_info.get("Encrypted") == encrypted).is_true()
    if kms_key_id:
        assert_that(volume_info.get("KmsKeyId")).matches(kms_key_id)


def _test_root_volume_encryption(cluster, os, region, scheduler, encrypted):
    logging.info("Testing root volume encryption.")
    if scheduler == "slurm":
        # If the scheduler is slurm, root volumes both on head and compute can be encrypted
        instance_ids = cluster.instances()
        for instance in instance_ids:
            root_volume_id = utils.get_root_volume_id(instance, region, os)
            _test_ebs_encrypted_with_kms(root_volume_id, region, encrypted=encrypted)
    else:
        # If the scheduler is awsbatch, only the headnode root volume can be encrypted.
        root_volume_id = utils.get_root_volume_id(cluster.cfn_resources["HeadNode"], region, os)
        _test_ebs_encrypted_with_kms(root_volume_id, region, encrypted=encrypted)


def _assert_root_volume_configuration(cluster, os, region, scheduler):
    logging.info("Testing root volume type, iops, throughput.")

    # Test root volume of head node
    head_node = cluster.cfn_resources["HeadNode"]
    if utils.dict_has_nested_key(cluster.config, ("HeadNode", "LocalStorage", "RootVolume")):
        logging.info("Checking head node root volume settings")
        root_volume_id = utils.get_root_volume_id(head_node, region, os)
        expected_settings = cluster.config["HeadNode"]["LocalStorage"]["RootVolume"]
        _assert_volume_configuration(expected_settings, root_volume_id, region)
    if scheduler == "slurm":
        # Only if the scheduler is slurm, root volumes both on compute can be configured
        instance_ids = cluster.instances()
        for instance in instance_ids:
            if instance == head_node:
                # head node is already checked
                continue
            root_volume_id = utils.get_root_volume_id(instance, region, os)
            if utils.dict_has_nested_key(
                cluster.config, ("Scheduling", "Queues", 0, "ComputeSettings", "LocalStorage", "RootVolume")
            ):
                logging.info("Checking compute node root volume settings")
                expected_settings = cluster.config["Scheduling"]["Queues"][0]["ComputeSettings"]["LocalStorage"][
                    "RootVolume"
                ]
                _assert_volume_configuration(expected_settings, root_volume_id, region)


def _assert_volume_configuration(expected_settings, volume_id, region):
    actual_root_volume_settings = (
        boto3.client("ec2", region_name=region).describe_volumes(VolumeIds=[volume_id]).get("Volumes")[0]
    )
    for key in expected_settings:
        assert_that(actual_root_volume_settings[key]).is_equal_to(expected_settings[key])


@pytest.fixture(scope="class")
def snapshots_factory():
    factory = EBSSnapshotsFactory()
    yield factory
    factory.release_all()


@pytest.fixture(scope="module")
def kms_key_factory():
    factory = KMSKeyFactory()
    yield factory
    factory.release_all()
