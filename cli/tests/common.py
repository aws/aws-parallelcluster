from collections import namedtuple

MockedBoto3Request = namedtuple("MockedBoto3Request", ["method", "response", "expected_params"])


def read_text(path):
    """Read the content of a file."""
    with path.open() as f:
        return f.read()
