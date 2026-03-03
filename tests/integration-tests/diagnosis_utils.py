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
from utils import find_all_matches_in_log

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
