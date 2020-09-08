# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from assertpy import assert_that
from retrying import retry
from time_utils import minutes, seconds


def assert_initial_conditions(scheduler_commands, num_static_nodes, num_dynamic_nodes, partition, cancel_job_id=None):
    """Assert cluster is in expected state before test starts; return list of compute nodes."""
    logging.info(
        "Assert initial condition, expect cluster to have {num_nodes} idle nodes".format(
            num_nodes=num_static_nodes + num_dynamic_nodes
        )
    )
    wait_for_num_nodes_in_scheduler(
        scheduler_commands, num_static_nodes + num_dynamic_nodes, filter_by_partition=partition
    )
    nodes_in_scheduler = scheduler_commands.get_compute_nodes(partition)
    static_nodes = []
    dynamic_nodes = []
    for node in nodes_in_scheduler:
        if "-st-" in node:
            static_nodes.append(node)
        if "-dy-" in node:
            dynamic_nodes.append(node)
    assert_that(len(static_nodes)).is_equal_to(num_static_nodes)
    assert_that(len(dynamic_nodes)).is_equal_to(num_dynamic_nodes)
    assert_compute_node_states(scheduler_commands, nodes_in_scheduler, expected_states=["idle", "mixed", "allocated"])
    if cancel_job_id:
        # Cancel warm up job so no extra scaling behavior should be happening
        scheduler_commands.cancel_job(cancel_job_id)

    return static_nodes, dynamic_nodes


def submit_initial_job(
    scheduler_commands, job, partition, instance_type, num_nodes, node_type="dynamic", other_options=None
):
    return scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": job,
            "partition": partition,
            "constraint": "{0},{1}".format(instance_type, node_type),
            "nodes": num_nodes,
            "other_options": other_options,
        }
    )


def assert_compute_node_states(scheduler_commands, compute_nodes, expected_states):
    node_states = scheduler_commands.get_nodes_status(compute_nodes)
    for node in compute_nodes:
        assert_that(expected_states).contains(node_states.get(node))


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))
def wait_for_num_nodes_in_scheduler(scheduler_commands, desired, filter_by_partition=None):
    assert_num_nodes_in_scheduler(scheduler_commands, desired, filter_by_partition)


def assert_num_nodes_in_scheduler(scheduler_commands, desired, filter_by_partition=None):
    if filter_by_partition:
        assert_that(len(scheduler_commands.get_compute_nodes(filter_by_partition))).is_equal_to(desired)
    else:
        assert_that(len(scheduler_commands.get_compute_nodes())).is_equal_to(desired)
