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
import time

import boto3
import configparser
import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from tests.common.scaling_common import (
    get_batch_ce_max_size,
    get_batch_ce_min_size,
    get_max_asg_capacity,
    get_min_asg_capacity,
    watch_compute_nodes,
)
from tests.common.schedulers_common import SlurmCommands
from time_utils import minutes


@pytest.mark.dimensions("eu-west-1", "c5.xlarge", "centos7", "slurm")
@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_update_slurm(region, pcluster_config_reader, clusters_factory, test_datadir, s3_bucket_factory):
    # Create S3 bucket for pre/post install scripts
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "preinstall.sh"), "scripts/preinstall.sh")
    bucket.upload_file(str(test_datadir / "postinstall.sh"), "scripts/postinstall.sh")

    # Create cluster with initial configuration
    init_config_file = pcluster_config_reader()
    cluster = clusters_factory(init_config_file)

    # Command executors
    command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = SlurmCommands(command_executor)

    # Create shared dir for script results
    command_executor.run_remote_command("mkdir /shared/script_results")

    # Update cluster with new configuration
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.update.ini", bucket=bucket_name)
    cluster.config_file = str(updated_config_file)
    cluster.update()

    # Get initial, new and old compute instances references, to be able to execute specific tests in different group of
    # instances
    # Get initial compute nodes
    initial_compute_nodes = slurm_commands.get_compute_nodes()

    # Get new compute nodes
    new_compute_nodes = _add_compute_nodes(slurm_commands)

    # Old compute node instance refs
    old_compute_node = initial_compute_nodes[0]
    old_compute_instance = _get_instance(region, cluster.cfn_name, old_compute_node)

    # New compute node instance refs
    new_compute_node = new_compute_nodes[0]
    new_compute_instance = _get_instance(region, cluster.cfn_name, new_compute_node)

    # Read updated configuration
    updated_config = configparser.ConfigParser()
    updated_config.read(updated_config_file)

    # Check new ASG settings
    _check_initial_queue(region, cluster.cfn_name, updated_config.getint("cluster default", "initial_queue_size"))
    _check_max_queue(region, cluster.cfn_name, updated_config.getint("cluster default", "max_queue_size"))

    # Check new S3 resources
    _check_s3_read_resource(region, cluster, updated_config.get("cluster default", "s3_read_resource"))
    _check_s3_read_write_resource(region, cluster, updated_config.get("cluster default", "s3_read_write_resource"))

    # Check new Additional IAM policies
    _check_role_attached_policy(region, cluster, updated_config.get("cluster default", "additional_iam_policies"))

    # Check old and new compute instance types
    _check_compute_instance_type(old_compute_instance, cluster.config.get("cluster default", "compute_instance_type"))
    _check_compute_instance_type(new_compute_instance, updated_config.get("cluster default", "compute_instance_type"))

    # Check old and new instance life cycle
    _check_ondemand_instance(old_compute_instance)
    _check_spot_instance(new_compute_instance)

    # Check old and new compute root volume size
    _check_compute_root_volume_size(
        command_executor,
        slurm_commands,
        test_datadir,
        cluster.config.get("cluster default", "compute_root_volume_size"),
        old_compute_node,
    )
    _check_compute_root_volume_size(
        command_executor,
        slurm_commands,
        test_datadir,
        updated_config.get("cluster default", "compute_root_volume_size"),
        new_compute_node,
    )

    # Check old and new extra_json
    _check_extra_json(command_executor, slurm_commands, old_compute_node, "test_value_1")
    _check_extra_json(command_executor, slurm_commands, new_compute_node, "test_value_2")

    # Check pre and post install on new nodes
    _check_script(
        command_executor,
        slurm_commands,
        new_compute_node,
        "preinstall",
        updated_config.get("cluster default", "pre_install_args"),
    )
    _check_script(
        command_executor,
        slurm_commands,
        new_compute_node,
        "postinstall",
        updated_config.get("cluster default", "post_install_args"),
    )


def _check_max_queue(region, stack_name, queue_size):
    asg_max_size = get_max_asg_capacity(region, stack_name)
    assert_that(asg_max_size).is_equal_to(queue_size)


def _check_initial_queue(region, stack_name, queue_size):
    asg_min_size = get_min_asg_capacity(region, stack_name)
    assert_that(asg_min_size).is_equal_to(queue_size)


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

    estimated_scaleup_time = 8
    watch_compute_nodes(
        scheduler_commands=slurm_commands,
        max_monitoring_time=minutes(estimated_scaleup_time),
        number_of_nodes=number_of_nodes,
    )

    return [node for node in slurm_commands.get_compute_nodes() if node not in initial_compute_nodes]


def _get_instance(region, stack_name, host, none_expected=False):
    hostname = "{0}.{1}.compute.internal".format(host, region)
    ec2_resource = boto3.resource("ec2", region_name=region)
    instance = next(
        iter(
            ec2_resource.instances.filter(
                Filters=[
                    {"Name": "tag:Application", "Values": [stack_name]},
                    {"Name": "private-dns-name", "Values": [hostname]},
                ]
            )
            or []
        ),
        None,
    )
    if not none_expected:
        assert_that(instance).is_not_none()
    return instance


