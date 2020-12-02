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

import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from retrying import retry

from tests.cloudwatch_logging import cloudwatch_logging_boto3_utils as cw_logs_utils
from tests.common.schedulers_common import get_scheduler_commands

LOGGER = logging.getLogger(__name__)
DEFAULT_SHARED_DIR = "/shared"
DEFAULT_RETENTION_DAYS = 14
NODE_CONFIG_PATH = "/etc/chef/dna.json"
HEAD_NODE_ROLE_NAME = "MasterServer"
COMPUTE_NODE_ROLE_NAME = "ComputeFleet"
NODE_ROLE_NAMES = {HEAD_NODE_ROLE_NAME, COMPUTE_NODE_ROLE_NAME}


def _get_log_group_name_for_cluster(cluster_name):
    """Return the name of the log group to be created for the given cluster if CloudWatch logging is enabled."""
    return "/aws/parallelcluster/{0}".format(cluster_name)


def _dump_json(obj, indent=4):
    """Dump obj to a JSON string."""
    return json.dumps(obj, indent=indent)


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

    def __init__(self, scheduler, os, cluster, feature_key=None, shared_dir=DEFAULT_SHARED_DIR):
        """Get the state of the cluster as it pertains to the CloudWatch logging feature."""
        self.scheduler = scheduler
        self.platform = self._base_os_to_platform(os)
        self.cluster = cluster
        self.feature_key = feature_key
        self.shared_dir = self._get_shared_dir(shared_dir)
        self.remote_command_executor = RemoteCommandExecutor(self.cluster)
        self.scheduler_commands = get_scheduler_commands(self.scheduler, self.remote_command_executor)
        self._relevant_logs = {HEAD_NODE_ROLE_NAME: [], COMPUTE_NODE_ROLE_NAME: []}
        self._cluster_log_state = {HEAD_NODE_ROLE_NAME: {}, COMPUTE_NODE_ROLE_NAME: {}}
        self._set_cluster_log_state()

    @property
    def compute_nodes_count(self):
        """Return the number of compute nodes in the cluster."""
        if self.scheduler == "awsbatch":
            return 0  # batch "computes" use a different log group
        else:
            return self.scheduler_commands.compute_nodes_count()

    @property
    def is_feature_specific(self):
        """Return a boolean describing if this instance is concerned only with logs for a specific feature."""
        return self.feature_key is not None

    def get_logs_state(self):
        """Get the state of the log files applicable to each of the cluster's EC2 instances."""
        desired_keys = ["hostname", "instance_id", "node_role", "agent_status", "logs"]
        states = [{key: self._cluster_log_state.get(HEAD_NODE_ROLE_NAME).get(key) for key in desired_keys}]
        states.extend(
            [
                {key: host_dict[key] for key in desired_keys}
                for hostname, host_dict in self._cluster_log_state.get(COMPUTE_NODE_ROLE_NAME).items()
            ]
        )
        assert_that(states).is_length(self.compute_nodes_count + 1)  # computes + head node
        return states

    @staticmethod
    def _get_shared_dir(shared_dir):
        """Return the path to the cluster's shared dir, ensuring that it's first character is /."""
        if shared_dir[:1] != "/":
            shared_dir = "/{shared_dir}".format(shared_dir=shared_dir)
        return shared_dir

    def _dump_cluster_log_state(self):
        """Dump the JSON-ified string of self._cluster_log_state for debugging purposes."""
        return _dump_json(self._cluster_log_state)

    @staticmethod
    def _base_os_to_platform(base_os):
        """Turn the name of a base OS into the platform."""
        # Special case: alinux is how the config file refers to amazon linux, but in the chef cookbook
        # (and the cloudwatch log config produced by it) the platform is "amazon".
        translations = {"alinux": "amazon"}
        no_digits = base_os.rstrip(string.digits)
        return translations.get(no_digits, no_digits)

    def _set_head_node_instance(self, instance):
        """Set the head node instance field in self.cluster_log_state."""
        self._cluster_log_state.get(HEAD_NODE_ROLE_NAME).update(
            {
                "node_role": HEAD_NODE_ROLE_NAME,
                "hostname": instance.get("PrivateDnsName"),
                "instance_id": instance.get("InstanceId"),
            }
        )

    def _add_compute_instance(self, instance):
        """Update the cluster's log state by adding a compute node."""
        compute_hostname = self._run_command_on_head_node(
            "ssh -o StrictHostKeyChecking=no -q {} hostname -f".format(instance.get("PrivateDnsName"))
        )
        self._cluster_log_state[COMPUTE_NODE_ROLE_NAME][compute_hostname] = {
            "node_role": COMPUTE_NODE_ROLE_NAME,
            "hostname": instance.get("PrivateDnsName"),
            "instance_id": instance.get("InstanceId"),
        }

    def _get_initial_cluster_log_state(self):
        """Get EC2 instances belonging to this cluster. Figure out their roles in the cluster."""
        for instance in cw_logs_utils.get_ec2_instances():
            tags = {tag.get("Key"): tag.get("Value") for tag in instance.get("Tags", [])}
            if tags.get("ClusterName", "") != self.cluster.name:
                continue
            elif tags.get("Name", "") == "Master":
                self._set_head_node_instance(instance)
            else:
                self._add_compute_instance(instance)
        LOGGER.debug("After getting initial cluster state:\n{0}".format(self._dump_cluster_log_state()))

    def _read_log_configs_from_head_node(self):
        """Read the log configs file at /usr/local/etc/cloudwatch_log_files.json."""
        read_cmd = "cat /usr/local/etc/cloudwatch_log_files.json"
        config = json.loads(self._run_command_on_head_node(read_cmd))
        return config.get("log_configs")

    def _read_head_node_config(self):
        """Read the node configuration JSON file at NODE_CONFIG_PATH on the head node."""
        read_cmd = "cat {0}".format(NODE_CONFIG_PATH)
        head_node_config = json.loads(self._run_command_on_head_node(read_cmd)).get("cfncluster", {})
        assert_that(head_node_config).is_not_empty()
        LOGGER.info("DNA config read from head node: {0}".format(_dump_json(head_node_config)))
        return head_node_config

    def _read_compute_node_config(self):
        """Read the node configuration JSON file at NODE_CONFIG_PATH on a compute node."""
        compute_node_config = {}
        compute_hostname_to_config = self._run_command_on_computes("cat {{redirect}} {0}".format(NODE_CONFIG_PATH))

        # Use first one, since ParallelCluster-specific node config should be the same on every compute node
        for _, config_json in compute_hostname_to_config.items():
            compute_node_config = json.loads(config_json).get("cfncluster", {})
            break

        assert_that(compute_node_config).is_not_empty()
        LOGGER.info("DNA config read from compute node: {0}".format(_dump_json(compute_node_config)))
        return compute_node_config

    def _read_node_configs(self):
        """Return a dict mapping node role names to the config at NODE_CONFIG_PATH."""
        return {
            HEAD_NODE_ROLE_NAME: self._read_head_node_config(),
            COMPUTE_NODE_ROLE_NAME: self._read_compute_node_config(),
        }

    @staticmethod
    def _clean_log_config(log):
        """Remove unnecessary fields from the given log dict."""
        desired_keys = ["file_path", "log_stream_name", "feature_conditions"]
        return {key: log[key] for key in desired_keys}

    def _filter_logs_on_platform_and_scheduler(self, logs):
        """Filter from logs all entries that don't support the cluster's OS or scheduler."""
        return [
            log for log in logs if self.scheduler in log.get("schedulers") and self.platform in log.get("platforms")
        ]

    def _log_is_relevant_for_feature(self, log, node_config):
        """Return a boolean describing whether log contains a feature_conditions entry relevant to self.feature_key."""
        for feature_condition in log.get("feature_conditions", []):
            if all(
                [
                    self.feature_key == feature_condition.get("dna_key"),
                    node_config.get(self.feature_key) in feature_condition.get("satisfying_values"),
                ]
            ):
                return True
        return False

    def _get_node_roles_for_which_feature_is_relevant(self, log, node_configs):
        """
        Return a list of the node types on which the feature-specific log is applicable.

        This is necessary because even though a log might support a certain node role, that particular node type might
        not be enabled on that node type in the current cluster.
        """
        applicable_node_roles = []
        for node_role in log.get("node_roles"):
            if self._log_is_relevant_for_feature(log, node_configs[node_role]):
                applicable_node_roles.append(node_role)
        return applicable_node_roles

    def _filter_logs_on_feature_key(self, logs):
        """Filter from logs all entires that aren't specific to the feature whose logs are desired."""
        node_configs = self._read_node_configs()
        filtered_logs = []
        for log in logs:
            applicable_node_roles = self._get_node_roles_for_which_feature_is_relevant(log, node_configs)
            if applicable_node_roles:
                log["node_roles"] = applicable_node_roles
                filtered_logs.append(log)
        assert_that(filtered_logs).is_not_empty()
        return filtered_logs

    def _filter_logs_on_feature(self, logs):
        """Filter logs based on whether or not we're testing for a specific feature."""
        if self.is_feature_specific:
            return self._filter_logs_on_feature_key(logs)
        else:
            return [log for log in logs if not log.get("feature_conditions")]

    def _populate_relevant_logs_for_node_roles(self, logs):
        """Populate self._relevant_logs with the entries of logs."""
        # When the scheduler is AWS Batch, only keep log that whose config's node_role value is MasterServer, since
        # Batch doesn't have compute nodes in the traditional sense.
        desired_node_roles = {HEAD_NODE_ROLE_NAME} if self.scheduler == "awsbatch" else NODE_ROLE_NAMES
        for log in logs:
            for node_role in set(log.get("node_roles")) & desired_node_roles:
                self._relevant_logs[node_role].append(self._clean_log_config(log))

    def _filter_logs(self, logs):
        """Populate self._relevant_logs with logs appropriate for the two different node types."""
        logs = self._filter_logs_on_platform_and_scheduler(logs)
        logs = self._filter_logs_on_feature(logs)
        self._populate_relevant_logs_for_node_roles(logs)

    def _create_log_entries_for_nodes(self):
        """Create an entry for each relevant log in self._cluster_log_state."""
        self._cluster_log_state[HEAD_NODE_ROLE_NAME]["logs"] = {
            log.get("file_path"): log for log in self._relevant_logs.get(HEAD_NODE_ROLE_NAME)
        }
        for _hostname, compute_instance_dict in self._cluster_log_state.get(COMPUTE_NODE_ROLE_NAME).items():
            compute_instance_dict["logs"] = {
                log.get("file_path"): log.copy() for log in self._relevant_logs.get(COMPUTE_NODE_ROLE_NAME)
            }

    def _get_relevant_logs(self):
        """Get subset of all log configs that apply to this cluster's scheduler/os combo."""
        logs = self._read_log_configs_from_head_node()
        self._filter_logs(logs)
        self._create_log_entries_for_nodes()
        LOGGER.debug("After populating relevant logs:\n{0}".format(self._dump_cluster_log_state()))

    def _run_command_on_head_node(self, cmd):
        """Run cmd on cluster's head node."""
        return self.remote_command_executor.run_remote_command(cmd, timeout=60).stdout.strip()

    def _run_command_on_computes(self, cmd, assert_success=True):
        """Run cmd on all computes in the cluster."""
        # Create directory in self.shared_dir to direct outputs to
        out_dir = Path(self._run_command_on_head_node("mktemp -d -p {shared_dir}".format(shared_dir=self.shared_dir)))
        redirect = " > {out_dir}/$(hostname -f) ".format(out_dir=out_dir)
        remote_cmd = cmd.format(redirect=redirect)

        # Run the command, wait for it to complete
        submit_out = self.scheduler_commands.submit_command(remote_cmd, nodes=self.compute_nodes_count)
        job_id = self.scheduler_commands.assert_job_submitted(submit_out.stdout)
        self.scheduler_commands.wait_job_completed(job_id)
        if assert_success:
            self.scheduler_commands.assert_job_succeeded(job_id)

        # Read the output and map it to the hostname
        outputs = {}
        result_files = self._run_command_on_head_node("ls {0}".format(out_dir))
        for hostname in result_files.split():
            outputs[hostname] = self._run_command_on_head_node("sudo cat {0}".format(out_dir / hostname))
        self._run_command_on_head_node("rm -rf {0}".format(out_dir))
        return outputs

    def _populate_head_node_log_existence(self):
        """Figure out which of the relevant logs for the head node don't exist."""
        for log_path, log_dict in self._cluster_log_state.get(HEAD_NODE_ROLE_NAME).get("logs").items():
            cmd = "[ -f {path} ] && echo exists || echo does not exist".format(path=log_path)
            output = self._run_command_on_head_node(cmd)
            log_dict["exists"] = output == "exists"

    def _populate_compute_log_existence(self):
        """Figure out which of the relevant logs for the ComputeFleet nodes don't exist."""
        if self.compute_nodes_count == 0:
            return
        for log_dict in self._relevant_logs.get(COMPUTE_NODE_ROLE_NAME):
            cmd = "[ -f {path} ] && echo {{redirect}} exists || " "echo {{redirect}} does not exist".format(
                path=log_dict.get("file_path")
            )
            hostname_to_output = self._run_command_on_computes(cmd)
            for hostname, output in hostname_to_output.items():
                node_log_dict = (
                    self._cluster_log_state.get(COMPUTE_NODE_ROLE_NAME)
                    .get(hostname)
                    .get("logs")
                    .get(log_dict.get("file_path"))
                )
                node_log_dict["exists"] = output == "exists"

    def _populate_log_existence(self):
        """Figure out which of the relevant logs for each node type don't exist."""
        self._populate_head_node_log_existence()
        self._populate_compute_log_existence()
        LOGGER.debug("After populating log existence:\n{0}".format(self._dump_cluster_log_state()))

    def _populate_head_node_log_emptiness_and_tail(self):
        """Figure out which of the relevant logs for the head node are empty."""
        for log_path, log_dict in self._cluster_log_state.get(HEAD_NODE_ROLE_NAME).get("logs").items():
            if not log_dict.get("exists"):
                continue
            output = self._run_command_on_head_node("sudo tail -n 1 {path}".format(path=log_path))
            log_dict["is_empty"] = output == ""
            log_dict["tail"] = output

    def _populate_compute_log_emptiness_and_tail(self):
        """Figure out which of the relevant logs for the ComputeFleet nodes are empty."""
        if self.compute_nodes_count == 0:
            return
        for log_dict in self._relevant_logs.get(COMPUTE_NODE_ROLE_NAME):
            # If this file doesn't exist on any of the computes, don't assert success
            assert_success = True
            for _, compute_dict in self._cluster_log_state.get(COMPUTE_NODE_ROLE_NAME).items():
                if not compute_dict.get("logs").get(log_dict.get("file_path")).get("exists"):
                    assert_success = False
                    break
            cmd = "sudo tail {{redirect}} -n 1 {path}".format(path=log_dict.get("file_path"))
            hostname_to_output = self._run_command_on_computes(cmd, assert_success=assert_success)
            for hostname, output in hostname_to_output.items():
                host_log_dict = (
                    self._cluster_log_state.get(COMPUTE_NODE_ROLE_NAME)
                    .get(hostname)
                    .get("logs")
                    .get(log_dict.get("file_path"))
                )
                host_log_dict["is_empty"] = output == ""
                host_log_dict["tail"] = output

    def _populate_log_emptiness_and_tail(self):
        """Figure out which of the relevant logs for each node type are empty."""
        self._populate_head_node_log_emptiness_and_tail()
        self._populate_compute_log_emptiness_and_tail()
        LOGGER.debug("After populating log emptiness and tails:\n{0}".format(self._dump_cluster_log_state()))

    def _populate_head_node_agent_status(self):
        """Get the cloudwatch agent's status for the head node."""
        status_cmd = "/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status"
        status = json.loads(self._run_command_on_head_node(status_cmd))
        self._cluster_log_state[HEAD_NODE_ROLE_NAME]["agent_status"] = status.get("status")

    def _populate_compute_agent_status(self):
        """Get the cloudwatch agent's status for all the compute nodes in the cluster."""
        if self.compute_nodes_count == 0:
            return
        status_cmd = "/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl {redirect} -a status"
        compute_statuses = self._run_command_on_computes(status_cmd)
        hostname_to_status_dict = {hostname: json.loads(status) for hostname, status in compute_statuses.items()}
        for hostname, status_dict in hostname_to_status_dict.items():
            self._cluster_log_state[COMPUTE_NODE_ROLE_NAME][hostname]["agent_status"] = status_dict.get("status")

    def _populate_agent_status(self):
        """Get the cloudwatch agent's status for all the nodes in the cluster."""
        self._populate_head_node_agent_status()
        self._populate_compute_agent_status()
        LOGGER.debug("After populating agent statuses:\n{0}".format(self._dump_cluster_log_state()))

    def _set_cluster_log_state(self):
        """
        Get the state of the cluster as it pertains to the CloudWatch logging feature.

        In particular:
        * Identify which EC2 instances belong to this cluster
        * Identify which logs are relevant to the head node and compute fleet nodes
        * Identify whether each of a node's relevant logs contain data or not. If they do contain
          data, save the last line of the file.
        * Get the CloudWatch agent's status for each node
        """
        self._get_initial_cluster_log_state()
        self._get_relevant_logs()
        self._populate_log_existence()
        self._populate_log_emptiness_and_tail()
        self._populate_agent_status()


