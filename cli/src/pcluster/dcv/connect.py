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
import subprocess as sub
import webbrowser

from pcluster.config.pcluster_config import PclusterConfig
from pcluster.constants import PCLUSTER_ISSUES_LINK
from pcluster.dcv.utils import DCV_CONNECT_SCRIPT
from pcluster.utils import error, get_cfn_param, get_head_node_ip_and_username, get_stack, get_stack_name, retry

LOGGER = logging.getLogger(__name__)


class DCVConnectionError(Exception):
    """Error raised with DCV connection fails."""

    pass


def _check_command_output(cmd):
    return sub.check_output(cmd, shell=True, universal_newlines=True, stderr=sub.STDOUT).strip()


def dcv_connect(args):
    """
    Execute pcluster dcv connect command.

    :param args: pcluster cli arguments.
    """
    # Parse configuration file to read the AWS section
    PclusterConfig.init_aws()  # FIXME it always searches for the default configuration file

    # Prepare ssh command to execute in the head node instance
    stack = get_stack(get_stack_name(args.cluster_name))
    shared_dir = get_cfn_param(stack.get("Parameters"), "SharedDir")
    head_node_ip, username = get_head_node_ip_and_username(args.cluster_name)
    cmd = 'ssh {CFN_USER}@{HEAD_NODE_IP} {KEY} "{REMOTE_COMMAND} {DCV_SHARED_DIR}"'.format(
        CFN_USER=username,
        HEAD_NODE_IP=head_node_ip,
        KEY="-i {0}".format(args.key_path) if args.key_path else "",
        REMOTE_COMMAND=DCV_CONNECT_SCRIPT,
        DCV_SHARED_DIR=shared_dir,
    )

    try:
        url = retry(_retrieve_dcv_session_url, func_args=[cmd, args.cluster_name, head_node_ip], attempts=4)
        url_message = "Please use the following one-time URL in your browser within 30 seconds:\n{0}".format(url)
    except DCVConnectionError as e:
        error(
            "Something went wrong during DCV connection.\n{0}"
            "Please check the logs in the /var/log/parallelcluster/ folder "
            "of the head node and submit an issue {1}\n".format(e, PCLUSTER_ISSUES_LINK)
        )

    if args.show_url:
        LOGGER.info(url_message)
        return

    try:
        if not webbrowser.open_new(url):
            raise webbrowser.Error("Unable to open the Web browser.")
    except webbrowser.Error as e:
        LOGGER.info("{0}\n{1}".format(e, url_message))


def _retrieve_dcv_session_url(ssh_cmd, cluster_name, head_node_ip):
    """Connect by ssh to the head node instance, prepare DCV session and return the DCV session URL."""
    try:
        LOGGER.debug("SSH command: {0}".format(ssh_cmd))
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
                "of the head node and submit an issue {1}".format(ssh_cmd, PCLUSTER_ISSUES_LINK)
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
        IP=head_node_ip, PORT=dcv_server_port, TOKEN=dcv_session_token, SESSION_ID=dcv_session_id
    )
