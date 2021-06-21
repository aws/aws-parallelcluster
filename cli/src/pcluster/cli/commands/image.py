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
from tabulate import tabulate

from pcluster import utils
from pcluster.aws.aws_api import AWSApi
from pcluster.cli.commands.common import CliCommand, Iso8601Arg, validate_output_file_path
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


class ExportImageLogsCommand(CliCommand):
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
        parser.add_argument("image_id", help="Export the logs related to the image id provided here.")
        parser.add_argument("--output", help="File path to save log archive to.", type=os.path.realpath)
        # Export options
        parser.add_argument(
            "--bucket",
            required=True,
            help="S3 bucket to export image builder logs data to. It must be in the same region of the image",
        )
        parser.add_argument(
            "--bucket-prefix",
            help="Keypath under which exported logs data will be stored in s3 bucket. "
            "Also serves as top-level directory in resulting archive.",
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
                "(e.g. 1984-09-15T19:20:30+01:00), time elements might be omitted. Defaults to image build start time"
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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
        try:
            output_file_path = args.output or os.path.realpath(
                f"{args.image_id}-logs-{datetime.now().timestamp()}.tar.gz"
            )
            self._validate_command_args(output_file_path)
            self._export_image_logs(args, output_file_path)
        except Exception as e:
            utils.error(f"Unable to export image's logs.\n{e}")

    @staticmethod
    def _validate_command_args(output_file_path: str):
        validate_output_file_path(output_file_path)

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
    help = "List the logs of the image saved to CloudWatch."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("image_id", help="List the logs of the image id provided here.")
        parser.add_argument("--next-token", help="Token for paginated requests")

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
        try:
            self._list_image_logs(args)
        except Exception as e:
            utils.error(f"Unable to list image's logs.\n{e}")

    @staticmethod
    def _list_image_logs(args: Namespace):
        imagebuilder = ImageBuilder(image_id=args.image_id)
        response = imagebuilder.list_logs(next_token=args.next_token)

        # Print CFN Stack events stream
        if not response.get("stackEventsStream", None):
            print(f"There is no stack associated to the image id {args.image_id}")
        elif not args.next_token:
            print("{}\n".format(tabulate(response.get("stackEventsStream", []), headers="keys", tablefmt="plain")))

        if not response.get("logStreams", None):
            print("There are no cluster's logs saved in CloudWatch.")
        else:
            # List CW log streams
            output_headers = {
                "logStreamName": "Log Stream Name",
                "firstEventTimestamp": "First Event",
                "lastEventTimestamp": "Last Event",
            }
            filtered_result = []
            for item in response.get("logStreams", []):
                filtered_item = {}
                for key, output_key in output_headers.items():
                    value = item.get(key)
                    if key.endswith("Timestamp"):
                        value = utils.timestamp_to_isoformat(value)
                    filtered_item[output_key] = value
                filtered_result.append(filtered_item)
            print(tabulate(filtered_result, headers="keys", tablefmt="plain"))
            if response.get("nextToken", None):
                print("\nnextToken is: %s", response["nextToken"])


class GetImageLogEventsCommand(CliCommand):
    """Implement pcluster get-image-log-events command."""

    # CLI
    name = "get-image-log-events"
    help = "Retrieve the events of a log stream of the image builder saved to CloudWatch."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("image_id", help="Get the log stream of the image id provided here.")
        parser.add_argument(
            "--log-stream-name",
            help="Log stream name, as reported by 'pcluster list-image-logs' command.",
            required=True,
        )
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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
        try:
            self._validate_args(args)
            self._get_image_log_events(args)
        except Exception as e:
            utils.error(f"Unable to get cluster's log events.\n{e}")

    @staticmethod
    def _validate_args(args: Namespace):
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

    def _get_image_log_events(self, args: Namespace):
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
        response = imagebuilder.get_log_events(**kwargs)

        if args.log_stream_name != STACK_EVENTS_LOG_STREAM_NAME:
            # Print log stream events
            self._print_log_events(response.get("events", []), args.stream)
            if args.stream:
                # stream content
                next_token = response.get("nextForwardToken", None)
                while next_token is not None and args.stream:
                    LOGGER.debug("NextToken is %s", next_token)
                    period = args.stream_period or 5
                    LOGGER.debug("Waiting other %s seconds...", period)
                    time.sleep(period)

                    kwargs["next_token"] = next_token
                    response = imagebuilder.get_log_events(**kwargs)
                    next_token = response.get("nextForwardToken", None)
                    self._print_log_events(response.get("events", []), args.stream)
            else:
                LOGGER.info("\nnextBackwardToken is: %s", response["nextBackwardToken"])
                LOGGER.info("nextForwardToken is: %s", response["nextForwardToken"])
        else:
            # Print CFN stack events
            for event in response.get("events", []):
                print(AWSApi.instance().cfn.format_event(event))

    @staticmethod
    def _print_log_events(events: list, stream=None):
        """
        Print given events.

        :param events: list of boto3 events
        """
        if not events:
            message = "No events found."
            if stream:
                LOGGER.debug(message)
            else:
                print(message)
        else:
            for event in events:
                print("{0}: {1}".format(utils.timestamp_to_isoformat(event["timestamp"]), event["message"]))
