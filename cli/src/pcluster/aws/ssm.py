# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from pcluster.aws.common import AWSExceptionHandler, Boto3Client


class SsmClient(Boto3Client):
    """SSM Boto3 client."""

    def __init__(self):
        super().__init__("ssm")

    @AWSExceptionHandler.handle_client_exception
    def get_parameter(self, name: str):
        """
        Retrieve a Parameter.

        :param name: Parameter name.
        :return: Parameter info
        """
        return self._client.get_parameter(Name=name)
