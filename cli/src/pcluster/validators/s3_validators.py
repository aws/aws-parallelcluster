import re
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from common.aws.aws_api import AWSApi
from common.boto3.common import AWSClientError
from common.utils import get_url_scheme
from pcluster.validators.common import FailureLevel, Validator
from pcluster.validators.utils import get_bucket_name_from_s3_url


class UrlValidator(Validator):
    """
    Url Validator.

    Validate given url with s3, https or file prefix.
    """

    def _validate(self, url):
        scheme = get_url_scheme(url)
        if scheme in ["https", "s3", "file"]:
            if scheme == "s3":
                self._validate_s3_uri(url)
            else:
                try:
                    urlopen(url)
                except HTTPError as e:
                    self._add_failure(
                        f"The url '{url}' causes HTTPError, the error code is '{e.code}',"
                        f" the error reason is '{e.reason}'.",
                        FailureLevel.WARNING,
                    )
                except URLError as e:
                    self._add_failure(
                        f"The url '{url}' causes URLError, the error reason is '{e.reason}'.",
                        FailureLevel.WARNING,
                    )
                except ValueError:
                    self._add_failure(
                        f"The value '{url}' is not a valid URL.",
                        FailureLevel.ERROR,
                    )
        else:
            self._add_failure(
                f"The value '{url}' is not a valid URL, choose URL with 'https', 's3' or 'file' prefix.",
                FailureLevel.ERROR,
            )

    def _validate_s3_uri(self, url: str):
        try:
            match = re.match(r"s3://(.*?)/(.*)", url)
            if not match or len(match.groups()) < 2:
                self._add_failure(f"s3 url '{url}' is invalid.", FailureLevel.ERROR)
            else:
                bucket_name, object_name = match.group(1), match.group(2)
                AWSApi.instance().s3.head_object(bucket_name=bucket_name, object_name=object_name)

        except AWSClientError:
            # Todo: Check that bucket is in s3_read_resource or s3_read_write_resource.
            self._add_failure(("The S3 object does not exist or you do not have access to it."), FailureLevel.ERROR)


class S3BucketUriValidator(Validator):
    """S3 Bucket Url Validator."""

    def _validate(self, url):

        if get_url_scheme(url) == "s3":
            try:
                bucket = get_bucket_name_from_s3_url(url)
                AWSApi.instance().s3.head_bucket(bucket_name=bucket)
            except AWSClientError as e:
                self._add_failure(str(e), FailureLevel.ERROR)
        else:
            self._add_failure(f"The value '{url}' is not a valid S3 URI.", FailureLevel.ERROR)


class S3BucketValidator(Validator):
    """S3 Bucket Validator."""

    def _validate(self, bucket):

        try:
            AWSApi.instance().s3.head_bucket(bucket_name=bucket)
            # Check versioning is enabled on the bucket
            bucket_versioning_status = AWSApi.instance().s3.get_bucket_versioning_status(bucket)
            if bucket_versioning_status != "Enabled":
                self._add_failure(
                    "The S3 bucket {0} specified cannot be used by cluster "
                    "because versioning setting is: {1}, not 'Enabled'. Please enable bucket versioning.".format(
                        bucket, bucket_versioning_status
                    ),
                    FailureLevel.ERROR,
                )
        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)
