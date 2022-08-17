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

from tests.common.assertions import assert_errors_in_logs, assert_no_msg_in_logs
from tests.common.hit_common import assert_compute_node_states, assert_initial_conditions, wait_for_compute_nodes_states
from tests.common.scaling_common import get_batch_ce, get_batch_ce_max_size, get_batch_ce_min_size
from tests.common.schedulers_common import SlurmCommands
from tests.common.utils import generate_random_string, retrieve_latest_ami


@pytest.mark.usefixtures("os", "instance")
def test_update_slurm(region, pcluster_config_reader, s3_bucket_factory, clusters_factory, test_datadir):
    # Create S3 bucket for pre/post install scripts
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    for script in ["preinstall.sh", "postinstall.sh", "updated_preinstall.sh", "updated_postinstall.sh"]:
        bucket.upload_file(str(test_datadir / script), f"scripts/{script}")

    # Create cluster with initial configuration
    init_config_file = pcluster_config_reader(resource_bucket=bucket_name, bucket=bucket_name)
    cluster = clusters_factory(init_config_file)

    # Update cluster with the same configuration, command should not result any error even if not using force update
    cluster.update(str(init_config_file), force_update="true")

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
                }
            },
            "compute_type": "ondemand",
        },
    }

    _assert_scheduler_nodes(queues_config=initial_queues_config, slurm_commands=slurm_commands)
    _assert_launch_templates_config(queues_config=initial_queues_config, cluster_name=cluster.name, region=region)

    # submit job in queue1 to verify original pre/post-install script execution
    initial_compute_nodes = slurm_commands.get_compute_nodes(filter_by_partition="queue1")
    _check_script(command_executor, slurm_commands, initial_compute_nodes[0], "preinstall", "QWE")
    _check_script(command_executor, slurm_commands, initial_compute_nodes[0], "postinstall", "RTY")

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
    cluster.update(str(updated_config_file), force_update="true")

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
                }
            },
            "compute_type": "ondemand",
            "networking": {"placement_group": {"enabled": False}},
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
            "networking": {"placement_group": {"enabled": False}},
        },
    }

    _assert_scheduler_nodes(queues_config=updated_queues_config, slurm_commands=slurm_commands)
    _assert_launch_templates_config(queues_config=updated_queues_config, cluster_name=cluster.name, region=region)

    # Read updated configuration
    with open(updated_config_file, encoding="utf-8") as conf_file:
        updated_config = yaml.safe_load(conf_file)

    # Check new S3 resources
    check_s3_read_resource(region, cluster, get_policy_resources(updated_config, enable_write_access=False))
    check_s3_read_write_resource(region, cluster, get_policy_resources(updated_config, enable_write_access=True))

    # Check new Additional IAM policies
    _check_role_attached_policy(region, cluster, additional_policy_arn)

    # Assert that the job submitted before the update is still running
    assert_that(slurm_commands.get_job_info(job_id)).contains("JobState=RUNNING")

    _check_volume(cluster, updated_config, region)

    # Launch a new instance for queue1 and test updated pre/post install script execution and extra json update
    # Add a new dynamic node t2.micro to queue1-i3
    new_compute_node = _add_compute_nodes(slurm_commands, "queue1", "t2.micro")

    assert_that(len(new_compute_node)).is_equal_to(1)
    _check_script(command_executor, slurm_commands, new_compute_node[0], "updated_preinstall", "ABC")
    _check_script(command_executor, slurm_commands, new_compute_node[0], "updated_postinstall", "DEF")

    # check new extra json
    _check_extra_json(command_executor, slurm_commands, new_compute_node[0], "test_value")


def _assert_launch_templates_config(queues_config, cluster_name, region):
    logging.info("Checking launch templates")
    ec2_client = boto3.client("ec2", region_name=region)
    for queue, queue_config in queues_config.items():
        for compute_resource_name, compute_resource_config in queue_config["compute_resources"].items():
            launch_template_name = f"{cluster_name}-{queue}-{compute_resource_name}"
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
            running_instances = len(
                re.compile(rf"{queue}-(dy|st)-{compute_resource_name}-\d+ (idle|mixed|alloc)\n").findall(
                    slurm_nodes_str
                )
            )
            power_saved_instances = len(
                re.compile(rf"{queue}-(dy|st)-{compute_resource_name}-\d+ idle~\n").findall(slurm_nodes_str)
            )
            assert_that(running_instances).is_equal_to(compute_resource_config["expected_running_instances"])
            assert_that(power_saved_instances).is_equal_to(compute_resource_config["expected_power_saved_instances"])


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


def _get_cfn_ebs_volume_ids(cluster):
    # get the list of configured ebs volume ids
    # example output: ['vol-000', 'vol-001', 'vol-002']
    return cluster.cfn_outputs["EBSIds"].split(",")


