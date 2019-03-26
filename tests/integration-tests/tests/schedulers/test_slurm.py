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
import logging
import time

import boto3
import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from tests.common.scaling_common import get_compute_nodes_allocation
from tests.common.schedulers_common import SlurmCommands
from time_utils import minutes


@pytest.mark.regions(["us-west-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_slurm(region, pcluster_config_reader, clusters_factory):
    """
    Test all AWS Slurm related features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    scaledown_idletime = 3
    max_queue_size = 5
    cluster_config = pcluster_config_reader(scaledown_idletime=scaledown_idletime, max_queue_size=max_queue_size)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_slurm_version(remote_command_executor)
    _test_dynamic_max_cluster_size(remote_command_executor, region, cluster.asg)
    _test_cluster_limits(remote_command_executor, max_queue_size, region, cluster.asg)
    _test_job_dependencies(remote_command_executor, region, cluster.cfn_name, scaledown_idletime)
    _test_dynamic_dummy_nodes(remote_command_executor, max_queue_size)


def _test_slurm_version(remote_command_executor):
    logging.info("Testing Slurm Version")
    version = remote_command_executor.run_remote_command("sinfo -V").stdout
    assert_that(version).is_equal_to("slurm 18.08.6-2")


def _test_dynamic_max_cluster_size(remote_command_executor, region, asg_name):
    logging.info("Testing max cluster size updated when ASG limits change")
    asg_client = boto3.client("autoscaling", region_name=region)

    # Check current dummy-nodes settings
    asg = asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name]).get("AutoScalingGroups")[0]
    current_max_size = asg.get("MaxSize")
    _assert_dummy_nodes(remote_command_executor, current_max_size)

    # Change ASG value and check dummy-nodes settings
    new_max_size = 1
    asg_client.update_auto_scaling_group(AutoScalingGroupName=asg_name, MaxSize=new_max_size)
    time.sleep(40)
    _assert_dummy_nodes(remote_command_executor, new_max_size)

    # Restore initial cluster size
    asg_client.update_auto_scaling_group(AutoScalingGroupName=asg_name, MaxSize=current_max_size)
    time.sleep(40)
    _assert_dummy_nodes(remote_command_executor, current_max_size)


def _test_dynamic_dummy_nodes(remote_command_executor, max_queue_size):
    logging.info("Testing dummy nodes are automatically reconfigured based on actual compute nodes")
    _assert_dummy_nodes(remote_command_executor, max_queue_size)
    slurm_commands = SlurmCommands(remote_command_executor)
    result = slurm_commands.submit_command("sleep 1", nodes=1)
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    _assert_dummy_nodes(remote_command_executor, max_queue_size - 1)


def _test_job_dependencies(remote_command_executor, region, stack_name, scaledown_idletime):
    logging.info("Testing cluster doesn't scale when job dependencies are not satisfied")
    slurm_commands = SlurmCommands(remote_command_executor)
    result = slurm_commands.submit_command("sleep 60", nodes=1)
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    result = remote_command_executor.run_remote_command("sbatch -N 1 --wrap='sleep 1' -d afterok:{0}".format(job_id))
    dependent_job_id = slurm_commands.assert_job_submitted(result.stdout)

    # Wait for reason to be computed
    time.sleep(3)
    assert_that(_get_job_info(remote_command_executor, job_id)).contains(
        "JobState=PENDING Reason=Nodes_required_for_job_are_DOWN,_DRAINED"
        "_or_reserved_for_jobs_in_higher_priority_partitions"
    )
    assert_that(_get_job_info(remote_command_executor, dependent_job_id)).contains("JobState=PENDING Reason=Dependency")

    jobs_execution_time = 1
    estimated_scaleup_time = 5
    asg_capacity_time_series, compute_nodes_time_series, timestamps = get_compute_nodes_allocation(
        scheduler_commands=slurm_commands,
        region=region,
        stack_name=stack_name,
        max_monitoring_time=minutes(jobs_execution_time)
        + minutes(scaledown_idletime)
        + minutes(estimated_scaleup_time)
        + minutes(10),
    )
    assert_that(max(asg_capacity_time_series)).is_equal_to(1)
    assert_that(max(compute_nodes_time_series)).is_equal_to(1)
    assert_that(asg_capacity_time_series[-1]).is_equal_to(0)
    assert_that(compute_nodes_time_series[-1]).is_equal_to(0)


def _test_cluster_limits(remote_command_executor, max_queue_size, region, asg_name):
    logging.info("Testing cluster doesn't scale when job requires a capacity that is higher than the max available")
    slurm_commands = SlurmCommands(remote_command_executor)
    result = slurm_commands.submit_command("sleep 1", nodes=max_queue_size + 1)
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    # Wait for reason to be computed
    time.sleep(3)
    assert_that(_get_job_info(remote_command_executor, job_id)).contains("JobState=PENDING Reason=PartitionNodeLimit")

    # Check we are not scaling
    time.sleep(60)
    asg_client = boto3.client("autoscaling", region_name=region)
    asg = asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name]).get("AutoScalingGroups")[0]
    assert_that(asg.get("DesiredCapacity")).is_equal_to(0)


def _retrieve_slurm_dummy_nodes_from_config(remote_command_executor):
    retrieve_dummy_nodes_command = "sudo cat /opt/slurm/etc/slurm_parallelcluster_nodes.conf | head -n 1"
    return remote_command_executor.run_remote_command(retrieve_dummy_nodes_command).stdout


def _retrieve_slurm_dummy_nodes(remote_command_executor):
    retrieve_dummy_nodes_command = "scontrol -F show nodes | grep 'State=FUTURE'"
    return len(remote_command_executor.run_remote_command(retrieve_dummy_nodes_command).stdout.split("\n"))


def _assert_dummy_nodes(remote_command_executor, count):
    __tracebackhide__ = True
    dummy_nodes_config = _retrieve_slurm_dummy_nodes_from_config(remote_command_executor)
    assert_that(dummy_nodes_config).is_equal_to("NodeName=dummy-compute[1-{0}] CPUs=2048 State=FUTURE".format(count))
    dummy_nodes_count = _retrieve_slurm_dummy_nodes(remote_command_executor)
    assert_that(dummy_nodes_count).is_equal_to(count)


def _get_job_info(remote_command_executor, job_id):
    return remote_command_executor.run_remote_command("scontrol show jobs -o {0}".format(job_id)).stdout
