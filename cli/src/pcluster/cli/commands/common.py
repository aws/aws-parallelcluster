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
import sys
from abc import ABC, abstractmethod
from typing import Dict

import argparse
from argparse import ArgumentParser, Namespace
from flask.testing import FlaskClient

from pcluster import utils
from pcluster.api.flask_app import ParallelClusterFlaskApp
from pcluster.constants import SUPPORTED_REGIONS
from pcluster.utils import isoformat_to_epoch

LOGGER = logging.getLogger(__name__)


class CliCommand(ABC):
    """Abstract class for a CLI command."""

    def __init__(
        self,
        subparsers,
        region_arg: bool = True,
        config_arg: bool = False,  # TODO: remove
        nowait_arg: bool = False,  # TODO: remove
        expects_extra_args: bool = False,
        **argparse_kwargs,
    ):
        """Initialize a CLI command."""
        parser_name = argparse_kwargs.pop("name")
        parser = subparsers.add_parser(parser_name, **argparse_kwargs)
        parser.add_argument("--debug", action="store_true", help="Turn on debug logging.", default=False)
        if region_arg:
            parser.add_argument("-r", "--region", help="AWS Region to use.", choices=SUPPORTED_REGIONS)
        if config_arg:
            parser.add_argument(
                "-c", "--config", dest="config_file", help="Defines an alternative config file.", required=True
            )
        if nowait_arg:
            parser.add_argument(
                "-nw",
                "--nowait",
                action="store_true",
                help="Do not wait for stack events after executing stack command.",
            )
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

    @staticmethod
    def _exit_on_http_status(http_response):
        if 200 <= http_response.status_code <= 299:
            sys.exit(0)
        else:
            sys.exit(1)


class CliCommandV3(CliCommand, ABC):  # TODO: remove once all commands are converted
    """Temporary class to identify pcluster v3 commands."""

    pass


class DcvCommand(CliCommand, ABC):
    """Abstract class for DCV CLI commands."""

    pass


def print_json(obj):
    """Print formatted Json to stdout."""
    print(json.dumps(obj, indent=2))


def csv_type(choices):
    """Return a function that splits and checks comma-separated values."""

    def split_arg(arg):
        values = set(token.strip() for token in arg.split(","))
        for value in values:
            if value not in choices:
                raise argparse.ArgumentTypeError(
                    "invalid choice: {!r} (choose from {})".format(value, ", ".join(map(repr, choices)))
                )
        return values

    return split_arg


class ParallelClusterFlaskClient(FlaskClient):
    """ParallelCluster Api client to invoke the WSGI application programmatically."""

    def __init__(self, *args, **kwargs):
        flask_app = ParallelClusterFlaskApp().flask_app
        super().__init__(*args, application=flask_app, response_wrapper=flask_app.response_class, **kwargs)

    def open(self, *args, headers: Dict[str, str] = None, **kwargs):
        """Invoke ParallelCLuster Api functionalities as they were exposed by a HTTP endpoint."""
        default_headers = {
            "Accept": "application/json",
        }
        headers = headers or {}
        return super().open(*args, headers={**default_headers, **headers}, **kwargs)


class Iso8601Arg:
    """Class to validate ISO8601 parameters."""

    def __call__(self, value):
        """Check if the given value is in the ISO8601 format."""
        try:
            isoformat_to_epoch(value)
            return value
        except Exception as e:
            raise argparse.ArgumentTypeError(
                "Start time and end time filters must be in the ISO 8601 format: YYYY-MM-DDThh:mm:ssTZD "
                f"(e.g. 1984-09-15T19:20:30+01:00 or 1984-09-15). {e}"
            )


class GetLogEventsCommand(ABC):
    """Class to put in common code between image and cluster get log events commands."""

    @staticmethod
    def _register_common_command_args(parser: ArgumentParser) -> None:  # noqa: D102
        # Filters
        parser.add_argument(
            "--start-time",
            type=Iso8601Arg(),
            help=(
                "Start time of interval of interest for log events, ISO 8601 format: YYYY-MM-DDThh:mm:ssTZD "
                "(e.g. 1984-09-15T19:20:30+01:00), time elements might be omitted."
            ),
        )
        parser.add_argument(
            "--end-time",
            type=Iso8601Arg(),
            help=(
                "End time of interval of interest for log events, ISO 8601 format: YYYY-MM-DDThh:mm:ssTZD "
                "(e.g. 1984-09-15T19:20:30+01:00), time elements might be omitted. "
            ),
        )
        parser.add_argument("--head", help="Gets the first <head> lines of the log stream.", type=int)
        parser.add_argument("--tail", help="Gets the last <tail> lines of the log stream.", type=int)
        parser.add_argument("--next-token", help="Token for paginated requests.")
        # Stream utilities
        parser.add_argument(
            "--stream",
            help=(
                "Gets the log stream and waits for additional output to be produced. "
                "It can be used in conjunction with --tail to start from the latest <tail> lines of the log stream. "
                "It doesn't work for CloudFormation Stack Events log stream."
            ),
            action="store_true",
        )
        parser.add_argument("--stream-period", help="Sets the streaming period. Default is 5 seconds.", type=int)

    @staticmethod
    def _validate_common_args(args: Namespace):
        if args.head and args.tail:
            utils.error("Parameters validation error: 'tail' and 'head' options cannot be set at the same time")

        if args.stream:
            if args.next_token:
                utils.error(
                    "Parameters validation error: 'stream' and 'next-token' options cannot be set at the same time"
                )
            if args.head:
                utils.error("Parameters validation error: 'stream' and 'head' options cannot be set at the same time")
        else:
            if args.stream_period:
                utils.error("Parameters validation error: 'stream-period' can be used only with 'stream' option")


class ExportLogsCommand(ABC):
    """Class to put in common code between image and cluster export logs commands."""

    @staticmethod
    def _register_common_command_args(parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("--output", help="File path to save log archive to.", type=os.path.realpath)
        # Export options
        parser.add_argument(
            "--bucket-prefix", help="Keypath under which exported logs data will be stored in s3 bucket."
        )
        parser.add_argument(
            "--keep-s3-objects",
            action="store_true",
            help="Keep the exported objects exports to S3. The default behavior is to delete them.",
        )
        # Filters
        parser.add_argument(
            "--start-time",
            type=Iso8601Arg(),
            help=(
                "Start time of interval of interest for log events. ISO 8601 format: YYYY-MM-DDThh:mm:ssTZD "
                "(e.g. 1984-09-15T19:20:30+01:00), time elements might be omitted. Defaults to creation time"
            ),
        )
        parser.add_argument(
            "--end-time",
            type=Iso8601Arg(),
            help=(
                "End time of interval of interest for log events. ISO 8601 format: YYYY-MM-DDThh:mm:ssTZD "
                "(e.g. 1984-09-15T19:20:30+01:00), time elements might be omitted. Defaults to current time"
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
