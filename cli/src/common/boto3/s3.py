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
from botocore.exceptions import ClientError

from common.boto3.common import AWSClientError, AWSExceptionHandler, Boto3Client


class S3Client(Boto3Client):
    """S3 Boto3 client."""

    def __init__(self):
        super().__init__("s3")

    @AWSExceptionHandler.handle_client_exception
    def download_file(self, bucket_name, object_name, file_name):
        """Download generic file from S3."""
        self._client.download_file(bucket_name, object_name, file_name)

    def head_object(self, bucket_name, object_name):
        """Retrieve metadata from an object without returning the object itself."""
        try:
            return self._client.head_object(Bucket=bucket_name, Key=object_name)
        except ClientError as client_error:
            raise AWSClientError(
                function_name="head_object",
                message=_process_s3_bucket_error(client_error, bucket_name),
                error_code=client_error.response["Error"]["Code"],
            )

    def head_bucket(self, bucket_name):
        """Retrieve metadata for a bucket without returning the object itself."""
        try:
            return self._client.head_bucket(Bucket=bucket_name)
        except ClientError as client_error:
            raise AWSClientError(
                function_name="head_bucket",
                message=_process_s3_bucket_error(client_error, bucket_name),
                error_code=client_error.response["Error"]["Code"],
            )

    @AWSExceptionHandler.handle_client_exception
    def put_object(self, bucket_name, body, key):
        """Upload object content to s3."""
        return self._client.put_object(Bucket=bucket_name, Body=body, Key=key)

    @AWSExceptionHandler.handle_client_exception
    def get_object(self, bucket_name, key, version_id=None):
        """Get object content from s3."""
        if version_id:
            return self._client.get_object(Bucket=bucket_name, Key=key, VersionId=version_id)
        return self._client.get_object(Bucket=bucket_name, Key=key)

    @AWSExceptionHandler.handle_client_exception
    def get_bucket_versioning_status(self, bucket_name):
        """Return true if bucket versioning is enabled."""
        return self._client.get_bucket_versioning(Bucket=bucket_name).get("Status")

    def get_bucket_region(self, bucket_name):
        """Return bucket region."""
        try:
            bucket_region = self._client.get_bucket_location(Bucket=bucket_name).get("LocationConstraint")
            # Buckets in Region us-east-1 have a LocationConstraint of null
            # Example output from get_bucket_location for us-east-1:
            #   {'ResponseMetadata': {...}, 'LocationConstraint': None}
            if bucket_region is None:
                bucket_region = "us-east-1"
            return bucket_region
        except ClientError as client_error:
            raise AWSClientError(
                function_name="get_bucket_location",
                message=_process_s3_bucket_error(client_error, bucket_name),
                error_code=client_error.response["Error"]["Code"],
            )


def _process_s3_bucket_error(client_error, bucket_name):
    error_message = client_error.response.get("Error").get("Message")
    error_code = client_error.response["Error"]["Code"]

    if error_code == "NoSuchBucket":
        message = f"The S3 bucket '{bucket_name}' does not appear to exist: '{error_message}'"
    elif error_code == "AccessDenied":
        return f"You do not have access to the S3 bucket '{bucket_name}': '{error_message}'"
    else:
        message = f"Unexpected error when calling get_bucket_location on S3 bucket '{bucket_name}': '{error_message}'"
    return message
