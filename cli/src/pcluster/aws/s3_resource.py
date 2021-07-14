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
from pcluster.aws.common import AWSExceptionHandler, Boto3Resource, Cache


class S3Resource(Boto3Resource):
    """S3 Boto3 resource."""

    def __init__(self):
        super().__init__("s3")

    @AWSExceptionHandler.handle_client_exception
    @Cache.cached
    def get_bucket(self, bucket_name):
        """Get bucket object by bucket name."""
        return self._resource.Bucket(bucket_name)

    @AWSExceptionHandler.handle_client_exception
    def download_file(self, bucket_name, key, output):
        """Download file."""
        self.get_bucket(bucket_name).download_file(key, output)

    @AWSExceptionHandler.handle_client_exception
    def get_objects(self, bucket_name, prefix=None):
        """Get objects."""
        return self.get_bucket(bucket_name).objects.filter(Prefix=prefix)

    @AWSExceptionHandler.handle_client_exception
    def delete_objects(self, bucket_name, prefix=None):
        """Delete objects."""
        if prefix:
            self.get_bucket(bucket_name).objects.filter(Prefix=prefix).delete()
        else:
            self.get_bucket(bucket_name).objects.all().delete()

    @AWSExceptionHandler.handle_client_exception
    def delete_object(self, bucket_name, prefix=None):
        """Delete object versions by filter."""
        self.get_bucket(bucket_name).object_versions.filter(Prefix=prefix).delete()

    @AWSExceptionHandler.handle_client_exception
    def delete_object_versions(self, bucket_name, prefix=None):
        """Delete object versions by filter."""
        self.get_bucket(bucket_name).object_versions.filter(Prefix=prefix).delete()

    @AWSExceptionHandler.handle_client_exception
    def delete_all_object_versions(self, bucket_name):
        """Delete all object versions."""
        self.get_bucket(bucket_name).object_versions.delete()

    @AWSExceptionHandler.handle_client_exception
    def is_empty(self, bucket_name, prefix=None):
        """Return true whether the given bucket doesn't have any objects under the given key prefix."""
        return not any(self.get_bucket(bucket_name).objects.filter(Prefix=prefix).limit(1))
