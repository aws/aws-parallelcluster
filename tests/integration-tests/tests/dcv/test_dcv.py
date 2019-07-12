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
import boto3
import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor


def _check_ext_auth_blocking_invalid_sessions(remote_command_executor):
    assert_that(
        remote_command_executor.run_remote_command(
            "curl -s -X GET -G http://localhost:8444  "
            "-d action=requestToken -d authUser=centos -d sessionID=invalidSessionId"
        ).stdout
    ).is_equal_to("The given session for the user does not exists")


def _check_working_dcv_setup(external_authenticator_port, remote_command_executor):
    session_id, port, session_token = remote_command_executor.run_remote_command(
        "/opt/parallelcluster/scripts/pcluster_dcv_connect.sh /shared"
    ).stdout.split()

    _check_auth_ok(external_authenticator_port, remote_command_executor, session_id, session_token)


def _check_shared_dir(external_authenticator_port, remote_command_executor, shared_dir):
    session_id, port, session_token = remote_command_executor.run_remote_command(
        f"/opt/parallelcluster/scripts/pcluster_dcv_connect.sh {shared_dir}"
    ).stdout.split()

    assert_that(
        int(
            remote_command_executor.run_remote_command(
                "cat /var/log/dcv/server.log | grep -c {0}".format(shared_dir)
            ).stdout
        )
    ).is_greater_than(0)

    _check_auth_ok(external_authenticator_port, remote_command_executor, session_id, session_token)


def _check_auth_ok(external_authenticator_port, remote_command_executor, session_id, session_token):
    assert_that(
        remote_command_executor.run_remote_command(
            f"curl -s -k http://localhost:{external_authenticator_port} "
            f"-d sessionId={session_id} -d authenticationToken={session_token} -d clientAddr=someIp"
        ).stdout
    ).is_equal_to('<auth result="yes"><username>centos</username></auth>')


def _check_security_group(region, cluster, port, expected):
    security_group_id = cluster.cfn_resources.get("MasterSecurityGroup")
    client = boto3.client("ec2", region_name=region)
    response = client.describe_security_groups(GroupIds=[security_group_id])
    ips = response["SecurityGroups"][0]["IpPermissions"]
    target = next(filter(lambda x: x.get("FromPort", -1) == port, ips), {})
    assert_that(target["IpRanges"][0]["CidrIp"]).is_equal_to(expected)


@pytest.mark.regions(["eu-west-1"])
@pytest.mark.oss(["centos7"])
@pytest.mark.schedulers(["sge"])
def test_dcv_connection(region, instance, os, scheduler, pcluster_config_reader, clusters_factory, test_datadir):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _check_ext_auth_blocking_invalid_sessions(remote_command_executor)
    _check_working_dcv_setup(8444, remote_command_executor)


@pytest.mark.regions(["eu-west-1"])
@pytest.mark.oss(["centos7"])
@pytest.mark.schedulers(["sge"])
def test_custom_dcv_configuration(
    region, instance, os, scheduler, pcluster_config_reader, clusters_factory, test_datadir
):
    dcv_port = 5678
    external_authenticator_port = dcv_port + 1
    security_group_cidr = "192.168.1.1/32"
    shared_dir = "/myshared"

    cluster_config = pcluster_config_reader(port=str(dcv_port), access_from=security_group_cidr, shared=shared_dir)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _check_security_group(region, cluster, dcv_port, expected=security_group_cidr)
    _check_shared_dir(external_authenticator_port, remote_command_executor, shared_dir)
