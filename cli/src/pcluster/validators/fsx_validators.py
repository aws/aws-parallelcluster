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
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError, get_region
from pcluster.constants import FSX_HDD_THROUGHPUT, FSX_SSD_THROUGHPUT
from pcluster.validators.common import FailureLevel, Validator
from pcluster.validators.utils import get_bucket_name_from_s3_url


class FsxS3Validator(Validator):
    """
    FSX S3 validator.

    Verify compatibility of given S3 options for FSX.
    """

    def _validate(
        self,
        import_path,
        imported_file_chunk_size,
        export_path,
        auto_import_policy,
    ):
        if imported_file_chunk_size and not import_path:
            self._add_failure(
                "When specifying imported file chunk size, the import path option must be specified.",
                FailureLevel.ERROR,
            )

        if export_path and not import_path:
            self._add_failure(
                "When specifying export path, the import path option must be specified.",
                FailureLevel.ERROR,
            )

        if auto_import_policy and not import_path:
            self._add_failure(
                "When specifying auto import policy, the import path option must be specified.",
                FailureLevel.ERROR,
            )


class FsxPersistentOptionsValidator(Validator):
    """
    FSX persistent options validator.

    Verify compatibility of given persistent options for FSX.
    """

    def _validate(self, deployment_type, kms_key_id, per_unit_storage_throughput):
        persistent_deployment_types = ["PERSISTENT_1", "PERSISTENT_2"]
        if deployment_type in persistent_deployment_types:
            if not per_unit_storage_throughput:
                self._add_failure(
                    f"Per unit storage throughput must be specified when deployment type is {deployment_type}.",
                    FailureLevel.ERROR,
                )
        else:
            if kms_key_id:
                self._add_failure(
                    f"KMS key id can only be used when deployment type is one of {persistent_deployment_types}.",
                    FailureLevel.ERROR,
                )
            if per_unit_storage_throughput:
                self._add_failure(
                    "Per unit storage throughput can only be used when deployment type is one of"
                    f" {persistent_deployment_types}.",
                    FailureLevel.ERROR,
                )


class FsxBackupOptionsValidator(Validator):
    """FSX backup options validator."""

    def _validate(
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
                "When specifying daily automatic backup start time,"
                "the automatic backup retention days option must be specified.",
                FailureLevel.ERROR,
            )
        if not automatic_backup_retention_days and copy_tags_to_backups is not None:
            self._add_failure(
                "When specifying copy tags to backups, the automatic backup retention days option must be specified.",
                FailureLevel.ERROR,
            )
        persistent_deployment_types = ["PERSISTENT_1", "PERSISTENT_2"]
        if deployment_type not in persistent_deployment_types and automatic_backup_retention_days:
            self._add_failure(
                f"FSx automatic backup features can be used only with {persistent_deployment_types} file systems.",
                FailureLevel.ERROR,
            )
        if (
            imported_file_chunk_size or import_path or export_path or auto_import_policy
        ) and automatic_backup_retention_days:
            self._add_failure(
                "Backups cannot be created on S3-linked file systems.",
                FailureLevel.ERROR,
            )


class FsxStorageTypeOptionsValidator(Validator):
    """FSX storage type options validator."""

    def _validate(
        self,
        fsx_storage_type,
        deployment_type,
        per_unit_storage_throughput,
        drive_cache_type,
    ):
        if fsx_storage_type == "HDD":
            if deployment_type != "PERSISTENT_1":
                self._add_failure(
                    "For HDD file systems, deployment type must be PERSISTENT_1.",
                    FailureLevel.ERROR,
                )
            if per_unit_storage_throughput not in FSX_HDD_THROUGHPUT:
                self._add_failure(
                    "For HDD file systems, per unit storage throughput can only have "
                    f"the following values: {FSX_HDD_THROUGHPUT}.",
                    FailureLevel.ERROR,
                )
        else:  # SSD or None
            if drive_cache_type:
                self._add_failure(
                    "Drive cache type features can be used only with HDD file systems.",
                    FailureLevel.ERROR,
                )
            if per_unit_storage_throughput and per_unit_storage_throughput not in FSX_SSD_THROUGHPUT[deployment_type]:
                self._add_failure(
                    f"For {deployment_type} SSD file systems, per unit storage throughput can only have "
                    f"the following values: {FSX_SSD_THROUGHPUT[deployment_type]}.",
                    FailureLevel.ERROR,
                )


class FsxStorageCapacityValidator(Validator):
    """FSX storage capacity validator."""

    def _validate(
        self,
        storage_capacity,
        deployment_type,
        fsx_storage_type,
        per_unit_storage_throughput,
        file_system_id,
        backup_id,
    ):
        if file_system_id or backup_id:
            # if file_system_id is provided, don't validate storage_capacity
            # if backup_id is provided, validation for storage_capacity will be done in fsx_lustre_backup_validator.
            return
        if not storage_capacity:
            # if file_system_id is not provided, storage_capacity must be provided
            self._add_failure(
                "When specifying FSx configuration, storage capacity must be specified.",
                FailureLevel.ERROR,
            )
        elif deployment_type == "SCRATCH_1":
            if not (storage_capacity == 1200 or storage_capacity == 2400 or storage_capacity % 3600 == 0):
                self._add_failure(
                    "Capacity for FSx SCRATCH_1 file systems is 1,200 GB, 2,400 GB or increments of 3,600 GB.",
                    FailureLevel.ERROR,
                )
        elif deployment_type == "PERSISTENT_1" and fsx_storage_type == "HDD":
            if per_unit_storage_throughput == 12 and not storage_capacity % 6000 == 0:
                self._add_failure(
                    "Capacity for FSx PERSISTENT HDD 12 MB/s/TiB file systems is increments of 6,000 GiB.",
                    FailureLevel.ERROR,
                )
            elif per_unit_storage_throughput == 40 and not storage_capacity % 1800 == 0:
                self._add_failure(
                    "Capacity for FSx PERSISTENT HDD 40 MB/s/TiB file systems is increments of 1,800 GiB.",
                    FailureLevel.ERROR,
                )
        elif deployment_type in ["SCRATCH_2", "PERSISTENT_1", "PERSISTENT_2"]:
            if not (storage_capacity == 1200 or storage_capacity % 2400 == 0):
                self._add_failure(
                    f"Capacity for FSx {deployment_type} file systems is 1,200 GB or increments of 2,400 GB.",
                    FailureLevel.ERROR,
                )


class FsxBackupIdValidator(Validator):
    """Backup id validator."""

    def _validate(self, backup_id):
        if backup_id:
            try:
                AWSApi.instance().fsx.describe_backup(backup_id)
            except AWSClientError as e:
                self._add_failure(
                    "Failed to retrieve backup with Id '{0}': {1}".format(backup_id, str(e)),
                    FailureLevel.ERROR,
                )


class FsxAutoImportValidator(Validator):
    """Auto import validator."""

    def _validate(self, auto_import_policy, import_path):
        if auto_import_policy is not None:
            bucket = get_bucket_name_from_s3_url(import_path)
            if AWSApi.instance().s3.get_bucket_region(bucket) != get_region():
                self._add_failure("FSx auto import is not supported for cross-region buckets.", FailureLevel.ERROR)
