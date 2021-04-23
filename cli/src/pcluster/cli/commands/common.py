#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import logging
from abc import ABC, abstractmethod

import argparse

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
            parser.add_argument("-r", "--region", help="AWS Region to use.")
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


class DcvCommand(CliCommand, ABC):
    """Abstract class for DCV CLI commands."""

    pass
