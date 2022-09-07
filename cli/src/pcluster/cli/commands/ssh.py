# Copyright 2013-2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
# FIXME
# pylint: disable=too-many-locals
# pylint: disable=too-many-branches
# pylint: disable=too-many-statements

import json
import logging
import os
import textwrap
from builtins import str
from functools import partial
from typing import List

import argparse
from argparse import ArgumentParser, Namespace

from pcluster import utils
from pcluster.cli.commands.common import CliCommand, to_bool
from pcluster.models.cluster import Cluster

LOGGER = logging.getLogger(__name__)


def _ssh(args, extra_args):
    # pylint: disable=import-outside-toplevel
    """
    Execute an SSH command to the head node instance, according to the [aliases] section if there.

    :param args: pcluster CLI args
    :param extra_args: pcluster CLI extra_args
    """
    try:
        from shlex import quote as cmd_quote
    except ImportError:
        from pipes import quote as cmd_quote

    try:
        head_node = Cluster(args.cluster_name).head_node_instance
    except Exception as e:
        utils.error(f"Unable to connect to the cluster {args.cluster_name}.\n{e}")
    else:
        # build command
        cmd = "ssh {CFN_USER}@{HEAD_NODE_IP} {ARGS}".format(
            CFN_USER=head_node.default_user,
            HEAD_NODE_IP=head_node.public_ip or head_node.private_ip,
            ARGS=" ".join(cmd_quote(str(arg)) for arg in extra_args),
        )

        # run command
        if not args.dryrun:
            LOGGER.debug("SSH command: %s", cmd)
            # A nosec comment is appended to the following line in order to disable the B605 check.
            # This check is disabled for the following reasons:
            # - The args passed to the remote command are sanitized.
            # - The default command to which these args is known.
            # - Users have full control over any customization of the command to which args are passed.
            os.system(cmd)  # nosec nosemgrep
        else:
            print(json.dumps({"command": cmd}, indent=2))


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
        """Example:

  pcluster ssh --cluster-name mycluster -i ~/.ssh/id_rsa

Returns an ssh command with the cluster username and IP address pre-populated:

  ssh ec2-user@1.1.1.1 -i ~/.ssh/id_rsa"""
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
        parser.add_argument("-n", "--cluster-name", help="Name of the cluster to connect to.", required=True)
        parser.add_argument(
            "--dryrun",
            default=False,
            type=partial(to_bool, "dryrun"),
            help="Prints command and exits (defaults to 'false').",
        )

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102
        _ssh(args, extra_args)
