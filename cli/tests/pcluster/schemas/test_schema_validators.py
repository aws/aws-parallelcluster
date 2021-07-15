# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import re

import pytest
from assertpy import assert_that

from pcluster.schemas.cluster_schema import (
    AwsBatchComputeResourceSchema,
    AwsBatchQueueSchema,
    CloudWatchLogsSchema,
    ClusterSchema,
    DcvSchema,
    EbsSettingsSchema,
    EfsSettingsSchema,
    FsxLustreSettingsSchema,
    HeadNodeEphemeralVolumeSchema,
    HeadNodeNetworkingSchema,
    HeadNodeRootVolumeSchema,
    IamSchema,
    ImageSchema,
    QueueEphemeralVolumeSchema,
    QueueNetworkingSchema,
    QueueRootVolumeSchema,
    RaidSchema,
    SharedStorageSchema,
    SlurmComputeResourceSchema,
    SlurmQueueSchema,
    SshSchema,
)


@pytest.mark.parametrize(
    "mount_dir, expected_message",
    [
        ("/t_ 1-2( ):&;<>t?*+|", None),
        ("", "does not match expected pattern"),
        ("fake_value", None),
        ("/test", None),
        ("/test/test2", None),
        ("//test", "does not match expected pattern"),
        ("./test", "does not match expected pattern"),
        ("\\test", "does not match expected pattern"),
        (".test", "does not match expected pattern"),
        ("/test/.test2", "does not match expected pattern"),
        ("/test/.test2/test3", "does not match expected pattern"),
        ("/test//test2", "does not match expected pattern"),
        ("/test\\test2", "does not match expected pattern"),
        ("NONE", None),  # NONE is evaluated as a valid path
    ],
)
def test_mount_dir_validator(mount_dir, expected_message):
    _validate_and_assert_error(SharedStorageSchema(), {"MountDir": mount_dir}, expected_message)
    _validate_and_assert_error(HeadNodeEphemeralVolumeSchema(), {"MountDir": mount_dir}, expected_message)
    _validate_and_assert_error(QueueEphemeralVolumeSchema(), {"MountDir": mount_dir}, expected_message)


@pytest.mark.parametrize(
    "size, expected_message",
    [
        (25, None),
        ("", "Not a valid integer"),
        ("NONE", "Not a valid integer"),
        ("wrong_value", "Not a valid integer"),
        (19, "must be at least 35"),
        (36, None),
    ],
)
def test_root_volume_size_validator(size, expected_message):
    _validate_and_assert_error(HeadNodeRootVolumeSchema(), {"Size": size}, expected_message)
    _validate_and_assert_error(QueueRootVolumeSchema(), {"Size": size}, expected_message)


