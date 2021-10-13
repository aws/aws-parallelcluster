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


class SchedulerCommands(metaclass=ABCMeta):
    """Define common scheduler commands."""

    @abstractmethod
    def __init__(self, remote_command_executor):
        self._remote_command_executor = remote_command_executor

    @abstractmethod
    def assert_job_submitted(self, submit_output):
        """
        Assert that a job is successfully submitted.

        :param submit_output: stdout from the submit command.
        :return: the job id
        """
        pass

    @abstractmethod
    def wait_job_completed(self, job_id):
        """
        Wait for job completion.

        :param job_id: id of the job to wait for.
        :return: status of the job.
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
    def get_nodes_status(self):
        """Retrieve node state/status from scheduler"""
        pass


class AWSBatchCommands(SchedulerCommands):
    """Implement commands for awsbatch scheduler."""

    def __init__(self, remote_command_executor):
        super().__init__(remote_command_executor)

    @retry(
        retry_on_result=lambda result: "FAILED" not in result and any(status != "SUCCEEDED" for status in result),
        wait_fixed=seconds(7),
        stop_max_delay=minutes(15),
    )
    def wait_job_completed(self, job_id):  # noqa: D102
        result = self._remote_command_executor.run_remote_command("awsbstat -d {0}".format(job_id), log_output=True)
        return re.findall(r"status\s+: (.+)", result.stdout)

    def get_job_exit_status(self, job_id):  # noqa: D102
        return self.wait_job_completed(job_id)

    def assert_job_submitted(self, awsbsub_output):  # noqa: D102
        __tracebackhide__ = True
        match = re.search(r"Job ([a-z0-9\-]{36}) \(.+\) has been submitted.", awsbsub_output)
        assert_that(match).is_not_none()
        return match.group(1)

    def submit_command(self, command, nodes=1, slots=None):  # noqa: D102
        return self._remote_command_executor.run_remote_command('echo "{0}" | awsbsub -n {1}'.format(command, nodes))

    def submit_script(self, script, script_args=None, nodes=1, additional_files=None, slots=None):  # noqa: D102
        raise NotImplementedError

    def assert_job_succeeded(self, job_id, children_number=0):  # noqa: D102
        __tracebackhide__ = True
        status = self.get_job_exit_status(job_id)
        assert_that(status).is_length(1 + children_number)
        assert_that(status).contains_only("SUCCEEDED")

    def compute_nodes_count(self):  # noqa: D102
        raise NotImplementedError

    def get_compute_nodes(self):  # noqa: D102
        raise NotImplementedError

    def wait_for_locked_node(self):  # noqa: D102
        raise NotImplementedError

    def get_node_cores(self):  # noqa: D102
        raise NotImplementedError

    def set_nodes_state(self, compute_nodes, state):
        """Not implemented."""
        raise NotImplementedError

    def get_nodes_status(self):
        """Not implemented."""
        raise NotImplementedError


class SlurmCommands(SchedulerCommands):
    """Implement commands for slurm scheduler."""

    def __init__(self, remote_command_executor):
        super().__init__(remote_command_executor)

    @retry(
        retry_on_result=lambda result: "JobState" not in result
        or any(
            value in result
            for value in ["EndTime=Unknown", "JobState=RUNNING", "JobState=COMPLETING", "JobState=CONFIGURING"]
        ),
        wait_fixed=seconds(10),
        stop_max_delay=minutes(12),
    )
    def wait_job_completed(self, job_id):  # noqa: D102
        result = self._remote_command_executor.run_remote_command(
            "scontrol show jobs -o {0}".format(job_id), raise_on_error=False
        )
        return result.stdout

    def get_job_exit_status(self, job_id):  # noqa: D102
        result = self._remote_command_executor.run_remote_command("scontrol show jobs -o {0}".format(job_id))
        match = re.search(r"ExitCode=(.+?) ", result.stdout)
        return match.group(1)

    def assert_job_submitted(self, sbatch_output):  # noqa: D102
        __tracebackhide__ = True
        match = re.search(r"Submitted batch job ([0-9]+)", sbatch_output)
        assert_that(match).is_not_none()
        return match.group(1)

    def submit_command(
        self,
        command,
        nodes=0,
        slots=None,
        host=None,
        after_ok=None,
        partition=None,
        constraint=None,
        other_options=None,
        raise_on_error=True,
    ):
        """Submit job with command."""
        job_submit_command = "--wrap='{0}'".format(command)

        return self._submit_batch_job(
            job_submit_command,
            nodes,
            slots,
            host,
            after_ok,
            partition,
            constraint,
            other_options,
            raise_on_error=raise_on_error,
        )

    def submit_script(
        self,
        script,
        script_args=None,
        nodes=0,
        slots=None,
        host=None,
        after_ok=None,
        partition=None,
        constraint=None,
        other_options=None,
        additional_files=None,
        raise_on_error=True,
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
            nodes,
            slots,
            host,
            after_ok,
            partition,
            constraint,
            other_options,
            additional_files,
            raise_on_error=raise_on_error,
        )

    def _submit_batch_job(
        self,
        job_submit_command,
        nodes=0,
        slots=None,
        host=None,
        after_ok=None,
        partition=None,
        constraint=None,
        other_options=None,
        additional_files=None,
        raise_on_error=True,
    ):
        submission_command = "sbatch"
        if host:
            submission_command += " --nodelist={0}".format(host)
        if slots:
            submission_command += " -n {0}".format(slots)
        if nodes > 0:
            submission_command += " -N {0}".format(nodes)
        if after_ok:
            submission_command += " -d afterok:{0}".format(after_ok)
        if partition:
            submission_command += " -p {0}".format(partition)
        if constraint:
            submission_command += " -C '{0}'".format(constraint)
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
        if stderr is not None or stdout is not None:
            if stderr == stdout:
                result = self._remote_command_executor.run_remote_command(f'echo "stderr/stdout:" && cat {stderr}')
                logging.error(result.stdout)
            else:
                if stderr is not None:
                    stderr_result = self._remote_command_executor.run_remote_command(f'echo "stderr" && cat {stderr}')
                    logging.error(stderr_result.stdout)

                if stdout is not None:
                    stdout_result = self._remote_command_executor.run_remote_command(f'echo "stdout" && cat {stdout}')
                    logging.error(stdout_result.stdout)
        else:
            logging.error("Unable to retrieve job output.")

    def assert_job_succeeded(self, job_id, children_number=0):  # noqa: D102
        result = self._remote_command_executor.run_remote_command("scontrol show jobs -o {0}".format(job_id))
        try:
            assert_that(result.stdout).contains("JobState=COMPLETED")
        except AssertionError:
            self._dump_job_output(result.stdout)
            raise

    def compute_nodes_count(self, filter_by_partition=None):  # noqa: D102
        return len(self.get_compute_nodes(filter_by_partition))

    def get_compute_nodes(self, filter_by_partition=None):  # noqa: D102
        command = "sinfo --Node --noheader --responding"
        if filter_by_partition:
            command += " --partition {}".format(filter_by_partition)
        # Print first and fourth columns to get nodename and state only (default partition contains *)
        # Filter out nodes that are not responding or in power saving states
        command += " | awk '{print $1, $4}' | grep -v '[*#~%]' | awk '{print $1}'"
        result = self._remote_command_executor.run_remote_command(command)
        return result.stdout.splitlines()

    @retry(retry_on_result=lambda result: "drain" not in result, wait_fixed=seconds(3), stop_max_delay=minutes(5))
    def wait_for_locked_node(self):  # noqa: D102
        return self._remote_command_executor.run_remote_command("/opt/slurm/bin/sinfo -h -o '%t'").stdout

    def get_node_cores(self, partition=None):
        """Return number of slots from the scheduler."""
        check_core_cmd = "/opt/slurm/bin/sinfo -o '%c' -h"
        if partition:
            check_core_cmd += " -p {}".format(partition)
        result = self._remote_command_executor.run_remote_command(check_core_cmd)
        return re.search(r"(\d+)", result.stdout).group(1)

    def get_job_info(self, job_id):
        """Return job details from slurm"""
        return self._remote_command_executor.run_remote_command("scontrol show jobs -o {0}".format(job_id)).stdout

    def cancel_job(self, job_id):
        """Cancel a job"""
        return self._remote_command_executor.run_remote_command("scancel {}".format(job_id))

    def set_nodes_state(self, compute_nodes, state):
        """Put nodes into a state."""
        self._remote_command_executor.run_remote_command(
            "sudo /opt/slurm/bin/scontrol update NodeName={} state={} reason=testing".format(
                ",".join(compute_nodes), state
            )
        )

    def set_partition_state(self, partition, state):
        """Put partition into a state."""
        self._remote_command_executor.run_remote_command(
            "sudo /opt/slurm/bin/scontrol update partition={} state={}".format(partition, state)
        )

    def get_nodes_status(self, filter_by_nodes=None):
        """Retrieve node state/status from scheduler"""
        result = self._remote_command_executor.run_remote_command(
            "/opt/slurm/bin/sinfo -N --long -h | awk '{print$1, $4}'"
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

    def get_node_addr_host(self):
        """Return a list of nodename, nodeaddr, nodehostname entries."""
        # q1-dy-c5xlarge-1 172.31.4.241 q1-dy-c5xlarge-1
        # q1-dy-c5xlarge-2 172.31.4.136 q1-dy-c5xlarge-2
        # q1-dy-c5xlarge-3 q1-dy-c5xlarge-3 q1-dy-c5xlarge-3
        return self._remote_command_executor.run_remote_command(
            "/opt/slurm/bin/sinfo -O NodeList:' ',NodeAddr:' ',NodeHost:' ' -N -h | awk '{print$1, $2, $3}'"
        ).stdout.splitlines()

    def submit_command_and_assert_job_accepted(self, submit_command_args):
        """Submit a command and assert the job is accepted by scheduler."""
        result = self.submit_command(**submit_command_args)
        return self.assert_job_submitted(result.stdout)

    def get_partition_state(self, partition):
        """Get the state of the partition."""
        return self._remote_command_executor.run_remote_command(
            f'/opt/slurm/bin/scontrol show partition={partition} | grep -oP "State=\\K(\\S+)"'
        ).stdout

    @retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))
    def wait_job_running(self, job_id):
        """Wait till job starts running."""
        result = self._remote_command_executor.run_remote_command("scontrol show jobs -o {0}".format(job_id))
        assert_that(result.stdout).contains("JobState=RUNNING")


class TorqueCommands(SchedulerCommands):
    """Implement commands for torque scheduler."""

    def __init__(self, remote_command_executor):
        super().__init__(remote_command_executor)

    @retry(
        retry_on_result=lambda result: "job_state = C" not in result, wait_fixed=seconds(3), stop_max_delay=minutes(12)
    )
    def wait_job_completed(self, job_id):  # noqa: D102
        result = self._remote_command_executor.run_remote_command("qstat -f {0}".format(job_id))
        return result.stdout

    def get_job_exit_status(self, job_id):  # noqa: D102
        result = self._remote_command_executor.run_remote_command("qstat -f {0}".format(job_id))
        match = re.search(r"exit_status = (\d+)", result.stdout)
        return match.group(1)

    def assert_job_submitted(self, qsub_output):  # noqa: D102
        __tracebackhide__ = True
        # qsub_output is the id of the job in case of successful submissions
        id = qsub_output
        # check that the job exists
        self._remote_command_executor.run_remote_command("qstat -f {0}".format(id))
        return id

    def submit_command(self, command, nodes=1, slots=None, after_ok=None):  # noqa: D102
        flags = "-l nodes={0}:ppn={1}".format(nodes or 1, slots or 1)
        if after_ok:
            flags += " -W depend=afterok:{0}".format(after_ok)
        return self._remote_command_executor.run_remote_command(
            "echo '{0}' | qsub {1}".format(command, flags), raise_on_error=False
        )

    def submit_script(self, script, script_args=None, nodes=1, slots=None, additional_files=None):  # noqa: D102
        if not additional_files:
            additional_files = []
        script_name = os.path.basename(script)
        additional_files.append(script)
        flags = "-l nodes={0}:ppn={1}".format(nodes or 1, slots or 1)
        if script_args:
            flags += ' -F "{0}"'.format(" ".join(script_args))
        return self._remote_command_executor.run_remote_command(
            "qsub {0} {1}".format(flags, script_name), additional_files=additional_files
        )

    def assert_job_succeeded(self, job_id, children_number=0):  # noqa: D102
        __tracebackhide__ = True
        status = self.get_job_exit_status(job_id)
        assert_that(status).is_equal_to("0")

    def compute_nodes_count(self):  # noqa: D102
        result = self._remote_command_executor.run_remote_command("echo $(( $(pbsnodes -l all | wc -l) - 1))")
        # split()[-1] to extract last line and trim whitespaces
        return int(result.stdout.split()[-1])

    def get_compute_nodes(self):  # noqa: D102
        result = self._remote_command_executor.run_remote_command(
            "pbsnodes -l all | grep -v $(hostname) | awk '{print $1}'"
        )
        return result.stdout.splitlines()

    @retry(retry_on_result=lambda result: "offline" not in result, wait_fixed=seconds(5), stop_max_delay=minutes(5))
    def wait_for_locked_node(self):  # noqa: D102
        # discard the first node since that is the head node
        return self._remote_command_executor.run_remote_command(r'pbsnodes | grep -e "\sstate = " | tail -n +2').stdout

    def get_node_cores(self):
        """Return number of slots from the scheduler."""
        result = self._remote_command_executor.run_remote_command("pbsnodes | tail -n +10")
        return re.search(r"np = (\d+)", result.stdout).group(1)

    def set_nodes_state(self, compute_nodes, state):
        """Not implemented."""
        raise NotImplementedError

    def get_nodes_status(self):
        """Not implemented."""
        raise NotImplementedError


def get_scheduler_commands(scheduler, remote_command_executor):
    scheduler_commands = {
        "awsbatch": AWSBatchCommands,
        "slurm": SlurmCommands,
        "torque": TorqueCommands,
    }
    return scheduler_commands[scheduler](remote_command_executor)
