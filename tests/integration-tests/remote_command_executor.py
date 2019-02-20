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
from typing import NamedTuple

from paramiko import AutoAddPolicy, SSHClient


class RemoteCommandResult(NamedTuple):
    """Wrap the results from a remote command execution."""

    return_code: int = 0
    stdout: str = ""
    stderr: str = ""


class RemoteCommandExecutionError(Exception):
    """Signal a failure in remote command execution."""

    pass


class RemoteCommandExecutor:
    """Execute remote commands on the cluster master node."""

    USERNAMES = {
        "alinux": "ec2-user",
        "centos6": "centos",
        "centos7": "centos",
        "ubuntu1404": "ubuntu",
        "ubuntu1604": "ubuntu",
    }

    def __init__(self, cluster):
        self.__ssh_client = SSHClient()
        self.__ssh_client.load_system_host_keys()
        self.__ssh_client.set_missing_host_key_policy(AutoAddPolicy())
        self.__ssh_client.connect(
            hostname=cluster.master_ip, username=self.USERNAMES[cluster.os], key_filename=cluster.ssh_key
        )
        self.__sftp_client = self.__ssh_client.open_sftp()
        self.__user_at_hostname = "{0}@{1}".format(self.USERNAMES[cluster.os], cluster.master_ip)

    def __del__(self):
        try:
            self.__ssh_client.close()
        except Exception as e:
            # Catch all exceptions if we fail to close the clients
            logging.warning("Exception raised when closing remote clients: {0}".format(e))

    def run_remote_command(self, command, log_error=True, additional_files=None, raise_on_error=True):
        """
        Execute remote command on the cluster master node.

        :param command: command to execute.
        :param log_error: log errors.
        :param additional_files: additional files to copy before executing script.
        :return: result of the execution.
        """
        if isinstance(command, list):
            command = " ".join(command)
        self._copy_additional_files(additional_files)
        logging.info("Executing remote command command on {0}: {1}".format(self.__user_at_hostname, command))
        stdin, stdout, stderr = self.__ssh_client.exec_command(command, get_pty=True)
        result = RemoteCommandResult(
            return_code=stdout.channel.recv_exit_status(),
            stdout="\n".join(stdout.read().decode().splitlines()),
            stderr="\n".join(stderr.read().decode().splitlines()),
        )
        if result.return_code != 0 and raise_on_error:
            if log_error:
                logging.error(
                    "Command {0} failed with error:\n{1}\nand output:\n{2}".format(
                        command, result.stderr, result.stdout
                    )
                )
            raise RemoteCommandExecutionError
        return result

    def run_remote_script(self, script_file, args=None, log_error=True, additional_files=None):
        """
        Execute a script remotely on the cluster master node.

        Script is copied to the master home dir before being executed.
        :param script_file: local path to the script to execute remotely.
        :param args: args to pass to the script when invoked.
        :param log_error: log errors.
        :param additional_files: additional files to copy before executing script.
        :return: result of the execution.
        """
        script_name = os.path.basename(script_file)
        self.__sftp_client.put(script_file, script_name)
        if not args:
            args = []
        return self.run_remote_command(
            ["/bin/bash", "--login", script_name] + args, log_error=log_error, additional_files=additional_files
        )

    def _copy_additional_files(self, files):
        for file in files or []:
            self.__sftp_client.put(file, os.path.basename(file))
