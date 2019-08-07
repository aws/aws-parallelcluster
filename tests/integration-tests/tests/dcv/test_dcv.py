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

import pytest
from assertpy import assert_that

from remote_command_executor import RemoteCommandExecutor


@pytest.mark.regions(["eu-west-1"])
@pytest.mark.oss(["centos7"])
@pytest.mark.schedulers(["sge"])
def test_dcv_connection(region, instance, os, scheduler, pcluster_config_reader, clusters_factory, test_datadir):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    output = remote_command_executor.run_remote_command("/opt/parallelcluster/scripts/pcluster_dcv_connect.sh /shared")
    session_id, port, session_token = output.split()
    assert_that(
        remote_command_executor.run_remote_command(f"curl -k http://localhost:{port} -d sessionId={session_id} -d authenticationToken={session_token}")
    ).is_equal_to('<auth result="yes"><username>centos</username></auth>')