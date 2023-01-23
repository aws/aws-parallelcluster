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

from pcluster import utils
from pcluster.api.controllers.common import assert_supported_operation
from pcluster.aws.common import get_region
from pcluster.cli.commands.common import CliCommand, ExportLogsCommand
from pcluster.constants import Operation
from pcluster.models.imagebuilder import ImageBuilder

LOGGER = logging.getLogger(__name__)


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
        parser.add_argument(
            "-i", "--image-id", help="Export the logs related to the image id provided here.", required=True
        )
        # Export options
        parser.add_argument(
            "--bucket",
            required=True,
            help="S3 bucket to export image builder logs data to. It must be in the same region of the image",
        )
        # Export options
        parser.add_argument(
            "--bucket-prefix",
            help="Keypath under which exported logs data will be stored in s3 bucket. Defaults to "
            "<image_id>-logs-<current time in the format of yyyyMMddHHmm>",
        )

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102 #pylint: disable=unused-argument
        assert_supported_operation(operation=Operation.EXPORT_IMAGE_LOGS, region=args.region or get_region())
        try:
            if args.output_file:
                self._validate_output_file_path(args.output_file)
            return self._export_image_logs(args, args.output_file)
        except Exception as e:
            utils.error(f"Unable to export image's logs.\n{e}")
            return None

    @staticmethod
    def _export_image_logs(args: Namespace, output_file: str = None):
        """Export the logs associated to the image."""
        LOGGER.debug("Beginning export of logs for the image: %s", args.image_id)

        # retrieve imagebuilder config and generate model
        imagebuilder = ImageBuilder(image_id=args.image_id)
        url = imagebuilder.export_logs(
            bucket=args.bucket,
            bucket_prefix=args.bucket_prefix,
            keep_s3_objects=args.keep_s3_objects,
            start_time=args.start_time,
            end_time=args.end_time,
            output_file=output_file,
        )
        LOGGER.debug("Image's logs exported correctly to %s", url)
        return {"path": output_file} if output_file else {"url": url}
