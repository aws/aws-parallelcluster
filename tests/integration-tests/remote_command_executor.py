import os
import shlex

from utils import run_command


class RemoteCommandExecutor:
    """Execute remote commands on the cluster master node."""

    DEFAULT_SSH_OPTIONS = [
        "-o {0}".format(option)
        for option in [
            "StrictHostKeyChecking=no",
            "BatchMode=yes",
            "ConnectTimeout=60",
            "ServerAliveCountMax=5",
            "ServerAliveInterval=30",
        ]
    ]

    USERNAMES = {
        "alinux": "ec2-user",
        "centos6": "centos",
        "centos7": "centos",
        "ubuntu1404": "ubuntu",
        "ubuntu1604": "ubuntu",
    }

    def __init__(self, cluster):
        self.__ssh_options = list(self.DEFAULT_SSH_OPTIONS)
        self.__ssh_options.extend(["-i", cluster.ssh_key])
        self.__user_at_hostname = "{0}@{1}".format(self.USERNAMES[cluster.os], cluster.master_ip)

    def run_remote_command(self, command):
        """Execute remote command on the cluster master node."""
        if isinstance(command, str):
            command = shlex.split(command)
        return run_command(["ssh", "-n"] + self.__ssh_options + [self.__user_at_hostname] + command)

    def run_remote_script(self, script_file, args=None, additional_files=None):
        """
        Execute a script remotely on the cluster master node.

        Script is copied to the master home dir before being executed.
        :param script_file: local path to the script to execute remotely.
        :param args: args to pass to the script when invoked.
        :param additional_files: additional files to copy before executing script.
        :return: result of the execution.
        """
        """
        Execute a script remotely on the cluster master node.

        Script is copied to the master home dir before being executed
        """
        run_command(["scp"] + self.__ssh_options + [script_file, self.__user_at_hostname + ":."])
        for file in additional_files or []:
            run_command(["scp"] + self.__ssh_options + [file, self.__user_at_hostname + ":."])

        script_name = os.path.basename(script_file)
        if not args:
            args = []
        return self.run_remote_command(["/bin/bash", "--login", script_name] + args)
