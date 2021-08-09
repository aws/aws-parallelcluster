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
        },
        "loggers": {
            "": {"handlers": ["default"], "level": "WARNING", "propagate": False},  # root logger
            "pcluster": {"handlers": ["default"], "level": "INFO", "propagate": False},
        },
    }
    os.makedirs(os.path.dirname(logfile), exist_ok=True)
    logging.config.dictConfig(logging_config)
