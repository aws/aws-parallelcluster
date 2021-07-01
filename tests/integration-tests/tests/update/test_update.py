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
import re
import time

import boto3
import pytest
import utils
import yaml
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from s3_common_utils import check_s3_read_resource, check_s3_read_write_resource, get_policy_resources

from tests.common.hit_common import assert_initial_conditions
from tests.common.scaling_common import get_batch_ce, get_batch_ce_max_size, get_batch_ce_min_size
from tests.common.schedulers_common import SlurmCommands


@pytest.mark.dimensions("us-west-1", "c5.xlarge", "*", "slurm")
@pytest.mark.usefixtures("os", "instance")
def test_update_slurm(region, pcluster_config_reader, s3_bucket_factory, clusters_factory, test_datadir):
    # Create S3 bucket for pre/post install scripts
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "preinstall.sh"), "scripts/preinstall.sh")
    bucket.upload_file(str(test_datadir / "postinstall.sh"), "scripts/postinstall.sh")

    # Create cluster with initial configuration
    init_config_file = pcluster_config_reader(resource_bucket=bucket_name)
    cluster = clusters_factory(init_config_file)

    # Update cluster with the same configuration, command should not result any error even if not using force update
    cluster.update(str(init_config_file), force=True)

    # Command executors
    command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = SlurmCommands(command_executor)

    # Create shared dir for script results
    command_executor.run_remote_command("mkdir -p /shared/script_results")

    initial_queues_config = {
        "queue1": {
            "compute_resources": {
                "queue1-i1": {
                    "instance_type": "c5.xlarge",
                    "expected_running_instances": 1,
                    "expected_power_saved_instances": 1,
                    "enable_efa": False,
                    "disable_hyperthreading": False,
                },
                "queue1-i2": {
                    "instance_type": "t2.micro",
                    "expected_running_instances": 1,
                    "expected_power_saved_instances": 9,
                    "enable_efa": False,
                    "disable_hyperthreading": False,
                },
            },
            "compute_type": "ondemand",
        },
        "queue2": {
            "compute_resources": {
                "queue2-i1": {
                    "instance_type": "c5n.18xlarge",
                    "expected_running_instances": 0,
                    "expected_power_saved_instances": 10,
                    "enable_efa": False,
                    "disable_hyperthreading": False,
                },
            },
            "compute_type": "ondemand",
        },
    }

    _assert_scheduler_nodes(queues_config=initial_queues_config, slurm_commands=slurm_commands)
    _assert_launch_templates_config(queues_config=initial_queues_config, cluster_name=cluster.name, region=region)

    # Submit a job in order to verify that jobs are not affected by an update of the queue size
    result = slurm_commands.submit_command("sleep infinity", constraint="static&c5.xlarge")
    job_id = slurm_commands.assert_job_submitted(result.stdout)

    # Update cluster with new configuration
    additional_policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonAppStreamServiceAccess"
    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update.yaml",
        bucket=bucket_name,
        resource_bucket=bucket_name,
        additional_policy_arn=additional_policy_arn,
    )
    cluster.update(str(updated_config_file))

    # Here is the expected list of nodes.
    # the cluster:
    # queue1-st-c5xlarge-1
    # queue1-st-c5xlarge-2
    assert_initial_conditions(slurm_commands, 2, 0, partition="queue1")

    updated_queues_config = {
        "queue1": {
            "compute_resources": {
                "queue1-i1": {
                    "instance_type": "c5.xlarge",
                    "expected_running_instances": 2,
                    "expected_power_saved_instances": 2,
                    "disable_hyperthreading": False,
                    "enable_efa": False,
                },
                "queue1-i2": {
                    "instance_type": "c5.2xlarge",
                    "expected_running_instances": 0,
                    "expected_power_saved_instances": 10,
                    "disable_hyperthreading": False,
                    "enable_efa": False,
                },
                "queue1-i3": {
                    "instance_type": "t2.micro",
                    "expected_running_instances": 0,
                    "expected_power_saved_instances": 10,
                    "disable_hyperthreading": False,
                    "enable_efa": False,
                },
            },
            "compute_type": "spot",
        },
        "queue2": {
            "compute_resources": {
                "queue2-i1": {
                    "instance_type": "c5n.18xlarge",
                    "expected_running_instances": 0,
                    "expected_power_saved_instances": 1,
                    "enable_efa": True,
                    "disable_hyperthreading": True,
                },
            },
            "compute_type": "ondemand",
        },
        "queue3": {
            "compute_resources": {
                "queue3-i1": {
                    "instance_type": "c5n.18xlarge",
                    "expected_running_instances": 0,
                    "expected_power_saved_instances": 10,
                    "disable_hyperthreading": True,
                    "enable_efa": True,
                },
                "queue3-i2": {
                    "instance_type": "t2.xlarge",
                    "expected_running_instances": 0,
                    "expected_power_saved_instances": 10,
                    "disable_hyperthreading": False,
                    "enable_efa": False,
                },
            },
            "compute_type": "ondemand",
        },
    }

    _assert_scheduler_nodes(queues_config=updated_queues_config, slurm_commands=slurm_commands)
    _assert_launch_templates_config(queues_config=updated_queues_config, cluster_name=cluster.name, region=region)

    # Read updated configuration
    with open(updated_config_file) as conf_file:
        updated_config = yaml.safe_load(conf_file)

    # Check new S3 resources
    check_s3_read_resource(region, cluster, get_policy_resources(updated_config, enable_write_access=False))
    check_s3_read_write_resource(region, cluster, get_policy_resources(updated_config, enable_write_access=True))

    # Check new Additional IAM policies
    _check_role_attached_policy(region, cluster, additional_policy_arn)

    # Assert that the job submitted before the update is still running
    assert_that(slurm_commands.get_job_info(job_id)).contains("JobState=RUNNING")

    # TODO add following tests:
    # - Check Additional IAM policies
    # - Check compute root volume size
    # - Check pre/post install scripts
    # - Test extra json


