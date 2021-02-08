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
from common.boto3.common import AWSExceptionHandler, Boto3Client
from common.boto3.ec2 import Ec2Client


class EfsClient(Boto3Client):
    """S3 Boto3 client."""

    def __init__(self, ec2_client: Ec2Client):
        super().__init__("efs")
        self._ec2_client = ec2_client

    @AWSExceptionHandler.handle_client_exception
    def get_efs_mount_target_id(self, efs_fs_id, avail_zone):
        """
        Search for a Mount Target Id in given availability zone for the given EFS file system id.

        :param efs_fs_id: EFS file system Id
        :param avail_zone: Availability zone to verify
        :return: the mount_target_id or None
        """
        mount_target_id = None
        if efs_fs_id:
            mount_targets = self._client.describe_mount_targets(FileSystemId=efs_fs_id)

            for mount_target in mount_targets.get("MountTargets"):
                # Check to see if there is an existing mt in the az of the stack
                mount_target_subnet = mount_target.get("SubnetId")
                if avail_zone == self._ec2_client.get_availability_zone_of_subnet(mount_target_subnet):
                    mount_target_id = mount_target.get("MountTargetId")

        return mount_target_id
