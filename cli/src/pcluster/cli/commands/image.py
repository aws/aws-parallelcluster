#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.

# pylint: disable=import-outside-toplevel

import logging
from typing import List

from argparse import ArgumentParser, Namespace

from pcluster.cli.commands.common import CliCommand

LOGGER = logging.getLogger(__name__)


class BuildImageCommand(CliCommand):
    """Implement pcluster build-image command."""

    # CLI
    name = "build-image"
    help = "Creates a custom AMI to use with AWS ParallelCluster."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description, config_arg=True)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument(
            "-i",
            "--id",
            dest="id",
            required=True,
            help="Specifies the id to use for building the AWS ParallelCluster Image.",
        )

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
        from pcluster.cli_commands.commands import build_image

        build_image(args)


class DeleteImageCommand(CliCommand):
    """Implement pcluster delete-image command."""

    # CLI
    name = "delete-image"
    help = "Deletes an image and related image builder stack."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument(
            "-i", "--id", dest="id", required=True, help="Id of the AWS ParallelCluster Image to delete."
        )
        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            help="Force EC2 AMI deletion even if AMI is shared or instance is using it.",
        )

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
        from pcluster.cli_commands.commands import delete_image

        delete_image(args)


class DescribeImageCommand(CliCommand):
    """Implement pcluster describe-image command."""

    # CLI
    name = "describe-image"
    help = "Describes the specified ParallelCluster image."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument(
            "-i", "--id", dest="id", required=True, help="Id of the AWS ParallelCluster Image to describe."
        )

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
        from pcluster.cli_commands.commands import describe_image

        describe_image(args)


class ListImagesCommand(CliCommand):
    """Implement pcluster list-images command."""

    # CLI
    name = "list-images"
    help = (
        "Displays a list of images built by AWS ParallelCluster in a given AWS region associated with "
        "status and version."
    )
    description = help
    epilog = (
        "This command lists the name, status and version of images built by AWS ParallelCluster in a given "
        "AWS region."
    )

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description, epilog=self.epilog)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("--color", action="store_true", default=False, help="Display the image status in color.")

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
        from pcluster.cli_commands.commands import list_images

        list_images(args)
