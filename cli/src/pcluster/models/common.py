import logging

import yaml

LOGGER = logging.getLogger(__name__)


class LimitExceeded(Exception):
    """Base exception type for errors caused by exceeding the limit of some underlying AWS service."""

    pass


class BadRequest(Exception):
    """Base exception type for errors caused by problems in the request."""

    pass


class Conflict(Exception):
    """Base exception type for errors caused by some conflict (such as a resource already existing)."""

    pass


def parse_config(config):
    """Parse a YAML configuration into a dictionary."""
    try:
        config_dict = yaml.safe_load(config)
        if not isinstance(config_dict, dict):
            LOGGER.error("Failed: parsed config is not a dict")
            raise Exception("parsed config is not a dict")
        return config_dict
    except Exception as e:
        LOGGER.error("Failed when parsing the configuration due to invalid YAML document: %s", e)
        raise BadRequest("configuration must be a valid YAML document")
