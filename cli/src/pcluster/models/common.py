class LimitExceeded(Exception):
    """Base exception type for errors caused by exceeding the limit of some underlying AWS service."""

    pass


class BadRequest(Exception):
    """Base exception type for errors caused by problems in the request."""

    pass


class Conflict(Exception):
    """Base exception type for errors caused by some conflict (such as a resource already existing)."""

    pass
