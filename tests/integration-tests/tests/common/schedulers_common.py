# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import logging
import os
import re
from abc import ABCMeta, abstractmethod

from assertpy import assert_that
from retrying import retry
from time_utils import minutes, seconds

from tests.common.utils import is_blank


class SchedulerCommands(metaclass=ABCMeta):
    """Define common scheduler commands."""

    @abstractmethod
    def __init__(self, remote_command_executor):
        self._remote_command_executor = remote_command_executor

    @abstractmethod
    def assert_job_submitted(self, submit_output, test_only: bool = False):
        """
        Assert that a job is successfully submitted.

        :param submit_output: stdout from the submit command.
        :param test_only: boolean flag defining whether the job submission was only a test (relevant for Slurm only)
        :return: the job id
        """
        pass

    @abstractmethod
    def wait_job_completed(self, job_id, timeout=None):
        """
        Wait for job completion.

        :param job_id: id of the job to wait for.
        :param timeout: max minutes to wait for job to complete
        :return: status of the job.
        """
        pass

    @abstractmethod
    def wait_job_queue_empty(self, timeout):
        """
        Wait for job queue to be empty.

        param timeout: max minutes to wait for job queue to be empty
        """
        pass

    @abstractmethod
    def get_job_exit_status(self, job_id):
        """
        Retrieve the job exist status.

        :param job_id: id of the job.
        :return: the job exist status.
        """
        pass

    @abstractmethod
    def submit_command(self, command, nodes=1, slots=None):
        """
        Submit a job to the scheduler.

        :param command: command to submit.
        :return: result from remote command execution.
        """
        pass

    @abstractmethod
    def submit_script(self, script, script_args=None, nodes=1, slots=None, additional_files=None):
        """
        Submit a job to the scheduler by using a script file.

        :param script: script to submit.
        :return: result from remote command execution.
        """
        pass

    @abstractmethod
    def assert_job_succeeded(self, job_id, children_number=0):
        """
        Assert that the job succeeded.

        :param job_id: id of the job to check.
        :param children_number: number of expected children. (e.g. array, multi-node)
        """
        pass

    @abstractmethod
    def compute_nodes_count(self):
        """Retrieve the number of compute nodes attached to the scheduler."""
        pass

    @abstractmethod
    def get_compute_nodes(self):
        """Retrieve the list of compute nodes attached to the scheduler."""
        pass

    @abstractmethod
    def wait_for_locked_node(self):
        """Wait for at least one node to be locked."""
        pass

    @abstractmethod
    def get_node_cores(self):
        """Get number of slots per instance."""
        pass

    @abstractmethod
    def set_nodes_state(self, compute_nodes, state):
        """Set nodes to down state in scheduler"""
        pass

    @abstractmethod
    def get_nodes_status(self, filter_by_nodes=None):
        """Retrieve node state/status from scheduler"""
        pass


