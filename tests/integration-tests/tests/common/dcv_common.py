# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
"""Shared helpers to launch DCV sessions and validate the DCV external authenticator."""

import logging
import re

from assertpy import assert_that

DCV_CONNECT_SCRIPT = "/opt/parallelcluster/scripts/pcluster_dcv_connect.sh"
DCV_SERVER_URL = "https://localhost"

# Output emitted by the DCV connect script, e.g.:
#   PclusterDcvServerPort=8443 PclusterDcvSessionId=mysession PclusterDcvSessionToken=<token>
_DCV_SESSION_REGEX = r"PclusterDcvServerPort=([\d]+) PclusterDcvSessionId=([\w]+) PclusterDcvSessionToken=([\w-]+)"


def start_dcv_session(remote_command_executor, shared_dir):
    """Run the DCV connect script and return (server_port, session_id, session_token)."""
    command_execution = remote_command_executor.run_remote_command(f"{DCV_CONNECT_SCRIPT} {shared_dir}")
    dcv_parameters = re.search(_DCV_SESSION_REGEX, command_execution.stdout)
    assert_that(dcv_parameters).described_as(
        "Command '{0} {1}' failed, output: {2}, error: {3}".format(
            DCV_CONNECT_SCRIPT, shared_dir, command_execution.stdout, command_execution.stderr
        )
    ).is_not_none()
    return dcv_parameters.group(1), dcv_parameters.group(2), dcv_parameters.group(3)


def assert_authenticator_accepts_session(
    remote_command_executor, authenticator_port, session_id, session_token, username
):
    """Assert the DCV external authenticator validates the given session for the given username."""
    response = remote_command_executor.run_remote_command(
        f"curl -s -k {DCV_SERVER_URL}:{authenticator_port} "
        f"-d sessionId={session_id} -d authenticationToken={session_token} -d clientAddr=someIp"
    ).stdout
    assert_that(response).is_equal_to('<auth result="yes"><username>{0}</username></auth>'.format(username))


def check_dcv_session_authentication(remote_command_executor, authenticator_port, shared_dir, username):
    """Open a DCV session and verify the authenticator validates it for the given username.

    This drives the full DCV authenticator path, including its session-ownership check that
    resolves the username to a numeric UID.
    """
    logging.info("Starting DCV session for user %s", username)
    _, session_id, session_token = start_dcv_session(remote_command_executor, shared_dir)
    logging.info("Verifying DCV authenticator validates the session for user %s", username)
    assert_authenticator_accepts_session(
        remote_command_executor, authenticator_port, session_id, session_token, username
    )
