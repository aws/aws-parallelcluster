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
import os
import shlex

from fabric import Connection
from retrying import retry
from utils import get_username_for_os, run_command


class RemoteCommandExecutionError(Exception):
    """Signal a failure in remote command execution."""

    def __init__(self, result):
        self.result = result


class RemoteCommandExecutor:
    """Execute remote commands on the cluster head node."""

    def __init__(self, cluster, compute_node_ip=None, username=None, bastion=None, alternate_ssh_key=None):
        """
        Initiate SSH connection

        By default, commands are executed on head node. If `compute_node_ip` is specified, execute commands on compute.
        """
        if not username:
            username = get_username_for_os(cluster.os)
        if compute_node_ip:
            # Since compute nodes may not be publicly accessible, always use head node as the bastion.
            node_ip = compute_node_ip
            bastion = f"{username}@{cluster.head_node_ip}"
        else:
            node_ip = cluster.head_node_ip
        connection_kwargs = {
            "host": node_ip,
            "user": username,
            "forward_agent": False,
            "connect_kwargs": {"key_filename": [alternate_ssh_key if alternate_ssh_key else cluster.ssh_key]},
        }
        if bastion:
            # Need to execute simple ssh command before using Connection to avoid Paramiko _check_banner error
            run_command(
                f"ssh -i {cluster.ssh_key} -o StrictHostKeyChecking=no {bastion} hostname", timeout=30, shell=True
            )
            connection_kwargs["gateway"] = f"ssh -W %h:%p -A {bastion}"
            connection_kwargs["forward_agent"] = True
        self.__connection = Connection(**connection_kwargs)
        self.__user_at_hostname = "{0}@{1}".format(username, node_ip)

    def __del__(self):
        try:
            self.__connection.close()
        except Exception as e:
            # Catch all exceptions if we fail to close the clients
            logging.warning("Exception raised when closing remote ssh client: {0}".format(e))

    @retry(wait_exponential_multiplier=1000, stop_max_attempt_number=5)
    def _run_command(self, command, **kwargs):
        return self.__connection.run(command, **kwargs)

    def run_remote_command(
        self,
        command,
        log_error=True,
        additional_files=None,
        raise_on_error=True,
        login_shell=True,
        hide=False,
        log_output=False,
        timeout=None,
        pty=True,
    ):
        """
        Execute remote command on the cluster head node.

        :param command: command to execute.
        :param log_error: log errors.
        :param additional_files: additional files to copy before executing script.
        :param raise_on_error: if True raises a RemoteCommandExecutionError on failures
        :param login_shell: if True prepends /bin/bash --login -c to the given command
        :param hide: do not print command output to the local stdout
        :param log_output: log the command output.
        :param timeout: interrupt connection after N seconds, default of None = no timeout
        :param pty: if True, uses pty to execute commands; default is True.
        :return: result of the execution.
        """
        if isinstance(command, list):
            command = " ".join(command)
        self._copy_additional_files(additional_files)
        logging.info("Executing remote command on {0}: {1}".format(self.__user_at_hostname, command))
        if login_shell:
            command = "/bin/bash --login -c {0}".format(shlex.quote(command))

        result = self._run_command(command, warn=True, pty=pty, hide=hide, timeout=timeout)
        result.stdout = "\n".join(result.stdout.splitlines())
        result.stderr = "\n".join(result.stderr.splitlines())
        if log_output:
            logging.info("Command output:\n%s", result.stdout)
        if result.failed and raise_on_error:
            if log_error:
                logging.error(
                    "Command {0} failed with error:\n{1}\nand output:\n{2}".format(
                        command, result.stderr, result.stdout
                    )
                )
            raise RemoteCommandExecutionError(result)
        return result

    def run_remote_script(
        self,
        script_file,
        args=None,
        log_error=True,
        additional_files=None,
        hide=False,
        timeout=None,
        run_as_root=False,
        login_shell=True,
        pty=True,
    ):
        """
        Execute a script remotely on the cluster head node.

        Script is copied to the head node home dir before being executed.
        :param script_file: local path to the script to execute remotely.
        :param args: args to pass to the script when invoked.
        :param log_error: log errors.
        :param additional_files: list of additional files (full path) to copy before executing script.
        :param hide: do not print command output to the local stdout
        :param timeout: interrupt connection after N seconds, default of None = no timeout
        :param run_as_root: boolean; if True 'sudo' is prepended to the command used to run the script
        :param login_shell: boolean; passed to run_remote_command
        :param pty: if True, uses pty to execute commands; default is True.
        :return: result of the execution.
        """
        script_name = os.path.basename(script_file)
        self.__connection.put(script_file, script_name)
        if not args:
            args = []
        cmd = ["/bin/bash", script_name] + args
        if run_as_root:
            cmd.insert(0, "sudo")
        return self.run_remote_command(
            cmd,
            log_error=log_error,
            additional_files=additional_files,
            hide=hide,
            timeout=timeout,
            login_shell=login_shell,
            pty=pty,
        )

    def _copy_additional_files(self, files):
        if not files:
            local_remote_paths = []
        elif isinstance(files, list):
            local_remote_paths = [{"local": path, "remote": os.path.basename(path)} for path in files]
        else:
            # Assume files is a dict mapping local paths to remote paths
            local_remote_paths = [{"local": local, "remote": remote} for local, remote in files.items()]
        for local_remote_path in local_remote_paths or []:
            logging.info("Copying file to remote location: %s", local_remote_path)
            self.__connection.put(**local_remote_path)

    def get_remote_files(self, *args, **kwargs):
        """
        Get a remote file to the local filesystem or file-like object.

        Simply a wrapper for `.Connection.get`. Please see its documentation for
        all details.

        :param str remote:
            Remote file to download.
            May be absolute, or relative to the remote working directory.
        :param local:
            Local path to store downloaded file in, or a file-like object.
        :param bool preserve_mode:
            Whether to `os.chmod` the local file so it matches the remote
            file's mode (default: ``True``).
        :returns: A `.Result` object.
        """
        return self.__connection.get(*args, **kwargs)

    def clear_log_file(self, path: str):
        """Clear a log file in a specific path."""

        self.run_remote_command(f"sudo truncate -s 0 {path}")

    def clear_clustermgtd_log(self):
        """Clear clustermgtd log file."""

        self.clear_log_file("/var/log/parallelcluster/clustermgtd")

    def clear_slurm_resume_log(self):
        """Clear slurm_resume log file."""

        self.clear_log_file("/var/log/parallelcluster/slurm_resume.log")

    def clear_slurmctld_log(self):
        """Clear slurmctld log file."""

        self.clear_log_file("/var/log/slurmctld.log")
