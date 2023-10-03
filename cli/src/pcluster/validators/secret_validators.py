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
from pcluster.validators.common import (
    FailureLevel,
    Validator,
    get_arn_service_and_resource,
    handle_arn_aws_client_error,
)


# TODO: Possibly extend to dictionaries of pairs {"allowed_service" : "allowed_resource"}.
class ArnServiceAndResourceValidator(Validator):
    """Validate that Arn is a valid ARN in given region."""

    def _validate(self, arn: str, region: str, expected_service: str, expected_resource: str):
        service, resource = get_arn_service_and_resource(arn)
        if not (service == expected_service and resource == expected_resource):
            self._add_failure(f"The {arn} is not supported in region {region}.", FailureLevel.ERROR)


class MungeKeySecretSizeAndBase64Validator(Validator):
    """Validate that MungeKeySecretArn exists.

    In Base64 encoding:
    - Every 3 bytes of input are represented as 4 characters in the encoded string.
    - The length of the encoded string must be a multiple of 4.
    - Valid Base64 characters include upper/lowercase letters,
      numbers, '+', '/', and possibly trailing '=' padding chars.
    - The '=' padding is used if the number of bytes being encoded is not divisible by 3.
    Given these rules:
    - "validBase64" is valid because its length is a multiple of 4 and uses valid Base64 characters.
    - "invalidBase64" is invalid because its length is not a multiple of 4.

    Also:
    - The size of the decoded munge key must between 256 and 8192 bits.
    """

    def _validate(self, munge_key_secret_arn: str):
        try:
            # Get the actual key value to check if it is a valid Base64
            secret_response = AWSApi.instance().secretsmanager.get_secret_value(munge_key_secret_arn)
            secret_value = secret_response.get("SecretString")

            if not secret_value:
                self._add_failure(
                    f"The secret {munge_key_secret_arn} does not contain a valid secret string.",
                    FailureLevel.ERROR,
                )
                return

            try:
                # Try decoding key value from Base64
                decoded_secret = base64.b64decode(secret_value, validate=True)
                # Check if the size of the decoding key is within the accepted range
                decoded_secret_size_in_bits = len(decoded_secret) * 8
                if decoded_secret_size_in_bits < 256 or decoded_secret_size_in_bits > 8192:
                    self._add_failure(
                        f"The size of the decoded munge key in the secret {munge_key_secret_arn} is "
                        f"{decoded_secret_size_in_bits} bits. Please use a key with a size between 256 and 8192 bits.",
                        FailureLevel.ERROR,
                    )
            except binascii.Error:
                self._add_failure(
                    f"The content of the secret {munge_key_secret_arn} is not a valid Base64 encoded string. "
                    f"Please refer to the ParallelCluster official documentation for more information.",
                    FailureLevel.ERROR,
                )
        except AWSClientError as e:
            handle_arn_aws_client_error(e, munge_key_secret_arn, self)