def _check_compute_instance_type(instance, compute_instance_type):
    assert_that(instance.instance_type).is_equal_to(compute_instance_type)


def _check_spot_instance(instance):
    assert_that(instance.instance_lifecycle).is_equal_to("spot")


def _check_ondemand_instance(instance):
    assert_that(not hasattr(instance, "instance_life_cycle"))


def _check_compute_root_volume_size(command_executor, slurm_commands, test_datadir, compute_root_volume_size, host):
    # submit a job to retrieve compute root volume size and save in a file
    result = slurm_commands.submit_script(str(test_datadir / "slurm_get_root_volume_size.sh"), host=host)
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    slurm_commands.assert_job_succeeded(job_id)

    # read volume size from file
    time.sleep(5)  # wait a bit to be sure to have the file
    result = command_executor.run_remote_command("cat /shared/{0}_root_volume_size.txt".format(host))
    assert_that(result.stdout).matches(r"{size}G".format(size=compute_root_volume_size))


def _retrieve_script_output(slurm_commands, script_name, host):
    # submit a job to retrieve pre and post install outputs
    command = "cp /tmp/{0}_out.txt /shared/script_results/{1}_{0}_out.txt".format(script_name, host)
    result = slurm_commands.submit_command(command, host=host)

    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    slurm_commands.assert_job_succeeded(job_id)

    time.sleep(5)  # wait a bit to be sure to have the files


def _check_script(command_executor, slurm_commands, host, script_name, script_arg):
    _retrieve_script_output(slurm_commands, script_name, host)
    result = command_executor.run_remote_command("cat /shared/script_results/{1}_{0}_out.txt".format(script_name, host))
    assert_that(result.stdout).matches(r"{0}-{1}".format(script_name, script_arg))


def _retrieve_extra_json(slurm_commands, host):
    # submit a job to retrieve the value of the custom key test_key provided with extra_json
    command = "jq .test_key /etc/chef/dna.json > /shared/{0}_extra_json.txt".format(host)
    result = slurm_commands.submit_command(command, host=host)

    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    slurm_commands.assert_job_succeeded(job_id)

    time.sleep(5)  # wait a bit to be sure to have the files


def _check_extra_json(command_executor, slurm_commands, host, expected_value):
    _retrieve_extra_json(slurm_commands, host)
    result = command_executor.run_remote_command("cat /shared/{0}_extra_json.txt".format(host))
    assert_that(result.stdout).is_equal_to('"{0}"'.format(expected_value))


def _check_role_inline_policy(region, cluster, policy_name, policy_statement):
    iam_client = boto3.client("iam", region_name=region)
    root_role = cluster.cfn_resources.get("RootRole")

    statement = (
        iam_client.get_role_policy(RoleName=root_role, PolicyName=policy_name)
        .get("PolicyDocument")
        .get("Statement")[0]
        .get("Resource")[0]
    )
    assert_that(statement).is_equal_to(policy_statement)


def _check_s3_read_resource(region, cluster, s3_arn):
    _check_role_inline_policy(region, cluster, "S3Read", s3_arn)


def _check_s3_read_write_resource(region, cluster, s3_arn):
    _check_role_inline_policy(region, cluster, "S3ReadWrite", s3_arn)


def _check_role_attached_policy(region, cluster, policy_arn):
    iam_client = boto3.client("iam", region_name=region)
    root_role = cluster.cfn_resources.get("RootRole")

    result = iam_client.list_attached_role_policies(RoleName=root_role)

    policies = [p["PolicyArn"] for p in result["AttachedPolicies"]]
    assert policy_arn in policies


@pytest.mark.dimensions("eu-west-1", "c5.xlarge", "alinux2", "awsbatch")
@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_update_awsbatch(region, pcluster_config_reader, clusters_factory, test_datadir, s3_bucket_factory):
    # Create cluster with initial configuration
    init_config_file = pcluster_config_reader()
    cluster = clusters_factory(init_config_file)

    # Verify initial configuration
    _verify_initialization(region, cluster, cluster.config)

    # Update cluster with new configuration
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.update.ini")
    cluster.config_file = str(updated_config_file)
    cluster.update()

    # Read updated configuration
    updated_config = configparser.ConfigParser()
    updated_config.read(updated_config_file)

    # verify updated parameters
    _verify_initialization(region, cluster, updated_config)


def _verify_initialization(region, cluster, config):
    # Verify initial settings
    _test_max_vcpus(region, cluster.cfn_name, config.getint("cluster default", "max_vcpus"))
    _test_min_vcpus(region, cluster.cfn_name, config.getint("cluster default", "min_vcpus"))


def _test_max_vcpus(region, stack_name, vcpus):
    asg_max_size = get_batch_ce_max_size(stack_name, region)
    assert_that(asg_max_size).is_equal_to(vcpus)


def _test_min_vcpus(region, stack_name, vcpus):
    asg_min_size = get_batch_ce_min_size(stack_name, region)
    assert_that(asg_min_size).is_equal_to(vcpus)
