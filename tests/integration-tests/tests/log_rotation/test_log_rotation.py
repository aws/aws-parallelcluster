# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from retrying import retry
from time_utils import minutes, seconds

from tests.cloudwatch_logging.cloudwatch_logging_boto3_utils import get_cluster_log_groups_from_boto3, get_log_events


@pytest.mark.usefixtures("instance", "os", "scheduler")
def test_log_rotation(
    region, pcluster_config_reader, s3_bucket_factory, clusters_factory, test_datadir, scheduler_commands_factory, os
):
    """Test parallelcluster log rotation configuration."""
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)

    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = scheduler_commands_factory(remote_command_executor)
    compute_node_ip = cluster.describe_cluster_instances(node_type="Compute")[0].get("privateIpAddress")
    headnode_ip = cluster.describe_cluster_instances(node_type="HeadNode")[0].get("privateIpAddress")
    log_group_name = get_cluster_log_groups_from_boto3(f"/aws/parallelcluster/{cluster.name}")[0].get("logGroupName")

    logging.info("Verifying ParallelCluster log rotation configuration.")
    common_logs = [
        {"log_name": "cloud-init", "log_path": "/var/log/cloud-init.log", "existence": True},
        {"log_name": "supervisord", "log_path": "/var/log/supervisord.log", "existence": True},
        {"log_name": "bootstrap_error_msg", "log_path": "/var/log/parallelcluster/bootstrap_error_msg"},
    ]
    headnode_specified_logs = [
        {
            "log_name": "clustermgtd",
            "log_path": "/var/log/parallelcluster/clustermgtd",
            "existence": True,
            "trigger_new_entries": True,
        },
        {
            "log_name": "clusterstatusmgtd",
            "log_path": "/var/log/parallelcluster/clusterstatusmgtd",
            "existence": True,
            "trigger_new_entries": True,
        },
        {"log_name": "cfn-init", "log_path": "/var/log/cfn-init.log", "existence": True},
        {"log_name": "dcv-agent", "log_path": "/var/log/dcv/agent.*.log"},
        {"log_name": "dcv-session-launcher", "log_path": "/var/log/dcv/sessionlauncher.log", "existence": False},
        {"log_name": "Xdcv", "log_path": "/var/log/dcv/Xdcv.*.log"},
        {
            "log_name": "dcv-server",
            "log_path": "/var/log/dcv/server.log",
            "existence": True,
            "trigger_new_entries": True,
        },
        {"log_name": "dcv-xsession", "log_path": "/var/log/dcv/dcv-xsession.*.log"},
        {"log_name": "slurmdbd", "log_path": "/var/log/slurmdbd.log"},
        {"log_name": "slurmctld", "log_path": "/var/log/slurmctld.log", "existence": True, "trigger_new_entries": True},
        {
            "log_name": "compute_console_output",
            "log_path": "/var/log/parallelcluster/compute_console_output.log",
            "existence": True,
        },
        {
            "log_name": "slurm_fleet_status_manager",
            "log_path": "/var/log/parallelcluster/slurm_fleet_status_manager.log",
            "existence": True,
        },
        {
            "log_name": "slurm_suspend",
            "log_path": "/var/log/parallelcluster/slurm_suspend.log",
            "existence": True,
            "trigger_new_entries": True,
        },
        {
            "log_name": "slurm_resume",
            "log_path": "/var/log/parallelcluster/slurm_resume.log",
            "existence": True,
            "trigger_new_entries": True,
        },
        {"log_name": "chef-client", "log_path": "/var/log/chef-client.log", "existence": True},
        {
            "log_name": "clustermgtd_events",
            "log_path": "/var/log/parallelcluster/clustermgtd.events",
            "existence": True,
        },
        {
            "log_name": "slurm_resume_events",
            "log_path": "/var/log/parallelcluster/slurm_resume.events",
            "existence": True,
        },
    ]
    compute_specified_logs = [
        {"log_name": "cloud-init-output", "log_path": "/var/log/cloud-init-output.log", "existence": True},
        {
            "log_name": "computemgtd",
            "log_path": "/var/log/parallelcluster/computemgtd",
            "existence": True,
            "trigger_new_entries": True,
        },
        {"log_name": "slurmd", "log_path": "/var/log/slurmd.log", "existence": True},
    ]

    before_log_rotation_message = "test message before log rotation."
    after_log_rotation_message = "test message after log rotation."
    _test_headnode_log_rotation(
        os,
        headnode_specified_logs,
        common_logs,
        remote_command_executor,
        before_log_rotation_message,
        after_log_rotation_message,
        slurm_commands,
        cluster,
        headnode_ip,
        log_group_name,
    )
    _test_compute_log_rotation(
        os,
        compute_specified_logs,
        common_logs,
        remote_command_executor,
        before_log_rotation_message,
        after_log_rotation_message,
        cluster,
        compute_node_ip,
        log_group_name,
    )


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))
def _wait_file_not_empty(remote_command_executor, file_path, compute_node_ip=None):
    if compute_node_ip:
        size = _run_command_on_node(remote_command_executor, f"stat --format=%s {file_path}", compute_node_ip)
    else:
        size = remote_command_executor.run_remote_command(f"stat --format=%s {file_path}").stdout
    assert_that(size).is_not_equal_to("0")


