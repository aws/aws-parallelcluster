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
from tabulate import tabulate

from pcluster import utils
from pcluster.api.models.cluster_status import ClusterStatusEnum
from pcluster.aws.aws_api import AWSApi
from pcluster.cli.commands.common import (
    CliCommand,
    CliCommandV3,
    DcvCommand,
    ParallelClusterFlaskClient,
    csv_type,
    print_json,
)
from pcluster.constants import PCLUSTER_VERSION_TAG
from pcluster.models.cluster import Cluster
from pcluster.validators.common import FailureLevel

LOGGER = logging.getLogger(__name__)


class CreateClusterCommand(CliCommand):
    """Implement pcluster create command."""

    # CLI
    name = "create"
    help = "Creates a new cluster."
    description = help

    def __init__(self, subparsers):
        super().__init__(
            subparsers, name=self.name, help=self.help, description=self.description, config_arg=True, nowait_arg=True
        )

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("cluster_name", help="Defines the name of the cluster")
        parser.add_argument(
            "--disable-update-check",
            action="store_true",
            default=False,
            help="Disable check for ParallelCluster updates.",
        )
        parser.add_argument(
            "--suppress-validators", action="store_true", default=False, help="Disable validators execution."
        )
        parser.add_argument(
            "--validation-failure-level",
            type=self._failure_level_type,
            choices=list(FailureLevel),
            default=FailureLevel.ERROR.name,
            help="Min validation level that will cause the creation to fail.",
        )
        parser.add_argument(
            "-nr", "--norollback", action="store_true", default=False, help="Disables stack rollback on error."
        )
        parser.add_argument(
            "-u",
            "--template-url",
            help="Specifies the URL for a custom CloudFormation template, if it was used at creation time.",
        )

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
        from pcluster.cli_commands.commands import create

        create(args)

    @staticmethod
    def _failure_level_type(failure_level_string):
        try:
            return FailureLevel[failure_level_string.upper()]
        except KeyError:
            raise argparse.ArgumentTypeError(f"invalid value '{failure_level_string}'")


class UpdateClusterCommand(CliCommand):
    """Implement pcluster update command."""

    # CLI
    name = "update"
    help = "Updates a running cluster using the values in the config file."
    description = help

    def __init__(self, subparsers):
        super().__init__(
            subparsers, name=self.name, help=self.help, description=self.description, config_arg=True, nowait_arg=True
        )

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("cluster_name", help="Names the cluster to update.")
        parser.add_argument(
            "-nr",
            "--norollback",
            action="store_true",
            default=False,
            help="Disable CloudFormation stack rollback on error.",
        )
        parser.add_argument(
            "--suppress-validators", action="store_true", default=False, help="Disable validators execution."
        )
        parser.add_argument(
            "-f", "--force", action="store_true", help="Forces the update skipping security checks. Not recommended."
        )

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
        from pcluster.cli_commands import update

        update.execute(args)


class DeleteClusterCommand(CliCommand):
    """Implement pcluster delete command."""

    # CLI
    name = "delete"
    help = "Deletes a cluster."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description, nowait_arg=True)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("cluster_name", help="Names the cluster to delete.")
        parser.add_argument(
            "--keep-logs",
            action="store_true",
            help="Keep cluster's CloudWatch log group data after deleting. The log group will persist until it's "
            "deleted manually, but log events will still expire based on the previously configured retention time",
        )

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
        from pcluster.cli_commands.commands import delete

        delete(args)


class StartClusterCommand(CliCommand):
    """Implement pcluster start command."""

    # CLI
    name = "start"
    help = "Starts the compute fleet for a cluster that has been stopped."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("cluster_name", help="Starts the compute fleet of the cluster name provided here.")

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
        from pcluster.cli_commands.commands import start

        start(args)


class StopClusterCommand(CliCommand):
    """Implement pcluster stop command."""

    # CLI
    name = "stop"
    help = "Stops the compute fleet, leaving the head node running."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("cluster_name", help="Stops the compute fleet of the cluster name provided here.")

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
        from pcluster.cli_commands.commands import stop

        stop(args)


