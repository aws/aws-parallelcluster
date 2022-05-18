import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.utils import get_url_scheme
from pcluster.validators.common import FailureLevel, Validator
from pcluster.validators.utils import get_bucket_name_from_s3_url


class UrlValidator(Validator):
    """
    Url Validator.

    Validate given url with s3 or https prefix.
    """

    def _validate(
        self,
        url,
        retries=3,
        fail_on_https_error: bool = False,
        fail_on_s3_error: bool = False,
        expected_bucket_owner: str = None,
    ):
        scheme = get_url_scheme(url)
        if scheme in ["https", "s3"]:
            try:
                if scheme == "s3":
                    self._validate_s3_uri(
                        url, fail_on_error=fail_on_s3_error, expected_bucket_owner=expected_bucket_owner
                    )
                else:
                    if expected_bucket_owner:
                        self._add_failure("S3BucketOwner can only be specified with S3 URL", FailureLevel.ERROR)
                    self._validate_https_uri(url, fail_on_error=fail_on_https_error)
            except ConnectionError as e:
                if retries > 0:
                    time.sleep(5)
                    self._validate(url, retries=retries - 1)
                else:
                    self._add_failure(f"The url '{url}' causes ConnectionError: {e}.", FailureLevel.WARNING)

        else:
            self._add_failure(
                f"The value '{url}' is not a valid URL, choose URL with 'https' or 's3' prefix.",
                FailureLevel.ERROR,
            )

    def _validate_s3_uri(self, url: str, fail_on_error: bool, expected_bucket_owner: str):
        try:
            match = re.match(r"s3://(.*?)/(.*)", url)
            if not match or len(match.groups()) < 2:
                self._add_failure(f"s3 url '{url}' is invalid.", FailureLevel.ERROR)
            else:
                bucket_name, object_name = match.group(1), match.group(2)
                AWSApi.instance().s3.head_object(
                    bucket_name=bucket_name, object_name=object_name, expected_bucket_owner=expected_bucket_owner
                )

        except AWSClientError as e:
            # Todo: Check that bucket is in s3_read_resource or s3_read_write_resource.
            self._add_failure(
                str(e), FailureLevel.ERROR if expected_bucket_owner or fail_on_error else FailureLevel.WARNING
            )

    def _validate_https_uri(self, url: str, fail_on_error: bool):
        try:
            with urlopen(url):  # nosec nosemgrep
                pass
        except HTTPError as e:
            self._add_failure(
                f"The url '{url}' causes HTTPError, the error code is '{e.code}',"
                f" the error reason is '{e.reason}'.",
                FailureLevel.ERROR if fail_on_error else FailureLevel.WARNING,
            )
        except URLError as e:
            self._add_failure(
                f"The url '{url}' causes URLError, the error reason is '{e.reason}'.",
                FailureLevel.ERROR if fail_on_error else FailureLevel.WARNING,
            )
        except ValueError:
            self._add_failure(
                f"The value '{url}' is not a valid URL.",
                FailureLevel.ERROR,
            )


class S3BucketUriValidator(Validator):
    """S3 Bucket Url Validator."""

    def _validate(self, url):

        if get_url_scheme(url) == "s3":
            try:
                bucket = get_bucket_name_from_s3_url(url)
                AWSApi.instance().s3.head_bucket(bucket_name=bucket)
            except AWSClientError as e:
                if e.error_code == "403":
                    self._add_failure(
                        f"{str(e)}. Please attach a policy that allows the s3:ListBucket action for the resource "
                        f"<ARN of bucket {bucket}> to the role or instance profile performing this operation.",
                        FailureLevel.ERROR,
                    )
                else:
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


class S3BucketRegionValidator(Validator):
    """Validate S3 bucket is in the same region with the cloudformation stack."""

    def _validate(self, bucket, region):
        try:
            bucket_region = AWSApi.instance().s3.get_bucket_region(bucket)
            if bucket_region != region:
                self._add_failure(
                    f"The S3 bucket {bucket} specified cannot be used because "
                    "it is not in the same region of the cluster.",
                    FailureLevel.ERROR,
                )
        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)
