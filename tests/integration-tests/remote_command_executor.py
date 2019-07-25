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


class RemoteCommandExecutionError(Exception):
    """Signal a failure in remote command execution."""

    def __init__(self, result):
        self.result = result


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
        self.__connection = Connection(
            host=cluster.master_ip,
            user=self.USERNAMES[cluster.os],
            forward_agent=False,
            connect_kwargs={"key_filename": cluster.ssh_key},
        )
        self.__user_at_hostname = "{0}@{1}".format(self.USERNAMES[cluster.os], cluster.master_ip)

    def __del__(self):
        try:
            self.__connection.close()
        except Exception as e:
            # Catch all exceptions if we fail to close the clients
            logging.warning("Exception raised when closing remote ssh client: {0}".format(e))

    def run_remote_command(
        self, command, log_error=True, additional_files=None, raise_on_error=True, login_shell=True, hide=False
    ):
        """
        Execute remote command on the cluster master node.

        :param command: command to execute.
        :param log_error: log errors.
        :param additional_files: additional files to copy before executing script.
        :param raise_on_error: if True raises a RemoteCommandExecutionError on failures
        :param login_shell: if True prepends /bin/bash --login -c to the given command
        :param hide: do not print command output to the local stdout
        :return: result of the execution.
        """
        if isinstance(command, list):
            command = " ".join(command)
        self._copy_additional_files(additional_files)
        logging.info("Executing remote command command on {0}: {1}".format(self.__user_at_hostname, command))
        if login_shell:
            command = "/bin/bash --login -c {0}".format(shlex.quote(command))

        result = self.__connection.run(command, warn=True, pty=True, hide=hide)
        result.stdout = "\n".join(result.stdout.splitlines())
        result.stderr = "\n".join(result.stderr.splitlines())
        if result.failed and raise_on_error:
            if log_error:
                logging.error(
                    "Command {0} failed with error:\n{1}\nand output:\n{2}".format(
                        command, result.stderr, result.stdout
                    )
                )
            raise RemoteCommandExecutionError(result)
        return result

    def run_remote_script(self, script_file, args=None, log_error=True, additional_files=None, hide=False):
        """
        Execute a script remotely on the cluster master node.

        Script is copied to the master home dir before being executed.
        :param script_file: local path to the script to execute remotely.
        :param args: args to pass to the script when invoked.
        :param log_error: log errors.
        :param additional_files: additional files to copy before executing script.
        :param hide: do not print command output to the local stdout
        :return: result of the execution.
        """
        script_name = os.path.basename(script_file)
        self.__connection.put(script_file, script_name)
        if not args:
            args = []
        return self.run_remote_command(
            ["/bin/bash", "--login", script_name] + args,
            log_error=log_error,
            additional_files=additional_files,
            hide=hide,
        )

    def _copy_additional_files(self, files):
        for file in files or []:
            self.__connection.put(file, os.path.basename(file))
