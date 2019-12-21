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

import boto3
import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from utils import run_command

SERVER_URL = "https://localhost"
DCV_CONNECT_SCRIPT = "/opt/parallelcluster/scripts/pcluster_dcv_connect.sh"


@pytest.mark.parametrize(
    "dcv_port, access_from, shared_dir", [(8443, "0.0.0.0/0", "/shared"), (5678, "192.168.1.1/32", "/myshared")]
)
@pytest.mark.regions(["eu-west-1", "cn-northwest-1"])  # DCV license bucket not present in us-gov
@pytest.mark.oss(["centos7"])
@pytest.mark.instances(["c4.xlarge", "g3.8xlarge"])
@pytest.mark.schedulers(["sge"])
def test_dcv_configuration(
    dcv_port, access_from, shared_dir, region, instance, os, scheduler, pcluster_config_reader, clusters_factory
):
    dcv_authenticator_port = dcv_port + 1
    cluster_config = pcluster_config_reader(dcv_port=str(dcv_port), access_from=access_from, shared_dir=shared_dir)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # check configuration parameters
    _check_security_group(region, cluster, dcv_port, expected_cidr=access_from)

    # dcv connect show url
    env = operating_system.environ.copy()
    env["AWS_DEFAULT_REGION"] = region
    operating_system.system(
        r"sudo sed -i 's/\#   StrictHostKeyChecking ask/   StrictHostKeyChecking no/g' /etc/ssh/ssh_config"
    )
    result = run_command(["pcluster", "dcv", "connect", cluster.name, "--show-url"], env=env)
    assert_that(result.stdout).matches(
        r"Please use the following one-time URL in your browser within 30 seconds:\n"
        r"https:\/\/(\b(?:\d{1,3}\.){3}\d{1,3}\b):" + str(dcv_port) + r"\?authToken=(.*)"
    )
    operating_system.system(
        r"sudo sed -i 's/\#   StrictHostKeyChecking no/   StrictHostKeyChecking ask/g' /etc/ssh/ssh_config"
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
        _check_auth_ok(remote_command_executor, dcv_authenticator_port, dcv_session_id, dcv_session_token)
    else:
        print(
            "Command '{0} {1}' fails, output: {2}, error: {3}".format(
                DCV_CONNECT_SCRIPT, shared_dir, command_execution.stdout, command_execution.stderr
            )
        )
        raise AssertionError

    # check shared dir configuration
    _check_shared_dir(remote_command_executor, shared_dir)


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


def _check_auth_ok(remote_command_executor, external_authenticator_port, session_id, session_token):
    assert_that(
        remote_command_executor.run_remote_command(
            f"curl -s -k {SERVER_URL}:{external_authenticator_port} "
            f"-d sessionId={session_id} -d authenticationToken={session_token} -d clientAddr=someIp"
        ).stdout
    ).is_equal_to('<auth result="yes"><username>centos</username></auth>')


def _check_security_group(region, cluster, port, expected_cidr):
    security_group_id = cluster.cfn_resources.get("MasterSecurityGroup")
    response = boto3.client("ec2", region_name=region).describe_security_groups(GroupIds=[security_group_id])

    ips = response["SecurityGroups"][0]["IpPermissions"]
    target = next(filter(lambda x: x.get("FromPort", -1) == port, ips), {})
    assert_that(target["IpRanges"][0]["CidrIp"]).is_equal_to(expected_cidr)
