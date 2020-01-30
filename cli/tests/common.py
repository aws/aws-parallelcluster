from collections import namedtuple

MockedBoto3Request = namedtuple(
    "MockedBoto3Request", ["method", "response", "expected_params", "generate_error", "error_code"]
)
# Set defaults for attributes of the namedtuple. Since fields with a default value must come after any fields without
# a default, the defaults are applied to the rightmost parameters. In this case generate_error = False and
# error_code = None
MockedBoto3Request.__new__.__defaults__ = (False, None)


def read_text(path):
    """Read the content of a file."""
    with path.open() as f:
        return f.read()
