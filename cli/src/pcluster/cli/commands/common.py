#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import json
import logging
import sys
from abc import ABC, abstractmethod
from typing import Dict

import argparse
from flask.testing import FlaskClient

from pcluster.api.flask_app import ParallelClusterFlaskApp
from pcluster.constants import SUPPORTED_REGIONS

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
            parser.add_argument("-c", "--config", dest="config_file", help="Defines an alternative config file.")
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
