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
import os as operating_system
import re

import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from utils import (
    add_keys_to_known_hosts,
    check_headnode_security_group,
    get_username_for_os,
    remove_keys_from_known_hosts,
    run_command,
)

from tests.cloudwatch_logging.test_cloudwatch_logging import FeatureSpecificCloudWatchLoggingTestRunner

SERVER_URL = "https://localhost"
DCV_CONNECT_SCRIPT = "/opt/parallelcluster/scripts/pcluster_dcv_connect.sh"


@pytest.mark.dimensions("cn-northwest-1", "c4.xlarge", "alinux2", "slurm")
@pytest.mark.dimensions("us-gov-west-1", "c5.xlarge", "ubuntu1804", "slurm")
@pytest.mark.dimensions("eu-west-1", "g3.8xlarge", "alinux2", "slurm")
@pytest.mark.dimensions("eu-west-1", "g3.8xlarge", "centos7", "slurm")
@pytest.mark.dimensions("eu-west-1", "g3.8xlarge", "centos8", "slurm")
@pytest.mark.dimensions("eu-west-1", "g3.8xlarge", "ubuntu1804", "slurm")
@pytest.mark.dimensions("eu-west-1", "m6g.xlarge", "alinux2", "slurm")
@pytest.mark.dimensions("eu-west-1", "m6g.xlarge", "centos7", "slurm")
@pytest.mark.dimensions("eu-west-1", "m6g.xlarge", "centos8", "slurm")
@pytest.mark.dimensions("eu-west-1", "m6g.xlarge", "ubuntu1804", "slurm")
def test_dcv_configuration(
    region,
    instance,
    os,
    scheduler,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
):
    _test_dcv_configuration(
        8443,
        "0.0.0.0/0",
        "/shared",
        region,
        instance,
        os,
        scheduler,
        pcluster_config_reader,
        clusters_factory,
        test_datadir,
    )


@pytest.mark.parametrize(
    "dcv_port, access_from, shared_dir", [(8443, "0.0.0.0/0", "/shared"), (5678, "192.168.1.1/32", "/myshared")]
)
@pytest.mark.dimensions("eu-west-1", "c5.xlarge", "centos7", "sge")
@pytest.mark.dimensions("eu-west-2", "c5.xlarge", "centos8", "sge")
def test_dcv_with_remote_access(
    dcv_port,
    access_from,
    shared_dir,
    region,
    instance,
    os,
    scheduler,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
):
    _test_dcv_configuration(
        dcv_port,
        access_from,
        shared_dir,
        region,
        instance,
        os,
        scheduler,
        pcluster_config_reader,
        clusters_factory,
        test_datadir,
    )


def _test_dcv_configuration(
    dcv_port,
    access_from,
    shared_dir,
    region,
    instance,
    os,
    scheduler,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
):
    dcv_authenticator_port = dcv_port + 1
    cluster_config = pcluster_config_reader(dcv_port=str(dcv_port), access_from=access_from, shared_dir=shared_dir)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # check configuration parameters
    check_headnode_security_group(region, cluster, dcv_port, expected_cidr=access_from)

    # dcv connect show url
    env = operating_system.environ.copy()
    env["AWS_DEFAULT_REGION"] = region

    # add ssh key to jenkins user known hosts file to avoid ssh keychecking prompt
    host_keys_file = operating_system.path.expanduser("~/.ssh/known_hosts")
    add_keys_to_known_hosts(cluster.head_node_ip, host_keys_file)

    try:
        result = run_command(["pcluster", "dcv", "connect", cluster.name, "--show-url"], env=env)
    finally:
        # remove ssh key from jenkins user known hosts file
        remove_keys_from_known_hosts(cluster.head_node_ip, host_keys_file, env=env)

    assert_that(result.stdout).matches(
        r"Please use the following one-time URL in your browser within 30 seconds:\n"
        r"https:\/\/(\b(?:\d{1,3}\.){3}\d{1,3}\b):" + str(dcv_port) + r"\?authToken=(.*)"
    )

    # check error cases
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
    _check_auth_ko(
        remote_command_executor, dcv_authenticator_port, "-d action=sessionToken -d authUser=centos", "Wrong parameters"
    )

    # launch a session and verify the authenticator works
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

    # check shared dir configuration
    _check_shared_dir(remote_command_executor, shared_dir)

    # Ensure no system programs crashed
    _check_no_crashes(remote_command_executor, test_datadir)

    # Check that logs are stored in CloudWatch as expected
    FeatureSpecificCloudWatchLoggingTestRunner.run_tests_for_feature(
        cluster, scheduler, os, "dcv_enabled", region, shared_dir
    )


def _check_auth_ko(remote_command_executor, dcv_authenticator_port, params, expected_message):
    assert_that(
        remote_command_executor.run_remote_command(
            f"curl -s -k -X GET -G {SERVER_URL}:{dcv_authenticator_port} {params}"
        ).stdout
    ).contains(expected_message)


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
