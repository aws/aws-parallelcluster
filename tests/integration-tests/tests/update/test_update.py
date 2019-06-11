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
import time
from collections import namedtuple

import boto3
import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from tests.common.scaling_common import get_max_asg_capacity, watch_compute_nodes
from tests.common.schedulers_common import SlurmCommands
from time_utils import minutes

PClusterConfig = namedtuple(
    "PClusterConfig",
    [
        "max_queue_size",
        "compute_instance_type",
        "compute_root_volume_size",
        "s3_read_resource",
        "s3_read_write_resource",
    ],
)


@pytest.mark.dimensions("eu-west-1", "c5.xlarge", "alinux", "slurm")
@pytest.mark.usefixtures("os", "scheduler")
def test_update(instance, region, pcluster_config_reader, clusters_factory, test_datadir):
    """
    Test 'pcluster update' command.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    s3_arn = "arn:aws:s3:::fake_bucket/*"
    init_config = PClusterConfig(
        max_queue_size=5,
        compute_instance_type=instance,
        compute_root_volume_size=30,
        s3_read_resource=s3_arn,
        s3_read_write_resource=s3_arn,
    )
    cluster = _init_cluster(clusters_factory, pcluster_config_reader, init_config)
    command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = SlurmCommands(command_executor)

    _verify_initialization(command_executor, slurm_commands, region, test_datadir, cluster, init_config)

    s3_arn_updated = "arn:aws:s3:::fake_bucket/fake_folder/*"
    updated_config = PClusterConfig(
        max_queue_size=10,
        compute_instance_type="c4.xlarge",
        compute_root_volume_size=40,
        s3_read_resource=s3_arn_updated,
        s3_read_write_resource=s3_arn_updated,
    )
    _update_cluster(cluster, updated_config)

    # verify updated parameters
    _test_max_queue(region, cluster.cfn_name, updated_config.max_queue_size)
    _test_s3_read_resource(region, cluster, updated_config.s3_read_resource)
    _test_s3_read_write_resource(region, cluster, updated_config.s3_read_write_resource)

    # verify params that are NOT updated in OLD compute nodes
    compute_nodes = slurm_commands.get_compute_nodes()
    _test_compute_instance_type(region, cluster.cfn_name, init_config.compute_instance_type, compute_nodes[0])
    _test_compute_root_volume_size(
        command_executor, slurm_commands, test_datadir, init_config.compute_root_volume_size, compute_nodes[0]
    )
    # add compute nodes and verify updated params in NEW compute nodes
    new_compute_nodes = _add_compute_nodes(slurm_commands)
    _test_compute_instance_type(region, cluster.cfn_name, updated_config.compute_instance_type, new_compute_nodes[0])
    _test_compute_root_volume_size(
        command_executor, slurm_commands, test_datadir, updated_config.compute_root_volume_size, new_compute_nodes[0]
    )


def _init_cluster(clusters_factory, pcluster_config_reader, config):
    # read configuration and create cluster
    cluster_config = pcluster_config_reader(
        max_queue_size=config.max_queue_size,
        compute_instance_type=config.compute_instance_type,
        compute_root_volume_size=config.compute_root_volume_size,
        s3_read_resource=config.s3_read_resource,
        s3_read_write_resource=config.s3_read_write_resource,
    )
    cluster = clusters_factory(cluster_config)
    return cluster


def _verify_initialization(command_executor, slurm_commands, region, test_datadir, cluster, config):
    # Verify initial settings
    _test_max_queue(region, cluster.cfn_name, config.max_queue_size)
    _test_s3_read_resource(region, cluster, config.s3_read_resource)
    _test_s3_read_write_resource(region, cluster, config.s3_read_write_resource)

    # Verify Compute nodes initial settings
    compute_nodes = slurm_commands.get_compute_nodes()
    _test_compute_instance_type(region, cluster.cfn_name, config.compute_instance_type, compute_nodes[0])
    _test_compute_root_volume_size(
        command_executor, slurm_commands, test_datadir, config.compute_root_volume_size, compute_nodes[0]
    )


def _update_cluster(cluster, config):
    # change cluster.config settings
    _update_cluster_property(cluster, "max_queue_size", str(config.max_queue_size))
    _update_cluster_property(cluster, "compute_instance_type", config.compute_instance_type)
    _update_cluster_property(cluster, "compute_root_volume_size", str(config.compute_root_volume_size))
    _update_cluster_property(cluster, "s3_read_resource", config.s3_read_resource)
    _update_cluster_property(cluster, "s3_read_write_resource", config.s3_read_write_resource)
    # rewrite configuration file starting from the updated cluster.config object
    with open(cluster.config_file, "w") as configfile:
        cluster.config.write(configfile)
    # update cluster
    cluster.update()


def _update_cluster_property(cluster, property_name, property_value):
    cluster.config.set("cluster default", property_name, property_value)


def _test_max_queue(region, stack_name, queue_size):
    asg_max_size = get_max_asg_capacity(region, stack_name)
    assert_that(asg_max_size).is_equal_to(queue_size)


def _add_compute_nodes(slurm_commands, number_of_nodes=1):
    """
    Add new compute nodes to the cluster.

    It is required because some changes will be available only on new compute nodes.
    :param cluster: the cluster
    :param number_of_nodes: number of nodes to add
    :return an array containing the new compute nodes only
    """
    initial_compute_nodes = slurm_commands.get_compute_nodes()

    number_of_nodes = len(initial_compute_nodes) + number_of_nodes
    # submit a job to perform a scaling up action and have new instances
    result = slurm_commands.submit_command("sleep 1", nodes=number_of_nodes)
    slurm_commands.assert_job_submitted(result.stdout)

    estimated_scaleup_time = 5
    watch_compute_nodes(
        scheduler_commands=slurm_commands,
        max_monitoring_time=minutes(estimated_scaleup_time),
        number_of_nodes=number_of_nodes,
    )

    return [node for node in slurm_commands.get_compute_nodes() if node not in initial_compute_nodes]


def _test_compute_instance_type(region, stack_name, compute_instance_type, host):
    hostname = "{0}.{1}.compute.internal".format(host, region)
    ec2_resource = boto3.resource("ec2", region_name=region)
    instance_types = []
    for instance in ec2_resource.instances.filter(
        Filters=[
            {"Name": "tag:Application", "Values": [stack_name]},
            {"Name": "private-dns-name", "Values": [hostname]},
        ]
    ):
        instance_types.append(instance.instance_type)

    assert_that(instance_types).contains(compute_instance_type)


def _test_compute_root_volume_size(command_executor, slurm_commands, test_datadir, compute_root_volume_size, host):
    # submit a job to retrieve compute root volume size and save in a file
    result = slurm_commands.submit_script(str(test_datadir / "slurm_get_root_volume_size.sh"), host=host)
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    slurm_commands.assert_job_succeeded(job_id)

    # read volume size from file
    time.sleep(5)  # wait a bit to be sure to have the file
    result = command_executor.run_remote_command("cat /shared/{0}_root_volume_size.txt".format(host))
    assert_that(result.stdout).matches(r"{size}G".format(size=compute_root_volume_size))


def _test_policy_statement(region, cluster, policy_name, policy_statement):
    iam_client = boto3.client("iam", region_name=region)
    root_role = cluster.cfn_resources.get("RootRole")

    statement = (
        iam_client.get_role_policy(RoleName=root_role, PolicyName=policy_name)
        .get("PolicyDocument")
        .get("Statement")[0]
        .get("Resource")[0]
    )
    assert_that(statement).is_equal_to(policy_statement)


def _test_s3_read_resource(region, cluster, s3_arn):
    _test_policy_statement(region, cluster, "S3Read", s3_arn)


def _test_s3_read_write_resource(region, cluster, s3_arn):
    _test_policy_statement(region, cluster, "S3ReadWrite", s3_arn)