def _get_ebs_volume_info(volume_id, region):
    volume = boto3.client("ec2", region_name=region).describe_volumes(VolumeIds=[volume_id]).get("Volumes")[0]
    volume_type = volume.get("VolumeType")
    volume_iops = volume.get("Iops")
    volume_throughput = volume.get("Throughput")
    return volume_type, volume_iops, volume_throughput


def _check_volume(cluster, config, region):
    logging.info("checking volume throughout and iops change")
    volume_ids = _get_cfn_ebs_volume_ids(cluster)
    volume_type = config["SharedStorage"][0]["EbsSettings"]["VolumeType"]
    actual_volume_type, actual_volume_iops, actual_volume_throughput = _get_ebs_volume_info(volume_ids[0], region)
    if volume_type:
        assert_that(actual_volume_type).is_equal_to(volume_type)
    else:
        # the default volume type is gp3
        assert_that("gp3").is_equal_to(volume_type)
    if volume_type in ["io1", "io2", "gp3"]:
        volume_iops = config["SharedStorage"][0]["EbsSettings"]["Iops"]
        assert_that(actual_volume_iops).is_equal_to(int(volume_iops))
        if volume_type == "gp3":
            throughput = config["SharedStorage"][0]["EbsSettings"]["Throughput"]
            volume_throughput = throughput if throughput else 125
            assert_that(actual_volume_throughput).is_equal_to(int(volume_throughput))


def _check_script(command_executor, slurm_commands, host, script_name, script_arg):
    logging.info(f"Checking {script_name} script")

    # submit a job to retrieve pre and post install outputs
    output_file_path = f"/shared/script_results/{host}_{script_name}_out.txt"
    command = f"cp /tmp/{script_name}_out.txt {output_file_path}"
    result = slurm_commands.submit_command(command, host=host)

    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    slurm_commands.assert_job_succeeded(job_id)

    time.sleep(5)  # wait a bit to be sure to have the file

    result = command_executor.run_remote_command(f"cat {output_file_path}")
    assert_that(result.stdout).matches(rf"{script_name}-{script_arg}")


def _add_compute_nodes(slurm_commands, partition, constraint, number_of_nodes=1):
    """
    Add new compute nodes to the cluster.
    It is required because some changes will be available only on new compute nodes.
    :param cluster: the cluster
    :param number_of_nodes: number of nodes to add
    :return: an array containing the new compute nodes only
    """
    logging.info(f"launch a new {constraint} compute node in partition {partition}")
    initial_compute_nodes = slurm_commands.get_compute_nodes()

    # submit a job to perform a scaling up action and have new instances
    result = slurm_commands.submit_command("sleep 1", nodes=number_of_nodes, partition=partition, constraint=constraint)
    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    slurm_commands.assert_job_succeeded(job_id)

    return [node for node in slurm_commands.get_compute_nodes() if node not in initial_compute_nodes]


def _retrieve_extra_json(slurm_commands, host):
    # submit a job to retrieve the value of the custom key test_key provided with extra_json
    command = "jq .test_key /etc/chef/dna.json > /shared/{0}_extra_json.txt".format(host)
    result = slurm_commands.submit_command(command, host=host)

    job_id = slurm_commands.assert_job_submitted(result.stdout)
    slurm_commands.wait_job_completed(job_id)
    slurm_commands.assert_job_succeeded(job_id)

    time.sleep(5)  # wait a bit to be sure to have the files


def _check_extra_json(command_executor, slurm_commands, host, expected_value):
    logging.info("checking extra json")
    _retrieve_extra_json(slurm_commands, host)
    result = command_executor.run_remote_command("cat /shared/{0}_extra_json.txt".format(host))
    assert_that(result.stdout).is_equal_to('"{0}"'.format(expected_value))


@pytest.mark.usefixtures("os", "instance")
def test_update_awsbatch(region, pcluster_config_reader, clusters_factory, test_datadir):
    # Create cluster with initial configuration
    init_config_file = pcluster_config_reader()
    cluster = clusters_factory(init_config_file)

    # Verify initial configuration
    _verify_initialization(region, cluster, cluster.config)

    # Update cluster with the same configuration
    cluster.update(str(init_config_file), force_update="true")

    # Update cluster with new configuration
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.update.yaml")
    cluster.update(str(updated_config_file))

    # Read updated configuration
    with open(updated_config_file, encoding="utf-8") as conf_file:
        updated_config = yaml.safe_load(conf_file)

    # verify updated parameters
    _verify_initialization(region, cluster, updated_config)