def _assert_launch_templates_config(queues_config, cluster_name, region):
    logging.info("Checking launch templates")
    ec2_client = boto3.client("ec2", region_name=region)
    for queue, queue_config in queues_config.items():
        for compute_resource_config in queue_config["compute_resources"].values():
            launch_template_name = f"{cluster_name}-{queue}-{compute_resource_config.get('instance_type')}"
            logging.info("Validating LaunchTemplate: %s", launch_template_name)
            launch_template_data = ec2_client.describe_launch_template_versions(
                LaunchTemplateName=launch_template_name, Versions=["$Latest"]
            )["LaunchTemplateVersions"][0]["LaunchTemplateData"]
            if queue_config["compute_type"] == "spot":
                assert_that(launch_template_data["InstanceMarketOptions"]["MarketType"]).is_equal_to(
                    queue_config["compute_type"]
                )
            else:
                assert_that("InstanceMarketOptions").is_not_in(launch_template_data)
            assert_that(launch_template_data["InstanceType"]).is_equal_to(compute_resource_config["instance_type"])
            if compute_resource_config["disable_hyperthreading"]:
                assert_that(launch_template_data["CpuOptions"]["ThreadsPerCore"]).is_equal_to(1)
            else:
                assert_that("CpuOptions").is_not_in(launch_template_data)
            if compute_resource_config["enable_efa"]:
                assert_that(launch_template_data["NetworkInterfaces"][0]["InterfaceType"]).is_equal_to("efa")
            else:
                assert_that("InterfaceType").is_not_in(launch_template_data["NetworkInterfaces"][0])


def _assert_scheduler_nodes(queues_config, slurm_commands):
    logging.info("Checking scheduler nodes")
    slurm_nodes = slurm_commands.get_nodes_status()
    slurm_nodes_str = ""
    for node, state in slurm_nodes.items():
        slurm_nodes_str += f"{node} {state}\n"
    for queue, queue_config in queues_config.items():
        for compute_resource_name, compute_resource_config in queue_config["compute_resources"].items():
            sanitized_name = re.sub(r"[^A-Za-z0-9]", "", compute_resource_name)
            running_instances = len(
                re.compile(fr"{queue}-(dy|st)-{sanitized_name}-\d+ (idle|mixed|alloc)\n").findall(slurm_nodes_str)
            )
            power_saved_instances = len(
                re.compile(fr"{queue}-(dy|st)-{sanitized_name}-\d+ idle~\n").findall(slurm_nodes_str)
            )
            assert_that(running_instances).is_equal_to(compute_resource_config["expected_running_instances"])
            assert_that(power_saved_instances).is_equal_to(compute_resource_config["expected_power_saved_instances"])


