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
import re
import textwrap
import time
from datetime import datetime
from typing import List

import argparse
from argparse import ArgumentParser, Namespace

from pcluster import utils
from pcluster.cli.commands.common import CliCommand, ExportLogsCommand, GetLogEventsCommand
from pcluster.constants import STACK_EVENTS_LOG_STREAM_NAME_FORMAT
from pcluster.models.cluster import Cluster

LOGGER = logging.getLogger(__name__)


class SshCommand(CliCommand):
    """Implement pcluster ssh command."""

    # CLI
    name = "ssh"
    help = "Connects to the head node instance using SSH."
    description = (
        "Run ssh command with the cluster username and IP address pre-populated. "
        "Arbitrary arguments are appended to the end of the ssh command."
    )
    epilog = textwrap.dedent(
        """Example::

  $ pcluster ssh mycluster -i ~/.ssh/id_rsa

Returns an ssh command with the cluster username and IP address pre-populated::

  $ ssh ec2-user@1.1.1.1 -i ~/.ssh/id_rsa"""
    )

    def __init__(self, subparsers):
        super().__init__(
            subparsers,
            name=self.name,
            help=self.help,
            description=self.description,
            epilog=self.epilog,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            expects_extra_args=True,
        )

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("cluster_name", help="Name of the cluster to connect to.")
        parser.add_argument("-d", "--dryrun", action="store_true", default=False, help="Prints command and exits.")

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
        from pcluster.cli_commands.commands import ssh

        ssh(args, extra_args)


class ConfigureCommand(CliCommand):
    """Implement pcluster configure command."""

    # CLI
    name = "configure"
    help = "Start the AWS ParallelCluster configuration."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: argparse.ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("-c", "--config", help="Path of the output config file.")

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
        from pcluster.cli_commands.configure.easyconfig import configure

        configure(args)


class DcvConnectCommand(CliCommand):
    """Implement pcluster dcv connect command."""

    # CLI
    name = "dcv-connect"
    help = "Permits to connect to the head node through an interactive session by using NICE DCV."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("cluster_name", help="Name of the cluster to connect to")
        parser.add_argument(
            "--key-path", "-k", dest="key_path", help="Key path of the SSH key to use for the connection"
        )
        parser.add_argument("--show-url", "-s", action="store_true", default=False, help="Print URL and exit")

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
        from pcluster.cli_commands.dcv.connect import dcv_connect

        dcv_connect(args)


class ExportClusterLogsCommand(ExportLogsCommand, CliCommand):
    """Implement pcluster export-cluster-logs command."""

    # CLI
    name = "export-cluster-logs"
    help = "Export the logs of the cluster to a local tar.gz archive by passing through an Amazon S3 Bucket."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("cluster_name", help="Export the logs of the cluster name provided here.")
        # Export options
        parser.add_argument(
            "--bucket",
            required=True,
            help="S3 bucket to export cluster logs data to. It must be in the same region of the cluster",
        )
        super()._register_common_command_args(parser)
        # Filters
        filters_arg = _FiltersArg(accepted_filters=["private-dns-name", "node-type"])
        parser.add_argument(
            "--filters",
            nargs="+",
            type=filters_arg,
            help=(
                "The filters in the form Name=a,Values=1 Name=b,Values=2,3.\nAccepted filters are:\n"
                "private-dns-name - The short form of the private DNS name of the instance (e.g. ip-10-0-0-101).\n"
                "node-type - The node type, the only accepted value for this filter is HeadNode."
            ),
        )

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102 #pylint: disable=unused-argument
        try:
            output_file_path = args.output or os.path.realpath(
                f"{args.cluster_name}-logs-{datetime.now().strftime('%Y%m%d%H%M')}.tar.gz"
            )
            self._validate_output_file_path(output_file_path)
            self._export_cluster_logs(args, output_file_path)
        except Exception as e:
            utils.error(f"Unable to export cluster's logs.\n{e}")

    @staticmethod
    def _export_cluster_logs(args: Namespace, output_file_path: str):
        """Export the logs associated to the cluster."""
        LOGGER.info("Beginning export of logs for the cluster: %s", args.cluster_name)
        cluster = Cluster(args.cluster_name)
        cluster.export_logs(
            output=output_file_path,
            bucket=args.bucket,
            bucket_prefix=args.bucket_prefix,
            keep_s3_objects=args.keep_s3_objects,
            start_time=args.start_time,
            end_time=args.end_time,
            filters=" ".join(args.filters) if args.filters else None,
        )
        LOGGER.info("Cluster's logs exported correctly to %s", output_file_path)


