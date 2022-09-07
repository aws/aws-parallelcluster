#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import json
import logging
import os
from abc import ABC, abstractmethod
from functools import partial

import argparse
from argparse import ArgumentParser

from pcluster import utils
from pcluster.cli.exceptions import ParameterException
from pcluster.utils import to_utc_datetime

LOGGER = logging.getLogger(__name__)


def exit_msg(msg):
    raise ParameterException({"message": msg})


def to_bool(param, in_str):
    """Take a boolean string and convert it into a boolean value."""
    if in_str in {"false", "False", "FALSE", False}:
        return False
    elif in_str in {"true", "True", "TRUE", True}:
        return True
    return exit_msg(f"Bad Request: Wrong type, expected 'boolean' for parameter '{param}'")


def to_number(param, in_str):
    """Take a string and convert it into a double."""
    try:
        return float(in_str)
    except ValueError:
        return exit_msg(f"Bad Request: Wrong type, expected 'number' for parameter '{param}'")


def to_int(param, in_str):
    """Take a string and convert it into an int."""
    try:
        return int(in_str)
    except ValueError:
        return exit_msg(f"Bad Request: Wrong type, expected 'int' for parameter '{param}'")


class CliCommand(ABC):
    """Abstract class for a CLI command."""

    def __init__(self, subparsers, region_arg: bool = True, expects_extra_args: bool = False, **argparse_kwargs):
        """Initialize a CLI command."""
        parser_name = argparse_kwargs.pop("name")
        parser = subparsers.add_parser(parser_name, **argparse_kwargs)
        parser.add_argument("--debug", action="store_true", help="Turn on debug logging.", default=False)
        if region_arg:
            parser.add_argument("-r", "--region", help="AWS Region this operation corresponds to.")
        self.register_command_args(parser)
        parser.set_defaults(func=self.execute, expects_extra_args=expects_extra_args)

    @abstractmethod
    def register_command_args(self, parser: argparse.ArgumentParser) -> None:
        """Register CLI arguments."""
        pass

    @abstractmethod
    def execute(self, args, extra_args) -> None:
        """Execute CLI command."""
        pass


def print_json(obj):
    """Print formatted Json to stdout."""
    print(json.dumps(obj, indent=2))


class Iso8601Arg:
    """Class to validate ISO8601 parameters."""

    def __call__(self, value):
        """Check if the given value is in the ISO8601 format."""
        try:
            return to_utc_datetime(value)
        except Exception as e:
            raise argparse.ArgumentTypeError(
                "Start time and end time filters must be in the ISO 8601 UTC format: YYYY-MM-DDThh:mm:ssZ "
                f"(e.g. 1984-09-15T19:20:30Z or 1984-09-15). {e}"
            )


class ExportLogsCommand:
    """Class to put in common code between image and cluster export logs commands."""

    @staticmethod
    def _register_common_command_args(parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument(
            "--output-file",
            help="File path to save log archive to. If this is provided the logs are saved "
            "locally. Otherwise they are uploaded to S3 with the url returned in the output. "
            "Default is to upload to S3.",
            type=os.path.realpath,
        )

        parser.add_argument(
            "--keep-s3-objects",
            type=partial(to_bool, "keep-s3-objects"),
            default=False,
            help="Keep the exported objects exports to S3. (Defaults to 'false'.)",
        )
        # Filters
        parser.add_argument(
            "--start-time",
            type=Iso8601Arg(),
            help=(
                "Start time of interval of interest for log events. ISO 8601 format: YYYY-MM-DDThh:mm:ssZ "
                "(e.g. 1984-09-15T19:20:30Z), time elements might be omitted. Defaults to creation time"
            ),
        )
        parser.add_argument(
            "--end-time",
            type=Iso8601Arg(),
            help=(
                "End time of interval of interest for log events. ISO 8601 format: YYYY-MM-DDThh:mm:ssZ "
                "(e.g. 1984-09-15T19:20:30Z), time elements might be omitted. Defaults to current time"
            ),
        )

    @staticmethod
    def _validate_output_file_path(file_path: str):
        """Verify that a file can be written to the given path."""
        file_dir = os.path.dirname(file_path)
        if not os.path.isdir(file_dir):
            try:
                os.makedirs(file_dir)
            except Exception as e:
                utils.error(f"Failed to create parent directory {file_dir} for file {file_path}. Reason: {e}")
        if not os.access(file_dir, os.W_OK):
            utils.error(f"Cannot write file: {file_path}. {file_dir} is not writeable.")
