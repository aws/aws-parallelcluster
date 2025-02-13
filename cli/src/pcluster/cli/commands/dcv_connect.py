# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import logging
import re

# A nosec comment is appended to the following line in order to disable the B404 check.
# In this file the input of the module subprocess is trusted.
import subprocess as sub  # nosec B404
import time
import webbrowser
from typing import List

from argparse import ArgumentParser, Namespace

from pcluster.cli.commands.common import CliCommand
from pcluster.constants import PCLUSTER_ISSUES_LINK
from pcluster.models.cluster import Cluster
from pcluster.utils import error

DCV_CONNECT_SCRIPT = "/opt/parallelcluster/scripts/pcluster_dcv_connect.sh"
LOGGER = logging.getLogger(__name__)
IPV4_REGEX = r"^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])$"


class DCVConnectionError(Exception):
    """Error raised with DCV connection fails."""

    pass


def _check_command_output(cmd):
    # A nosec comment is appended to the following line in order to disable the B602 check.
    # This is done because it's needed to enable the desired functionality. The only caller
    # of this function is _retrieve_dcv_session_url, which passes a command that is safe.
    return sub.check_output(cmd, shell=True, universal_newlines=True, stderr=sub.STDOUT).strip()  # nosec B602 nosemgrep


def _validate_login_node_ip_arg(ip, login_nodes):
    """Check if ip is a valid IPv4 address and belongs to a login node."""
    if not re.match(IPV4_REGEX, ip):
        error(f"{ip} is not a valid IPv4 address.")

    login_node_ips = set()

    for node in login_nodes:
        login_node_ips.update([node.public_ip, node.private_ip])

    if ip not in login_node_ips:
        error(f"{ip} is not an IP address of a login node.")


def _dcv_connect(args):
    """
    Execute pcluster dcv connect command.

    :param args: pcluster cli arguments.
    """
    try:
        cluster = Cluster(args.cluster_name)

        if args.login_node_ip:
            login_nodes = cluster.login_node_instances
            _validate_login_node_ip_arg(args.login_node_ip, login_nodes)

            node_ip = args.login_node_ip
            default_user = login_nodes[0].default_user
        else:
            head_node = cluster.head_node_instance

            node_ip = head_node.public_ip or head_node.private_ip
            default_user = head_node.default_user

    except Exception as e:
        error(f"Unable to connect to the cluster.\n{e}")
    else:

        # Prepare ssh command to execute in the node instance
        cmd = 'ssh {CFN_USER}@{NODE_IP} {KEY} "{REMOTE_COMMAND} /home/{CFN_USER}"'.format(
            CFN_USER=default_user,
            NODE_IP=node_ip,
            KEY="-i {0}".format(args.key_path) if args.key_path else "",
            REMOTE_COMMAND=DCV_CONNECT_SCRIPT,
        )

        try:
            url = _retry(_retrieve_dcv_session_url, func_args=[cmd, args.cluster_name, node_ip], attempts=4)
            url_message = f"Please use the following one-time URL in your browser within 30 seconds:\n{url}"

            if args.show_url:
                print(url_message)
                return

            try:
                if not webbrowser.open_new(url):
                    raise webbrowser.Error("Unable to open the Web browser.")
            except webbrowser.Error as e:
                print(f"{e}\n{url_message}")

        except DCVConnectionError as e:
            error(
                "Something went wrong during DCV connection.\n{0}"
                "Please check the logs in the /var/log/parallelcluster/ folder "
                "of the node and submit an issue {1}\n".format(e, PCLUSTER_ISSUES_LINK)
            )


def _retrieve_dcv_session_url(ssh_cmd, cluster_name, node_ip):
    """Connect by ssh to the head or login node instance, prepare DCV session and return the DCV session URL."""
    try:
        LOGGER.debug("SSH command: %s", ssh_cmd)
        output = _check_command_output(ssh_cmd)
        # At first ssh connection, the ssh command alerts it is adding the host to the known hosts list
        if re.search("Permanently added .* to the list of known hosts.", output):
            output = _check_command_output(ssh_cmd)

        dcv_parameters = re.search(
            r"PclusterDcvServerPort=([\d]+) PclusterDcvSessionId=([\w]+) PclusterDcvSessionToken=([\w-]+)", output
        )
        if dcv_parameters:
            dcv_server_port = dcv_parameters.group(1)
            dcv_session_id = dcv_parameters.group(2)
            dcv_session_token = dcv_parameters.group(3)
        else:
            error(
                "Something went wrong during DCV connection. Please manually execute the command:\n{0}\n"
                "If the problem persists, please check the logs in the /var/log/parallelcluster/ folder "
                "of the node and submit an issue {1}".format(ssh_cmd, PCLUSTER_ISSUES_LINK)
            )

    except sub.CalledProcessError as e:
        if "{0}: No such file or directory".format(DCV_CONNECT_SCRIPT) in e.output:
            error(
                "The cluster {0} has been created with an old version of ParallelCluster "
                "without the DCV support.".format(cluster_name)
            )
        else:
            raise DCVConnectionError(e.output)

    return "https://{IP}:{PORT}?authToken={TOKEN}#{SESSION_ID}".format(
        IP=node_ip,
        PORT=dcv_server_port,  # pylint: disable=E0606
        TOKEN=dcv_session_token,  # pylint: disable=E0606
        SESSION_ID=dcv_session_id,  # pylint: disable=E0606
    )


def _retry(func, func_args, attempts=1, wait=0):  # pylint: disable=R1710
    """
    Call function and re-execute it if it raises an Exception.

    :param func: the function to execute.
    :param func_args: the positional arguments of the function.
    :param attempts: the maximum number of attempts. Default: 1.
    :param wait: delay between attempts. Default: 0.
    :returns: the result of the function.
    """
    while attempts:
        try:
            return func(*func_args)
        except Exception as e:
            attempts -= 1
            if not attempts:
                raise e

            LOGGER.debug("%s, retrying in %s seconds..", e, wait)
            time.sleep(wait)
    return None


class DcvConnectCommand(CliCommand):
    """Implement pcluster dcv connect command."""

    # CLI
    name = "dcv-connect"
    help = "Permits connection to the head or login nodes through an interactive session by using Amazon DCV."
    description = help

    def __init__(self, subparsers):
        super().__init__(subparsers, name=self.name, help=self.help, description=self.description)

    def register_command_args(self, parser: ArgumentParser) -> None:  # noqa: D102
        parser.add_argument("-n", "--cluster-name", help="Name of the cluster to connect to", required=True)
        parser.add_argument("--key-path", dest="key_path", help="Key path of the SSH key to use for the connection")
        parser.add_argument("--show-url", action="store_true", default=False, help="Print URL and exit")
        parser.add_argument("--login-node-ip", dest="login_node_ip", help="IP address of a login node to connect to")

    def execute(self, args: Namespace, extra_args: List[str]) -> None:  # noqa: D102  #pylint: disable=unused-argument
        _dcv_connect(args)
