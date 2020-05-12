import logging
import sys

import boto3
from botocore.exceptions import ClientError

LOGGER = logging.getLogger(__name__)
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(module)s - %(message)s", level=logging.INFO)


class S3DocumentManager:
    """Class to manage S3 Operations."""

    def __init__(self, _region, _credentials=None):
        self._region = _region
        self._credentials = _credentials or {}

    def download(self, s3_bucket, document_s3_path, version_id=None):
        """
        Download object from S3.

        :param s3_bucket: bucket
        :param document_s3_path: s3 path
        :param version_id:
        :return:
        """
        try:
            s3 = boto3.resource("s3", region_name=self._region, **self._credentials)
            if version_id:
                instances_file_content = s3.ObjectVersion(s3_bucket, document_s3_path, version_id).get()["Body"].read()
            else:
                instances_file_content = s3.Object(s3_bucket, document_s3_path).get()["Body"].read()
            return instances_file_content
        except Exception as e:
            self.error(
                f"Failed when downloading file {document_s3_path} from bucket {s3_bucket} "
                f"in region {self._region} with error {e}"
            )
            raise

    def upload(self, s3_bucket, s3_key, data, dryrun=True, md5=None, public_read=True):
        """
        Upload a document to S3.

        :param s3_bucket: bucket
        :param s3_key: s3 key
        :param data: byte encoded data
        :param dryrun: don't actually upload, just print and exit
        :param md5: md5 checksum of the file
        :param public_read: make the files publicly readable
        """
        try:
            if not dryrun:
                object = boto3.resource("s3", region_name=self._region, **self._credentials).Object(s3_bucket, s3_key)
                extra_args = {}
                if md5:
                    extra_args["ContentMD5"] = md5
                if public_read:
                    extra_args["ACL"] = "public-read"
                object.put(Body=data, **extra_args)
            else:
                logging.info(
                    "Dryrun mode enabled. The following file would have been uploaded to s3://%s/%s:\n%s",
                    s3_bucket,
                    s3_key,
                    data,
                )
        except Exception as e:
            self.error(
                f"Failed when uploading file {s3_key} to bucket {s3_bucket} in region {self._region} with error {e}"
            )
            raise

    def version_exists(self, s3_bucket, document_s3_path):
        """
        Sees if the object exists.

        :param s3_bucket: bucket
        :param document_s3_path: key_path
        :return: True if exists else False
        """
        try:
            self.get_current_version(s3_bucket, document_s3_path)
            return True
        except ClientError:
            return False

    def get_current_version(self, s3_bucket, document_s3_path, raise_on_object_not_found=True):
        """
        Get the most recent version of the s3 file.

        :param s3_bucket: bucket
        :param document_s3_path: s3 key path to the object
        :param raise_on_object_not_found: Raise an exception if not found
        :return: versionId if it's versioned, else None
        """
        try:
            response = boto3.client("s3", region_name=self._region, **self._credentials).head_object(
                Bucket=s3_bucket, Key=document_s3_path
            )
            if not response.get("VersionId"):
                self.error(f"Versioning not enabled for s3://{s3_bucket}")
            return response.get("VersionId")
        except ClientError as e:
            if e.response.get("Error").get("Code") == "404" and not raise_on_object_not_found:
                logging.warning("No Object Exists to rollback too... Continuing without rollback data.")
            else:
                raise e

    def copy(self, s3_src_bucket, s3_dest_bucket, s3_object, s3_object_version=None, dryrun=True, public_read=True):
        """
        Copy an S3 object between S3 buckets.

        :param s3_src_bucket: Source bucket
        :param s3_dest_bucket: Destination bucket
        :param s3_object: Object to copy
        :param s3_object_version: Version of the object to copy
        :param dryrun: don't actually copy, just print and exit
        :param public_read: make the files publicly readable
        """
        try:
            if not dryrun:
                s3 = boto3.resource("s3", region_name=self._region, **self._credentials)
                copy_source = {"Bucket": s3_src_bucket, "Key": s3_object}
                if s3_object_version:
                    copy_source["VersionId"] = s3_object_version
                extra_args = {}
                if public_read:
                    extra_args["ACL"] = "public-read"
                s3.meta.client.copy(copy_source, s3_dest_bucket, s3_object, ExtraArgs=extra_args)
            else:
                logging.info(
                    "Dryrun mode enabled. The following file with version %s would have been copied from s3://%s/%s "
                    "to s3://%s/%s",
                    s3_object_version or "latest",
                    s3_src_bucket,
                    s3_object,
                    s3_dest_bucket,
                    s3_object,
                )
        except Exception as e:
            self.error(
                f"Failed when copying file {s3_object} with version {s3_object_version or 'latest'} from bucket "
                f"{s3_src_bucket} to bucket {s3_dest_bucket} in region {self._region} with error {e}"
            )
            raise

    def revert_object(self, s3_bucket, s3_key, version_id, dryrun=True):
        """
        Revert object to a previous version from S3.

        :param s3_bucket: bucket
        :param s3_key: key path for s3 file
        :param version_id: versionId to revert too
        :param dryrun: skip upload if dryrun = True
        :return:
        """
        logging.info(f"Reverting object {s3_key} in bucket {s3_bucket} to version {version_id}")
        logging.info(
            "Revert is performed with a roll-forward. "
            "The reverted file will have a different version id but the same ETag"
        )

        current_version = self.get_current_version(s3_bucket, s3_key)
        logging.info(f"Current version: {current_version}")
        if version_id != current_version:
            self.copy(
                s3_src_bucket=s3_bucket,
                s3_dest_bucket=s3_bucket,
                s3_object=s3_key,
                s3_object_version=version_id,
                dryrun=dryrun,
            )
        else:
            logging.info(f"Current version is already the requested one: {version_id}")

    def is_bucket_versioning_enabled(self, bucket_name):
        """
        Check if versioning is enabled on a given bucket.

        :param bucket_name: name of the S3 bucket to check for versioning.
        :return: True if versioning is enabled, False otherwise.
        """
        try:
            s3 = boto3.client("s3", region_name=self._region, **self._credentials)
            return s3.get_bucket_versioning(Bucket=bucket_name).get("Status") == "Enabled"
        except Exception as e:
            self.error(f"Failed when checking versioning for S3 bucket {bucket_name} with error {e}")
            raise

    @staticmethod
    def error(message, fail_on_error=True):
        """Print an error message and Raise SystemExit exception to the stderr if fail_on_error is true."""
        if fail_on_error:
            LOGGER.error(message)
            sys.exit()
        else:
            LOGGER.error(message)