@pytest.mark.usefixtures("instance")
def test_update_compute_ami(region, os, pcluster_config_reader, ami_copy, clusters_factory, test_datadir, request):
    # Create cluster with initial configuration
    ec2 = boto3.client("ec2", region)
    pcluster_ami_id = retrieve_latest_ami(region, os, ami_type="pcluster", request=request)
    init_config_file = pcluster_config_reader(global_custom_ami=pcluster_ami_id)
    cluster = clusters_factory(init_config_file)
    instances = cluster.get_cluster_instance_ids(node_type="Compute")
    logging.info(instances)
    _check_instance_ami_id(ec2, instances, pcluster_ami_id)

    pcluster_copy_ami_id = ami_copy(
        pcluster_ami_id, "-".join(["test", "update", "computenode", generate_random_string()])
    )

    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update.yaml", global_custom_ami=pcluster_ami_id, custom_ami=pcluster_copy_ami_id
    )
    # stop compute fleet before updating queue image
    cluster.stop()
    cluster.update(str(updated_config_file), force_update="true")
    instances = cluster.get_cluster_instance_ids(node_type="Compute")
    logging.info(instances)
    _check_instance_ami_id(ec2, instances, pcluster_copy_ami_id)


def _check_instance_ami_id(ec2, instances, expected_queue_ami):
    for instance_id in instances:
        instance_info = ec2.describe_instances(Filters=[], InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]
        assert_that(instance_info["ImageId"]).is_equal_to(expected_queue_ami)


def _verify_initialization(region, cluster, config):
    # Verify initial settings
    _test_max_vcpus(
        region, cluster.cfn_name, config["Scheduling"]["AwsBatchQueues"][0]["ComputeResources"][0]["MaxvCpus"]
    )
    _test_min_vcpus(
        region, cluster.cfn_name, config["Scheduling"]["AwsBatchQueues"][0]["ComputeResources"][0]["MinvCpus"]
    )
    spot_bid_percentage = config["Scheduling"]["AwsBatchQueues"][0]["ComputeResources"][0]["SpotBidPercentage"]
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


@pytest.mark.parametrize(
    "queue_update_strategy",
    [
        "DRAIN",
        "TERMINATE",
    ],
)
@pytest.mark.usefixtures("instance")
def test_queue_parameters_update(
    region,
    os,
    pcluster_config_reader,
    ami_copy,
    clusters_factory,
    scheduler_commands_factory,
    request,
    queue_update_strategy,
):
    """Test update cluster with drain strategy."""
    # Create cluster with initial configuration
    initial_compute_root_volume_size = 35
    updated_compute_root_volume_size = 40
    pcluster_ami_id = retrieve_latest_ami(region, os, ami_type="pcluster", request=request)
    pcluster_copy_ami_id = ami_copy(
        pcluster_ami_id, "-".join(["test", "update", "computenode", generate_random_string()])
    )

    init_config_file = pcluster_config_reader(
        global_custom_ami=pcluster_ami_id, initial_compute_root_volume_size=initial_compute_root_volume_size
    )

    cluster = clusters_factory(init_config_file)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    _test_update_queue_strategy_without_running_job(
        pcluster_config_reader,
        pcluster_ami_id,
        cluster,
        region,
        os,
        remote_command_executor,
        scheduler_commands,
        updated_compute_root_volume_size,
        queue_update_strategy,
    )

    # test update without setting queue strategy, update will fail
    _test_update_without_queue_strategy(
        pcluster_config_reader, pcluster_ami_id, pcluster_copy_ami_id, cluster, updated_compute_root_volume_size
    )

    _test_update_queue_strategy_with_running_job(
        scheduler_commands,
        pcluster_config_reader,
        pcluster_ami_id,
        pcluster_copy_ami_id,
        updated_compute_root_volume_size,
        cluster,
        remote_command_executor,
        region,
        queue_update_strategy,
    )

    # assert queue drain strategy doesn't trigger protected mode
    assert_no_msg_in_logs(
        remote_command_executor,
        ["/var/log/parallelcluster/clustermgtd"],
        ["Node bootstrap error"],
    )


def _test_update_without_queue_strategy(
    pcluster_config_reader, pcluster_ami_id, pcluster_copy_ami_id, cluster, updated_compute_root_volume_size
):
    """Test update without setting queue strategy, update will fail."""
    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update.yaml",
        global_custom_ami=pcluster_ami_id,
        custom_ami=pcluster_copy_ami_id,
        updated_compute_root_volume_size=updated_compute_root_volume_size,
    )
    response = cluster.update(str(updated_config_file), raise_on_error=False)
    assert_that(response["message"]).is_equal_to("Update failure")
    assert_that(response.get("updateValidationErrors")[0].get("message")).contains(
        "All compute nodes must be stopped or QueueUpdateStrategy must be set"
    )


def _check_queue_ami(cluster, ec2, ami, queue_name):
    """Check if the ami of the queue instances are expected"""
    instances = cluster.get_cluster_instance_ids(node_type="Compute", queue_name=queue_name)
    _check_instance_ami_id(ec2, instances, ami)


