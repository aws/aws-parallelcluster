# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import re

import boto3
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import seconds
from utils import find_all_matches_in_log, get_username_for_os

from tests.common.utils import get_config_version_from_ddb, get_deployed_config_version

RCA_LOG_FILES = [
    "/var/log/chef-client.log",
    "/var/log/parallelcluster/clustermgtd",
    "/var/log/cfn-init.log",
    "/var/log/cloud-init-output.log",
    "/var/log/parallelcluster/slurmctld.log",
]
RCA_HEAD_NODE_CONSOLE_OUTPUT = "HeadNode Console Output"
PATTERN_GENERIC_FAILURE = r"error|fail|fatal|exception|critical"
PATTERN_CHEF_ERROR = r"(ERROR|FATAL):"
PATTERN_ICE_ERROR = r"InsufficientInstanceCapacity.*?sufficient\s+(\S+)\s+capacity"
CMD_RETRIEVE_RECIPE_EXECUTION = (
    "cat /var/log/chef-client.log"
    " | grep 'INFO: Run List is'"
    " | sed -E 's/^\\[([^]]+)\\].*recipe\\[([^]]+)\\].*/\\1 \\2/'"
)
PATTERN_IMDS_UNREACHABLE = r"cloud-init.*Timed out, no response from urls:.*169\.254\.169\.254"
PATTERN_NETWORK_FAILURE = r"cloud-init.*Failed to establish a new connection"
# Matches the chef-client.log block in the EC2 console output
PATTERN_CHEF_CLIENT_LOG_BLOCK = re.compile(
    r"[^\n]*BEGIN CHEF-CLIENT\.LOG[^\n]*.*?[^\n]*END CHEF-CLIENT\.LOG[^\n]*",
    re.DOTALL,
)


def retrieve_console_errors(region, instance_id):
    """
    Retrieve error lines from the head node EC2 console output.

    Uses boto3 to fetch the latest console output and filters for error lines.
    Also appends the full chef-client.log block when present, so RCA has the full chef run
    context instead of just lines matching the generic failure pattern.

    :param region: AWS region of the cluster.
    :param instance_id: EC2 instance ID of the head node.
    :return: String with error lines from console output, or a message if none found / retrieval failed.
    """
    try:
        ec2 = boto3.client("ec2", region_name=region)
        response = ec2.get_console_output(InstanceId=instance_id, Latest=True)
        console_output = response.get("Output", "")
        if not console_output or not console_output.strip():
            return "No console output available"

        error_lines = [
            line for line in console_output.splitlines() if re.search(PATTERN_GENERIC_FAILURE, line, re.IGNORECASE)
        ]
        sections = []
        sections.append("\n".join(error_lines) if error_lines else "No error found")

        chef_match = PATTERN_CHEF_CLIENT_LOG_BLOCK.search(console_output)
        if chef_match:
            sections.append(chef_match.group(0))

        return "\n==========\n".join(sections)
    except Exception as e:
        logging.warning("Exception retrieving console output: %s", e)
        return f"Failed to retrieve console output: {e}"


def extract_ice_from_rca_details(rca_details):
    """Extract unique InsufficientInstanceCapacity errors from RCA details."""
    instance_types = set()
    clustermgtd_log = rca_details.get("/var/log/parallelcluster/clustermgtd", "")
    for match in re.finditer(PATTERN_ICE_ERROR, clustermgtd_log):
        instance_types.add(match.group(1))
    return [f"InsufficientInstanceCapacity on {it}" for it in sorted(instance_types)]


def extract_imds_unreachable_from_rca_details(rca_details):
    """Check console output for IMDS unreachable errors."""
    console_log = rca_details.get(RCA_HEAD_NODE_CONSOLE_OUTPUT, "")
    if re.search(PATTERN_IMDS_UNREACHABLE, console_log):
        return ["Head Node could not bootstrap due to IMDS being unreachable"]
    return []


def extract_dns_failure_from_rca_details(rca_details):
    """Check console output for DNS/connectivity failures during bootstrap."""
    console_log = rca_details.get(RCA_HEAD_NODE_CONSOLE_OUTPUT, "")
    if re.search(PATTERN_NETWORK_FAILURE, console_log):
        return ["Head Node could not bootstrap due to network failure"]
    return []


