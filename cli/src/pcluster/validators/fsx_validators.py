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

from pcluster.constants import FSX_HDD_THROUGHPUT, FSX_SSD_THROUGHPUT
from pcluster.models.common import FailureLevel, Param, Validator


class FsxS3Validator(Validator):
    """FSX S3 validator."""

    def _validate(
        self, import_path: Param, imported_file_chunk_size: Param, export_path: Param, auto_import_policy: Param
    ):
        """Verify compatibility of given S3 options for FSX."""
        if imported_file_chunk_size.value and not import_path.value:
            self._add_failure(
                "When specifying imported file chunk size, the import path option must be specified",
                FailureLevel.CRITICAL,
                [imported_file_chunk_size, import_path],
            )

        if export_path.value and not import_path.value:
            self._add_failure(
                "When specifying export path, the import path option must be specified",
                FailureLevel.CRITICAL,
                [export_path, import_path],
            )

        if auto_import_policy.value and not import_path.value:
            self._add_failure(
                "When specifying auto import policy, the import path option must be specified",
                FailureLevel.CRITICAL,
                [auto_import_policy, import_path],
            )


class FsxPersistentOptionsValidator(Validator):
    """FSX persistent options validator."""

    def _validate(self, deployment_type: Param, kms_key_id: Param, per_unit_storage_throughput: Param):
        """Verify compatibility of given persistent options for FSX."""
        if deployment_type.value == "PERSISTENT_1":
            if not per_unit_storage_throughput.value:
                self._add_failure(
                    "per unit storage throughput must be specified when deployment type is `PERSISTENT_1'",
                    FailureLevel.CRITICAL,
                    [deployment_type, per_unit_storage_throughput],
                )
        else:
            if kms_key_id.value:
                self._add_failure(
                    "kms key id can only be used when deployment type is `PERSISTENT_1'",
                    FailureLevel.CRITICAL,
                    [deployment_type, kms_key_id],
                )
            if per_unit_storage_throughput.value:
                self._add_failure(
                    "per unit storage throughput can only be used when deployment type is `PERSISTENT_1'",
                    FailureLevel.CRITICAL,
                    [deployment_type, per_unit_storage_throughput],
                )


class FsxBackupOptionsValidator(Validator):
    """FSX backup options validator."""

    def _validate(
        self,
        automatic_backup_retention_days: Param,
        daily_automatic_backup_start_time: Param,
        copy_tags_to_backups: Param,
        deployment_type: Param,
        imported_file_chunk_size: Param,
        import_path: Param,
        export_path: Param,
        auto_import_policy: Param,
    ):
        """Verify compatibility of given backup options for FSX."""
        if not automatic_backup_retention_days.value and daily_automatic_backup_start_time.value:
            self._add_failure(
                "When specifying daily automatic backup start time,"
                "the automatic backup retention days option must be specified",
                FailureLevel.CRITICAL,
                [automatic_backup_retention_days, daily_automatic_backup_start_time],
            )
        if not automatic_backup_retention_days.value and copy_tags_to_backups.value is not None:
            self._add_failure(
                "When specifying copy tags to backups, " "the automatic backup retention days option must be specified",
                FailureLevel.CRITICAL,
                [automatic_backup_retention_days, copy_tags_to_backups],
            )
        if deployment_type.value != "PERSISTENT_1" and automatic_backup_retention_days.value:
            self._add_failure(
                "FSx automatic backup features can be used only with 'PERSISTENT_1' file systems",
                FailureLevel.CRITICAL,
                [deployment_type, automatic_backup_retention_days],
            )
        if (
            imported_file_chunk_size.value or import_path.value or export_path.value or auto_import_policy.value
        ) and automatic_backup_retention_days.value:
            self._add_failure(
                "Backups cannot be created on S3-linked file systems",
                FailureLevel.CRITICAL,
                [automatic_backup_retention_days],
            )