class SlurmCommands(SchedulerCommands):
    """Implement commands for slurm scheduler."""

    def __init__(self, remote_command_executor):
        super().__init__(remote_command_executor)

    def wait_job_completed(self, job_id, timeout=None):  # noqa: D102
        if not timeout:
            timeout = 12

        @retry(
            retry_on_result=lambda result: "JobState" not in result
            or any(
                value in result
                for value in [
                    "EndTime=Unknown",
                    "JobState=RUNNING",
                    "JobState=COMPLETING",
                    "JobState=CONFIGURING",
                    "JobState=PENDING",
                ]
            ),
            wait_fixed=seconds(10),
            stop_max_delay=minutes(timeout),
        )
        def _job_status_retryer():
            result = self._remote_command_executor.run_remote_command(
                "scontrol show jobs -o {0}".format(job_id), raise_on_error=False
            )
            return result.stdout

        return _job_status_retryer()

    def wait_job_queue_empty(self, timeout=12):
        """Waits until the job queue is empty."""

        @retry(
            retry_on_result=lambda result: bool(result.stdout.strip()),  # Retry works with only boolean values
            wait_fixed=seconds(10),
            stop_max_delay=minutes(timeout),
        )
        def _job_queue_empty():
            return self._remote_command_executor.run_remote_command("squeue -h")

        return _job_queue_empty()

    def get_job_exit_status(self, job_id):  # noqa: D102
        return self.get_job_info(job_id, field="ExitCode")

    def get_job_start_time(self, job_id):  # noqa: D102
        return self.get_job_info(job_id, field="StartTime")

    def get_job_submit_time(self, job_id):  # noqa: D102
        return self.get_job_info(job_id, field="SubmitTime")

    def get_job_eligible_time(self, job_id):  # noqa: D102
        return self.get_job_info(job_id, field="EligibleTime")

    def assert_job_submitted(self, sbatch_output, test_only: bool = False):  # noqa: D102
        __tracebackhide__ = True
        if test_only:
            match = re.search(r"Job ([0-9]+) to start at", sbatch_output)
        else:
            match = re.search(r"Submitted batch job ([0-9]+)", sbatch_output)
        assert_that(match).is_not_none()
        return match.group(1)

    def assert_no_jobs_in_queue(self):
        """Checks that the job queue is now empty."""
        result = self._remote_command_executor.run_remote_command("squeue -h")
        assert_that(result.stdout).is_empty()

    def submit_command(
        self,
        command,
        nodes=0,
        slots=None,
        ntasks_per_node=None,
        host=None,
        after_ok=None,
        partition=None,
        constraint=None,
        prefer=None,
        other_options=None,
        raise_on_error=True,
        test_only=False,
    ):
        """Submit job with command."""
        job_submit_command = "--wrap='{0}'".format(command)

        return self._submit_batch_job(
            job_submit_command,
            nodes=nodes,
            slots=slots,
            ntasks_per_node=ntasks_per_node,
            host=host,
            after_ok=after_ok,
            partition=partition,
            constraint=constraint,
            prefer=prefer,
            other_options=other_options,
            raise_on_error=raise_on_error,
            test_only=test_only,
        )

    def submit_script(
        self,
        script,
        script_args=None,
        nodes=0,
        slots=None,
        ntasks_per_node=None,
        host=None,
        after_ok=None,
        partition=None,
        constraint=None,
        other_options=None,
        additional_files=None,
        raise_on_error=True,
        test_only=False,
    ):
        """Submit job with script."""
        if not additional_files:
            additional_files = []
        if not script_args:
            script_args = []
        additional_files.append(script)
        script_name = os.path.basename(script)
        job_submit_command = " {0} {1}".format(script_name, " ".join(script_args))

        return self._submit_batch_job(
            job_submit_command,
            nodes=nodes,
            slots=slots,
            ntasks_per_node=ntasks_per_node,
            host=host,
            after_ok=after_ok,
            partition=partition,
            constraint=constraint,
            other_options=other_options,
            additional_files=additional_files,
            raise_on_error=raise_on_error,
            test_only=test_only,
        )

    def _submit_batch_job(  # noqa: C901
        self,
        job_submit_command,
        nodes=0,
        slots=None,
        ntasks_per_node=None,
        host=None,
        after_ok=None,
        partition=None,
        constraint=None,
        prefer=None,
        other_options=None,
        additional_files=None,
        raise_on_error=True,
        test_only=False,
    ):
        submission_command = "sbatch"
        if host:
            submission_command += " --nodelist={0}".format(host)
        if slots:
            submission_command += " -n {0}".format(slots)
        if ntasks_per_node:
            submission_command += " --ntasks-per-node {0}".format(ntasks_per_node)
        if nodes > 0:
            submission_command += " -N {0}".format(nodes)
        if after_ok:
            submission_command += " -d afterok:{0}".format(after_ok)
        if partition:
            submission_command += " -p {0}".format(partition)
        if constraint:
            submission_command += " -C '{0}'".format(constraint)
        if prefer:
            submission_command += " --prefer='{0}'".format(prefer)
        if test_only:
            submission_command += " --test-only"
        if other_options:
            submission_command += " {0}".format(other_options)
        submission_command += " {0}".format(job_submit_command)

        if additional_files:
            return self._remote_command_executor.run_remote_command(
                submission_command, additional_files=additional_files, raise_on_error=raise_on_error
            )
        else:
            return self._remote_command_executor.run_remote_command(submission_command, raise_on_error=raise_on_error)

    def _dump_job_output(self, job_info):
        params = re.split(r"\s+", job_info)
        stderr = None
        stdout = None
        for param in params:
            match_stderr = re.match(r"StdErr=(.*)?", param)
            match_stdout = re.match(r"StdOut=(.*)?", param)
            if match_stderr:
                stderr = match_stderr.group(1)
                logging.info("stderr:" + stderr)
            if match_stdout:
                stdout = match_stdout.group(1)
                logging.info("stdout:" + stdout)
        dump_timeout = 60
        if not is_blank(stderr) or not is_blank(stdout):
            if not is_blank(stderr) and stderr == stdout:
                result = self._remote_command_executor.run_remote_command(
                    f'echo "stderr/stdout:" && cat {stderr}', timeout=dump_timeout
                )
                logging.error(result.stdout)
            else:
                if not is_blank(stderr):
                    stderr_result = self._remote_command_executor.run_remote_command(
                        f'echo "stderr" && cat {stderr}', timeout=dump_timeout
                    )
                    logging.error(stderr_result.stdout)

                if not is_blank(stdout):
                    stdout_result = self._remote_command_executor.run_remote_command(
                        f'echo "stdout" && cat {stdout}', timeout=dump_timeout
                    )
                    logging.error(stdout_result.stdout)
        else:
            logging.error("Unable to retrieve job output.")

    def assert_job_succeeded(self, job_id, children_number=0):  # noqa: D102
        self.assert_job_state(job_id, "COMPLETED")

    def assert_job_state(self, job_id, expected_state):  # noqa: D102
        result = self._remote_command_executor.run_remote_command("scontrol show jobs -o {0}".format(job_id))
        try:
            assert_that(result.stdout).contains(f"JobState={expected_state}")
        except AssertionError:
            logging.error("JobState of jobid %s not in %s:\n%s", job_id, expected_state, result.stdout)
            self._dump_job_output(result.stdout)
            raise

    def compute_nodes_count(self, filter_by_partition=None):  # noqa: D102
        return len(self.get_compute_nodes(filter_by_partition))

    def get_compute_nodes(self, filter_by_partition=None, all_nodes=None):  # noqa: D102
        command = "sinfo --Node --noheader"
        if filter_by_partition:
            command += " --partition {}".format(filter_by_partition)
        # Get nodename and state only (default partition contains *)
        # Filter out nodes that are not responding or in power saving states
        if not all_nodes:
            command += " -o '%N %t' | grep -v '[*#~%]'"
        command += " | awk '{print $1}'"
        result = self._remote_command_executor.run_remote_command(command)
        return result.stdout.splitlines()

    def get_unique_static_nodes(self):
        """Get list of unique static node names (useful if custom partitions are included in a cluster)"""
        command = "scontrol show nodes -o  | grep -iE 'State=IDLE\+CLOUD ' | awk '/^NodeName/ {print $1}'"  # noqa: W605
        result = self._remote_command_executor.run_remote_command(command)
        logging.info("All running nodes: %s", result.stdout)
        return result.stdout.splitlines()

    def get_nodename_from_ip(self, ip: str):
        """Get the nodename from IP address"""
        command = (
            f"scontrol show nodes --json | "
            f'jq -r --arg ip "{ip}" \'.nodes[] | '
            f"select(.address == $ip) | .hostname'"
        )  # noqa: W605
        result = self._remote_command_executor.run_remote_command(command)
        logging.info(f"Nodename for {ip} is: {result.stdout}")
        return result.stdout

    def get_batch_host_for_job(self, job_id: str):
        """Get the node list for a given job."""
        command = f"scontrol show jobs {job_id} --json | jq -r '.jobs[].batch_host'"  # noqa: W605
        result = self._remote_command_executor.run_remote_command(command)
        logging.info(f"Nodename for {job_id} is: {result.stdout}")
        return result.stdout

    @retry(retry_on_result=lambda result: "drain" not in result, wait_fixed=seconds(3), stop_max_delay=minutes(5))
    def wait_for_locked_node(self):  # noqa: D102
        return self._remote_command_executor.run_remote_command("sinfo -h -o '%t'").stdout

    def get_node_cores(self, partition=None):
        """Return number of slots from the scheduler."""
        check_core_cmd = "sinfo -o '%c' -h"
        if partition:
            check_core_cmd += " -p {}".format(partition)
        result = self._remote_command_executor.run_remote_command(check_core_cmd)
        return re.search(r"(\d+)", result.stdout).group(1)

    def get_partitions(self):
        """Return partitions in the cluster."""
        check_partitions_cmd = "sinfo --format=%R -h"
        result = self._remote_command_executor.run_remote_command(check_partitions_cmd)
        return result.stdout.splitlines()

    def get_partition_info(self, partition, field=None):
        """Return partitions details. If field is provided, only the fieed is returned."""
        result = self._remote_command_executor.run_remote_command(
            "scontrol show partition {0}".format(partition)
        ).stdout
        if field is not None:
            match = re.search(rf"(\s{field})=(\S*)", result)
            return match.group(2)
        return result

    def get_job_info(self, job_id, field=None):
        """Return job details from slurm. If field is provided, only the field is returned"""
        result = self._remote_command_executor.run_remote_command("scontrol show jobs -o {0}".format(job_id)).stdout
        if field is not None:
            match = re.search(rf"(\s{field})=(\S*)", result)
            return match.group(2)
        return result

    def cancel_job(self, job_id):
        """Cancel a job"""
        return self._remote_command_executor.run_remote_command("scancel {}".format(job_id))

    def set_nodes_state(self, compute_nodes, state):
        """Put nodes into a state."""
        self._remote_command_executor.run_remote_command(
            "sudo -i scontrol update NodeName={} state={} reason=testing".format(",".join(compute_nodes), state)
        )

    def set_partition_state(self, partition, state):
        """Put partition into a state."""
        self._remote_command_executor.run_remote_command(
            "sudo -i scontrol update partition={} state={}".format(partition, state)
        )

    def get_nodes_status(self, filter_by_nodes=None):
        """Retrieve node state/status from scheduler"""
        result = self._remote_command_executor.run_remote_command(
            "sinfo -N --long -h | awk '{print$1, $4}'"
        ).stdout.splitlines()
        current_node_states = {}
        for entry in result:
            nodename, state = entry.split()
            current_node_states[nodename] = state
        return (
            {node: current_node_states.get(node, "Unable to retrieve state") for node in filter_by_nodes}
            if filter_by_nodes
            else current_node_states
        )

    @retry(wait_fixed=seconds(15), stop_max_delay=minutes(8))
    def wait_nodes_status(self, status, filter_by_nodes=None):
        """Wait nodes to reach the status specified"""
        nodes_status = self.get_nodes_status(filter_by_nodes)
        for node_status in nodes_status.values():
            assert_that(node_status).is_equal_to(status)

    def get_node_addr_host(self):
        """Return a list of nodename, nodeaddr, nodehostname entries."""
        # q1-dy-c5xlarge-1 172.31.4.241 q1-dy-c5xlarge-1
        # q1-dy-c5xlarge-2 172.31.4.136 q1-dy-c5xlarge-2
        # q1-dy-c5xlarge-3 q1-dy-c5xlarge-3 q1-dy-c5xlarge-3
        return self._remote_command_executor.run_remote_command(
            "sinfo -O NodeList:' ',NodeAddr:' ',NodeHost:' ' -N -h | awk '{print$1, $2, $3}'"
        ).stdout.splitlines()

    def get_node_addr(self, node_name):
        """Get NodeAddr attribute of a slurm compute node."""
        result = self._remote_command_executor.run_remote_command(f"scontrol show nodes {node_name}").stdout
        node_addr = re.search(r"NodeAddr=(.*) NodeHostName", result).group(1)
        return node_addr

    def get_job_instance_id(self, job_id):
        """Return the id of the EC2 instance the job is running on, as reported by Slurm."""
        node_name = self._remote_command_executor.run_remote_command(
            f'scontrol show jobs {job_id} --json | jq -r ".jobs[0].batch_host"'
        ).stdout.strip()
        return self._remote_command_executor.run_remote_command(
            f'scontrol show nodes {node_name} --json | jq -r ".nodes[0].instance_id"'
        ).stdout.strip()

    def submit_command_and_assert_job_accepted(self, submit_command_args):
        """Submit a command and assert the job is accepted by scheduler."""
        result = self.submit_command(**submit_command_args)
        return self.assert_job_submitted(result.stdout, test_only=submit_command_args.get("test_only", False))

    def submit_command_and_assert_job_succeeded(self, job_command_args):
        """Submit a command and assert the job succeeded."""
        result = self.submit_command(**job_command_args)
        job_id = self.assert_job_submitted(result.stdout)
        self.wait_job_completed(job_id)
        self.assert_job_succeeded(job_id)

    def submit_command_and_get_output(self, job_command_args):
        """Submit a command, assert the job succeeded, and return the job's stdout.

        Reads back `slurm-<job_id>.out`, which sbatch writes to the job's submit directory.
        """
        result = self.submit_command(**job_command_args)
        job_id = self.assert_job_submitted(result.stdout)
        self.wait_job_completed(job_id)
        self.assert_job_succeeded(job_id)
        return self._remote_command_executor.run_remote_command(f"cat slurm-{job_id}.out").stdout

    def run_command_and_assert_job_succeeded(self, command, nodes=1, timeout=12):
        """Run a command as a step and assert the job succeeded.

        salloc runs srun on the head node rather than on the batch host as sbatch does, so the stdio of a
        wide step does not aggregate on a compute node.
        """
        result = self._remote_command_executor.run_remote_command(
            f"salloc -N {nodes} srun {command}", timeout=minutes(timeout) // 1000
        )
        allocation = re.search(r"Granted job allocation (\d+)", f"{result.stdout}\n{result.stderr}")
        if not allocation:
            raise Exception(f"Could not find the job id in the salloc output: {result.stdout} {result.stderr}")
        job_id = allocation.group(1)
        self.wait_job_completed(job_id, timeout=timeout)
        self.assert_job_succeeded(job_id)

    def get_partition_state(self, partition):
        """Get the state of the partition."""
        return self._remote_command_executor.run_remote_command(
            f'scontrol show partition={partition} | grep -oP "State=\\K(\\S+)"'
        ).stdout

    @retry(wait_fixed=seconds(10), stop_max_delay=minutes(13))
    def wait_job_running(self, job_id):
        """Wait till job starts running."""
        result = self._remote_command_executor.run_remote_command("scontrol show jobs -o {0}".format(job_id))
        assert_that(result.stdout).contains("JobState=RUNNING")

    @retry(wait_fixed=seconds(10), stop_max_delay=minutes(13))
    def wait_job_requeued(self, job_id, times=1):
        """Wait till the job has been requeued at least `times` times (Restarts>=times)."""
        restarts = self.get_job_info(job_id, field="Restarts")
        assert_that(int(restarts)).is_greater_than_or_equal_to(times)

    def get_node_info(self, nodename):
        """Get node info."""
        return self._remote_command_executor.run_remote_command("scontrol show nodes {0}".format(nodename)).stdout

    def get_conf_param(self, param):
        """Get value of configuration parameter."""
        result = self._remote_command_executor.run_remote_command("scontrol show config | grep {0}".format(param))
        match = re.search(r"(\s+)= (.*)$", result.stdout)
        return match.group(2)

    def get_node_attribute(self, nodename, attribute):
        """Get node attribute."""
        # This method is implemented with `sinfo`, so please refer to the `sinfo` documentation
        check_attribute_cmd = f"sinfo --noheader --nodes={nodename} -O {attribute}:100"
        result = self._remote_command_executor.run_remote_command(check_attribute_cmd)
        match = re.search(r"(\S*)\s*$", result.stdout)
        return match.group(1)

    def reboot_compute_node(self, nodename, asap: bool):
        """Reboot a compute node via Slurm."""
        asap_string = "asap" if asap else ""
        command = f"sudo -i scontrol reboot {asap_string} {nodename}"
        self._remote_command_executor.run_remote_command(command)

    def get_accounting_users(
        self, fields=("user", "account", "adminlevel", "coordinators", "defaultaccount", "defaultwckey")
    ):
        """Return a list of scheduler user accounts as a list of dicts."""
        users = self._remote_command_executor.run_remote_command(
            f"sacctmgr list users -nP Format={','.join(fields)}"
        ).stdout
        return (dict(zip(fields, columns)) for columns in SlurmCommands._split_accounting_results(users))

    def get_accounting_job_records(
        self,
        job_id,
        fields=("jobid", "jobname", "partition", "account", "alloccpus", "state", "exitcode"),
        clusters=None,
    ):
        """Return job steps of {job_id} as a series of dicts."""
        command = f"sacct -nP -j {job_id} -o {','.join(fields)}"
        if clusters:
            command = command + f" --clusters {clusters}"
        records = self._remote_command_executor.run_remote_command(command).stdout
        return (dict(zip(fields, columns)) for columns in SlurmCommands._split_accounting_results(records))

    @staticmethod
    def _split_accounting_results(results):
        return (result.split("|") for result in results.splitlines())


def get_scheduler_commands(remote_command_executor, scheduler):
    scheduler_commands = {
        "slurm": SlurmCommands,
    }
    return scheduler_commands[scheduler](remote_command_executor)