@retry(stop_max_attempt_number=3, wait_fixed=seconds(5))
def retrieve_rca_details(cluster, num_errors=10):
    """
    Retrieve diagnostic info from cluster logs for root cause analysis.

    :param cluster: Cluster object with SSH access info.
    :param num_errors: Max error lines per log file.
    :return: Dict mapping log paths to error content, plus "SUMMARY" with conclusions.
    """
    logging.info("Retrieving RCA details")

    rca_details = {}

    rce = RemoteCommandExecutor(cluster)

    rca_details["SUMMARY"] = ["No root cause found"]
    for log_path in RCA_LOG_FILES:
        try:
            if log_path == "/var/log/chef-client.log":
                matches = find_all_matches_in_log(rce, log_path, PATTERN_CHEF_ERROR, num_errors, case_sensitive=True)
            else:
                matches = find_all_matches_in_log(rce, log_path, PATTERN_GENERIC_FAILURE, num_errors)
            rca_details[log_path] = "\n".join(matches) if matches else "No error found"
        except Exception as e:
            logging.warning("Failed to retrieve RCA details from log %s: %s", log_path, e)

    rce.close_connection()

    # Retrieve head node console output
    try:
        instance_id = cluster.head_node_instance_id
        if instance_id:
            rca_details[RCA_HEAD_NODE_CONSOLE_OUTPUT] = retrieve_console_errors(cluster.region, instance_id)
        else:
            logging.warning("Head node instance ID not available, skipping console output retrieval")
    except Exception as e:
        logging.warning("Failed to retrieve head node console output: %s", e)

    rca_details["SUMMARY"] = [
        *extract_ice_from_rca_details(rca_details),
        *extract_imds_unreachable_from_rca_details(rca_details),
        *extract_dns_failure_from_rca_details(rca_details),
    ]

    return rca_details


def get_cluster_nodes_snapshot(cluster):  # noqa: C901
    """
    Return an enriched snapshot of all cluster instances (head node, compute, login nodes).

    Calls describe-cluster-instances for each node type and augments each instance dict with:
    - deployed_config_version: cluster config version from dna.json on the node (via SSH).
    - ddb_config_version: cluster config version stored in DynamoDB (compute and login nodes only).
    - recipes: list of {"timestamp", "recipe"} dicts extracted from chef-client.log.
    - errors: list of error messages for any of the above that failed to retrieve.

    Compute nodes are reached via SSH through the head node (bastion).
    Login nodes are reached via SSH through the head node (bastion).
    The head node is reached directly.

    :param cluster: Cluster object (from clusters_factory) with SSH access and API methods.
    :return: dict with key "instances" containing a list of enriched instance dicts.
    """
    instances = []
    for node_type in ["HeadNode", "Compute", "LoginNode"]:
        for node in cluster.describe_cluster_instances(node_type=node_type):
            node["deployed_config_version"] = None
            node["ddb_config_version"] = None
            node["recipes"] = None
            node["errors"] = []

            n_id = node["instanceId"]
            n_ip = node["privateIpAddress"]

            # Build RemoteCommandExecutor args based on node type
            if node_type == "HeadNode":
                rce_args = {}
            elif node_type == "Compute":
                rce_args = dict(compute_node_ip=n_ip)
            else:
                username = get_username_for_os(cluster.os)
                rce_args = dict(login_node_ip=n_ip, bastion=f"{username}@{cluster.head_node_ip}")

            # Config version from dna.json on the node
            try:
                node["deployed_config_version"] = get_deployed_config_version(cluster, **rce_args)
            except Exception as e:
                node["errors"].append(f"Failed to get deployed config version: {e}")

            # Config version from DynamoDB (not applicable for head node)
            if node_type != "HeadNode":
                try:
                    node["ddb_config_version"] = get_config_version_from_ddb(cluster.region, cluster.name, n_id)
                except Exception as e:
                    node["errors"].append(f"Failed to get DynamoDB config version: {e}")

            # Executed recipes
            try:
                rce = RemoteCommandExecutor(cluster, **rce_args)
                result = rce.run_remote_command(CMD_RETRIEVE_RECIPE_EXECUTION)
                node["recipes"] = []
                for line in result.stdout.strip().splitlines():
                    parts = line.split(" ", 1)
                    if len(parts) == 2:
                        node["recipes"].append({"timestamp": parts[0], "recipe": parts[1]})
                    else:
                        node["recipes"].append({"timestamp": None, "recipe": line})
            except Exception as e:
                node["errors"].append(f"Failed to get recipes: {e}")

            instances.append(node)

    return {"instances": instances}
