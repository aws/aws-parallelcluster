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

import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from utils import get_cluster_nodes_instance_ids

from tests.common.assertions import assert_no_errors_in_logs, wait_for_num_instances_in_cluster
from tests.common.schedulers_common import get_scheduler_commands


@pytest.mark.regions(["us-east-2"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.oss(["ubuntu1804"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_hit_cli_commands(scheduler, region, pcluster_config_reader, clusters_factory):
    """Test pcluster cli commands are working."""
    # Use long scale down idle time so we know nodes are terminated by pcluster stop
    cluster_config = pcluster_config_reader(scaledown_idletime=60)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    _test_pcluster_instances_and_status(cluster, region, compute_fleet_status="RUNNING")
    _test_pcluster_stop_and_start(scheduler_commands, cluster, region, expected_num_nodes=2, hit_cluster=True)
    assert_no_errors_in_logs(remote_command_executor, scheduler)


@pytest.mark.regions(["us-west-2"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["sge"])
@pytest.mark.oss(["centos7"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_sit_cli_commands(scheduler, region, pcluster_config_reader, clusters_factory):
    """Test pcluster cli commands are working."""
    cluster_config = pcluster_config_reader(scaledown_idletime=60)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    _test_pcluster_instances_and_status(cluster, region)
    _test_pcluster_stop_and_start(scheduler_commands, cluster, region, expected_num_nodes=1)
    assert_no_errors_in_logs(remote_command_executor, scheduler)


def _test_pcluster_instances_and_status(cluster, region, compute_fleet_status=None):
    """Test pcluster status and pcluster instances functionalities."""
    logging.info("Testing that pcluster status and pcluster instances output are expected")
    cluster_instances_from_ec2 = get_cluster_nodes_instance_ids(cluster.cfn_name, region)
    cluster_instances_from_cli = cluster.instances()
    assert_that(set(cluster_instances_from_cli)).is_equal_to(set(cluster_instances_from_ec2))
    expected_status_details = ["Status: CREATE_COMPLETE", "MasterServer: RUNNING"]
    if compute_fleet_status:
        expected_status_details.append("ComputeFleetStatus: {0}".format(compute_fleet_status))
    cluster_status = cluster.status()
    for detail in expected_status_details:
        assert_that(cluster_status).contains(detail)


def _test_pcluster_stop_and_start(scheduler_commands, cluster, region, expected_num_nodes, hit_cluster=False):
    """Test pcluster start and stop functionality."""
    logging.info("Testing pcluster stop functionalities")
    cluster_stop_output = cluster.stop()
    if hit_cluster:
        # Sample pcluster stop output:
        # Compute fleet status is: RUNNING. Submitting status change request.
        # Request submitted successfully. It might take a while for the transition to complete.
        # Please run 'pcluster status' if you need to check compute fleet status
        expected_stop_output = (
            r"Compute fleet status is: RUNNING.*Submitting status change request.*" "\nRequest submitted successfully"
        )
        assert_that(cluster_stop_output).matches(expected_stop_output)
    wait_for_num_instances_in_cluster(cluster.cfn_name, region, desired=0)
    if hit_cluster:
        _test_pcluster_instances_and_status(cluster, region, compute_fleet_status="STOPPED")
    else:
        _test_pcluster_instances_and_status(cluster, region)

    logging.info("Testing pcluster start functionalities")
    # Do a complicated sequence of start and stop and see if commands will still work
    cluster.start()
    cluster.stop()
    cluster.stop()
    cluster_start_output = cluster.start()
    if hit_cluster:
        # Sample pcluster start output:
        # Compute fleet status is: STOPPED. Submitting status change request.
        # Request submitted successfully. It might take a while for the transition to complete.
        # Please run 'pcluster status' if you need to check compute fleet statu
        expected_start_output = (
            r"Compute fleet status is: STOP.*Submitting status change request.*" "\nRequest submitted successfully"
        )
        assert_that(cluster_start_output).matches(expected_start_output)
    wait_for_num_instances_in_cluster(cluster.cfn_name, region, desired=expected_num_nodes)
    if hit_cluster:
        _test_pcluster_instances_and_status(cluster, region, compute_fleet_status="RUNNING")
    else:
        _test_pcluster_instances_and_status(cluster, region)
