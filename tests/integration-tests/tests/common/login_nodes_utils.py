# Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

import boto3
from assertpy import assert_that
from retrying import retry
from time_utils import minutes


def terminate_login_nodes(cluster):
    """
    Terminate all login nodes of the cluster.
    :param cluster: the cluster.
    :return: None.
    """
    logging.info(f"Terminating login nodes for cluster: {cluster.name}")
    instance_ids = cluster.get_cluster_instance_ids(node_type="LoginNode")
    ec2 = boto3.client("ec2", region_name=cluster.region)
    ec2.terminate_instances(InstanceIds=instance_ids)
    ec2.get_waiter("instance_terminated").wait(InstanceIds=instance_ids)
    logging.info(f"Login nodes for cluster {cluster.name} have been terminated: {instance_ids}")


def assert_login_nodes_count(cluster, count: int):
    """
    Assert on the number of running login nodes.
    :param cluster: the cluster.
    :param count: the expected number of login nodes.
    :return: None.
    :raise assertion failure when the number of running login nodes is not as expected.
    """
    login_nodes = cluster.get_cluster_instance_ids(node_type="LoginNode")
    assert_that(login_nodes).is_length(count)


def wait_for_login_fleet_stop(cluster, wait_fixed=None, stop_max_delay=None):
    """
    Wait for the login fleet to be stopped, i.e. no running login nodes.
    :param cluster: the cluster.
    :param wait_fixed: the time to wait between each retry (default: 1 minute).
    :param stop_max_delay: the max time for the retry strategy (default: 10 minutes).
    :return: None.
    :raise assertion failure when there is at least one login node running.
    """
    retry(
        wait_fixed=wait_fixed if wait_fixed is not None else minutes(1),
        stop_max_delay=stop_max_delay if stop_max_delay is not None else minutes(10),
    )(assert_login_nodes_count)(cluster, 0)
