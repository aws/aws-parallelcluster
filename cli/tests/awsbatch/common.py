from collections import namedtuple

MockedBoto3Request = namedtuple("MockedBoto3Request", ["method", "response", "expected_params"])

DEFAULT_AWSBATCHCLICONFIG_MOCK_CONFIG = {
    "region": "region",
    "proxy": None,
    "aws_access_key_id": "aws_access_key_id",
    "aws_secret_access_key": "aws_secret_access_key",
    "job_queue": "job_queue",
}


def read_text(path):
    """Read the content of a file."""
    with path.open() as f:
        return f.read()
