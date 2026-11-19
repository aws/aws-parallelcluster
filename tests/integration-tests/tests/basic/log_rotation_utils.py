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
from assertpy import assert_that
from retrying import retry
from time_utils import minutes, seconds

from tests.cloudwatch_logging.cloudwatch_logging_boto3_utils import get_log_events


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(9))
def _wait_file_not_empty(remote_command_executor, file_path, compute_node_ip=None):
    if compute_node_ip:
        size = _run_command_on_node(remote_command_executor, f"stat --format=%s {file_path}", compute_node_ip)
    else:
        size = remote_command_executor.run_remote_command(f"stat --format=%s {file_path}").stdout
    assert_that(size).is_not_equal_to("0")

def _touch_file(remote_command_executor, file_path, compute_node_ip=None):
    """Touch a file on head node or compute node."""
    command = f"touch {file_path}"
    if compute_node_ip:
        _run_command_on_node(remote_command_executor, command, compute_node_ip)
    else:
        remote_command_executor.run_remote_command(command)


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
            log_path = log.get("log_path")
            log_file_user = remote_command_executor.get_user_to_operate_on_file(log_path)
            _run_command_on_node(
                remote_command_executor,
                f"echo '{before_log_rotation_message}' | sudo -u {log_file_user} tee --append {log_path}",
                compute_node_ip,
            )
    # Flush changes to the disk using sync to ensure file is not detected as empty by mistake and not rotate
    _run_command_on_node(
        remote_command_executor,
        "sync",
        compute_node_ip,
    )
    # remove date extension to old rotated file
    _run_command_on_node(
        remote_command_executor, "sudo sed -i 's/dateext/nodateext/g' /etc/logrotate.conf", compute_node_ip
    )
    # force log rotate without waiting for logs to reach certain size
    _run_command_on_node(remote_command_executor, "sudo logrotate -f /etc/logrotate.conf", compute_node_ip)
    # check if logs are rotated
    if "ubuntu" in os:
        log_file = "/var/lib/logrotate/status"
        log_file_user = remote_command_executor.get_user_to_operate_on_file(log_file)
        result = _run_command_on_node(
            remote_command_executor, f"sudo -u {log_file_user} cat {log_file}", compute_node_ip
        )
    else:
        log_file = "/var/lib/logrotate/logrotate.status"
        log_file_user = remote_command_executor.get_user_to_operate_on_file(log_file)
        result = _run_command_on_node(
            remote_command_executor, f"sudo -u {log_file_user} cat /var/lib/logrotate/logrotate.status", compute_node_ip
        )
    for log in logs:
        log_path = log.get("log_path")
        assert_that(result).contains(log_path)
        if log.get("existence"):
            # assert logs before rotation are in the rotated log files
            log_file_user = remote_command_executor.get_user_to_operate_on_file(f"{log_path}.1")
            rotate_log = _run_command_on_node(
                remote_command_executor, f"sudo -u {log_file_user} cat {log_path}.1", compute_node_ip
            )
            assert_that(rotate_log).contains(before_log_rotation_message)


def _test_logs_written_to_new_file(logs, remote_command_executor, compute_node_ip=None):
    """Test newly generated logs write to log_file.log instead of log_file.log.1."""
    # test logs are written to new log files after rotation.
    # For those logs that do not necessarily have new entries,
    # we touch the file to force the existence for later checks.
    for log in logs:
        if log.get("trigger_new_entries"):
            _wait_file_not_empty(remote_command_executor, log.get("log_path"), compute_node_ip)
        else:
            _touch_file(remote_command_executor, log.get("log_path"), compute_node_ip)


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
            log_path = log.get("log_path")
            log_file_user = remote_command_executor.get_user_to_operate_on_file(log_path)
            _run_command_on_node(
                remote_command_executor,
                f"echo '{after_log_rotation_message}' | sudo -u {log_file_user} tee --append {log_path}",
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
