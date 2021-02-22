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

from common.aws.aws_api import AWSApi
from common.boto3.common import AWSClientError
from pcluster.validators.common import FailureLevel, Validator


class KmsKeyValidator(Validator):
    """Kms key validator."""

    def _validate(self, kms_key_id: str):
        try:
            AWSApi.instance().kms.describe_key(kms_key_id=kms_key_id)
        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)
