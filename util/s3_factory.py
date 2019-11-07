import logging
import sys

import boto3
from botocore.exceptions import ClientError

LOGGER = logging.getLogger(__name__)
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(module)s - %(message)s", level=logging.INFO)


class S3DocumentManager:
    """
    Class to manage S3 Operations.
    """

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
                "Failed when downloading file %s from bucket %s in region %s with error %s".format(
                    document_s3_path, s3_bucket, self._region, e
                )
            )
            raise

    def upload(self, s3_bucket, s3_key, data, dryrun=True):
        """
        Upload a document to S3.

        :param s3_bucket: bucket
        :param s3_key: s3 key
        :param data: byte encoded data
        :param dryrun: don't actually upload, just print and exit
        """
        try:
            if not dryrun:
                object = boto3.resource("s3", region_name=self._region, **self._credentials).Object(s3_bucket, s3_key)
                object.put(Body=data, ACL="public-read")
            else:
                logging.info(
                    "Dryrun mode enabled. The following file would have been uploaded to s3://%s/%s:\n%s",
                    s3_bucket,
                    s3_key,
                    data,
                )
        except Exception as e:
            self.error(
                "Failed when uploading file %s to bucket %s in region %s with error %s".format(
                    s3_key, s3_bucket, self._region, e
                )
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

    def get_current_version(self, s3_bucket, document_s3_path):
        """
        Get the most recent version of the s3 file.

        :param s3_bucket: bucket
        :param document_s3_path: s3 key path to the object
        :return: versionId if it's versioned, else None
        """
        response = boto3.client("s3", region_name=self._region, **self._credentials).head_object(
            Bucket=s3_bucket, Key=document_s3_path
        )
        if not response.get("VersionId"):
            self.error(f"Versioning not enabled for s3://{s3_bucket}")
        return response.get("VersionId")

    def revert_object(self, s3_bucket, s3_key, version_id, dryrun=True):
        """
        Revert object to a previous version from S3.

        :param s3_bucket: bucket
        :param s3_key: key path for s3 file
        :param version_id: versionId to revert too
        :param dryrun: skip upload if dryrun = True
        :return:
        """
        logging.info(f"Reverting object {s3_key} in region {self._region}")

        if version_id != self.get_current_version(s3_bucket, s3_key):
            current_object = self.download(s3_bucket, s3_key)
            logging.info(f"Current version: {current_object}")
            reverting_object = self.download(s3_bucket, s3_key, version_id)
            self.upload(s3_bucket, s3_key, reverting_object, dryrun=dryrun)
        else:
            logging.info(f"Current version is already the requested one: {version_id}")

    @staticmethod
    def error(message, fail_on_error=True):
        """Print an error message and Raise SystemExit exception to the stderr if fail_on_error is true."""
        if fail_on_error:
            LOGGER.error(message)
            sys.exit()
        else:
            LOGGER.error(message)