class ClusterStatusCommand(CliCommand):
    """Implement pcluster status command."""

    # CLI
    name = "status"
    help = "Displays the current status of the cluster."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description, nowait_arg=True)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("cluster_name", help="Shows the status of the cluster with the name provided here.")

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
        from pcluster.cli_commands.commands import status

        status(args)


class ListClustersCommandV2(CliCommand):  # TODO: to be removed
    """Implement pcluster list command."""

    # CLI
    name = "list"
    help = "Displays a list of stacks created by AWS ParallelCluster."
    description = help
    epilog = f"This command lists the names of any CloudFormation stacks with tag {PCLUSTER_VERSION_TAG}"

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description, epilog=self.epilog)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("--color", action="store_true", default=False, help="Display the cluster status in color.")

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
        from pcluster.cli_commands.commands import list_clusters

        list_clusters(args)


class ListClustersCommand(CliCommandV3):
    """Implement pcluster list-clusters command."""

    # CLI
    name = "list-clusters"
    help = "Retrieves the list of existing AWS ParallelCluster clusters."
    description = help
    # HTTP API
    method = "GET"
    url = "/v3/clusters"

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        cluster_status_values = [e.value for e in ClusterStatusEnum]

        parser.add_argument("--next-token", help="Token for paginated requests")
        parser.add_argument(
            "--cluster-status",
            type=csv_type(cluster_status_values),
            help=f"Comma separated status values to filter by. Available values are {cluster_status_values}",
        )

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
        query_string = [
            ("region", args.region),
            ("nextToken", args.next_token),
        ]
        if args.cluster_status:
            query_string.extend([("clusterStatus", status) for status in args.cluster_status])
        with ParallelClusterFlaskClient() as client:
            response = client.open(self.url, method=self.method, query_string=query_string)
        print_json(response.get_json())
        self._exit_on_http_status(response)


class InstancesCommand(CliCommand):
    """Implement pcluster instances command."""

    # CLI
    name = "instances"
    help = "Displays a list of all instances in a cluster."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("cluster_name", help="Display the instances for the cluster with the name provided here.")

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
        from pcluster.cli_commands.commands import instances

        instances(args)


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


class DcvConnectCommand(DcvCommand):
    """Implement pcluster dcv connect command."""

    # CLI
    name = "connect"
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


class ExportClusterLogsCommand(CliCommand):
    """Implement pcluster export-cluster-logs command."""

    # CLI
    name = "export-cluster-logs"
    help = "Export the logs of the cluster to a local tar.gz archive by passing through an Amazon S3 Bucket."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("cluster_name", help="Export the logs of the cluster name provided here.")
        parser.add_argument("--output", help="File path to save log archive to.", type=os.path.realpath)
        # Export options
        parser.add_argument(
            "--bucket",
            required=True,
            help="S3 bucket to export cluster logs data to. It must be in the same region of the cluster",
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
            help=(
                "Start time of interval of interest for log events. ISO 8601 format: YYYY-MM-DDThh:mm:ssTZD "
                "(e.g. 1984-09-15T19:20:30+01:00), time elements might be omitted. Defaults to cluster's start time"
            ),
        )
        parser.add_argument(
            "--end-time",
            help=(
                "End time of interval of interest for log events. ISO 8601 format: YYYY-MM-DDThh:mm:ssTZD "
                "(e.g. 1984-09-15T19:20:30+01:00), time elements might be omitted. Defaults to current time"
            ),
        )
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
                f"{args.cluster_name}-logs-{datetime.now().timestamp()}.tar.gz"
            )
            self._validate_command_args(output_file_path)
            self._export_cluster_logs(args, output_file_path)
        except Exception as e:
            utils.error(f"Unable to export cluster's logs.\n{e}")

    @staticmethod
    def _validate_command_args(output_file_path: str):
        # Verify that a file can be written to the given path
        file_dir = os.path.dirname(output_file_path)
        if not os.path.isdir(file_dir):
            try:
                os.makedirs(file_dir)
            except Exception as e:
                utils.error(f"Failed to create parent directory {file_dir} for cluster's logs archive. Reason: {e}")
        if not os.access(file_dir, os.W_OK):
            utils.error(f"Cannot write cluster's log archive to {output_file_path}. {file_dir} is not writeable.")

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
    help = "List the logs of the cluster saved to CloudWatch."
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
        response = cluster.list_logs(
            filters=" ".join(args.filters) if args.filters else None,
            next_token=args.next_token,
        )
        # Print CFN Stack events stream
        if not args.next_token:
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