@pytest.mark.parametrize(
    "capacity_type, expected_message",
    [
        ("ONDEMAND", None),
        ("", "Must be one of: ONDEMAND, SPOT"),
        ("wrong_value", "Must be one of: ONDEMAND, SPOT"),
        ("NONE", "Must be one of: ONDEMAND, SPOT"),
        ("SPOT", None),
    ],
)
def test_compute_type_validator(capacity_type, expected_message):
    _validate_and_assert_error(SlurmQueueSchema(), {"CapacityType": capacity_type}, expected_message)
    _validate_and_assert_error(AwsBatchQueueSchema(), {"CapacityType": capacity_type}, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"MinCount": -1}, "Must be greater than or equal"),
        ({"MinCount": 0}, None),
        ({"MaxCount": 0}, "Must be greater than or equal"),
        ({"MaxCount": 1}, None),
        ({"SpotPrice": ""}, "Not a valid number"),
        ({"SpotPrice": "NONE"}, "Not a valid number"),
        ({"SpotPrice": "wrong_value"}, "Not a valid number"),
        ({"SpotPrice": -1.1}, "Must be greater than or equal"),
        ({"SpotPrice": 0}, None),
        ({"SpotPrice": 0.09}, None),
        ({"SpotPrice": 0}, None),
        ({"SpotPrice": 0.1}, None),
        ({"SpotPrice": 1}, None),
        ({"SpotPrice": 100}, None),
        ({"SpotPrice": 100.0}, None),
        ({"SpotPrice": 100.1}, None),
        ({"SpotPrice": 101}, None),
    ],
)
def test_slurm_compute_resource_validator(section_dict, expected_message):
    _validate_and_assert_error(SlurmComputeResourceSchema(), section_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"MinvCpus": -1}, "Must be greater than or equal"),
        ({"MinvCpus": 0}, None),
        ({"DesiredvCpus": -1}, "Must be greater than or equal"),
        ({"DesiredvCpus": 0}, None),
        ({"MaxvCpus": 0}, "Must be greater than or equal"),
        ({"MaxvCpus": 1}, None),
        ({"SpotBidPercentage": ""}, "Not a valid integer"),
        ({"SpotBidPercentage": "wrong_value"}, "Not a valid integer"),
        ({"SpotBidPercentage": 1}, None),
        ({"SpotBidPercentage": 22}, None),
        ({"SpotBidPercentage": 101}, "Must be.*less than or equal to 100"),
    ],
)
def test_awsbatch_compute_resource_validator(section_dict, expected_message):
    _validate_and_assert_error(AwsBatchComputeResourceSchema(), section_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"ComputeResources": []}, "Length must be 1"),
        ({"ComputeResources": [{"Name": "compute_resource1", "InstanceTypes": ["c5.xlarge"]}]}, None),
        (
            {
                "ComputeResources": [
                    {"Name": "compute_resource1", "InstanceTypes": ["c4.xlarge", "c5.xlarge"]},
                    {"Name": "compute_resource1", "InstanceTypes": ["c4.xlarge"]},
                ]
            },
            "Length must be 1",
        ),
    ],
)
def test_awsbatch_queue_validator(section_dict, expected_message):
    _validate_and_assert_error(AwsBatchQueueSchema(), section_dict, expected_message)


@pytest.mark.parametrize(
    "custom_ami, expected_message",
    [
        ("", "does not match expected pattern"),
        ("wrong_value", "does not match expected pattern"),
        ("ami-12345", "does not match expected pattern"),
        ("ami-123456789", "does not match expected pattern"),
        ("NONE", "does not match expected pattern"),
        ("ami-12345678", None),
        ("ami-12345678901234567", None),
    ],
)
def test_custom_ami_validator(custom_ami, expected_message):
    _validate_and_assert_error(ImageSchema(), {"CustomAmi": custom_ami}, expected_message)


