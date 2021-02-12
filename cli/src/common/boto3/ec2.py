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

# TODO move s3_factory.py and awsbatch/utils.py here

from common.boto3.common import AWSClientError, AWSExceptionHandler, Boto3Client


class Ec2Client(Boto3Client):
    """Implement EC2 Boto3 client."""

    def __init__(self):
        super().__init__("ec2")

    @AWSExceptionHandler.handle_client_exception
    def describe_instance_type_offerings(self):
        """Return a list of instance types."""
        return [
            offering.get("InstanceType")
            for offering in self._paginate_results(self._client.describe_instance_type_offerings)
        ]

    @AWSExceptionHandler.handle_client_exception
    def describe_image(self, ami_id):
        """Return a dict of ami info."""
        result = self._client.describe_images(ImageIds=[ami_id])
        if result.get("Images"):
            return result.get("Images")[0]
        raise AWSClientError(function_name="describe_image", message=f"Image {ami_id} not found")

    @AWSExceptionHandler.handle_client_exception
    def describe_key_pair(self, key_name):
        """Return the given key, if exists."""
        return self._client.describe_key_pairs(KeyNames=[key_name])

    @AWSExceptionHandler.handle_client_exception
    def describe_placement_group(self, group_name):
        """Return the given placement group, if exists."""
        return self._client.describe_placement_group(GroupNames=[group_name])
