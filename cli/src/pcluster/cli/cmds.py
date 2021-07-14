#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
# pylint: disable=import-outside-toplevel

from typing import List

import argparse

from pcluster import utils
from pcluster.cli.commands.common import CliCommand, print_json


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

    def execute(  # noqa: D102
        self, args: argparse.Namespace, extra_args: List[str]  # pylint: disable=unused-argument
    ) -> None:
        print_json({"version": utils.get_installed_version()})
