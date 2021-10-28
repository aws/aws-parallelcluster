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
from utils import get_username_for_os, run_command


class RemoteCommandExecutionError(Exception):
    """Signal a failure in remote command execution."""

    def __init__(self, result):
        self.result = result


class RemoteCommandExecutor:
    """Execute remote commands on the cluster head node."""

    def __init__(self, cluster, username=None, bastion=None):
        head_node_ip = cluster.head_node_ip
        if not username:
            username = get_username_for_os(cluster.os)
        connection_kwargs = {
            "host": head_node_ip,
            "user": username,
            "forward_agent": False,
            "connect_kwargs": {"key_filename": [cluster.ssh_key]},
        }
        if bastion:
            # Need to execute simple ssh command before using Connection to avoid Paramiko _check_banner error
            run_command(
                "ssh -tt -i {key_path} -o StrictHostKeyChecking=no "
                '-o ProxyCommand="ssh -tt -o StrictHostKeyChecking=no -W %h:%p -A {bastion}" '
                "-A {user}@{head_node} hostname".format(
                    key_path=cluster.ssh_key, bastion=bastion, user=username, head_node=head_node_ip
                ),
                timeout=30,
                shell=True,
            )
            connection_kwargs["gateway"] = f"ssh -W %h:%p -A {bastion}"
            connection_kwargs["forward_agent"] = True
        self.__connection = Connection(**connection_kwargs)
        self.__user_at_hostname = "{0}@{1}".format(username, head_node_ip)

    def __del__(self):
        try:
            self.__connection.close()
        except Exception as e:
            # Catch all exceptions if we fail to close the clients
            logging.warning("Exception raised when closing remote ssh client: {0}".format(e))

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
        :return: result of the execution.
        """
        if isinstance(command, list):
            command = " ".join(command)
        self._copy_additional_files(additional_files)
        logging.info("Executing remote command command on {0}: {1}".format(self.__user_at_hostname, command))
        if login_shell:
            command = "/bin/bash --login -c {0}".format(shlex.quote(command))

        result = self.__connection.run(command, warn=True, pty=True, hide=hide, timeout=timeout)
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
        :login_shell: boolean; passed to run_remote_command
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
            self.__connection.put(**local_remote_path)
