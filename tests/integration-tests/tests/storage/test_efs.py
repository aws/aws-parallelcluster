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
import json
import logging

import boto3
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from utils import get_compute_nodes_instance_ips, get_vpc_snakecase_value, get_arn_partition

from tests.common.utils import reboot_head_node, get_sts_endpoint
from tests.storage.storage_common import (
    test_efs_correctly_mounted,
    verify_directory_correctly_shared,
    write_file_into_efs,
)


@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_efs_compute_az(region, pcluster_config_reader, clusters_factory, vpc_stack, scheduler_commands_factory):
    """
    Test when compute subnet is in a different AZ from head node subnet.

    A compute mount target should be created and the efs correctly mounted on compute.
    """
    _assert_subnet_az_relations(region, vpc_stack, expected_in_same_az=False)
    mount_dir = "efs_mount_dir"
    cluster_config = pcluster_config_reader(mount_dir=mount_dir)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    mount_dir = "/" + mount_dir
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    test_efs_correctly_mounted(remote_command_executor, mount_dir)
    _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_efs_same_az(region, pcluster_config_reader, clusters_factory, vpc_stack, scheduler_commands_factory):
    """
    Test when compute subnet is in the same AZ as head node subnet.

    No compute mount point needed and the efs correctly mounted on compute.
    """
    _assert_subnet_az_relations(region, vpc_stack, expected_in_same_az=True)
    mount_dir = "efs_mount_dir"
    cluster_config = pcluster_config_reader(mount_dir=mount_dir)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    mount_dir = "/" + mount_dir
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    test_efs_correctly_mounted(remote_command_executor, mount_dir)
    _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


@pytest.mark.usefixtures("instance")
def test_multiple_efs(
        os,
        region,
        scheduler,
        efs_stack_factory,
        efs_mount_target_stack_factory,
        pcluster_config_reader,
        clusters_factory,
        vpc_stack,
        request,
        key_name,
        cfn_stacks_factory,
        scheduler_commands_factory,
        run_benchmarks,
):
    """
    Test when efs_fs_id is provided in the config file, the existing efs can be correctly mounted.

    To verify the efs is the existing efs, the test expects a file with random ran inside the efs mounted
    """
    # Names of files that will be written from separate instance. The test checks the cluster nodes can access them.
    existing_efs_filenames = []
    existing_efs_mount_dirs = []
    iam_authorizations = [False, False, True]
    encryption_in_transits = [False, True, True]
    if request.config.getoption("benchmarks") and os == "alinux2":
        # Only create more EFS when benchmarks are specified. Limiting OS to reduce cost of too many file systems
        num_existing_efs = 20
    else:
        num_existing_efs = 3
    # TODO: create an additional EFS with file system policy to prevent anonymous access
    # existing_efs_ids = ["fs-02870d9c9383ad4a1", "fs-0f7c1aed44c02d117", "fs-0cdef194a08301bb9", "fs-0fd73b2031ce6332a", "fs-0f33426966487052a", "fs-0583785a4c8cbaed7"]
    # existing_efs_ids = ["fs-0a05e97d75bed3b6a", "fs-0de014f8dfcf6765a", "fs-0f1344c4e36a19ffe"]
    existing_efs_ids = efs_stack_factory(num_existing_efs)
    account_id = (
        boto3.client("sts", region_name=region, endpoint_url=get_sts_endpoint(region))
        .get_caller_identity()
        .get("Account")
    )
    policy = {
        "Version": "2012-10-17",
        "Id": "efs-policy-wizard-2b0679e4-cbf2-4cb7-a9d0-2f3bb4a6f911",
        "Statement": [
            {
                "Sid": "efs-block-not-iam-in-account",
                "Effect": "Deny",
                "Principal": {
                    "AWS": "*"
                },
                "Action": [
                    "elasticfilesystem:ClientMount",
                    "elasticfilesystem:ClientRootAccess",
                    "elasticfilesystem:ClientWrite"
                ],
                "Resource": f"arn:{get_arn_partition(region)}:elasticfilesystem:{region}:{account_id}:file-system/{existing_efs_ids[-1]}",
                "Condition": {"StringNotLike": {"aws:PrincipalAccount": account_id}}
            }
        ]
    }
    boto3.client("efs").put_file_system_policy(
        FileSystemId=existing_efs_ids[-1],
        Policy=json.dumps(policy)
    )
    logging.info("finished applying policy")
    efs_mount_target_stack_factory(existing_efs_ids)
    logging.info("created efs_mount_target_stack_factory")
    existing_efs_filenames.extend(
        write_file_into_efs(
            region, vpc_stack, existing_efs_ids, request, key_name, cfn_stacks_factory, efs_mount_target_stack_factory
        )
    )
    logging.info("extended existing_efs_filenames")
    for i in range(num_existing_efs):
        existing_efs_mount_dirs.append(f"/existing_efs_mount_dir_{i}")
    logging.info("appended to existing_efs_mount_dirs")
    new_efs_mount_dirs = ["/shared"]  # OSU benchmark relies on /shared directory

    _assert_subnet_az_relations(region, vpc_stack, expected_in_same_az=False)
    logging.info("asserted subnet_az")
    # TODO: change cluster configuration file to test different tls and iam settings to EFS.
    cluster_config = pcluster_config_reader(
        existing_efs_mount_dirs=existing_efs_mount_dirs,
        existing_efs_ids=existing_efs_ids,
        new_efs_mount_dirs=new_efs_mount_dirs,
        iam_authorizations=iam_authorizations,
        encryption_in_transits=encryption_in_transits,
    )
    logging.info(cluster_config)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    for i in range(num_existing_efs):
        remote_command_executor.run_remote_command(f"cat {existing_efs_mount_dirs[i]}/{existing_efs_filenames[i]}")

    all_mount_dirs = existing_efs_mount_dirs + new_efs_mount_dirs
    # append false for the one new_efs_mount_dir
    iam_authorizations.append(False)
    encryption_in_transits.append(False)
    _check_efs_correctly_mounted_and_shared(all_mount_dirs, remote_command_executor, scheduler_commands,
                                            iam_authorizations, encryption_in_transits)

    if scheduler == "slurm":  # Only Slurm supports compute nodes reboot
        remote_command_executor, scheduler_commands = _check_efs_after_nodes_reboot(
            all_mount_dirs, cluster, remote_command_executor, scheduler_commands_factory, iam_authorizations, encryption_in_transits
        )

    run_benchmarks(remote_command_executor, scheduler_commands)


