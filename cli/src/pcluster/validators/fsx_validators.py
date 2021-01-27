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
from pcluster.validators.common import FailureLevel, Validator


class FsxValidator(Validator):
    """FSX validator."""

    def validate(self, fsx_config):
        """Validate FSX config."""
        import_path = fsx_config.import_path.value
        imported_file_chunk_size = fsx_config.imported_file_chunk_size.value
        export_path = fsx_config.export_path.value
        auto_import_policy = fsx_config.auto_import_policy.value
        deployment_type = fsx_config.deployment_type.value
        kms_key_id = fsx_config.kms_key_id.value
        per_unit_storage_throughput = fsx_config.per_unit_storage_throughput.value
        daily_automatic_backup_start_time = fsx_config.daily_automatic_backup_start_time.value
        automatic_backup_retention_days = fsx_config.automatic_backup_retention_days.value
        copy_tags_to_backups = fsx_config.copy_tags_to_backups.value
        storage_type = fsx_config.storage_type.value
        drive_cache_type = fsx_config.drive_cache_type.value

        self._validate_s3_options(import_path, imported_file_chunk_size, export_path, auto_import_policy)
        self._validate_persistent_options(deployment_type, kms_key_id, per_unit_storage_throughput)
        self._validate_backup_options(
            automatic_backup_retention_days,
            daily_automatic_backup_start_time,
            copy_tags_to_backups,
            deployment_type,
            imported_file_chunk_size,
            import_path,
            export_path,
            auto_import_policy,
        ),
        self._validate_storage_type_options(
            storage_type, deployment_type, per_unit_storage_throughput, drive_cache_type
        )

        self._validate_fsx_storage_capacity(fsx_config)
        self._validate_fsx_ignored_parameters(fsx_config)
        return self._failures

    def _validate_s3_options(self, import_path, imported_file_chunk_size, export_path, auto_import_policy):
        """Verify compatibility of given S3 options for FSX."""
        if imported_file_chunk_size and not import_path:
            self._add_failure(
                "When specifying imported file chunk size, the import path option must be specified",
                FailureLevel.CRITICAL,
            )

        if export_path and not import_path:
            self._add_failure(
                "When specifying export path, the import path option must be specified",
                FailureLevel.CRITICAL,
            )

        if auto_import_policy and not import_path:
            self._add_failure(
                "When specifying auto import policy, the import path option must be specified",
                FailureLevel.CRITICAL,
            )

    def _validate_persistent_options(self, deployment_type, kms_key_id, per_unit_storage_throughput):
        if deployment_type == "PERSISTENT_1":
            if not per_unit_storage_throughput:
                self._add_failure(
                    "'per_unit_storage_throughput' must be specified when 'deployment_type = PERSISTENT_1'",
                    FailureLevel.CRITICAL,
                )
        else:
            if kms_key_id:
                self._add_failure(
                    "'kms_key_id' can only be used when 'deployment_type = PERSISTENT_1'", FailureLevel.CRITICAL
                )
            if per_unit_storage_throughput:
                self._add_failure(
                    "'per_unit_storage_throughput' can only be used when 'deployment_type = PERSISTENT_1'",
                    FailureLevel.CRITICAL,
                )

    def _validate_backup_options(
        self,
        automatic_backup_retention_days,
        daily_automatic_backup_start_time,
        copy_tags_to_backups,
        deployment_type,
        imported_file_chunk_size,
        import_path,
        export_path,
        auto_import_policy,
    ):
        if not automatic_backup_retention_days and daily_automatic_backup_start_time:
            self._add_failure(
                "When specifying 'daily_automatic_backup_start_time', "
                "the 'automatic_backup_retention_days' option must be specified",
                FailureLevel.CRITICAL,
            )
        if not automatic_backup_retention_days and copy_tags_to_backups is not None:
            self._add_failure(
                "When specifying 'copy_tags_to_backups', "
                "the 'automatic_backup_retention_days' option must be specified",
                FailureLevel.CRITICAL,
            )
        if deployment_type != "PERSISTENT_1" and automatic_backup_retention_days:
            self._add_failure(
                "FSx automatic backup features can be used only with 'PERSISTENT_1' file systems", FailureLevel.CRITICAL
            )
        if (
            imported_file_chunk_size or import_path or export_path or auto_import_policy
        ) and automatic_backup_retention_days:
            self._add_failure("Backups cannot be created on S3-linked file systems", FailureLevel.CRITICAL)

    def _validate_storage_type_options(
        self, storage_type, deployment_type, per_unit_storage_throughput, drive_cache_type
    ):
        if storage_type == "HDD":
            if deployment_type != "PERSISTENT_1":
                self._add_failure(
                    "For HDD filesystems, 'deployment_type' must be 'PERSISTENT_1'", FailureLevel.CRITICAL
                )
            if per_unit_storage_throughput not in FSX_HDD_THROUGHPUT:
                self._add_failure(
                    "For HDD filesystems, 'per_unit_storage_throughput' can only have the following values: {0}".format(
                        FSX_HDD_THROUGHPUT
                    ),
                    FailureLevel.CRITICAL,
                )
        else:  # SSD or None
            if drive_cache_type is not None:
                self._add_failure(
                    "'drive_cache_type' features can be used only with HDD filesystems", FailureLevel.CRITICAL
                )
            if per_unit_storage_throughput and per_unit_storage_throughput not in FSX_SSD_THROUGHPUT:
                self._add_failure(
                    "For SSD filesystems, 'per_unit_storage_throughput' can only have the following values: {0}".format(
                        FSX_SSD_THROUGHPUT
                    ),
                    FailureLevel.CRITICAL,
                )

    def _validate_fsx_storage_capacity(self, fsx_config):
        storage_capacity = fsx_config.storage_capacity.value
        deployment_type = fsx_config.deployment_type.value
        storage_type = fsx_config.storage_type.value
        per_unit_storage_throughput = fsx_config.per_unit_storage_throughput.value
        if fsx_config.file_system_id.value or fsx_config.backup_id.value:
            # if file_system_id is provided, don't validate storage_capacity
            # if backup_id is provided, validation for storage_capacity will be done in fsx_lustre_backup_validator.
            return
        if not storage_capacity:
            # if file_system_id is not provided, storage_capacity must be provided
            self._add_failure(
                "When specifying 'fsx' section, the 'StorageCapacity' option must be specified", FailureLevel.CRITICAL
            )
        elif deployment_type == "SCRATCH_1":
            if not (storage_capacity == 1200 or storage_capacity == 2400 or storage_capacity % 3600 == 0):
                self._add_failure(
                    "Capacity for FSx SCRATCH_1 filesystem is 1,200 GB, 2,400 GB or increments of 3,600 GB",
                    FailureLevel.CRITICAL,
                )
        elif deployment_type == "PERSISTENT_1" and storage_type == "HDD":
            if per_unit_storage_throughput == 12 and not (storage_capacity % 6000 == 0):
                self._add_failure(
                    "Capacity for FSx PERSISTENT HDD 12 MB/s/TiB file systems is increments of 6,000 GiB",
                    FailureLevel.CRITICAL,
                )
            elif per_unit_storage_throughput == 40 and not (storage_capacity % 1800 == 0):
                self._add_failure(
                    "Capacity for FSx PERSISTENT HDD 40 MB/s/TiB file systems is increments of 1,800 GiB",
                    FailureLevel.CRITICAL,
                )
        elif deployment_type in ["SCRATCH_2", "PERSISTENT_1"]:
            if not (storage_capacity == 1200 or storage_capacity % 2400 == 0):
                self._add_failure(
                    "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB",
                    FailureLevel.CRITICAL,
                )