class CloudWatchLoggingTestRunner:
    """Tests and utilities for verifying that CloudWatch logging integration works as expected."""

    def __init__(
        self, log_group_name, enabled=True, retention_days=DEFAULT_RETENTION_DAYS, logs_persist_after_delete=False
    ):
        """Initialize class for CloudWatch logging testing."""
        self.log_group_name = log_group_name
        self.enabled = enabled
        self.retention_days = retention_days
        self.logs_persist_after_delete = logs_persist_after_delete

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
                if not log_dict.get("exists") or log_dict.get("is_empty"):
                    continue  # Log streams aren't created until events are logged to the file
                expected_stream_name = self._get_expected_log_stream_name(
                    instance.get("hostname"), instance.get("instance_id"), log_dict.get("log_stream_name")
                )
                expected_stream_index[expected_stream_name] = log_dict
        LOGGER.info("Expected stream index:\n{0}".format(_dump_json(expected_stream_index)))
        return expected_stream_index

    def verify_log_streams_exist(self, logs_state, expected_stream_index, observed_streams):
        """Verify that log streams representing the given logs exist."""
        observed_stream_names = [stream.get("logStreamName") for stream in observed_streams]
        assert_that(observed_stream_names).contains_only(*expected_stream_index)

    @retry(stop_max_attempt_number=3, wait_fixed=10 * 1000)  # Allow time for log events to reach the log stream
    def _verify_log_stream_data(self, logs_state, expected_stream_index, stream):
        """Verify that stream contains an event for the last line read from its corresponding log."""
        events = cw_logs_utils.get_log_events(self.log_group_name, stream.get("logStreamName"))
        assert_that(events).is_not_empty()
        expected_tail = expected_stream_index.get(stream.get("logStreamName")).get("tail")
        event_generator = (event for event in events if event.get("message") == expected_tail)
        assert_that(next(event_generator, None)).is_not_none()

    def verify_log_streams_data(self, logs_state, expected_stream_index, observed_streams):
        """Verify each observed log stream has >= 1 event and that its timestamp format is working."""
        for stream in observed_streams:
            self._verify_log_stream_data(logs_state, expected_stream_index, stream)

    def verify_log_group_exists(self, log_groups, cluster_has_been_deleted):
        """Verify whether or not the cluster's log group was created depending on whether it was enabled."""
        assert_that_log_group_names = assert_that(log_groups).extracting("logGroupName")
        if self.enabled and (not cluster_has_been_deleted or self.logs_persist_after_delete):
            assert_that_log_group_names.contains(self.log_group_name)
        else:
            assert_that_log_group_names.does_not_contain(self.log_group_name)

    def verify_log_group_retention_days(self, log_groups, cluster_has_been_deleted):
        """Verify whether or not the cluster's log group was created depending on whether it was enabled."""
        if not self.enabled or (cluster_has_been_deleted and not self.logs_persist_after_delete):
            return
        log_group = next((group for group in log_groups if group.get("logGroupName") == self.log_group_name), None)
        assert_that(log_group).is_not_none().is_equal_to(
            {"retentionInDays": self.retention_days}, include="retentionInDays"
        )

    def verify_agent_status(self, logs_state):
        """Verify CloudWatch agent is running on the head node (or not if not enabled)."""
        expected_status = "running" if self.enabled else "stopped"
        assert_that(logs_state).extracting("agent_status").contains_only(expected_status)

    @staticmethod
    def verify_logs_exist(logs_state):
        """Verify that the log files expected to exist on the nodes of this cluster do."""
        for host_dict in logs_state:
            for _log_path, log_dict in host_dict.get("logs").items():
                if len(log_dict.get("feature_conditions")) > 0:
                    continue  # Don't assert existence of a log if it depend on a feature being enabled
                assert_that(log_dict).is_equal_to({"exists": True}, include="exists")

    def run_tests(self, logs_state, cluster_has_been_deleted=False):
        """Run all CloudWatch logging integration tests."""
        log_groups = cw_logs_utils.get_cluster_log_groups_from_boto3(self.log_group_name)
        self.verify_log_group_exists(log_groups, cluster_has_been_deleted)
        self.verify_log_group_retention_days(log_groups, cluster_has_been_deleted)

        if not cluster_has_been_deleted:
            LOGGER.info("state of logs for cluster:\n{0}".format(_dump_json(logs_state)))
            self.verify_agent_status(logs_state)
            self.verify_logs_exist(logs_state)

        if self.enabled and (not cluster_has_been_deleted or self.logs_persist_after_delete):
            observed_streams = cw_logs_utils.get_log_streams(self.log_group_name)
            expected_stream_index = self._get_expected_log_stream_index(logs_state)
            self.verify_log_streams_exist(logs_state, expected_stream_index, observed_streams)
            self.verify_log_streams_data(logs_state, expected_stream_index, observed_streams)