class FsxStorageTypeOptionsValidator(Validator):
    """FSX storage type options validator."""

    def _validate(
        self, storage_type: Param, deployment_type: Param, per_unit_storage_throughput: Param, drive_cache_type: Param
    ):
        """Verify compatibility of given storage type options for FSX."""
        if storage_type.value == "HDD":
            if deployment_type.value != "PERSISTENT_1":
                self._add_failure(
                    "For HDD filesystems, deployment type must be 'PERSISTENT_1'",
                    FailureLevel.CRITICAL,
                    [storage_type, deployment_type],
                )
            if per_unit_storage_throughput.value not in FSX_HDD_THROUGHPUT:
                self._add_failure(
                    "For HDD filesystems, per unit storage throughput can only have the following values: {0}".format(
                        FSX_HDD_THROUGHPUT
                    ),
                    FailureLevel.CRITICAL,
                    [storage_type, per_unit_storage_throughput],
                )
        else:  # SSD or None
            if drive_cache_type.value:
                self._add_failure(
                    "drive cache type features can be used only with HDD filesystems",
                    FailureLevel.CRITICAL,
                    [storage_type, drive_cache_type],
                )
            if per_unit_storage_throughput.value and per_unit_storage_throughput.value not in FSX_SSD_THROUGHPUT:
                self._add_failure(
                    "For SSD filesystems, per unit storage throughput can only have the following values: {0}".format(
                        FSX_SSD_THROUGHPUT
                    ),
                    FailureLevel.CRITICAL,
                    [storage_type, per_unit_storage_throughput],
                )


class FsxStorageCapacityValidator(Validator):
    """FSX storage capacity validator."""

    def _validate(
        self,
        storage_capacity: Param,
        deployment_type: Param,
        storage_type: Param,
        per_unit_storage_throughput: Param,
        file_system_id: Param,
        backup_id: Param,
    ):
        """Verify compatibility of given storage capacity options for FSX."""
        if file_system_id.value or backup_id.value:
            # if file_system_id is provided, don't validate storage_capacity
            # if backup_id is provided, validation for storage_capacity will be done in fsx_lustre_backup_validator.
            return
        if not storage_capacity.value:
            # if file_system_id is not provided, storage_capacity must be provided
            self._add_failure(
                "When specifying 'fsx' section, the 'StorageCapacity' option must be specified",
                FailureLevel.CRITICAL,
                [storage_capacity],
            )
        elif deployment_type.value == "SCRATCH_1":
            if not (
                storage_capacity.value == 1200 or storage_capacity.value == 2400 or storage_capacity.value % 3600 == 0
            ):
                self._add_failure(
                    "Capacity for FSx SCRATCH_1 filesystem is 1,200 GB, 2,400 GB or increments of 3,600 GB",
                    FailureLevel.CRITICAL,
                    [storage_capacity, deployment_type],
                )
        elif deployment_type.value == "PERSISTENT_1" and storage_type.value == "HDD":
            if per_unit_storage_throughput.value == 12 and not (storage_capacity.value % 6000 == 0):
                self._add_failure(
                    "Capacity for FSx PERSISTENT HDD 12 MB/s/TiB file systems is increments of 6,000 GiB",
                    FailureLevel.CRITICAL,
                    [storage_capacity, deployment_type, storage_type, per_unit_storage_throughput],
                )
            elif per_unit_storage_throughput.value == 40 and not (storage_capacity.value % 1800 == 0):
                self._add_failure(
                    "Capacity for FSx PERSISTENT HDD 40 MB/s/TiB file systems is increments of 1,800 GiB",
                    FailureLevel.CRITICAL,
                    [storage_capacity, deployment_type, storage_type, per_unit_storage_throughput],
                )
        elif deployment_type.value in ["SCRATCH_2", "PERSISTENT_1"]:
            if not (storage_capacity.value == 1200 or storage_capacity.value % 2400 == 0):
                self._add_failure(
                    "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB",
                    FailureLevel.CRITICAL,
                    [storage_capacity, deployment_type],
                )
