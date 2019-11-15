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
from pcluster.dcv.utils import DCV_CONNECT_SCRIPT
from pcluster.utils import (
    PCLUSTER_ISSUES_LINK,
    error,
    get_cfn_param,
    get_master_ip_and_username,
    get_stack,
    get_stack_name,
)

LOGGER = logging.getLogger(__name__)


def _check_command_output(cmd):
    return sub.check_output(cmd, shell=True, universal_newlines=True, stderr=sub.STDOUT).strip()


def dcv_connect(args):
    """
    Execute pcluster dcv connect command.

    :param args: pcluster cli arguments.
    """
    # Parse configuration file to read the AWS section
    PclusterConfig.init_aws()  # FIXME it always searches for the default configuration file

    # Prepare ssh command to execute in the master instance
    stack = get_stack(get_stack_name(args.cluster_name))
    shared_dir = get_cfn_param(stack.get("Parameters"), "SharedDir")
    master_ip, username = get_master_ip_and_username(args.cluster_name)
    cmd = 'ssh {CFN_USER}@{MASTER_IP} {KEY} "{REMOTE_COMMAND} {DCV_SHARED_DIR}"'.format(
        CFN_USER=username,
        MASTER_IP=master_ip,
        KEY="-i {0}".format(args.key_path) if args.key_path else "",
        REMOTE_COMMAND=DCV_CONNECT_SCRIPT,
        DCV_SHARED_DIR=shared_dir,
    )

    # Connect by ssh to the master instance and prepare DCV session
    try:
        LOGGER.debug("SSH command: {0}".format(cmd))
        output = _check_command_output(cmd)
        # At first ssh connection, the ssh command alerts it is adding the host to the known hosts list
        if re.search("Permanently added .* to the list of known hosts.", output):
            output = _check_command_output(cmd)

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
                "of the master instance and submit an issue {1}.".format(cmd, PCLUSTER_ISSUES_LINK)
            )

    except sub.CalledProcessError as e:
        if "{0}: No such file or directory".format(DCV_CONNECT_SCRIPT) in e.output:
            error(
                "The cluster {0} has been created with an old version of ParallelCluster "
                "without the DCV support.".format(args.cluster_name)
            )
        else:
            error("Something went wrong during DCV connection.\n{0}".format(e.output))

    # Open web browser
    url = "https://{IP}:{PORT}?authToken={TOKEN}#{SESSION_ID}".format(
        IP=master_ip, PORT=dcv_server_port, TOKEN=dcv_session_token, SESSION_ID=dcv_session_id
    )
    try:
        webbrowser.open_new(url)
    except webbrowser.Error:
        LOGGER.info(
            "Unable to open the Web browser. "
            "Please use the following URL in your browser within 30 seconds:\n{0}".format(url)
        )
