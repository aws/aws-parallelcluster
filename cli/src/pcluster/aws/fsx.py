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
from pcluster.aws.aws_resources import FsxFileSystemInfo
from pcluster.aws.common import AWSExceptionHandler, Boto3Client, Cache


class FSxClient(Boto3Client):
    """S3 Boto3 client."""

    def __init__(self):
        super().__init__("fsx")

    @AWSExceptionHandler.handle_client_exception
    @Cache.cached
    def get_filesystem_info(self, fsx_fs_id):
        """
        Return FSx filesystem info.

        :param fsx_fs_id: FSx file system Id
        :return: filesystem info
        """
        return FsxFileSystemInfo(self._client.describe_file_systems(FileSystemIds=[fsx_fs_id]).get("FileSystems")[0])

    @AWSExceptionHandler.handle_client_exception
    def describe_backup(self, backup_id):
        """Describe backup."""
        return self._client.describe_backups(BackupIds=[backup_id]).get("Backups")[0]