class ListClusterLogsCommand(CliCommand):
    """Implement pcluster list-cluster-logs command."""

    # CLI
    name = "list-cluster-logs"
    help = "List the log streams associated to a cluster."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("cluster_name", help="List the logs of the cluster name provided here.")
        # Filters
        filters_arg = _FiltersArg(accepted_filters=["private-dns-name", "node-type"])
        parser.add_argument(
            "--filters",
            nargs="+",
            type=filters_arg,
            help=(
                "The filters in the form Name=a,Values=1 Name=b,Values=2,3.\nAccepted filters are:\n"
                "private-dns-name - The short form of the private DNS name of the instance (e.g. ip-10-0-0-101).\n"
                "node-type - The node type, the only accepted value for this filter is HeadNode."
            ),
        )
        parser.add_argument("--next-token", help="Token for paginated requests")

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102 #pylint: disable=unused-argument
        try:
            self._list_cluster_logs(args)
        except Exception as e:
            utils.error(f"Unable to list cluster's logs.\n{e}")

    @staticmethod
    def _list_cluster_logs(args: Namespace):
        cluster = Cluster(args.cluster_name)
        logs = cluster.list_logs(filters=" ".join(args.filters) if args.filters else None, next_token=args.next_token)
        if not args.next_token:
            logs.print_stack_log_streams()
        logs.print_cw_log_streams()


class _FiltersArg:
    """Class to implement regex parsing for filters parameter."""

    def __init__(self, accepted_filters: list):
        filter_regex = rf"Name=({'|'.join(accepted_filters)}),Values=[\w\-_.,]+"
        self._pattern = re.compile(fr"^({filter_regex})(\s+{filter_regex})*$")

    def __call__(self, value):
        if not self._pattern.match(value):
            raise argparse.ArgumentTypeError(f"filters parameter must be in the form {self._pattern.pattern} ")
        return value


class GetClusterLogEventsCommand(GetLogEventsCommand, CliCommand):
    """Implement pcluster get-cluster-log-events command."""

    # CLI
    name = "get-cluster-log-events"
    help = "Retrieve the events of a log stream of the cluster."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("cluster_name", help="Get the log stream of the cluster name provided here.")
        parser.add_argument(
            "--log-stream-name",
            help="Log stream name, as reported by 'pcluster list-cluster-logs' command.",
            required=True,
        )
        super()._register_common_command_args(parser)

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102 #pylint: disable=unused-argument
        try:
            self._validate_common_args(args)
            self._get_cluster_log_events(args)
        except Exception as e:
            utils.error(f"Unable to get cluster's log events.\n{e}")

    @staticmethod
    def _get_cluster_log_events(args: Namespace):
        """Get log events for a specific log stream of the cluster saved in CloudWatch."""
        kwargs = {
            "log_stream_name": args.log_stream_name,
            "start_time": args.start_time,
            "end_time": args.end_time,
            "start_from_head": args.head is not None,
            "limit": args.head or args.tail or None,
            "next_token": args.next_token,
        }
        cluster = Cluster(args.cluster_name)
        log_events = cluster.get_log_events(**kwargs)

        log_events.print_events()
        if args.stream and args.log_stream_name != STACK_EVENTS_LOG_STREAM_NAME_FORMAT.format(cluster.stack_name):
            # stream content
            next_token = log_events.next_ftoken
            while next_token is not None:
                period = args.stream_period or 5
                LOGGER.debug("Waiting other %s seconds...", period)
                time.sleep(period)

                kwargs["next_token"] = next_token
                log_events = cluster.get_log_events(**kwargs)
                next_token = log_events.next_ftoken
                log_events.print_events()
        else:
            log_events.print_next_tokens()