def _test_update_queue_strategy_without_running_job(
    pcluster_config_reader,
    pcluster_ami_id,
    cluster,
    region,
    os,
    remote_command_executor,
    scheduler_commands,
    updated_compute_root_volume_size,
    queue_update_strategy,
):
    """Test queue parameter update with drain stragegy without running job in the queue."""
    updated_config_file = pcluster_config_reader(
        config_file="pcluster.update_drain_without_running_job.yaml",
        global_custom_ami=pcluster_ami_id,
        updated_compute_root_volume_size=updated_compute_root_volume_size,
        queue_update_strategy=queue_update_strategy,
    )
    cluster.update(str(updated_config_file))
    # check chef client log contains expected log
    assert_errors_in_logs(
        remote_command_executor,
        ["/var/log/chef-client.log"],
        [
            f"Queue update strategy is \\({queue_update_strategy}\\)",
            "Adding queue \\(queue1\\) to list of queue to be updated",
        ],
    )
    queue1_nodes = scheduler_commands.get_compute_nodes("queue1")
    wait_for_compute_nodes_states(scheduler_commands, queue1_nodes, expected_states=["idle", "idle~"])
    # test volume size are expected after update
    instances = cluster.get_cluster_instance_ids(node_type="Compute", queue_name="queue1")
    for instance in instances:
        root_volume_id = utils.get_root_volume_id(instance, region, os)
        volume_size = (
            boto3.client("ec2", region_name=region)
            .describe_volumes(VolumeIds=[root_volume_id])
            .get("Volumes")[0]
            .get("Size")
        )
        assert_that(volume_size).is_equal_to(updated_compute_root_volume_size)


def _test_update_queue_strategy_with_running_job(
    scheduler_commands,
    pcluster_config_reader,
    pcluster_ami_id,
    pcluster_copy_ami_id,
    updated_compute_root_volume_size,
    cluster,
    remote_command_executor,
    region,
    queue_update_strategy,
):
    queue1_job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 3000",
            "nodes": -1,
            "partition": "queue1",
            "other_options": "-a 1-5",  # instance type has 4 cpus per node, which requires 2 nodes to run the job
        }
    )

    queue2_job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 3000", "nodes": -1, "partition": "queue2", "other_options": "-a 1-5"}
    )
    # Wait for the job to run
    scheduler_commands.wait_job_running(queue1_job_id)
    scheduler_commands.wait_job_running(queue2_job_id)

    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update_drain.yaml",
        global_custom_ami=pcluster_ami_id,
        custom_ami=pcluster_copy_ami_id,
        updated_compute_root_volume_size=updated_compute_root_volume_size,
        queue_update_strategy=queue_update_strategy,
    )
    cluster.update(str(updated_config_file))
    # check chef client log contains expected log
    assert_errors_in_logs(
        remote_command_executor,
        ["/var/log/chef-client.log"],
        [
            f"Queue update strategy is \\({queue_update_strategy}\\)",
            "Adding queue \\(queue2\\) to list of queue to be updated",
        ],
    )

    # after cluster update, check if queue1 node state are in working state
    ec2 = boto3.client("ec2", region)
    scheduler_commands.assert_job_state(queue1_job_id, "RUNNING")
    queue1_nodes = scheduler_commands.get_compute_nodes("queue1")
    assert_compute_node_states(scheduler_commands, queue1_nodes, expected_states=["mixed", "allocated"])
    # check queue1 AMIs are not replaced
    _check_queue_ami(cluster, ec2, pcluster_ami_id, "queue1")

    queue2_nodes = scheduler_commands.get_compute_nodes("queue2", all_nodes=True)
    # assert queue2 node state are in expected status corresponding to the queue strategy
    if queue_update_strategy == "DRAIN":
        scheduler_commands.assert_job_state(queue2_job_id, "RUNNING")
        _check_queue_ami(cluster, ec2, pcluster_ami_id, "queue2")
        assert_compute_node_states(scheduler_commands, queue2_nodes, expected_states=["draining", "draining!"])
        # requeue job in queue2 to launch new instances for nodes
        remote_command_executor.run_remote_command(f"scontrol requeue {queue2_job_id}")
    elif queue_update_strategy == "TERMINATE":
        scheduler_commands.assert_job_state(queue2_job_id, "PENDING")
        assert_compute_node_states(scheduler_commands, queue2_nodes, expected_states=["idle%", "idle!"])

    scheduler_commands.wait_job_running(queue2_job_id)
    # cancel job in queue1
    scheduler_commands.cancel_job(queue1_job_id)
    # check the new launching instances are using new amis
    _check_queue_ami(cluster, ec2, pcluster_ami_id, "queue1")
    _check_queue_ami(cluster, ec2, pcluster_copy_ami_id, "queue2")
    assert_compute_node_states(scheduler_commands, queue1_nodes, "idle")
