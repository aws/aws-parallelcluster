#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import logging.config
import os
import sys
from inspect import isabstract
from typing import List

import argparse
from botocore.exceptions import NoCredentialsError

import pcluster.cli.commands.cluster  # noqa: F401
import pcluster.cli.commands.image  # noqa: F401
from pcluster.cli.commands.common import CliCommand, DcvCommand
from pcluster.utils import get_cli_log_file, get_installed_version

LOGGER = logging.getLogger(__name__)


class VersionCommand(CliCommand):
    """Implement pcluster version command."""

    # CLI
    name = "version"
    help = "Displays the version of AWS ParallelCluster."
    description = "Displays the version of AWS ParallelCluster."

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description, region_arg=False)

    def register_command_args(self, parser: argparse.ArgumentParser) -> None:  # noqa: D102
        pass

    def execute(self, args: argparse.Namespace, extra_args: List[str]) -> None:  # noqa: D102
        print(get_installed_version())


class ParallelClusterCli:
    """
    Class representing the ParallelCluster CLI.

    Commands implementing the CliCommand abstract class are automatically discovered and added to the CLI.
    """

    def __init__(self):
        """Initialize ParallelCluster CLI."""
        self._config_logger()
        self._parser = argparse.ArgumentParser(
            description="pcluster is the AWS ParallelCluster CLI and permits "
            "launching and management of HPC clusters in the AWS cloud.",
            epilog='For command specific flags, please run: "pcluster [command] --help"',
        )
        subparsers = self._parser.add_subparsers(dest="command")
        subparsers.required = True
        for command_class in CliCommand.__subclasses__():
            if not isabstract(command_class):
                command_class(subparsers)  # pylint: disable=abstract-class-instantiated

        dcv = subparsers.add_parser(
            "dcv",
            help="The dcv command permits to use NICE DCV related features.",
            epilog='For dcv subcommand specific flags, please run: "pcluster dcv [subcommand] --help"',
        )
        dcv_subparsers = dcv.add_subparsers(dest="command")
        dcv_subparsers.required = True
        for dcv_command_class in DcvCommand.__subclasses__():
            dcv_command_class(dcv_subparsers)

    def handle_command(self):
        """Handle CLI command execution."""
        try:
            args, extra_args = self._parser.parse_known_args()

            if args.debug:
                logging.getLogger("pcluster").setLevel(logging.DEBUG)
            LOGGER.debug("Parsed CLI arguments: args(%s), extra_args(%s)", args, extra_args)

            # TODO: remove this logic from here
            # set region in the environment to make it available to all the boto3 calls
            if "region" in args and args.region:
                os.environ["AWS_DEFAULT_REGION"] = args.region

            if not args.expects_extra_args and extra_args:
                self._parser.print_usage()
                print("Invalid arguments %s" % extra_args)
                sys.exit(1)

            args.func(args, extra_args)
        except NoCredentialsError:  # TODO: remove from here
            LOGGER.error("AWS Credentials not found.")
            sys.exit(1)
        except KeyboardInterrupt:
            LOGGER.debug("Received KeyboardInterrupt. Exiting.")
            sys.exit(1)
        except Exception as e:
            LOGGER.exception("Unexpected error of type %s: %s", type(e).__name__, e)
            sys.exit(1)

    @staticmethod
    def _config_logger():
        logfile = get_cli_log_file()
        logging_config = {
            "version": 1,
            "disable_existing_loggers": True,
            "formatters": {
                "standard": {"format": "%(asctime)s - %(levelname)s - %(module)s - %(message)s"},
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
                "console": {  # TODO: remove console logger
                    "level": "DEBUG",
                    "formatter": "console",
                    "class": "logging.StreamHandler",
                    "stream": sys.stdout,
                },
            },
            "loggers": {
                "": {"handlers": ["default"], "level": "WARNING", "propagate": False},  # root logger
                "pcluster": {"handlers": ["default", "console"], "level": "INFO", "propagate": False},
            },
        }
        os.makedirs(os.path.dirname(logfile), exist_ok=True)
        logging.config.dictConfig(logging_config)


def main():
    ParallelClusterCli().handle_command()


if __name__ == "__main__":
    LOGGER = logging.getLogger("pcluster")
    main()