def _add_compute_nodes(scheduler_commands, slots_per_node, number_of_nodes=1):
    """
    Add new compute nodes to the cluster.

    It is required because some changes will be available only on new compute nodes.
    :param cluster: the cluster
    :param number_of_nodes: number of nodes to add
    :return an array containing the new compute nodes only
    """
    initial_compute_nodes = scheduler_commands.get_compute_nodes()

    number_of_nodes = len(initial_compute_nodes) + number_of_nodes
    # submit a job to perform a scaling up action and have new instances
    result = scheduler_commands.submit_command("sleep 1", nodes=number_of_nodes, slots=slots_per_node)
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    return [node for node in scheduler_commands.get_compute_nodes() if node not in initial_compute_nodes]


def _get_instance(region, stack_name, host, none_expected=False):
    if region == "us-east-1":
        hostname = "{0}.ec2.internal".format(host)
    else:
        hostname = "{0}.{1}.compute.internal".format(host, region)
    ec2_resource = boto3.resource("ec2", region_name=region)
    instance = next(
        iter(
            ec2_resource.instances.filter(
                Filters=[
                    {"Name": "tag:parallelcluster:cluster-name", "Values": [stack_name]},
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


def _check_compute_root_volume_size(command_executor, scheduler_commands, test_datadir, compute_root_volume_size, host):
    # submit a job to retrieve compute root volume size and save in a file
    result = scheduler_commands.submit_script(str(test_datadir / "slurm_get_root_volume_size.sh"), host=host)
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    # read volume size from file
    time.sleep(5)  # wait a bit to be sure to have the file
    result = command_executor.run_remote_command("cat /shared/{0}_root_volume_size.txt".format(host))
    assert_that(result.stdout).matches(r"{size}G".format(size=compute_root_volume_size))


def _retrieve_script_output(scheduler_commands, script_name, host):
    # submit a job to retrieve pre and post install outputs
    command = "cp /tmp/{0}_out.txt /shared/script_results/{1}_{0}_out.txt".format(script_name, host)
    result = scheduler_commands.submit_command(command, host=host)

    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    time.sleep(5)  # wait a bit to be sure to have the files


def _check_script(command_executor, scheduler_commands, host, script_name, script_arg):
    _retrieve_script_output(scheduler_commands, script_name, host)
    result = command_executor.run_remote_command("cat /shared/script_results/{1}_{0}_out.txt".format(script_name, host))
    assert_that(result.stdout).matches(r"{0}-{1}".format(script_name, script_arg))


def _retrieve_extra_json(scheduler_commands, host):
    # submit a job to retrieve the value of the custom key test_key provided with extra_json
    command = "jq .test_key /etc/chef/dna.json > /shared/{0}_extra_json.txt".format(host)
    result = scheduler_commands.submit_command(command, host=host)

    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    time.sleep(5)  # wait a bit to be sure to have the files


def _check_extra_json(command_executor, scheduler_commands, host, expected_value):
    _retrieve_extra_json(scheduler_commands, host)
    result = command_executor.run_remote_command("cat /shared/{0}_extra_json.txt".format(host))
    assert_that(result.stdout).is_equal_to('"{0}"'.format(expected_value))


def _check_role_attached_policy(region, cluster, policy_arn):
    iam_client = boto3.client("iam", region_name=region)
    cfn_resources = cluster.cfn_resources
    for resource in cfn_resources:
        if resource.startswith("Role"):
            logging.info("checking role %s", resource)
            role = cluster.cfn_resources.get(resource)
            result = iam_client.list_attached_role_policies(RoleName=role)
            policies = [p["PolicyArn"] for p in result["AttachedPolicies"]]
            assert_that(policy_arn in policies).is_true()


def get_cfn_ebs_volume_ids(cluster, region):
    # get the list of configured ebs volume ids
    # example output: ['vol-000', 'vol-001', 'vol-002']
    ebs_stack = utils.get_substacks(cluster.cfn_name, region=region, sub_stack_name="EBSCfnStack")[0]
    return utils.retrieve_cfn_outputs(ebs_stack, region).get("Volumeids").split(",")


def get_ebs_volume_info(volume_id, region):
    volume = boto3.client("ec2", region_name=region).describe_volumes(VolumeIds=[volume_id]).get("Volumes")[0]
    volume_type = volume.get("VolumeType")
    volume_iops = volume.get("Iops")
    volume_throughput = volume.get("Throughput")
    return volume_type, volume_iops, volume_throughput


def _check_volume(cluster, config, region):
    logging.info("checking volume throughout and iops change")
    volume_ids = get_cfn_ebs_volume_ids(cluster, region)
    volume_type = config.get("ebs custom", "volume_type")
    actual_volume_type, actual_volume_iops, actual_volume_throughput = get_ebs_volume_info(volume_ids[0], region)
    if volume_type:
        assert_that(actual_volume_type).is_equal_to(volume_type)
    else:
        # the default volume type is gp2
        assert_that("gp2").is_equal_to(volume_type)
    if volume_type in ["io1", "io2", "gp3"]:
        volume_iops = config.get("ebs custom", "volume_iops")
        assert_that(actual_volume_iops).is_equal_to(int(volume_iops))
        if volume_type == "gp3":
            throughput = config.get("ebs custom", "volume_throughput")
            volume_throughput = throughput if throughput else 125
            assert_that(actual_volume_throughput).is_equal_to(int(volume_throughput))


@pytest.mark.dimensions("eu-west-1", "c5.xlarge", "alinux2", "awsbatch")
@pytest.mark.usefixtures("os", "instance")
def test_update_awsbatch(region, pcluster_config_reader, clusters_factory, test_datadir):
    # Create cluster with initial configuration
    init_config_file = pcluster_config_reader()
    cluster = clusters_factory(init_config_file)

    # Verify initial configuration
    _verify_initialization(region, cluster, cluster.config)

    # Update cluster with the same configuration, command should not result any error even if not using force update
    cluster.update(str(init_config_file), force=False)

    # Update cluster with new configuration
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.update.yaml")
    cluster.update(str(updated_config_file))

    # Read updated configuration
    with open(updated_config_file) as conf_file:
        updated_config = yaml.safe_load(conf_file)

    # verify updated parameters
    _verify_initialization(region, cluster, updated_config)


def _verify_initialization(region, cluster, config):
    # Verify initial settings
    _test_max_vcpus(region, cluster.cfn_name, config["Scheduling"]["Queues"][0]["ComputeResources"][0]["MaxvCpus"])
    _test_min_vcpus(region, cluster.cfn_name, config["Scheduling"]["Queues"][0]["ComputeResources"][0]["MinvCpus"])
    spot_bid_percentage = config["Scheduling"]["Queues"][0]["ComputeResources"][0]["SpotBidPercentage"]
    assert_that(get_batch_spot_bid_percentage(cluster.cfn_name, region)).is_equal_to(spot_bid_percentage)


def _test_max_vcpus(region, stack_name, vcpus):
    ce_max_size = get_batch_ce_max_size(stack_name, region)
    assert_that(ce_max_size).is_equal_to(vcpus)


def _test_min_vcpus(region, stack_name, vcpus):
    ce_min_size = get_batch_ce_min_size(stack_name, region)
    assert_that(ce_min_size).is_equal_to(vcpus)


def get_batch_spot_bid_percentage(stack_name, region):
    client = boto3.client("batch", region_name=region)

    return (
        client.describe_compute_environments(computeEnvironments=[get_batch_ce(stack_name, region)])
        .get("computeEnvironments")[0]
        .get("computeResources")
        .get("bidPercentage")
    )
