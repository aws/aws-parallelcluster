# Copyright 2013-2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the 'License'). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the 'LICENSE.txt' file accompanying this file. This file is distributed on an 'AS IS' BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
# pylint: disable=import-outside-toplevel

from typing import List

import argparse
from argparse import Namespace

from pcluster.cli.commands.common import CliCommand


class ConfigureCommand(CliCommand):
    """Implement pcluster configure command."""

    # CLI
    name = "configure"
    help = "Start the AWS ParallelCluster configuration."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: argparse.ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("-c", "--config", help="Path to output the generated config file.", required=True)

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
        from pcluster.cli.commands.configure.easyconfig import configure

        configure(args)
