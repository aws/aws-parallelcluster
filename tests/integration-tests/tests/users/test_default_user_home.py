# Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor

# flake8: noqa


@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_default_user_local_home(
    region,
    scheduler,
    pcluster_config_reader,
    vpc_stack,
    scheduler_commands_factory,
    test_datadir,
    clusters_factory,
):
    """Verify the default user's home directory is moved on all instance types when set to local"""

    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    remote_command_executor_login_node = RemoteCommandExecutor(cluster, use_login_node=True)

    _check_local_home(remote_command_executor)
    _check_local_home(remote_command_executor_login_node)


def _check_local_home(remote_command_executor):
    """Check if the default user's home directory is mounted on the instance"""
    logging.info("Testing the default user's home is local")
    result = remote_command_executor.run_remote_command("pwd")
    assert_that(result.stdout).matches(r"/local/home*")