def _run_command_on_node(remote_command_executor, command, compute_node_ip=None):
    """Run remote command on head node or compute node."""
    if compute_node_ip:
        return remote_command_executor.run_remote_command(f"ssh -q {compute_node_ip} '{command}'").stdout
    else:
        return remote_command_executor.run_remote_command(f"{command}").stdout


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))
def _wait_log_in_log_stream(
    cluster, private_ip, log_name, log_group_name, before_log_rotation_message, after_log_rotation_message
):
    stream_names = cluster.get_all_log_stream_names()
    stream_name = next(
        (
            stream_name
            for stream_name in stream_names
            if private_ip.replace(".", "-") in stream_name and stream_name.endswith(log_name)
        ),
        None,
    )
    events = get_log_events(log_group_name, stream_name)
    log_data = " ".join(event["message"] for event in events)
    assert_that(log_data).matches(rf"{before_log_rotation_message}")
    assert_that(log_data).matches(rf"{after_log_rotation_message}")


def _test_headnode_log_rotation(
    os,
    headnode_specified_logs,
    common_logs,
    remote_command_executor,
    before_log_rotation_message,
    after_log_rotation_message,
    slurm_commands,
    cluster,
    private_ip,
    log_group_name,
):
    _test_logs_are_rotated(
        os, headnode_specified_logs + common_logs, remote_command_executor, before_log_rotation_message
    )
    # submit a job to launch a dynamic node to trigger new logs generation in slurm_resume, slurm_suspend
    slurm_commands.submit_command(
        command="hostname",
        nodes=1,
        constraint="dynamic",
    )
    _test_logs_written_to_new_file(headnode_specified_logs + common_logs, remote_command_executor)
    _test_logs_uploaded_to_cloudwatch(
        headnode_specified_logs + common_logs,
        remote_command_executor,
        cluster,
        private_ip,
        log_group_name,
        before_log_rotation_message,
        after_log_rotation_message,
    )


def _test_compute_log_rotation(
    os,
    compute_specified_logs,
    common_logs,
    remote_command_executor,
    before_log_rotation_message,
    after_log_rotation_message,
    cluster,
    compute_node_ip,
    log_group_name,
):
    _test_logs_are_rotated(
        os, compute_specified_logs + common_logs, remote_command_executor, before_log_rotation_message, compute_node_ip
    )
    _test_logs_written_to_new_file(compute_specified_logs + common_logs, remote_command_executor, compute_node_ip)
    _test_logs_uploaded_to_cloudwatch(
        compute_specified_logs + common_logs,
        remote_command_executor,
        cluster,
        compute_node_ip,
        log_group_name,
        before_log_rotation_message,
        after_log_rotation_message,
        compute_node_ip,
    )


def _test_logs_are_rotated(os, logs, remote_command_executor, before_log_rotation_message, compute_node_ip=None):
    """Test log_file.1 is created after log rotation."""
    # Write a log message to log file before log rotation in case of log file is empty and not rotate
    for log in logs:
        if log.get("existence"):
            _run_command_on_node(
                remote_command_executor,
                f"echo '{before_log_rotation_message}' | sudo tee --append {log.get('log_path')}",
                compute_node_ip,
            )
    # Flush changes to the disk using sync to ensure file is not detected as empty by mistake and not rotate
    _run_command_on_node(
        remote_command_executor,
        "sync",
        compute_node_ip,
    )
    # force log rotate without waiting for logs to reach certain size
    _run_command_on_node(remote_command_executor, "sudo logrotate -f /etc/logrotate.conf", compute_node_ip)
    # check if logs are rotated
    if os in ["alinux2", "centos7"]:
        result = _run_command_on_node(
            remote_command_executor, "cat /var/lib/logrotate/logrotate.status", compute_node_ip
        )
    else:
        result = _run_command_on_node(remote_command_executor, "cat /var/lib/logrotate/status", compute_node_ip)
    for log in logs:
        assert_that(result).contains(log.get("log_path"))
        if log.get("existence"):
            # assert logs before rotation are in the rotated log files
            rotate_log = _run_command_on_node(
                remote_command_executor, f"sudo cat {log.get('log_path')}.1", compute_node_ip
            )
            assert_that(rotate_log).contains(before_log_rotation_message)


def _test_logs_written_to_new_file(logs, remote_command_executor, compute_node_ip=None):
    """Test newly generated logs write to log_file.log instead of log_file.log.1."""
    # test logs are written to new log files after rotation
    for log in logs:
        if log.get("trigger_new_entries"):
            _wait_file_not_empty(remote_command_executor, log.get("log_path"), compute_node_ip)


def _test_logs_uploaded_to_cloudwatch(
    logs,
    remote_command_executor,
    cluster,
    private_ip,
    log_group_name,
    before_log_rotation_message,
    after_log_rotation_message,
    compute_private_ip=None,
):
    """Test logs before rotation and after rotation are uploaded to cloudwatch."""
    # write a log message to log file after log rotation in case log is empty
    for log in logs:
        if log.get("existence"):
            _run_command_on_node(
                remote_command_executor,
                f"echo '{after_log_rotation_message}' | sudo tee --append {log.get('log_path')}",
                compute_private_ip,
            )
            # assert both logs are in the cloudwatch logs
            _wait_log_in_log_stream(
                cluster,
                private_ip,
                log.get("log_name"),
                log_group_name,
                before_log_rotation_message,
                after_log_rotation_message,
            )
