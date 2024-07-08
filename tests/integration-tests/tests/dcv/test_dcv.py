# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import logging
import os as operating_system
import re

import pytest
import requests
from assertpy import assert_that
from framework.credential_providers import run_pcluster_command
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from utils import add_keys_to_known_hosts, check_node_security_group, get_username_for_os, remove_keys_from_known_hosts

from tests.cloudwatch_logging.test_cloudwatch_logging import FeatureSpecificCloudWatchLoggingTestRunner

SERVER_URL = "https://localhost"
DCV_CONNECT_SCRIPT = "/opt/parallelcluster/scripts/pcluster_dcv_connect.sh"


def test_dcv_configuration(region, instance, os, scheduler, pcluster_config_reader, clusters_factory, test_datadir):
    _test_dcv_configuration(
        8443, "0.0.0.0/0", region, instance, os, scheduler, pcluster_config_reader, clusters_factory, test_datadir
    )


@pytest.mark.parametrize("dcv_port, access_from", [(8443, "0.0.0.0/0"), (5678, "192.168.1.1/32")])
def test_dcv_with_remote_access(
    dcv_port, access_from, region, instance, os, scheduler, pcluster_config_reader, clusters_factory, test_datadir
):
    _test_dcv_configuration(
        dcv_port, access_from, region, instance, os, scheduler, pcluster_config_reader, clusters_factory, test_datadir
    )


def _test_dcv_configuration(
    dcv_port, access_from, region, instance, os, scheduler, pcluster_config_reader, clusters_factory, test_datadir
):
    dcv_authenticator_port = dcv_port + 1
    cluster_config = pcluster_config_reader(dcv_port=str(dcv_port), access_from=access_from)
    cluster = clusters_factory(cluster_config)

    # command executors for the head and login nodes
    head_node_remote_command_executor = RemoteCommandExecutor(cluster)
    login_node_remote_command_executor = RemoteCommandExecutor(cluster, use_login_node=True)

    # check configuration parameters of the head and login nodes
    check_node_security_group(region, cluster, dcv_port, expected_cidr=access_from, node_type="HeadNode")
    check_node_security_group(region, cluster, dcv_port, expected_cidr=access_from, node_type="LoginNode")

    # test dcv connect show url for head and login node
    _test_show_url(cluster, region, dcv_port, access_from)
    _test_show_url(cluster, region, dcv_port, access_from, use_login_node=True)

    # check error cases
    _check_error_cases(head_node_remote_command_executor, dcv_authenticator_port)
    _check_error_cases(login_node_remote_command_executor, dcv_authenticator_port)

    shared_dir = f"/home/{get_username_for_os(os)}"

    # launch a session and verify the authenticator works
    _test_authenticator(head_node_remote_command_executor, dcv_authenticator_port, shared_dir, os)
    _test_authenticator(login_node_remote_command_executor, dcv_authenticator_port, shared_dir, os)

    # check shared dir configuration
    _check_shared_dir(head_node_remote_command_executor, shared_dir)
    _check_shared_dir(login_node_remote_command_executor, shared_dir)

    # Ensure no system programs crashed
    _check_no_crashes(head_node_remote_command_executor, test_datadir)
    _check_no_crashes(login_node_remote_command_executor, test_datadir)

    # Check that logs are stored in CloudWatch as expected
    FeatureSpecificCloudWatchLoggingTestRunner.run_tests_for_feature(
        cluster, scheduler, os, "dcv_enabled", region, shared_dir
    )


def _check_auth_ko(remote_command_executor, dcv_authenticator_port, params, expected_message):
    try:
        assert_that(
            remote_command_executor.run_remote_command(
                f"curl -s -k -X GET -G {SERVER_URL}:{dcv_authenticator_port} {params}"
            ).stdout
        ).contains(expected_message)
    except RemoteCommandExecutionError as e:
        logging.info(f"Exception: {e}")
        assert_that(e.result.stdout).contains(expected_message)


