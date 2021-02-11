import pytest

from pcluster.validators.s3_validators import UrlValidator
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "url, response, expected_message",
    [
        ("s3://test/post_install.sh", True, None),
        ("https://test/cookbook.tgz", True, None),
        ("file:///test/node.tgz", True, None),
        (
            "fake://test/cookbook.tgz",
            False,
            "The value 'fake://test/cookbook.tgz' is not a valid URL, "
            "choose URL with 'https', 's3' or 'file' prefix.",
        ),
    ],
)
def test_url_validator(mocker, url, response, expected_message):
    mocker.patch("pcluster.validators.s3_validators.S3Client.__init__", return_value=None)
    mocker.patch(
        "pcluster.validators.s3_validators.S3Client.head_object",
        return_value=response,
    )
    mocker.patch("pcluster.validators.s3_validators.urlopen", return_value=None)

    actual_failures = UrlValidator().execute(url=url)
    assert_failure_messages(actual_failures, expected_message)
