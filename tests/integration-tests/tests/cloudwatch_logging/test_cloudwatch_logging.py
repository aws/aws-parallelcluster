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
import json
import logging
import random
import re
import string
from os import environ
from pathlib import Path

import boto3
import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from tests.common.schedulers_common import get_scheduler_commands

LOGGER = logging.getLogger(__name__)


class CloudWatchLoggingClusterState:
    """
    Encapsulate the state of a running cluster as it pertains to the CloudWatch logging feature.

    The state is stored in the self._cluster_log_state dict. Here is an example of what that
    structure might look like for a cluster with one compute node, each containing one log:
    {
        "MasterServer": {
            "node_role": "MasterServer",
            "hostname": "ip-10-0-127-157.us-west-1.compute.internal",
            "instance_id": "i-01be4c67943df785d",
            "logs": {
                "/var/log/cfn-init-cmd.log": {
                    "file_path": "/var/log/cfn-init-cmd.log",
                    "log_stream_name": "cfn-init-cmd",
                    "exists": true,
                    "is_empty": false,
                    "tail": "2019-11-01 21:58:07,407 P1974 [INFO] Completed successfully."
                }
            },
            "agent_status": "running"
        },
        "ComputeFleet": {
            "ip-10-0-155-82.us-west-1.compute.internal": {
                "node_role": "ComputeFleet",
                "hostname": "ip-10-0-155-82.us-west-1.compute.internal",
                "instance_id": "i-0d80db39340ce94d8",
                "logs": {
                    "/var/spool/torque/client_logs/*": {
                        "file_path": "/var/spool/torque/client_logs/*",
                        "log_stream_name": "torque-client",
                        "exists": true,
                        "is_empty": false,
                        "tail": "2019-11-01 22:00:14.7647 TORQUE authd daemon started"
                    }
                },
                "agent_status": "running"
            }
        }
    }
    """

    def __init__(self, scheduler, os, cluster, data_retriever):
        """Get the state of the cluster as it pertains to the CloudWatch logging feature."""
        self.scheduler = scheduler
        self.platform = self._base_os_to_platform(os)
        self.cluster = cluster
        self.remote_command_executor = RemoteCommandExecutor(self.cluster)
        self.scheduler_commands = get_scheduler_commands(self.scheduler, self.remote_command_executor)
        self.data_retriever = data_retriever
        self._relevant_logs = {"MasterServer": [], "ComputeFleet": []}
        self._cluster_log_state = {"MasterServer": {}, "ComputeFleet": {}}
        self._set_cluster_log_state()

    def get_logs_state(self):
        """Get the state of the log files applicable to each of the cluster's EC2 instances."""
        desired_keys = ["hostname", "instance_id", "node_role", "agent_status", "logs"]
        states = [{key: self._cluster_log_state.get("MasterServer").get(key) for key in desired_keys}]
        states.extend(
            [
                {key: host_dict[key] for key in desired_keys}
                for hostname, host_dict in self._cluster_log_state.get("ComputeFleet").items()
            ]
        )
        assert_that(states).is_length(self.scheduler_commands.compute_nodes_count() + 1)  # computes + master
        return states

    def _dump_cluster_log_state(self):
        """Dump the JSON-ified string of self._cluster_log_state for debugging purposes."""
        return json.dumps(self._cluster_log_state, indent=4)

    @staticmethod
    def _base_os_to_platform(base_os):
        """Turn the name of a base OS into the platform."""
        # Special case: alinux is how the config file refers to amazon linux, but in the chef cookbook
        # (and the cloudwatch log config produced by it) the platform is "amazon".
        translations = {"alinux": "amazon"}
        no_digits = base_os.rstrip(string.digits)
        return translations.get(no_digits, no_digits)

    def _set_master_instance(self, instance):
        """Set the master instance field in self.cluster_log_state."""
        self._cluster_log_state.get("MasterServer").update(
            {
                "node_role": "MasterServer",
                "hostname": instance.get("PrivateDnsName"),
                "instance_id": instance.get("InstanceId"),
            }
        )

    def _add_compute_instance(self, instance):
        """Update the cluster's log state by adding a compute node."""
        self._cluster_log_state["ComputeFleet"][instance.get("PrivateDnsName")] = {
            "node_role": "ComputeFleet",
            "hostname": instance.get("PrivateDnsName"),
            "instance_id": instance.get("InstanceId"),
        }

    def _get_initial_cluster_log_state(self):
        """Get EC2 instances belonging to this cluster. Figure out their roles in the cluster."""
        for instance in self.data_retriever.get_ec2_instances():
            tags = {tag.get("Key"): tag.get("Value") for tag in instance.get("Tags", [])}
            if tags.get("ClusterName", "") != self.cluster.name:
                continue
            elif tags.get("Name", "") == "Master":
                self._set_master_instance(instance)
            else:
                self._add_compute_instance(instance)
        LOGGER.debug("After getting initial cluster state:\n{}".format(self._dump_cluster_log_state()))

    def _read_log_configs_from_master(self):
        """Read the log configs file at /usr/local/etc/cloudwatch_log_files.json."""
        read_cmd = "cat /usr/local/etc/cloudwatch_log_files.json"
        config = json.loads(self._run_command_on_master(read_cmd))
        return config.get("log_configs")

    @staticmethod
    def _clean_log_config(log):
        """Remove unnecessary fields from the given log dict."""
        desired_keys = ["file_path", "log_stream_name"]
        return {key: log[key] for key in desired_keys}

    def _get_relevant_logs(self):
        """Get subset of all log configs that apply to this cluster's scheduler/os combo."""
        # Figure out which logs are relevant to the master and computes for this cluster
        logs = self._read_log_configs_from_master()
        for log in logs:
            if self.scheduler not in log.get("schedulers") or self.platform not in log.get("platforms"):
                continue
            for node_role in log.get("node_roles"):
                self._relevant_logs[node_role].append(self._clean_log_config(log))
        # Give each nodes representative dict in self._cluster_log_state a copy
        self._cluster_log_state["MasterServer"]["logs"] = {
            log.get("file_path"): log for log in self._relevant_logs.get("MasterServer")
        }
        for _hostname, compute_instance_dict in self._cluster_log_state.get("ComputeFleet").items():
            compute_instance_dict["logs"] = {
                log.get("file_path"): log.copy() for log in self._relevant_logs.get("ComputeFleet")
            }
        LOGGER.debug("After populating relevant logs:\n{}".format(self._dump_cluster_log_state()))

    def _run_command_on_master(self, cmd):
        """Run cmd on cluster's MasterServer."""
        return self.remote_command_executor.run_remote_command(cmd).stdout.strip()

    def _run_command_on_computes(self, cmd, assert_success=True):
        """Run cmd on all computes in the cluster."""
        # Create directory in /shared to direct outputs to
        out_dir = Path(self._run_command_on_master("mktemp -d -p /shared"))
        redirect = " > {out_dir}/$(hostname -f) ".format(out_dir=out_dir)
        remote_cmd = cmd.format(redirect=redirect)

        # Run the command, wait for it to complete
        submit_out = self.scheduler_commands.submit_command(
            remote_cmd, nodes=self.scheduler_commands.compute_nodes_count()
        )
        job_id = self.scheduler_commands.assert_job_submitted(submit_out.stdout)
        self.scheduler_commands.wait_job_completed(job_id)
        if assert_success:
            self.scheduler_commands.assert_job_succeeded(job_id)

        # Read the output and map it to the hostname
        outputs = {}
        result_files = self._run_command_on_master("ls {}".format(out_dir))
        for hostname in result_files.split():
            outputs[hostname] = self._run_command_on_master("sudo cat {}".format(out_dir / hostname))
        self._run_command_on_master("rm -rf {}".format(out_dir))
        return outputs

    def _populate_master_log_existence(self):
        """Figure out which of the relevant logs for the MasterServer don't exist."""
        for log_path, log_dict in self._cluster_log_state.get("MasterServer").get("logs").items():
            cmd = "[[ -n `ls {path}` ]] && echo exists || echo does not exist".format(path=log_path)
            output = self._run_command_on_master(cmd)
            log_dict["exists"] = output == "exists"

    def _populate_compute_log_existence(self):
        """Figure out which of the relevant logs for the ComputeFleet nodes don't exist."""
        for log_dict in self._relevant_logs.get("ComputeFleet"):
            cmd = "[[ -n `ls {path}` ]] && echo {{redirect}} exists || " "echo {{redirect}} does not exist".format(
                path=log_dict.get("file_path")
            )
            hostname_to_output = self._run_command_on_computes(cmd)
            for hostname, output in hostname_to_output.items():
                node_log_dict = (
                    self._cluster_log_state.get("ComputeFleet").get(hostname).get("logs").get(log_dict.get("file_path"))
                )
                node_log_dict["exists"] = output == "exists"

    def _populate_log_existence(self):
        """Figure out which of the relevant logs for each node type don't exist."""
        self._populate_master_log_existence()
        self._populate_compute_log_existence()
        LOGGER.debug("After populating log existence:\n{}".format(self._dump_cluster_log_state()))

    def _populate_master_log_emptiness_and_tail(self):
        """Figure out which of the relevant logs for the MasterServer are empty."""
        for log_path, log_dict in self._cluster_log_state.get("MasterServer").get("logs").items():
            if not log_dict.get("exists"):
                continue
            output = self._run_command_on_master("sudo tail -n 1 {path}".format(path=log_path))
            log_dict["is_empty"] = output == ""
            log_dict["tail"] = output

    def _populate_compute_log_emptiness_and_tail(self):
        """Figure out which of the relevant logs for the ComputeFleet nodes are empty."""
        for log_dict in self._relevant_logs.get("ComputeFleet"):
            # If this file doesn't exist on any of the computes, don't assert success
            assert_success = True
            for _, compute_dict in self._cluster_log_state.get("ComputeFleet").items():
                if not compute_dict.get("logs").get(log_dict.get("file_path")).get("exists"):
                    assert_success = False
                    break
            cmd = "sudo tail {{redirect}} -n 1 {path}".format(path=log_dict.get("file_path"))
            hostname_to_output = self._run_command_on_computes(cmd, assert_success=assert_success)
            for hostname, output in hostname_to_output.items():
                host_log_dict = (
                    self._cluster_log_state.get("ComputeFleet").get(hostname).get("logs").get(log_dict.get("file_path"))
                )
                host_log_dict["is_empty"] = output == ""
                host_log_dict["tail"] = output

    def _populate_log_emptiness_and_tail(self):
        """Figure out which of the relevant logs for each node type are empty."""
        self._populate_master_log_emptiness_and_tail()
        self._populate_compute_log_emptiness_and_tail()
        LOGGER.debug("After populating log emptiness and tails:\n{}".format(self._dump_cluster_log_state()))

    def _populate_master_agent_status(self):
        """Get the cloudwatch agent's status for the MasterServer."""
        status_cmd = "/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status"
        status = json.loads(self._run_command_on_master(status_cmd))
        self._cluster_log_state["MasterServer"]["agent_status"] = status.get("status")

    def _populate_compute_agent_status(self):
        """Get the cloudwatch agent's status for all the compute nodes in the cluster."""
        status_cmd = "/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl {redirect} -a status"
        compute_statuses = self._run_command_on_computes(status_cmd)
        hostname_to_status_dict = {hostname: json.loads(status) for hostname, status in compute_statuses.items()}
        for hostname, status_dict in hostname_to_status_dict.items():
            self._cluster_log_state["ComputeFleet"][hostname]["agent_status"] = status_dict.get("status")

    def _populate_agent_status(self):
        """Get the cloudwatch agent's status for all the nodes in the cluster."""
        self._populate_master_agent_status()
        self._populate_compute_agent_status()
        LOGGER.debug("After populating agent statuses:\n{}".format(self._dump_cluster_log_state()))

    def _set_cluster_log_state(self):
        """
        Get the state of the cluster as it pertains to the CloudWatch logging feature.

        In particular:
        * Identify which EC2 instances belong to this cluster
        * Identify which logs are relevant to the MasterServer and ComputeFleet nodes
        * Identify whether each of a node's relevant logs contain data or not. If they do contain
          data, save the last line of the file.
        * Get the CloudWatch agent's status for each node
        """
        self._get_initial_cluster_log_state()
        self._get_relevant_logs()
        self._populate_log_existence()
        self._populate_log_emptiness_and_tail()
        self._populate_agent_status()


