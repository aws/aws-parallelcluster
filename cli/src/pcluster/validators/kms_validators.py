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
from pcluster.aws.common import AWSClientError
from pcluster.validators.common import FailureLevel, Validator


class KmsKeyValidator(Validator):
    """Kms key validator."""

    def _validate(self, kms_key_id: str):
        try:
            AWSApi.instance().kms.describe_key(kms_key_id=kms_key_id)
        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)


class KmsKeyIdEncryptedValidator(Validator):
    """
    KmsKeyId encrypted validator.

    Validate KmsKeyId value based on encrypted value.
    """

    def _validate(self, kms_key_id, encrypted):
        if kms_key_id and not encrypted:
            self._add_failure(
                "Kms Key Id {0} is specified, the encrypted state must be True.".format(kms_key_id),
                FailureLevel.ERROR,
            )
