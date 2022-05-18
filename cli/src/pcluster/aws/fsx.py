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
from pcluster.aws.common import AWSExceptionHandler, Boto3Client


class FSxClient(Boto3Client):
    """S3 Boto3 client."""

    def __init__(self):
        super().__init__("fsx")
        self.cache = {}

    @AWSExceptionHandler.handle_client_exception
    def get_file_systems_info(self, fsx_fs_ids):
        """
        Return FSx file systems info.

        :param fsx_fs_ids: a list of FSx file system Id
        :return: a list of file systems info
        """
        result = []
        missed_fsx_fs_ids = []
        for file_system_id in fsx_fs_ids:
            cached_data = self.cache.get(file_system_id)
            if cached_data:
                result.append(cached_data)
            else:
                missed_fsx_fs_ids.append(file_system_id)
        if missed_fsx_fs_ids:
            response = list(self._paginate_results(self._client.describe_file_systems, FileSystemIds=missed_fsx_fs_ids))
            for file_system in response:
                file_system_info = FsxFileSystemInfo(file_system)
                self.cache[file_system_info.file_system_id] = file_system_info
                result.append(file_system_info)
        return result

    @AWSExceptionHandler.handle_client_exception
    def describe_backup(self, backup_id):
        """Describe backup."""
        return self._client.describe_backups(BackupIds=[backup_id]).get("Backups")[0]