class Boto3DataRetriever:
    """Class used to get data from CloudWatch logs."""

    def __init__(self, region):
        """Save references to the variables the class will need to get log data."""
        self.region = region

    def get_log_groups(self):
        """Get list of log groups."""
        logs_client = boto3.client("logs", region_name=self.region)
        log_groups = logs_client.describe_log_groups().get("logGroups")
        LOGGER.debug("Log groups: {}\n".format(json.dumps(log_groups, indent=4)))
        return log_groups

    def get_log_streams(self, log_group_name):
        """Get list of log streams."""
        logs_client = boto3.client("logs", region_name=self.region)
        streams = logs_client.describe_log_streams(logGroupName=log_group_name).get("logStreams")
        LOGGER.debug(
            "Log streams for {group}:\n{streams}".format(group=log_group_name, streams=json.dumps(streams, indent=4))
        )
        return streams

    def get_log_events(self, log_group_name, log_stream_name):
        """Get log events for the given log_stream_name."""
        logs_client = boto3.client("logs", region_name=self.region)
        events = logs_client.get_log_events(logGroupName=log_group_name, logStreamName=log_stream_name).get("events")
        LOGGER.debug(
            "Log events for {group}/{stream}:\n{events}".format(
                group=log_group_name, stream=log_stream_name, events=json.dumps(events, indent=4)
            )
        )
        return events

    def get_ec2_instances(self):
        """Iterate through ec2's describe_instances."""
        ec2_client = boto3.client("ec2", region_name=self.region)
        paginator = ec2_client.get_paginator("describe_instances")
        for page in paginator.paginate():
            for reservation in page.get("Reservations"):
                for instance in reservation.get("Instances"):
                    yield instance


