# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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


class EfsMountOptionsValidator(Validator):
    """
    EFS Mount Options validator.

    IAM Authorization requires Encryption in Transit.
    """

    def _validate(self, encryption_in_transit: bool, iam_authorization: bool, name: str):
        if iam_authorization and not encryption_in_transit:
            self._add_failure(
                "EFS IAM authorization cannot be enabled when encryption in-transit is disabled. "
                f"Please either disable IAM authorization or enable encryption in-transit for file system {name}",
                FailureLevel.ERROR,
            )


class EfsAccessPointOptionsValidator(Validator):
    """
    EFS Mount Options validator.

    IAM Authorization requires Encryption in Transit.
    """

    def _validate(self, access_point_id: str, file_system_id: str, encryption_in_transit: bool):

        if access_point_id and not file_system_id:
            self._add_failure(
                "An access point can only be specified when using an existing EFS file system. "
                f"Please either remove the access point id {access_point_id} "
                "or provide the file system id for the access point",
                FailureLevel.ERROR,
            )

        if access_point_id and not encryption_in_transit:
            self._add_failure(
                "An access point can only be specified when encryption in transit is enabled. "
                f"Please either remove the access point id {access_point_id} or enable encryption in transit.",
                FailureLevel.ERROR,
            )