def _check_shared_dir(remote_command_executor, shared_dir):
    assert_that(
        int(remote_command_executor.run_remote_command(f"cat /var/log/dcv/server.log | grep -c {shared_dir}").stdout)
    ).is_greater_than(0)


def _check_auth_ok(remote_command_executor, external_authenticator_port, session_id, session_token, os):
    username = get_username_for_os(os)
    assert_that(
        remote_command_executor.run_remote_command(
            f"curl -s -k {SERVER_URL}:{external_authenticator_port} "
            f"-d sessionId={session_id} -d authenticationToken={session_token} -d clientAddr=someIp"
        ).stdout
    ).is_equal_to('<auth result="yes"><username>{0}</username></auth>'.format(username))


def _check_no_crashes(remote_command_executor, test_datadir):
    """Verify no core files in /var/crash, which on ubuntu18 causes a popup when logging into the 1st session."""
    remote_command_executor.run_remote_script(str(test_datadir / "verify_no_core_files.sh"))


def _check_error_cases(remote_command_executor, dcv_authenticator_port):
    """Check DCV errors for both head and login nodes."""
    _check_auth_ko(
        remote_command_executor,
        dcv_authenticator_port,
        "-d action=requestToken -d authUser=centos -d sessionID=invalidSessionId",
        "The given session does not exists",
    )
    _check_auth_ko(
        remote_command_executor, dcv_authenticator_port, "-d action=test", "The action specified 'test' is not valid"
    )
    _check_auth_ko(
        remote_command_executor, dcv_authenticator_port, "-d action=requestToken -d authUser=centos", "Wrong parameters"
    )


def _test_show_url(cluster, region, dcv_port, access_from, use_login_node=False):
    """Test dcv-connect with --show-url."""
    env = operating_system.environ.copy()
    env["AWS_DEFAULT_REGION"] = region

    node_ip = cluster.get_login_node_public_ip() if use_login_node else cluster.head_node_ip

    # add ssh key to jenkins user known hosts file to avoid ssh keychecking prompt
    host_keys_file = operating_system.path.expanduser("~/.ssh/known_hosts")
    add_keys_to_known_hosts(node_ip, host_keys_file)

    dcv_connect_args = ["pcluster", "dcv-connect", "--cluster-name", cluster.name, "--show-url"]

    if use_login_node:
        dcv_connect_args.extend(["--login-node-ip", node_ip])

    try:
        result = run_pcluster_command(dcv_connect_args, env=env)
    finally:
        # remove ssh key from jenkins user known hosts file
        remove_keys_from_known_hosts(node_ip, host_keys_file, env=env)

    assert_that(result.stdout).matches(
        r"Please use the following one-time URL in your browser within 30 seconds:\n"
        r"https:\/\/(\b(?:\d{1,3}\.){3}\d{1,3}\b):" + str(dcv_port) + r"\?authToken=(.*)"
    )
    if access_from == "0.0.0.0/0":
        url = re.search(r"https:\/\/.*", result.stdout).group(0)
        response = requests.get(url, verify=False)
        assert_that(response.status_code).is_equal_to(200)


def _test_authenticator(remote_command_executor, dcv_authenticator_port, shared_dir, os):
    """Launch a DCV session and verify authenticator."""
    command_execution = remote_command_executor.run_remote_command(f"{DCV_CONNECT_SCRIPT} {shared_dir}")
    dcv_parameters = re.search(
        r"PclusterDcvServerPort=([\d]+) PclusterDcvSessionId=([\w]+) PclusterDcvSessionToken=([\w-]+)",
        command_execution.stdout,
    )
    if dcv_parameters:
        dcv_session_id = dcv_parameters.group(2)
        dcv_session_token = dcv_parameters.group(3)
        _check_auth_ok(remote_command_executor, dcv_authenticator_port, dcv_session_id, dcv_session_token, os)
    else:
        print(
            "Command '{0} {1}' fails, output: {2}, error: {3}".format(
                DCV_CONNECT_SCRIPT, shared_dir, command_execution.stdout, command_execution.stderr
            )
        )
        raise AssertionError
