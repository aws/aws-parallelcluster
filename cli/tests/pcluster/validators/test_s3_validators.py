import pytest

from pcluster.validators.s3_validators import S3BucketRegionValidator, S3BucketUriValidator, UrlValidator
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "url, response, expected_message",
    [
        ("s3://test/post_install.sh", True, None),
        ("https://test/cookbook.tgz", True, None),
        (
            "file:///test/node.tgz",
            False,
            "The value 'file:///test/node.tgz' is not a valid URL, " "choose URL with 'https' or 's3' prefix.",
        ),
        (
            "fake://test/cookbook.tgz",
            False,
            "The value 'fake://test/cookbook.tgz' is not a valid URL, " "choose URL with 'https' or 's3' prefix.",
        ),
    ],
)
def test_url_validator(mocker, url, response, expected_message, aws_api_mock):
    aws_api_mock.s3.head_object.return_value = response
    mocker.patch("pcluster.validators.s3_validators.urlopen")

    actual_failures = UrlValidator().execute(url=url)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "url, expected_message",
    [
        ("s3://test/test1/test2", None),
        ("http://test/test.json", "is not a valid S3 URI"),
    ],
)
def test_s3_bucket_uri_validator(mocker, url, expected_message, aws_api_mock):
    aws_api_mock.s3.head_bucket.return_value = True
    actual_failures = S3BucketUriValidator().execute(url=url)
    assert_failure_messages(actual_failures, expected_message)
    if url.startswith("s3://"):
        aws_api_mock.s3.head_bucket.assert_called()


@pytest.mark.parametrize(
    "bucket, bucket_region, cluster_region, expected_message",
    [
        ("bucket", "us-east-1", "us-east-1", None),
        ("bucket", "us-west-1", "us-west-1", None),
        ("bucket", "eu-west-1", "us-east-1", "cannot be used because it is not in the same region of the cluster."),
    ],
)
def test_s3_bucket_region_validator(mocker, bucket, bucket_region, cluster_region, expected_message, aws_api_mock):
    aws_api_mock.s3.get_bucket_region.return_value = bucket_region
    actual_failures = S3BucketRegionValidator().execute(bucket=bucket, region=cluster_region)
    assert_failure_messages(actual_failures, expected_message)
    aws_api_mock.s3.get_bucket_region.assert_called_with(bucket)