@pytest.mark.parametrize(
    "retention_in_days, expected_message",
    [
        # right value
        (1, None),
        (14, None),
        (3653, None),
        # invalid value
        (2, "Must be one of"),
        (3652, "Must be one of"),
        ("", "Not a valid integer"),
        ("not_an_int", "Not a valid integer"),
    ],
)
def test_retention_in_days_validator(retention_in_days, expected_message):
    """Verify that cw_log behaves as expected when parsed in a config file."""
    _validate_and_assert_error(CloudWatchLogsSchema(), {"RetentionInDays": retention_in_days}, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"Enabled": True}, None),
        ({"Enabled": "wrong_value"}, "Not a valid boolean"),
        ({"Enabled": ""}, "Not a valid boolean"),
        ({"Enabled": "NONE"}, "Not a valid boolean"),
        ({"Port": "wrong_value"}, "Not a valid integer"),
        ({"Port": ""}, "Not a valid integer"),
        ({"Port": "NONE"}, "Not a valid integer"),
        ({"Port": "wrong_value"}, "Not a valid integer"),
        ({"Port": "1"}, None),
        ({"Port": "20"}, None),
        ({"invalid_key": "fake_value"}, "Unknown field"),
    ],
)
def test_dcv_validator(section_dict, expected_message):
    """Verify that cw_log behaves as expected when parsed in a config file."""
    _validate_and_assert_error(DcvSchema(), section_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"AllowedIps": "wrong_value"}, "does not match expected patter"),
        ({"AllowedIps": ""}, "does not match expected pattern"),
        ({"AllowedIps": "wrong_value"}, "does not match expected pattern"),
        ({"AllowedIps": "111.111.111.111"}, "does not match expected pattern"),
        ({"AllowedIps": "111.111.111.111/222"}, "does not match expected pattern"),
        ({"AllowedIps": "NONE"}, "does not match expected pattern"),
        ({"AllowedIps": "0.0.0.0/0"}, None),
        ({"AllowedIps": "1.1.1.1/0"}, None),
        ({"AllowedIps": "1.1.1.1/8"}, None),
        ({"AllowedIps": "1.1.1.1/15"}, None),
        ({"AllowedIps": "1.1.1.1/32"}, None),
        ({"AllowedIps": "1.1.1.1/33"}, "does not match expected pattern"),
        ({"AllowedIps": "11.11.11.11/32"}, None),
        ({"AllowedIps": "111.111.111.111/22"}, None),
        ({"AllowedIps": "255.255.255.255/32"}, None),
        ({"AllowedIps": "255.255.255.256/32"}, "does not match expected pattern"),
    ],
)
def test_cidr_validator(section_dict, expected_message):
    """Verify that cw_log behaves as expected when parsed in a config file."""
    _validate_and_assert_error(DcvSchema(), section_dict, expected_message)
    _validate_and_assert_error(SshSchema(), section_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"SnapshotId": ""}, "does not match expected pattern"),
        ({"SnapshotId": "wrong_value"}, "does not match expected pattern"),
        ({"SnapshotId": "snap-12345"}, "does not match expected pattern"),
        ({"SnapshotId": "snap-123456789"}, "does not match expected pattern"),
        ({"SnapshotId": "NONE"}, "does not match expected pattern"),
        ({"SnapshotId": "snap-12345678"}, None),
        ({"SnapshotId": "snap-12345678901234567"}, None),
        ({"VolumeType": ""}, "Must be one of"),
        ({"VolumeType": "wrong_value"}, "Must be one of"),
        ({"VolumeType": "st1"}, None),
        ({"VolumeType": "sc1"}, None),
        ({"VolumeType": "NONE"}, "Must be one of"),
        ({"VolumeType": "io1"}, None),
        ({"VolumeType": "io2"}, None),
        ({"VolumeType": "standard"}, None),
        ({"Size": ""}, "Not a valid integer"),
        ({"Size": "NONE"}, "Not a valid integer"),
        ({"Size": "wrong_value"}, "Not a valid integer"),
        ({"Size": 10}, None),
        ({"Size": 3}, None),
        ({"Iops": ""}, "Not a valid integer"),
        ({"Iops": "NONE"}, "Not a valid integer"),
        ({"Iops": "wrong_value"}, "Not a valid integer"),
        ({"Iops": 10}, None),
        ({"Iops": 3}, None),
        ({"Throughput": ""}, "Not a valid integer"),
        ({"Throughput": "NONE"}, "Not a valid integer"),
        ({"Throughput": "wrong_value"}, "Not a valid integer"),
        ({"Throughput": 200}, None),
        ({"Encrypted": ""}, "Not a valid boolean"),
        ({"Encrypted": "NONE"}, "Not a valid boolean"),
        ({"Encrypted": True}, None),
        ({"Encrypted": False}, None),
        ({"KmsKeyId": ""}, None),
        ({"KmsKeyId": "fake_value"}, None),
        ({"KmsKeyId": "test"}, None),
        ({"KmsKeyId": "NONE"}, None),  # NONE is evaluated as a valid kms id
        ({"VolumeId": ""}, "does not match expected pattern"),
        ({"VolumeId": "wrong_value"}, "does not match expected pattern"),
        ({"VolumeId": "vol-12345"}, "does not match expected pattern"),
        ({"VolumeId": "vol-123456789"}, "does not match expected pattern"),
        ({"VolumeId": "NONE"}, "does not match expected pattern"),
        ({"VolumeId": "vol-12345678"}, None),
        ({"VolumeId": "vol-12345678901234567"}, None),
    ],
)
def test_ebs_validator(section_dict, expected_message):
    """Verify that cw_log behaves as expected when parsed in a config file."""
    _validate_and_assert_error(EbsSettingsSchema(), section_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"FileSystemId": ""}, "does not match expected pattern"),
        ({"FileSystemId": "wrong_value"}, "does not match expected pattern"),
        ({"FileSystemId": "fs-12345"}, "does not match expected pattern"),
        ({"FileSystemId": "fs-123456789"}, "does not match expected pattern"),
        ({"FileSystemId": "fs-12345678"}, None),
        ({"FileSystemId": "fs-12345678901234567"}, None),
        ({"PerformanceMode": ""}, "Must be one of"),
        ({"PerformanceMode": "maxIO"}, None),
        ({"PerformanceMode": "wrong_value"}, "Must be one of"),
        ({"PerformanceMode": "NONE"}, "Must be one of"),
        ({"KmsKeyId": ""}, None),
        ({"KmsKeyId": "fake_value"}, None),
        ({"KmsKeyId": "test"}, None),
        ({"KmsKeyId": "NONE"}, None),  # NONE is evaluated as a valid kms id
        ({"ProvisionedThroughput": 1}, None),
        ({"ProvisionedThroughput": 3}, None),
        ({"ProvisionedThroughput": 1024}, None),
        ({"ProvisionedThroughput": 102000}, "Must be.*less than or equal to 1024"),
        ({"ProvisionedThroughput": 0.01}, "Must be greater than or equal to 1"),
        ({"ProvisionedThroughput": 1025}, "Must be.*less than or equal to 1024"),
        ({"ProvisionedThroughput": "wrong_value"}, "Not a valid integer"),
        ({"Encrypted": ""}, "Not a valid boolean"),
        ({"Encrypted": "NONE"}, "Not a valid boolean"),
        ({"Encrypted": "true"}, None),
        ({"Encrypted": False}, None),
        ({"ThroughputMode": ""}, "Must be one of"),
        ({"ThroughputMode": "provisioned"}, None),
        ({"ThroughputMode": "wrong_value"}, "Must be one of"),
        ({"ThroughputMode": "NONE"}, "Must be one of"),
    ],
)
def test_efs_validator(section_dict, expected_message):
    """Verify that cw_log behaves as expected when parsed in a config file."""
    _validate_and_assert_error(EfsSettingsSchema(), section_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        (
            {"ThroughputMode": "bursting", "ProvisionedThroughput": 1024},
            "When specifying provisioned throughput, the throughput mode must be set to provisioned",
        ),
        (
            {"ThroughputMode": "provisioned"},
            "When specifying throughput mode to provisioned, the provisioned throughput option must be specified",
        ),
        ({"ThroughputMode": "provisioned", "ProvisionedThroughput": 1024}, None),
    ],
)
def test_efs_throughput_mode_provisioned_throughput_validator(section_dict, expected_message):
    _validate_and_assert_error(EfsSettingsSchema(), section_dict, expected_message, partial=False)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"FileSystemId": "fs-0123456789abcdef0"}, None),
        (
            {"FileSystemId": "fs-0123456789abcdef0", "StorageCapacity": 3600},
            "storage_capacity is ignored when an existing Lustre file system is specified",
        ),
        (
            {
                "BackupId": "backup-0ff8da96d57f3b4e3",
                "DeploymentType": "PERSISTENT_1",
            },
            "When restoring an FSx Lustre file system from backup, 'deployment_type' cannot be specified.",
        ),
        (
            {"BackupId": "backup-0ff8da96d57f3b4e3", "StorageCapacity": 7200},
            "When restoring an FSx Lustre file system from backup, 'storage_capacity' cannot be specified.",
        ),
        (
            {
                "BackupId": "backup-0ff8da96d57f3b4e3",
                "PerUnitStorageThroughput": 100,
            },
            "When restoring an FSx Lustre file system from backup, 'per_unit_storage_throughput' cannot be specified.",
        ),
        (
            {
                "BackupId": "backup-0ff8da96d57f3b4e3",
                "ImportedFileChunkSize": 1024,
            },
            "When restoring an FSx Lustre file system from backup, 'imported_file_chunk_size' cannot be specified.",
        ),
        (
            {
                "BackupId": "backup-0ff8da96d57f3b4e3",
                "KmsKeyId": "somekey",
            },
            "When restoring an FSx Lustre file system from backup, 'kms_key_id' cannot be specified.",
        ),
        ({"FileSystemId": ""}, "does not match expected pattern"),
        ({"FileSystemId": "wrong_value"}, "does not match expected pattern"),
        ({"FileSystemId": "fs-12345"}, "does not match expected pattern"),
        ({"FileSystemId": "fs-123456789"}, "does not match expected pattern"),
        ({"FileSystemId": "fs-12345678"}, "does not match expected pattern"),
        ({"FileSystemId": "fs-12345678901234567"}, None),
        ({"StorageCapacity": 3}, None),
        ({"StorageCapacity": "wrong_value"}, "Not a valid integer"),
        ({"StorageCapacity": ""}, "Not a valid integer"),
        ({"StorageCapacity": "NONE"}, "Not a valid integer"),
        ({"StorageCapacity": 10}, None),
        ({"KmsKeyId": ""}, None),
        ({"KmsKeyId": "fake_value"}, None),
        ({"KmsKeyId": "test"}, None),
        ({"KmsKeyId": "NONE"}, None),  # NONE is evaluated as a valid kms id
        ({"ImportedFileChunkSize": ""}, "Not a valid integer"),
        ({"ImportedFileChunkSize": "NONE"}, "Not a valid integer"),
        ({"ImportedFileChunkSize": "wrong_value"}, "Not a valid integer"),
        ({"ImportedFileChunkSize": 3}, None),
        ({"ImportedFileChunkSize": 0}, "has a minimum size of 1 MiB, and max size of 512,000 MiB"),
        ({"ImportedFileChunkSize": 1}, None),
        ({"ImportedFileChunkSize": 10}, None),
        ({"ImportedFileChunkSize": 512000}, None),
        ({"ImportedFileChunkSize": 512001}, "has a minimum size of 1 MiB, and max size of 512,000 MiB"),
        # TODO add regex for export path
        ({"ExportPath": ""}, None),
        ({"ExportPath": "fake_value"}, None),
        ({"ExportPath": "http://test"}, None),
        ({"ExportPath": "s3://test/test2"}, None),
        ({"ExportPath": "NONE"}, None),
        # TODO add regex for import path
        ({"ImportPath": ""}, None),
        ({"ImportPath": "fake_value"}, None),
        ({"ImportPath": "http://test"}, None),
        ({"ImportPath": "s3://test/test2"}, None),
        ({"ImportPath": "NONE"}, None),
        # TODO add regex for weekly_maintenance_start_time
        ({"WeeklyMaintenanceStartTime": ""}, "does not match expected pattern"),
        ({"WeeklyMaintenanceStartTime": "fake_value"}, "does not match expected pattern"),
        ({"WeeklyMaintenanceStartTime": "10:00"}, "does not match expected pattern"),
        ({"WeeklyMaintenanceStartTime": "1:10:00"}, None),
        ({"WeeklyMaintenanceStartTime": "1:1000"}, "does not match expected pattern"),
        ({"DeploymentType": "SCRATCH_1"}, None),
        ({"DeploymentType": "SCRATCH_2"}, None),
        ({"DeploymentType": "PERSISTENT_1"}, None),
        ({"DeploymentType": "BLAH"}, "Must be one of"),
        ({"PerUnitStorageThroughput": 12}, None),
        ({"PerUnitStorageThroughput": 40}, None),
        ({"PerUnitStorageThroughput": 50}, None),
        ({"PerUnitStorageThroughput": 100}, None),
        ({"PerUnitStorageThroughput": 200}, None),
        ({"PerUnitStorageThroughput": 101}, "Must be one of"),
        ({"PerUnitStorageThroughput": 1000}, "Must be one of"),
        ({"DailyAutomaticBackupStartTime": ""}, "does not match expected pattern"),
        ({"DailyAutomaticBackupStartTime": "01:00"}, None),
        ({"DailyAutomaticBackupStartTime": "23:00"}, None),
        ({"DailyAutomaticBackupStartTime": "25:00"}, "does not match expected pattern"),
        ({"DailyAutomaticBackupStartTime": "2300"}, "does not match expected pattern"),
        ({"AutomaticBackupRetentionDays": ""}, "Not a valid integer"),
        ({"AutomaticBackupRetentionDays": 0}, None),
        ({"AutomaticBackupRetentionDays": 35}, None),
        ({"AutomaticBackupRetentionDays": 36}, "Must be.*less than or equal to 35"),
        ({"CopyTagsToBackups": ""}, "Not a valid boolean"),
        ({"CopyTagsToBackups": "NONE"}, "Not a valid boolean"),
        ({"CopyTagsToBackups": True}, None),
        ({"CopyTagsToBackups": False}, None),
        ({"BackupId": ""}, "does not match expected pattern"),
        ({"BackupId": "back-0a1b2c3d4e5f6a7b8"}, "does not match expected pattern"),
        ({"BackupId": "backup-0A1B2C3d4e5f6a7b8"}, "does not match expected pattern"),
        ({"BackupId": "backup-0a1b2c3d4e5f6a7b8"}, None),
        ({"AutoImportPolicy": "NEW"}, None),
        ({"AutoImportPolicy": "NEW_CHANGED"}, None),
        ({"StorageType": "SSD"}, None),
        ({"StorageType": "HDD"}, None),
        ({"StorageType": "INVALID_VALUE"}, "Must be one of"),
        ({"DriveCacheType": "READ"}, None),
        ({"DriveCacheType": "INVALID_VALUE"}, "Must be one of"),
        ({"invalid_key": "fake_value"}, "Unknown field"),
    ],
)
def test_fsx_validator(section_dict, expected_message):
    _validate_and_assert_error(FsxLustreSettingsSchema(), section_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"Type": ""}, "Not a valid integer"),
        ({"Type": "NONE"}, "Not a valid integer"),
        ({"Type": "wrong_value"}, "Not a valid integer"),
        ({"Type": 10}, "Must be one of"),
        ({"Type": 3}, "Must be one of"),
        ({"Type": 0}, None),
        ({"Type": 1}, None),
        ({"NumberOfVolumes": ""}, "Not a valid integer"),
        ({"NumberOfVolumes": "NONE"}, "Not a valid integer"),
        ({"NumberOfVolumes": "wrong_value"}, "Not a valid integer"),
        ({"NumberOfVolumes": 0}, "Must be greater than or equal to 2"),
        ({"NumberOfVolumes": 1}, "Must be greater than or equal to 2"),
        ({"NumberOfVolumes": 6}, "Must be.*less than or equal to 5"),
        ({"NumberOfVolumes": 5}, None),
        ({"NumberOfVolumes": 2}, None),
    ],
)
def test_raid_validator(section_dict, expected_message):
    """Verify that cw_log behaves as expected when parsed in a config file."""
    _validate_and_assert_error(RaidSchema(), section_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"AdditionalSecurityGroups": [""]}, "does not match expected pattern"),
        ({"AdditionalSecurityGroups": ["wrong_value"]}, "does not match expected pattern"),
        ({"AdditionalSecurityGroups": ["sg-12345"]}, "does not match expected pattern"),
        ({"AdditionalSecurityGroups": ["sg-123456789"]}, "does not match expected pattern"),
        ({"AdditionalSecurityGroups": ["NONE"]}, "does not match expected pattern"),
        ({"AdditionalSecurityGroups": ["sg-12345678"]}, None),
        ({"AdditionalSecurityGroups": ["sg-12345678901234567"]}, None),
        ({"AssignPublicIp": ""}, "Not a valid boolean"),
        ({"AssignPublicIp": "NONE"}, "Not a valid boolean"),
        ({"AssignPublicIp": "true"}, None),
        ({"AssignPublicIp": "false"}, None),
        ({"SecurityGroups": [""]}, "does not match expected pattern"),
        ({"SecurityGroups": ["wrong_value"]}, "does not match expected pattern"),
        ({"SecurityGroups": ["sg-12345"]}, "does not match expected pattern"),
        ({"SecurityGroups": ["sg-123456789"]}, "does not match expected pattern"),
        ({"SecurityGroups": ["NONE"]}, "does not match expected pattern"),
        ({"SecurityGroups": ["sg-12345678"]}, None),
        ({"SecurityGroups": ["sg-12345678901234567"]}, None),
    ],
)
def test_base_networking_validator(section_dict, expected_message):
    """Verify that cw_log behaves as expected when parsed in a config file."""
    _validate_and_assert_error(HeadNodeNetworkingSchema(), section_dict, expected_message)
    _validate_and_assert_error(QueueNetworkingSchema(), section_dict, expected_message)