class FeatureSpecificCloudWatchLoggingTestRunner(CloudWatchLoggingTestRunner):
    """This class enables running CloudWatch logging tests for only logs specific to a certain feature."""

    def _verify_log_stream_data(self, logs_state, expected_stream_index, stream):
        """Check if the stream is in the expected log stream index before validating."""
        if stream.get("logStreamName") not in expected_stream_index:
            LOGGER.info("Skipping validation of {0}'s log stream data.".format(stream.get("logStreamName")))
        else:
            super()._verify_log_stream_data(logs_state, expected_stream_index, stream)

    def verify_log_streams_exist(self, logs_state, expected_stream_index, observed_streams):
        """Enable the expected streams list to be a subset of the observed streams."""
        observed_stream_names = [stream.get("logStreamName") for stream in observed_streams]
        assert_that(observed_stream_names).contains(*expected_stream_index)

    @classmethod
    def run_tests_for_feature(cls, cluster, scheduler, os, feature_key, region, shared_dir=DEFAULT_SHARED_DIR):
        """Verify that the logs for the given feature are present on the cluster and are stored in cloudwatch."""
        environ["AWS_DEFAULT_REGION"] = region
        cluster_logs_state = CloudWatchLoggingClusterState(
            scheduler, os, cluster, feature_key, shared_dir
        ).get_logs_state()
        test_runner = cls(_get_log_group_name_for_cluster(cluster.name))
        test_runner.run_tests(cluster_logs_state)


