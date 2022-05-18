# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from tests.common.utils import reboot_head_node, restart_head_node


@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
def test_head_node_stop(pcluster_config_reader, clusters_factory):
    head_ephemeral_mount = "/scratch_head"
    compute_ephemeral_mount = "/scratch_compute"
    folder = "myFolder"
    filename = "myFile"
    cluster_config = pcluster_config_reader(
        head_ephemeral_mount=head_ephemeral_mount, compute_ephemeral_mount=compute_ephemeral_mount
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_head_ephemeral_setup(remote_command_executor, head_ephemeral_mount, folder, filename)

    # reboot head_node (instance store is preserved)
    reboot_head_node(cluster, remote_command_executor)
    _test_head_ephemeral_preserved(remote_command_executor, head_ephemeral_mount, folder, filename)

    # stop/start head_node (instance store is recreated)
    restart_head_node(cluster)
    # RemoteCommandExecutor needs to be re-initialized because HeadNode changed public IP
    new_remote_command_executor = RemoteCommandExecutor(cluster)
    _test_head_ephemeral_recreated(new_remote_command_executor, head_ephemeral_mount, folder, filename)


def _test_head_ephemeral_setup(remote_command_executor, head_ephemeral_mount, folder, filename):
    logging.info(f"Testing ephemeral {head_ephemeral_mount} is correctly setup on creation")
    _create_file_and_folder(filename, folder, head_ephemeral_mount, remote_command_executor)
    _check_file_exists(filename, folder, head_ephemeral_mount, remote_command_executor)


def _test_head_ephemeral_preserved(remote_command_executor, head_ephemeral_mount, folder, filename):
    logging.info(f"Testing ephemeral {head_ephemeral_mount} is correctly preserved on reboot")
    _check_file_exists(filename, folder, head_ephemeral_mount, remote_command_executor)


def _test_head_ephemeral_recreated(remote_command_executor, head_ephemeral_mount, folder, filename):
    logging.info(f"Testing ephemeral {head_ephemeral_mount} is correctly recreated on restart")
    _check_folder_does_not_exists(folder, head_ephemeral_mount, remote_command_executor)


def _check_file_exists(filename, folder, head_ephemeral_mount, remote_command_executor):
    result = remote_command_executor.run_remote_command(f"ls {head_ephemeral_mount}/{folder}/")
    assert_that(result.stdout).contains(filename)


def _check_folder_does_not_exists(folder, head_ephemeral_mount, remote_command_executor):
    result = remote_command_executor.run_remote_command(f"ls {head_ephemeral_mount}/")
    assert_that(result.stdout).does_not_contain(folder)


def _create_file_and_folder(filename, folder, head_ephemeral_mount, remote_command_executor):
    remote_command_executor.run_remote_command(
        f"mkdir {head_ephemeral_mount}/{folder} && touch {head_ephemeral_mount}/{folder}/{filename}"
    )