class _FiltersArg:
    """Class to implement regex parsing for filters parameter."""

    def __init__(self, accepted_filters: list):
        filter_regex = rf"Name=({'|'.join(accepted_filters)}),Values=[\w\-_.,]+"
        self._pattern = re.compile(fr"^({filter_regex})(\s+{filter_regex})*$")

    def __call__(self, value):
        if not self._pattern.match(value):
            raise argparse.ArgumentTypeError(f"filters parameter must be in the form {self._pattern.pattern} ")
        return value


class GetClusterLogEventsCommand(CliCommand):
    """Implement pcluster get-cluster-log-events command."""

    # CLI
    name = "get-cluster-log-events"
    help = "Retrieve the events of a log stream of the cluster saved to CloudWatch."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("cluster_name", help="Get the log stream of the cluster name provided here.")
        parser.add_argument(
            "--log-stream-name",
            help="Log stream name, as reported by 'pcluster list-cluster-logs' command",
            required=True,
        )
        # Filters
        parser.add_argument(
            "--start-time",
            help=(
                "Start time of interval of interest for log events, "
                "expressed as the number of milliseconds after Jan 1, 1970 00:00:00 UTC."
            ),
            type=int,
        )
        parser.add_argument(
            "--end-time",
            help=(
                "End time of interval of interest for log events, "
                "expressed as the number of milliseconds after Jan 1, 1970 00:00:00 UTC."
            ),
            type=int,
        )
        parser.add_argument("--head", help="Gets the first <head> lines of the log stream", type=int)
        parser.add_argument("--tail", help="Gets the last <tail> lines of the log stream", type=int)
        parser.add_argument("--next-token", help="Token for paginated requests")
        # Stream utilities
        parser.add_argument(
            "--stream",
            help="Gets the log stream and waits for additional output to be produced. "
            "It can be used in conjunction with --tail to start from the "
            "latest <tail> lines of the log stream",
            action="store_true",
        )
        parser.add_argument("--stream-period", help="Sets the streaming period. Default is 5 seconds", type=int)

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102 #pylint: disable=unused-argument
        try:
            self._validate_args(args)
            self._get_cluster_log_events(args)
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

    def _get_cluster_log_events(self, args: Namespace):
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
        response = cluster.get_log_events(**kwargs)

        if args.log_stream_name != Cluster.STACK_EVENTS_LOG_STREAM_NAME:
            # Print log stream events
            self._print_log_events(response.get("events", []))
            if args.stream:
                # stream content
                next_token = response.get("nextForwardToken", None)
                while next_token is not None and args.stream:
                    LOGGER.debug("NextToken is %s", next_token)
                    period = args.stream_period or 5
                    LOGGER.debug("Waiting other %s seconds...", period)
                    time.sleep(period)

                    kwargs["next_token"] = next_token
                    result = cluster.get_log_events(**kwargs)
                    next_token = result.get("nextForwardToken", None)
                    self._print_log_events(result.get("events", []))
            else:
                LOGGER.info("\nnextBackwardToken is: %s", response["nextBackwardToken"])
                LOGGER.info("nextForwardToken is: %s", response["nextForwardToken"])
        else:
            # Print CFN stack events
            for event in response.get("events", []):
                print(AWSApi.instance().cfn.format_event(event))

    @staticmethod
    def _print_log_events(events: list):
        """
        Print given events.

        :param events: list of boto3 events
        """
        if not events:
            print("No events found.")
        else:
            for event in events:
                print("{0}: {1}".format(utils.timestamp_to_isoformat(event["timestamp"]), event["message"]))