def get_config_param_vals():
    """Return a dict used to set values for config file parameters."""
    # Allow certain params to be set via environment variable in case manually re-testing on an existing cluster
    retention_days = int(
        environ.get(
            "CW_LOGGING_RETENTION_DAYS",
            random.choice([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653]),
        )
    )
    queue_size = int(environ.get("CW_LOGGING_QUEUE_SIZE", 1))
    return {"enable": "true", "retention_days": retention_days, "queue_size": queue_size}


# In order to limit the number of CloudWatch logging tests while still covering all the OSes...
# 1) run the test for all of the schedulers with alinux2
@pytest.mark.dimensions("ca-central-1", "c5.xlarge", "alinux2", "*")
# 2) run the test for all of the OSes with slurm
@pytest.mark.dimensions("ap-east-1", "c5.xlarge", "*", "slurm")
# 3) run the test for a single scheduler-OS combination on an ARM instance
@pytest.mark.dimensions("eu-west-1", "m6g.xlarge", "alinux2", "slurm")
def test_cloudwatch_logging(region, scheduler, instance, os, pcluster_config_reader, clusters_factory):
    """
    Test all CloudWatch logging features.

    All tests are grouped in a single function so that the cluster can be reused for all of them.
    """
    environ["AWS_DEFAULT_REGION"] = region  # So that it doesn't have to be passed to boto3 calls
    config_params = get_config_param_vals()
    cluster_config = pcluster_config_reader(**config_params)
    cluster = clusters_factory(cluster_config)
    test_runner = CloudWatchLoggingTestRunner(
        log_group_name=_get_log_group_name_for_cluster(cluster.name),
        enabled=True,
        retention_days=config_params.get("retention_days"),
        logs_persist_after_delete=True,
    )
    cluster_logs_state = CloudWatchLoggingClusterState(scheduler, os, cluster).get_logs_state()
    _test_cw_logs_before_after_delete(cluster, cluster_logs_state, test_runner)


