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
PATTERN_GENERIC_FAILURE = r"error|fail|fatal|exception|critical"
PATTERN_CHEF_ERROR = r"ERROR:"
PATTERN_ICE_ERROR = r"InsufficientInstanceCapacity.*?sufficient\s+(\S+)\s+capacity"
CMD_RETRIEVE_RECIPE_EXECUTION = (
    "cat /var/log/chef-client.log"
    " | grep 'INFO: Run List is'"
    " | sed -E 's/^\\[([^]]+)\\].*recipe\\[([^]]+)\\].*/\\1 \\2/'"
)


def extract_ice_from_rca_details(rca_details):
    """Extract unique InsufficientInstanceCapacity errors from RCA details."""
    instance_types = set()
    clustermgtd_log = rca_details.get("/var/log/parallelcluster/clustermgtd", "")
    for match in re.finditer(PATTERN_ICE_ERROR, clustermgtd_log):
        instance_types.add(match.group(1))
    return [f"InsufficientInstanceCapacity on {it}" for it in sorted(instance_types)]


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

    rca_details["SUMMARY"] = [
        *extract_ice_from_rca_details(rca_details),
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
