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

from pcluster.aws.common import AWSExceptionHandler, Boto3Client


class IamClient(Boto3Client):
    """Iam Boto3 client."""

    def __init__(self):
        super().__init__("iam")

    @AWSExceptionHandler.handle_client_exception
    def get_policy(self, iam_policy):
        """Get policy information."""
        return self._client.get_policy(PolicyArn=iam_policy)

    @AWSExceptionHandler.handle_client_exception
    def get_role(self, role_name):
        """Get role information."""
        return self._client.get_role(RoleName=role_name)

    @AWSExceptionHandler.handle_client_exception
    def get_instance_profile(self, instance_profile_name):
        """Get instance profile information."""
        return self._client.get_instance_profile(InstanceProfileName=instance_profile_name)
