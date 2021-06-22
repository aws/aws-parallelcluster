#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.

# pylint: disable=import-outside-toplevel
import logging
import os
import time
from datetime import datetime
from typing import List

from argparse import ArgumentParser, Namespace

from pcluster import utils
from pcluster.cli.commands.common import CliCommand, ExportLogsCommand, GetLogEventsCommand
from pcluster.constants import STACK_EVENTS_LOG_STREAM_NAME
from pcluster.models.imagebuilder import ImageBuilder

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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
        from pcluster.cli_commands.commands import list_images

        list_images(args)


class ExportImageLogsCommand(ExportLogsCommand, CliCommand):
    """Implement pcluster export-image-logs command."""

    # CLI
    name = "export-image-logs"
    help = (
        "Export the logs of the image builder stack to a local tar.gz archive by passing through an Amazon S3 Bucket."
    )
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        super()._register_common_command_args(parser)
        parser.add_argument("image_id", help="Export the logs related to the image id provided here.")
        # Export options
        parser.add_argument(
            "--bucket",
            required=True,
            help="S3 bucket to export image builder logs data to. It must be in the same region of the image",
        )

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102 #pylint: disable=unused-argument
        try:
            output_file_path = args.output or os.path.realpath(
                f"{args.image_id}-logs-{datetime.now().timestamp()}.tar.gz"
            )
            self._validate_output_file_path(output_file_path)
            self._export_image_logs(args, output_file_path)
        except Exception as e:
            utils.error(f"Unable to export image's logs.\n{e}")

    @staticmethod
    def _export_image_logs(args: Namespace, output_file_path: str):
        """Export the logs associated to the image."""
        LOGGER.info("Beginning export of logs for the image: %s", args.image_id)

        # retrieve imagebuilder config and generate model
        imagebuilder = ImageBuilder(image_id=args.image_id)
        imagebuilder.export_logs(
            output=output_file_path,
            bucket=args.bucket,
            bucket_prefix=args.bucket_prefix,
            keep_s3_objects=args.keep_s3_objects,
            start_time=args.start_time,
            end_time=args.end_time,
        )
        LOGGER.info("Image's logs exported correctly to %s", output_file_path)


class ListImageLogsCommand(CliCommand):
    """Implement pcluster list-image-logs command."""

    # CLI
    name = "list-image-logs"
    help = "List the logs of the CloudFormation Stack and Image Builder process related associated to an image id."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("image_id", help="List the logs of the image id provided here.")
        parser.add_argument("--next-token", help="Token for paginated requests")

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102 #pylint: disable=unused-argument
        try:
            self._list_image_logs(args)
        except Exception as e:
            utils.error(f"Unable to list image's logs.\n{e}")

    @staticmethod
    def _list_image_logs(args: Namespace):
        imagebuilder = ImageBuilder(image_id=args.image_id)
        logs = imagebuilder.list_logs(next_token=args.next_token)
        logs.print_stack_log_streams()
        logs.print_cw_log_streams()


class GetImageLogEventsCommand(GetLogEventsCommand, CliCommand):
    """Implement pcluster get-image-log-events command."""

    # CLI
    name = "get-image-log-events"
    help = "Retrieve the events of a log stream of the image."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        super()._register_common_command_args(parser)
        parser.add_argument("image_id", help="Get the log stream of the image id provided here.")
        parser.add_argument(
            "--log-stream-name",
            help="Log stream name, as reported by 'pcluster list-image-logs' command.",
            required=True,
        )

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102 #pylint: disable=unused-argument
        try:
            self._validate_common_args(args)
            self._get_image_log_events(args)
        except Exception as e:
            utils.error(f"Unable to get cluster's log events.\n{e}")

    @staticmethod
    def _get_image_log_events(args: Namespace):
        """Get log events for a specific log stream of the image saved in CloudWatch."""
        kwargs = {
            "log_stream_name": args.log_stream_name,
            "start_time": args.start_time,
            "end_time": args.end_time,
            "start_from_head": args.head is not None,
            "limit": args.head or args.tail or None,
            "next_token": args.next_token,
        }
        imagebuilder = ImageBuilder(image_id=args.image_id)
        log_events = imagebuilder.get_log_events(**kwargs)

        log_events.print_events()
        if args.stream and args.log_stream_name != STACK_EVENTS_LOG_STREAM_NAME:
            # stream content
            next_token = log_events.next_ftoken
            while next_token is not None:
                period = args.stream_period or 5
                LOGGER.debug("Waiting other %s seconds...", period)
                time.sleep(period)

                kwargs["next_token"] = next_token
                log_events = imagebuilder.get_log_events(**kwargs)
                next_token = log_events.next_ftoken
                log_events.print_events()
        else:
            log_events.print_next_tokens()