def _check_efs_after_nodes_reboot(all_mount_dirs, cluster, remote_command_executor, scheduler_commands_factory,
                                  iam_authorizations=[], encryption_in_transits=[]):
    reboot_head_node(cluster, remote_command_executor)
    # Re-establish connection after head node reboot
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    compute_nodes = scheduler_commands.get_compute_nodes("queue-0")
    for compute_node in compute_nodes:
        scheduler_commands.reboot_compute_node(compute_node, asap=False)
    scheduler_commands.wait_nodes_status("idle", compute_nodes)
    _check_efs_correctly_mounted_and_shared(all_mount_dirs, remote_command_executor, scheduler_commands, iam_authorizations, encryption_in_transits)
    return remote_command_executor, scheduler_commands


def _check_efs_correctly_mounted_and_shared(all_mount_dirs, remote_command_executor, scheduler_commands,
                                            iam_authorizations=[], encryption_in_transits=[]):
    logging.info(iam_authorizations)
    logging.info(encryption_in_transits)
    for i, mount_dir in enumerate(all_mount_dirs):
        test_efs_correctly_mounted(remote_command_executor, mount_dir,
                                   encryption_in_transits[i] if len(encryption_in_transits) > 0 else False,
                                   iam_authorizations[i] if len(iam_authorizations) > 0 else False)
        _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


def _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands):
    logging.info("Testing efs correctly mounted on compute nodes")
    verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)


def _assert_subnet_az_relations(region, vpc_stack, expected_in_same_az):
    vpc = get_vpc_snakecase_value(vpc_stack)
    head_node_subnet_id = vpc["public_subnet_id"]
    compute_subnet_id = vpc["private_subnet_id"] if expected_in_same_az else vpc["private_additional_cidr_subnet_id"]
    head_node_subnet_az = boto3.resource("ec2", region_name=region).Subnet(head_node_subnet_id).availability_zone
    compute_subnet_az = boto3.resource("ec2", region_name=region).Subnet(compute_subnet_id).availability_zone
    if expected_in_same_az:
        assert_that(head_node_subnet_az).is_equal_to(compute_subnet_az)
    else:
        assert_that(head_node_subnet_az).is_not_equal_to(compute_subnet_az)


def _test_efs_utils(remote_command_executor, scheduler_commands, cluster, region, mount_dirs, efs_ids):
    # Collect a list of command executors of all compute nodes
    compute_node_remote_command_executors = []
    for compute_node_ip in get_compute_nodes_instance_ips(cluster.name, region):
        compute_node_remote_command_executors.append(RemoteCommandExecutor(cluster, compute_node_ip=compute_node_ip))
    # Unmount all EFS from head node and compute nodes
    for mount_dir in mount_dirs:
        command = f"sudo umount {mount_dir}"
        remote_command_executor.run_remote_command(command)
        for compute_node_remote_command_executor in compute_node_remote_command_executors:
            compute_node_remote_command_executor.run_remote_command(command)
    # Mount all EFS using EFS-utils
    assert_that(mount_dirs).is_length(len(efs_ids))
    for mount_dir, efs_id in zip(mount_dirs, efs_ids):
        command = f"sudo mount -t efs -o tls {efs_id}:/ {mount_dir}"
        remote_command_executor.run_remote_command(command)
        for compute_node_remote_command_executor in compute_node_remote_command_executors:
            compute_node_remote_command_executor.run_remote_command(command)
        _test_efs_correctly_shared(remote_command_executor, mount_dir, scheduler_commands)
    for mount_dir in mount_dirs:
        test_efs_correctly_mounted(remote_command_executor, mount_dir)
