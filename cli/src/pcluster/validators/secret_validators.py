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
import base64
import binascii

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.validators.common import FailureLevel, Validator


class MungeKeySecretArnValidator(Validator):
    """MungeKeySecretArn validator."""

    def _validate(self, munge_key_secret_arn: str, region: str):
        try:
            arn_components = munge_key_secret_arn.split(":")
            service = arn_components[2]
            resource = arn_components[5]
            if service == "secretsmanager" and resource == "secret":
                # Describe the secret to ensure it exists
                AWSApi.instance().secretsmanager.describe_secret(munge_key_secret_arn)

                # Get the actual secret value to check if it's valid Base64
                secret_response = AWSApi.instance().secretsmanager.get_secret_value(munge_key_secret_arn)
                secret_value = secret_response.get("SecretString")

                if not secret_value:
                    self._add_failure(
                        f"The secret {munge_key_secret_arn} does not contain a valid secret string.",
                        FailureLevel.ERROR,
                    )
                    return

                try:
                    # Attempt to decode the secret value from Base64
                    base64.b64decode(secret_value)
                except binascii.Error:
                    self._add_failure(
                        f"The secret {munge_key_secret_arn} does not contain valid Base64 encoded data.",
                        FailureLevel.ERROR,
                    )
            else:
                self._add_failure(
                    f"The secret {munge_key_secret_arn} is not supported in region {region}.", FailureLevel.ERROR
                )
        except AWSClientError as e:
            if e.error_code in ("ResourceNotFoundExceptionSecrets", "ParameterNotFound"):
                self._add_failure(f"The secret {munge_key_secret_arn} does not exist.", FailureLevel.ERROR)
            elif e.error_code == "AccessDeniedException":
                self._add_failure(
                    f"Cannot validate secret {munge_key_secret_arn} due to lack of permissions. "
                    "Please refer to ParallelCluster official documentation for more information.",
                    FailureLevel.WARNING,
                )
            else:
                self._add_failure(
                    f"Cannot validate secret {munge_key_secret_arn}. "
                    "Please refer to ParallelCluster official documentation for more information.",
                    FailureLevel.WARNING,
                )
