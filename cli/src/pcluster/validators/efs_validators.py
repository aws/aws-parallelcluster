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
