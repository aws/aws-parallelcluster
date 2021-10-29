#!/usr/bin/env python3
# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not
# use this file except in compliance with the License. A copy of the License is
# located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or
# implied. See the License for the specific language governing permissions and
# limitations under the License.

import logging.config
import os
import sys
from contextlib import contextmanager

from pcluster.utils import get_cli_log_file

LOGGER = logging.getLogger(__name__)


def config_logger():
    logfile = get_cli_log_file()
    logging_config = {
        "version": 1,
        "disable_existing_loggers": True,
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(levelname)s - %(filename)s:%(lineno)s:%(funcName)s() - %(message)s"
            },
            "console": {"format": "%(message)s"},
        },
        "handlers": {
            "default": {
                "level": "DEBUG",
                "formatter": "standard",
                "class": "logging.handlers.RotatingFileHandler",
                "filename": logfile,
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 3,
            },
            "console": {
                "level": "DEBUG",
                "formatter": "standard",
                "class": "logging.StreamHandler",
                "stream": sys.__stdout__,
            },
        },
        "loggers": {
            "": {"handlers": ["default"], "level": "WARNING", "propagate": False},  # root logger
            "pcluster": {"handlers": ["default"], "level": "INFO", "propagate": False},
        },
    }
    if os.environ.get("PCLUSTER_LOG_TO_STDOUT"):
        for logger in logging_config["loggers"].values():
            logger["handlers"] = ["console"]
    os.makedirs(os.path.dirname(logfile), exist_ok=True)
    logging.config.dictConfig(logging_config)


class LogWriter:
    """Write message to log file. It can be used to replace the default stdout/stderr to have it write to the logger."""

    def __init__(self, log_level, logger):
        self._log_level = log_level
        self._logger = logger

    def write(self, message):
        """Write message to log."""
        if message and message.strip():
            self._logger.log(self._log_level, message.strip())

    def flush(self):
        """No-op."""
        pass


@contextmanager
def redirect_stdouterr_to_logger():
    """Redirect default stdout and stderr to logger."""
    stdout_backup = sys.stdout
    stderr_backup = sys.stderr
    try:
        sys.stdout = LogWriter(logging.INFO, LOGGER)
        sys.stderr = LogWriter(logging.ERROR, LOGGER)
        yield
    finally:
        sys.stdout = stdout_backup
        sys.stderr = stderr_backup
