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

from pcluster.validators.common import FailureLevel, Validator


class FsxS3OptionsValidator(Validator):
    """FSX validator for S3 related options."""

    def __call__(self, import_path, imported_file_chunk_size, export_path, auto_import_policy):
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