@pytest.mark.parametrize(
    "subnet_id, expected_message",
    [
        ("", "does not match expected pattern"),
        ("subnet-12345", "does not match expected pattern"),
        ("subnet-123456789", "does not match expected pattern"),
        ("NONE", "does not match expected pattern"),
        ("subnet-12345678", None),
        ("subnet-12345678901234567", None),
    ],
)
def test_subnet_id_validator(subnet_id, expected_message):
    """Verify that cw_log behaves as expected when parsed in a config file."""
    _validate_and_assert_error(HeadNodeNetworkingSchema(), {"SubnetId": subnet_id}, expected_message)
    _validate_and_assert_error(QueueNetworkingSchema(), {"SubnetIds": [subnet_id]}, expected_message)


@pytest.mark.parametrize(
    "key, expected_message",
    [
        ("key1", None),
        ("parallelcluster:version", "The tag key prefix 'parallelcluster:' is reserved and cannot be used."),
    ],
)
def test_tags_validator(key, expected_message):
    _validate_and_assert_error(ClusterSchema(), {"Tags": [{"Key": key, "Value": "test_value"}]}, expected_message)


def _validate_and_assert_error(schema, section_dict, expected_message, partial=True):
    if expected_message:
        messages = schema.validate(section_dict, partial=partial)
        contain = False
        for message in list(messages.values()):
            if isinstance(message, dict):
                # Special case when validating lists
                for msg in list(message.values()):
                    if re.search(expected_message, msg[0]):
                        contain = True
            else:
                if re.search(expected_message, message[0]):
                    contain = True
        assert_that(contain).is_true()
    else:
        schema.validate(section_dict, partial=partial)


@pytest.mark.parametrize(
    "instance_role, expected_message",
    [
        ("", "does not match expected pattern"),
        ("arn:aws:iam::aws:role/CustomHeadNodeRole", None),
        ("CustomHeadNodeRole", "does not match expected pattern"),
        ("arn:aws:iam::aws:instance-profile/CustomNodeInstanceProfile", "does not match expected pattern"),
    ],
)
def test_instance_role_validator(instance_role, expected_message):
    """Verify that cw_log behaves as expected when parsed in a config file."""
    _validate_and_assert_error(IamSchema(), {"InstanceRole": instance_role}, expected_message)
