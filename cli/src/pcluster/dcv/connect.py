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
import time
import webbrowser

from api.pcluster_api import FullClusterInfo, PclusterApi
from pcluster.constants import PCLUSTER_ISSUES_LINK
from pcluster.dcv.utils import DCV_CONNECT_SCRIPT
from pcluster.utils import error, get_region

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
    result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=get_region())
    if isinstance(result, FullClusterInfo):
        # Prepare ssh command to execute in the head node instance
        cmd = 'ssh {CFN_USER}@{HEAD_NODE_IP} {KEY} "{REMOTE_COMMAND} /home/{CFN_USER}"'.format(
            CFN_USER=result.user,
            HEAD_NODE_IP=result.head_node_ip,
            KEY="-i {0}".format(args.key_path) if args.key_path else "",
            REMOTE_COMMAND=DCV_CONNECT_SCRIPT,
        )

        try:
            url = _retry(_retrieve_dcv_session_url, func_args=[cmd, args.cluster_name, result.head_node_ip], attempts=4)
            url_message = "Please use the following one-time URL in your browser within 30 seconds:\n{0}".format(url)

            if args.show_url:
                LOGGER.info(url_message)
                return

            try:
                if not webbrowser.open_new(url):
                    raise webbrowser.Error("Unable to open the Web browser.")
            except webbrowser.Error as e:
                LOGGER.info("{0}\n{1}".format(e, url_message))

        except DCVConnectionError as e:
            error(
                "Something went wrong during DCV connection.\n{0}"
                "Please check the logs in the /var/log/parallelcluster/ folder "
                "of the head node and submit an issue {1}\n".format(e, PCLUSTER_ISSUES_LINK)
            )
    else:
        error(f"Unable to connect to the cluster.\n{result.message}")


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


def _retry(func, func_args, attempts=1, wait=0):
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

            LOGGER.debug("{0}, retrying in {1} seconds..".format(e, wait))
            time.sleep(wait)