def _check_log_groups_after_test(test_func):  # noqa: D202
    """Verify that log groups outlive the cluster if expected."""

    def wrapped_test(cluster, *args, **kwargs):
        pre_test_log_groups = cw_logs_utils.get_cluster_log_groups(cluster.cfn_name)
        LOGGER.info("Log groups before deleting the cluster:\n{0}".format("\n".join(pre_test_log_groups)))
        try:
            test_func(cluster, *args, **kwargs)
            if pre_test_log_groups:
                post_test_log_groups = []
                for pre_test_lg in pre_test_log_groups:
                    post_test_log_groups.extend(
                        [lg.get("logGroupName") for lg in cw_logs_utils.get_cluster_log_groups_from_boto3(pre_test_lg)]
                    )
                LOGGER.info("Log groups after deleting the cluster:\n{0}".format("\n".join(post_test_log_groups)))
                assert_that(post_test_log_groups).contains(*pre_test_log_groups)
        finally:
            cw_logs_utils.delete_log_groups(pre_test_log_groups)

    return wrapped_test


@_check_log_groups_after_test
def _test_cw_logs_before_after_delete(cluster, cluster_logs_state, test_runner):
    """Verify CloudWatch logs integration behaves as expected while a cluster is running and after it's deleted."""
    test_runner.run_tests(cluster_logs_state, cluster_has_been_deleted=False)
    cluster.delete(keep_logs=True)
    test_runner.run_tests(cluster_logs_state, cluster_has_been_deleted=True)