class CloudWatchLoggingTestRunner:
    """Tests and utilities for verifying that CloudWatch logging integration works as expected."""

    def __init__(self, data_retriever, log_group_name, enabled, retention_days):
        """Initialize class for CloudWatch logging testing."""
        self.data_retriever = data_retriever
        self.log_group_name = log_group_name
        self.enabled = enabled
        self.retention_days = retention_days
        self.failures = []

    @staticmethod
    def _fqdn_to_local_hostname(fqdn):
        """Turn a fullly qualified domain name into a local hostname of the form ip-X-X-X-X."""
        local_hostname = fqdn.split(".")[0]
        assert_that(re.match(r"ip-\d{1,3}-\d{1,3}-\d{1,3}-\d{1,3}$", local_hostname)).is_not_none()
        return local_hostname

    @staticmethod
    def _get_expected_log_stream_name(hostname, instance_id, log_pseudonym):
        """Return expected log stream name for log with given pseudonym on specified host."""
        return ".".join([CloudWatchLoggingTestRunner._fqdn_to_local_hostname(hostname), instance_id, log_pseudonym])

    def _get_expected_log_stream_index(self, logs_state):
        """Get map from expected log stream names to dict representing logs from which their events come."""
        expected_stream_index = {}
        for instance in logs_state:
            for _log_path, log_dict in instance.get("logs").items():
                if log_dict.get("is_empty"):
                    continue  # Log streams aren't created until events are logged to the file
                expected_stream_name = self._get_expected_log_stream_name(
                    instance.get("hostname"), instance.get("instance_id"), log_dict.get("log_stream_name")
                )
                expected_stream_index[expected_stream_name] = log_dict
        LOGGER.info("Expected log streams:\n{}".format("\n".join(expected_stream_index.keys())))
        return expected_stream_index

    def verify_log_streams_exist(self, logs_state, expected_stream_index, observed_streams):
        """Verify that log streams representing the given logs exist."""
        observed_stream_names = [stream.get("logStreamName") for stream in observed_streams]
        assert_that(observed_stream_names).contains_only(*expected_stream_index)

    def verify_log_streams_data(self, logs_state, expected_stream_index, observed_streams):
        """Verify each observed log stream has >= 1 event and that its timestamp format is working."""
        for stream in observed_streams:
            events = self.data_retriever.get_log_events(self.log_group_name, stream.get("logStreamName"))
            assert_that(events).is_not_empty()
            expected_tail = expected_stream_index.get(stream.get("logStreamName")).get("tail")
            event_generator = (event for event in events if event.get("message") == expected_tail)
            assert_that(next(event_generator, None)).is_not_none()

    def verify_log_group_created(self, log_groups):
        """Verify whether or not the cluster's log group was created depending on whether it was enabled."""
        assert_that_log_group_names = assert_that(log_groups).extracting("logGroupName")
        if self.enabled:
            assert_that_log_group_names.contains(self.log_group_name)
        else:
            assert_that_log_group_names.does_not_contain(self.log_group_name)

    def verify_log_group_retention_days(self, log_groups):
        """Verify whether or not the cluster's log group was created depending on whether it was enabled."""
        if not self.enabled:
            return  # Log group should not be created if not enabled.
        log_group = next((group for group in log_groups if group.get("logGroupName") == self.log_group_name), None)
        assert_that(log_group).is_not_none().is_equal_to(
            {"retentionInDays": self.retention_days}, include="retentionInDays"
        )

    def verify_agent_status(self, logs_state):
        """Verify CloudWatch agent is running on the MasterServer (or not if not enabled)."""
        expected_status = "running" if self.enabled else "stopped"
        assert_that(logs_state).extracting("agent_status").contains_only(expected_status)

    @staticmethod
    def verify_logs_exist(logs_state):
        """Verify that the log files expected to exist on the nodes of this cluster do."""
        for host_dict in logs_state:
            for _log_path, log_dict in host_dict.get("logs").items():
                assert_that(log_dict).is_equal_to({"exists": True}, include="exists")

    def run_tests(self, logs_state):
        """Run all CloudWatch logging integration tests."""
        log_groups = self.data_retriever.get_log_groups()
        self.verify_log_group_created(log_groups)
        self.verify_log_group_retention_days(log_groups)

        LOGGER.info("state of logs for cluster:\n{}".format(json.dumps(logs_state, indent=4)))
        self.verify_agent_status(logs_state)
        self.verify_logs_exist(logs_state)

        if self.enabled:  # Log streams are only relevant when the feature is enabled
            observed_streams = self.data_retriever.get_log_streams(self.log_group_name)
            expected_stream_index = self._get_expected_log_stream_index(logs_state)
            self.verify_log_streams_exist(logs_state, expected_stream_index, observed_streams)
            self.verify_log_streams_data(logs_state, expected_stream_index, observed_streams)

        if self.failures:
            pytest.fail("Failures: {}".format(", ".join(self.failures)), pytrace=False)


