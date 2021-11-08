import logging
import os

from remote_command_executor import RemoteCommandExecutor
from utils import run_command

from tests.common.schedulers_common import get_scheduler_commands


class ClusterUser:
    """Class to represent a cluster user in a multi-user environment."""

    def __init__(self, user_num, test_datadir, cluster, scheduler, default_user_remote_command_executor):
        self._default_user_remote_command_executor = default_user_remote_command_executor
        self.user_num = user_num  # TODO: don't need to keep this?
        self.alias = f"PclusterUser{user_num}"
        self.ssh_keypair_path_prefix = str(test_datadir / self.alias)
        self.ssh_private_key_path = f"{self.ssh_keypair_path_prefix}.pem"
        self.ssh_public_key_path = f"{self.ssh_private_key_path}.pub"
        # TODO: randomly generate this. It's hardcoded here because it's also hard-coded in the script
        #       that creates users as part of the directory stack.
        self.password = "ApplesBananasCherries!"
        self._configure_public_ssh_keys()
        self._personalized_remote_command_executor = RemoteCommandExecutor(
            cluster, username=self.alias, alternate_ssh_key=self.ssh_private_key_path
        )
        self._personalized_scheduler_commands = get_scheduler_commands(
            scheduler, self._personalized_remote_command_executor
        )

    def _generate_ssh_keypair(self):
        """Create an RSA SSH keypair for the user."""
        logging.info("Creating SSH keypair for user %s", self.alias)
        cmd = [
            "ssh-keygen",
            "-q",
            "-f",
            self.ssh_keypair_path_prefix,
            "-t",
            "rsa",
            "-N",
            "",
            "-C",
            f"multi-user integ test {self.alias}",
        ]
        run_command(cmd)

    def _copy_public_ssh_key_to_authorized_keys(self):
        """Copy user's public SSH key to authorized keys file on cluster's head node."""
        # TODO: do this with a password instead of creating home directory. this ensures
        #       password auth works as expected as does automatic creation of home directory
        user_home_dir = f"/home/{self.alias}"
        user_ssh_dir = f"{user_home_dir}/.ssh"
        public_key_basename = os.path.basename(self.ssh_public_key_path)
        authorized_keys_path = f"{user_ssh_dir}/authorized_keys"
        cmd = " && ".join(
            [
                f"sudo mkdir -p {user_ssh_dir}",
                f"sudo chmod 700 {user_ssh_dir}",
                f"cat {public_key_basename} | sudo tee -a {authorized_keys_path}",
                f"sudo chmod 644 {authorized_keys_path}",
                f"sudo chown -R {self.alias} {user_home_dir}",
            ]
        )
        self._default_user_remote_command_executor.run_remote_command(cmd, additional_files=[self.ssh_public_key_path])

    def _configure_public_ssh_keys(self):
        self._generate_ssh_keypair()
        self._copy_public_ssh_key_to_authorized_keys()

    def submit_script(self, **submit_comand_kwargs):
        """Wrapper around SchedulerCommand's submit_script method."""
        return self._personalized_scheduler_commands.submit_script(**submit_comand_kwargs)

    def assert_job_succeeded(self, job_id):
        """Wrapper around SchedulerCommand's assert_job_succeded method."""
        self._personalized_scheduler_commands.assert_job_succeeded(job_id)

    def cleanup(self):
        """Cleanup resources associated with this user."""
        user_home_dir = f"/home/{self.alias}"
        logging.info("Removing home directory for user %s (%s)", self.alias, user_home_dir)
        self._default_user_remote_command_executor.run_remote_command(f"sudo rm -rf {user_home_dir}")
