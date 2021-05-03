#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.

# pylint: disable=import-outside-toplevel

import logging
import textwrap
from typing import List

import argparse
from argparse import ArgumentParser, Namespace

from pcluster.cli.commands.common import CliCommand, DcvCommand
from pcluster.constants import PCLUSTER_STACK_PREFIX
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
        parser.add_argument(
            "cluster_name",
            help="Defines the name of the cluster. The CloudFormation stack name will be "
            f"{PCLUSTER_STACK_PREFIX}[cluster_name]",
        )
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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
        from pcluster.cli_commands.commands import status

        status(args)


class ListClustersCommand(CliCommand):
    """Implement pcluster list command."""

    # CLI
    name = "list"
    help = "Displays a list of stacks associated with AWS ParallelCluster."
    description = help
    epilog = f"This command lists the names of any CloudFormation stacks named {PCLUSTER_STACK_PREFIX}*"

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description, epilog=self.epilog)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("--color", action="store_true", default=False, help="Display the cluster status in color.")

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
        from pcluster.cli_commands.commands import list_clusters

        list_clusters(args)


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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
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

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
        from pcluster.cli_commands.dcv.connect import dcv_connect

        dcv_connect(args)