@pytest.mark.parametrize("cw_logging_enabled", [True, False])
@pytest.mark.regions(["us-east-1", "cn-north-1", "us-gov-west-1"])
@pytest.mark.instances(["t2.micro", "c5.xlarge"])
def test_cloudwatch_logging(
    region, scheduler, instance, os, pcluster_config_reader, clusters_factory, cw_logging_enabled
):
    """
    Test all CloudWatch logging features.

    All tests are grouped in a single function so that the cluster can be reused for all of them.
    """
    # Allow certain params to be set via environment variable in case manually re-testing on an existing cluster
    retention_days = int(
        environ.get(
            "CW_LOGGING_RETENTION_DAYS",
            random.choice([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653]),
        )
    )
    queue_size = int(environ.get("CW_LOGGING_QUEUE_SIZE", 1))
    param_kwargs = {
        "enable": str(cw_logging_enabled).lower(),
        "retention_days": retention_days,
        "queue_size": queue_size,
    }
    cluster_config = pcluster_config_reader(**param_kwargs)
    cluster = clusters_factory(cluster_config)
    log_group_name = "/aws/parallelcluster/{}".format(cluster.name)
    data_retriever = Boto3DataRetriever(region)
    test_runner = CloudWatchLoggingTestRunner(data_retriever, log_group_name, cw_logging_enabled, retention_days)
    test_runner.run_tests(CloudWatchLoggingClusterState(scheduler, os, cluster, data_retriever).get_logs_state())
