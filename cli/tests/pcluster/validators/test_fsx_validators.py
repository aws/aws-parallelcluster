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
import pytest

from pcluster.models.common import Param
from pcluster.validators.fsx_validators import (
    FsxBackupOptionsValidator,
    FsxPersistentOptionsValidator,
    FsxS3Validator,
    FsxStorageCapacityValidator,
    FsxStorageTypeOptionsValidator,
)
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "import_path, imported_file_chunk_size, export_path, auto_import_policy, expected_message",
    [
        (
            "s3://test",
            1024,
            None,
            None,
            None,
        ),
        (
            None,
            1024,
            None,
            None,
            "When specifying imported file chunk size, the import path option must be specified",
        ),
        (
            "s3://test",
            None,
            "s3://test",
            None,
            None,
        ),
        (
            None,
            None,
            "s3://test",
            None,
            "When specifying export path, the import path option must be specified",
        ),
    ],
)
def test_fsx_s3_validator(import_path, imported_file_chunk_size, export_path, auto_import_policy, expected_message):
    actual_failures = FsxS3Validator()(
        Param(import_path), Param(imported_file_chunk_size), Param(export_path), Param(auto_import_policy)
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "deployment_type, kms_key_id, per_unit_storage_throughput, expected_message",
    [
        (
            "PERSISTENT_1",
            "9e8a129be-0e46-459d-865b-3a5bf974a22k",
            50,
            None,
        ),
        (
            "PERSISTENT_1",
            None,
            200,
            None,
        ),
        (
            "SCRATCH_2",
            "9e8a129be-0e46-459d-865b-3a5bf974a22k",
            None,
            "kms key id can only be used when deployment type is `PERSISTENT_1'",
        ),
        (
            "SCRATCH_1",
            None,
            200,
            "per unit storage throughput can only be used when deployment type is `PERSISTENT_1'",
        ),
        (
            "PERSISTENT_1",
            None,
            None,
            "per unit storage throughput must be specified when deployment type is `PERSISTENT_1'",
        ),
    ],
)
def test_fsx_persistent_options_validator(deployment_type, kms_key_id, per_unit_storage_throughput, expected_message):
    actual_failures = FsxPersistentOptionsValidator()(
        Param(deployment_type), Param(kms_key_id), Param(per_unit_storage_throughput)
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "automatic_backup_retention_days, daily_automatic_backup_start_time, copy_tags_to_backups, deployment_type,"
    "imported_file_chunk_size, import_path, export_path, auto_import_policy, expected_message",
    [
        (
            2,
            None,
            None,
            "SCRATCH_1",
            None,
            None,
            None,
            None,
            "FSx automatic backup features can be used only with 'PERSISTENT_1' file systems",
        ),
        (
            None,
            "03:00",
            None,
            None,
            None,
            None,
            None,
            None,
            "When specifying daily automatic backup start time,"
            "the automatic backup retention days option must be specified",
        ),
        (
            None,
            None,
            True,
            "PERSISTENT_1",
            None,
            None,
            None,
            None,
            "When specifying copy tags to backups, the automatic backup retention days option must be specified",
        ),
        (
            None,
            None,
            False,
            "PERSISTENT_1",
            None,
            None,
            None,
            None,
            "When specifying copy tags to backups, the automatic backup retention days option must be specified",
        ),
        (
            None,
            "03:00",
            True,
            None,
            None,
            None,
            None,
            None,
            "When specifying daily automatic backup start time,"
            "the automatic backup retention days option must be specified",
        ),
        (
            2,
            None,
            None,
            "PERSISTENT_1",
            1024,
            "s3://test",
            "s3://test",
            None,
            "Backups cannot be created on S3-linked file systems",
        ),
        (
            2,
            None,
            None,
            "PERSISTENT_1",
            1200,
            "s3://test",
            "s3://test",
            None,
            "Backups cannot be created on S3-linked file systems",
        ),
    ],
)
def test_fsx_backup_options_validator(
    automatic_backup_retention_days,
    daily_automatic_backup_start_time,
    copy_tags_to_backups,
    deployment_type,
    imported_file_chunk_size,
    import_path,
    export_path,
    auto_import_policy,
    expected_message,
):
    actual_failures = FsxBackupOptionsValidator()(
        Param(automatic_backup_retention_days),
        Param(daily_automatic_backup_start_time),
        Param(copy_tags_to_backups),
        Param(deployment_type),
        Param(imported_file_chunk_size),
        Param(import_path),
        Param(export_path),
        Param(auto_import_policy),
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "storage_type, deployment_type, per_unit_storage_throughput, drive_cache_type, expected_message",
    [
        (
            "HDD",
            "SCRATCH_1",
            12,
            "READ",
            "For HDD filesystems, deployment type must be 'PERSISTENT_1'",
        ),
        (
            "HDD",
            "PERSISTENT_1",
            50,
            "READ",
            r"For HDD filesystems, per unit storage throughput can only have the following values: \[12, 40\]",
        ),
        (
            "SSD",
            "PERSISTENT_1",
            12,
            None,
            r"For SSD filesystems, per unit storage throughput can only have the following values: \[50, 100, 200\]",
        ),
        (
            "SSD",
            "PERSISTENT_1",
            50,
            None,
            None,
        ),
        (
            None,
            "PERSISTENT_1",
            50,
            "READ",
            "drive cache type features can be used only with HDD filesystems",
        ),
    ],
)
def test_fsx_storage_type_options_validator(
    storage_type, deployment_type, per_unit_storage_throughput, drive_cache_type, expected_message
):
    actual_failures = FsxStorageTypeOptionsValidator()(
        Param(storage_type), Param(deployment_type), Param(per_unit_storage_throughput), Param(drive_cache_type)
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "storage_capacity, deployment_type, storage_type, per_unit_storage_throughput,"
    " file_system_id, backup_id, expected_message",
    [
        (
            1,
            "SCRATCH_1",
            None,
            None,
            None,
            None,
            "Capacity for FSx SCRATCH_1 filesystem is 1,200 GB, 2,400 GB or increments of 3,600 GB",
        ),
        (
            3600,
            "SCRATCH_2",
            None,
            None,
            None,
            None,
            "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB",
        ),
        (
            3600,
            "PERSISTENT_1",
            None,
            50,
            None,
            None,
            "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB",
        ),
        (
            3601,
            "PERSISTENT_1",
            None,
            50,
            None,
            None,
            "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB",
        ),
        (
            None,
            "SCRATCH_1",
            None,
            None,
            None,
            None,
            "When specifying 'fsx' section, the 'StorageCapacity' option must be specified",
        ),
        (
            1801,
            "PERSISTENT_1",
            "HDD",
            40,
            None,
            None,
            "Capacity for FSx PERSISTENT HDD 40 MB/s/TiB file systems is increments of 1,800 GiB",
        ),
        (
            6001,
            "PERSISTENT_1",
            "HDD",
            12,
            None,
            None,
            "Capacity for FSx PERSISTENT HDD 12 MB/s/TiB file systems is increments of 6,000 GiB",
        ),
        (1200, "SCRATCH_1", None, None, None, None, None),
        (2400, "SCRATCH_1", None, None, None, None, None),
        (3600, "SCRATCH_1", None, None, None, None, None),
        (
            1800,
            "PERSISTENT_1",
            "HDD",
            40,
            None,
            None,
            None,
        ),
        (
            6000,
            "PERSISTENT_1",
            "HDD",
            12,
            None,
            None,
            None,
        ),
    ],
)
def test_fsx_storage_capacity_validator(
    storage_capacity,
    deployment_type,
    storage_type,
    per_unit_storage_throughput,
    file_system_id,
    backup_id,
    expected_message,
):
    actual_failures = FsxStorageCapacityValidator()(
        Param(storage_capacity),
        Param(deployment_type),
        Param(storage_type),
        Param(per_unit_storage_throughput),
        Param(file_system_id),
        Param(backup_id),
    )
    assert_failure_messages(actual_failures, expected_message)
