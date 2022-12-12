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
import os.path
import re
import time

import boto3
import pytest
import utils
import yaml
from assertpy import assert_that
from botocore.exceptions import ClientError
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from s3_common_utils import check_s3_read_resource, check_s3_read_write_resource, get_policy_resources
from time_utils import minutes, seconds
from troposphere.fsx import LustreConfiguration
from utils import wait_for_computefleet_changed

from tests.common.assertions import assert_lines_in_logs, assert_no_msg_in_logs
from tests.common.hit_common import assert_compute_node_states, assert_initial_conditions, wait_for_compute_nodes_states
from tests.common.scaling_common import get_batch_ce, get_batch_ce_max_size, get_batch_ce_min_size
from tests.common.schedulers_common import SlurmCommands
from tests.common.utils import generate_random_string, retrieve_latest_ami
from tests.storage.storage_common import (
    check_fsx,
    create_fsx_ontap,
    create_fsx_open_zfs,
    test_ebs_correctly_mounted,
    test_efs_correctly_mounted,
    test_raid_correctly_configured,
    test_raid_correctly_mounted,
    verify_directory_correctly_shared,
)


@pytest.mark.usefixtures("os", "instance")
def test_update_slurm(region, pcluster_config_reader, s3_bucket_factory, clusters_factory, test_datadir):
    # Create S3 bucket for pre/post install scripts
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    for script in [
        "preinstall.sh",
        "postinstall.sh",
        "updated_preinstall.sh",
        "updated_postinstall.sh",
        "postupdate.sh",
        "updated_postupdate.sh",
        "failed_postupdate.sh",
    ]:
        bucket.upload_file(str(test_datadir / script), f"scripts/{script}")

    # Create cluster with initial configuration
    init_config_file = pcluster_config_reader(resource_bucket=bucket_name)
    cluster = clusters_factory(init_config_file)

    # Check update hook is NOT executed at cluster creation time
    assert_that(os.path.exists("/tmp/postupdate_out.txt")).is_false()

    # Update cluster with the same configuration, command should not result any error even if not using force update
    cluster.update(str(init_config_file), force_update="true")

    # Command executors
    command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = SlurmCommands(command_executor)

    # Check update hook is executed at cluster update time
    _check_head_node_script(command_executor, "postupdate", "UPDATE-ARG1")

    # Create shared dir for script results
    command_executor.run_remote_command("mkdir -p /shared/script_results")

    initial_queues_config = {
        "queue1": {
            "compute_resources": {
                "queue1-i1": {
                    "instances": [
                        {
                            "instance_type": "c5.xlarge",
                        }
                    ],
                    "expected_running_instances": 1,
                    "expected_power_saved_instances": 1,
                    "enable_efa": False,
                    "disable_hyperthreading": False,
                },
                "queue1-i2": {
                    "instances": [
                        {
                            "instance_type": "t2.micro",
                        }
                    ],
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
                    "instances": [
                        {
                            "instance_type": "c5n.18xlarge",
                        }
                    ],
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
        output_file="pcluster.config.update.successful.yaml",
        resource_bucket=bucket_name,
        additional_policy_arn=additional_policy_arn,
        postupdate_script="updated_postupdate.sh",
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
                    "instances": [
                        {
                            "instance_type": "c5.xlarge",
                        }
                    ],
                    "expected_running_instances": 2,
                    "expected_power_saved_instances": 2,
                    "disable_hyperthreading": False,
                    "enable_efa": False,
                },
                "queue1-i2": {
                    "instances": [
                        {
                            "instance_type": "c5.2xlarge",
                        }
                    ],
                    "expected_running_instances": 0,
                    "expected_power_saved_instances": 10,
                    "disable_hyperthreading": False,
                    "enable_efa": False,
                },
                "queue1-i3": {
                    "instances": [
                        {
                            "instance_type": "t2.micro",
                        }
                    ],
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
                    "instances": [
                        {
                            "instance_type": "c5n.18xlarge",
                        }
                    ],
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
                    "instances": [
                        {
                            "instance_type": "c5n.18xlarge",
                        }
                    ],
                    "expected_running_instances": 0,
                    "expected_power_saved_instances": 10,
                    "disable_hyperthreading": True,
                    "enable_efa": True,
                },
                "queue3-i2": {
                    "instances": [
                        {
                            "instance_type": "t2.xlarge",
                        }
                    ],
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

    logging.info(f"New compute node: {new_compute_node}")

    assert_that(len(new_compute_node), description="There should be only one new compute node").is_equal_to(1)
    _check_script(command_executor, slurm_commands, new_compute_node[0], "updated_preinstall", "ABC")
    _check_script(command_executor, slurm_commands, new_compute_node[0], "updated_postinstall", "DEF")

    # Check the new update hook with new args is executed at cluster update time
    _check_head_node_script(command_executor, "updated_postupdate", "UPDATE-ARG2")

    # Same as previous update, but with a post update script that fails
    failed_update_config_file = pcluster_config_reader(
        config_file="pcluster.config.update.yaml",
        output_file="pcluster.config.update.failed.yaml",
        resource_bucket=bucket_name,
        additional_policy_arn=additional_policy_arn,
        postupdate_script="failed_postupdate.sh",
    )
    cluster.update(str(failed_update_config_file), raise_on_error=False, log_error=False)

    _check_rollback_with_expected_error_message(region, cluster)

    # check new extra json
    _check_extra_json(command_executor, slurm_commands, new_compute_node[0], "test_value")


def _check_rollback_with_expected_error_message(region, cluster):
    """Verify that the update has been rolled back with the expected error message."""
    logging.info("Checking rollback with expected error message")
    client = boto3.client("cloudformation", region_name=region)

    stack_status = client.describe_stacks(StackName=cluster.name)["Stacks"][0]["StackStatus"]
    error_message = _get_update_failure_reason(client, cluster)

    assert_that(stack_status).is_equal_to("UPDATE_ROLLBACK_COMPLETE")
    assert_that(error_message).starts_with("WaitCondition received failed message: 'Update failed'")


def _get_update_failure_reason(client, cluster):
    """
    Return the error message of the event triggering the rolled back update.

    In case of update rollback, we expect a single resource to be in `CREATE_FAILED` state, namely
    the head node wait condition. This resource has the status reason with the expected error message.
    """
    paginator = client.get_paginator("describe_stack_events")
    for events in paginator.paginate(StackName=cluster.name):
        for event in events["StackEvents"]:
            if event["ResourceStatus"] == "CREATE_FAILED":
                return event["ResourceStatusReason"]
    return ""


def _check_head_node_script(command_executor, script_name, script_arg):
    """Verify that update hook script is executed with the right arguments."""
    logging.info(f"Checking {script_name} script")
    output_file_path = f"/tmp/{script_name}_out.txt"

    result = command_executor.run_remote_command(f"cat {output_file_path}")
    assert_that(result.stdout).matches(rf"{script_name}-{script_arg}")


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
            assert_that("InstanceType").is_not_in(launch_template_data)  # Using CreateFleet override
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
def test_update_instance_list(
    region, os, pcluster_config_reader, ami_copy, clusters_factory, test_datadir, request, scheduler_commands_factory
):
    ec2 = boto3.client("ec2", region)
    init_config_file = pcluster_config_reader()
    cluster = clusters_factory(init_config_file)
    # Command executor
    remote_command_executor = RemoteCommandExecutor(cluster)

    # Assert min count
    instances = cluster.get_cluster_instance_ids(node_type="Compute")
    logging.info(instances)
    assert_that(len(instances)).is_equal_to(1)

    # Submit exclusive job on static node
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 1000", "nodes": 1, "other_options": "--exclusive"}
    )
    # Check instance type is the expected for min count
    _check_instance_type(ec2, instances, "c5.xlarge")

    # Update cluster with new configuration, adding new instance type with lower price
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.update.yaml")
    cluster.update(str(updated_config_file))

    # Submit another exclusive job on lower price instance
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 1000", "nodes": 1, "other_options": "--exclusive"}
    )
    scheduler_commands.wait_job_running(job_id)

    # Get new instance
    new_instances = cluster.get_cluster_instance_ids(node_type="Compute")
    logging.info(new_instances)
    new_instances.remove(instances[0])
    # Check new instance type is the expected one
    _check_instance_type(ec2, new_instances, "c5a.xlarge")

    # Update cluster removing instance type from the list
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.update.remove.yaml")
    response = cluster.update(str(updated_config_file), raise_on_error=False)
    assert_that(response["message"]).is_equal_to("Update failure")
    assert_that(response.get("updateValidationErrors")[0].get("message")).contains("All compute nodes must be stopped")


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

    _wait_for_image_available(ec2, pcluster_copy_ami_id)

    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update.yaml", global_custom_ami=pcluster_ami_id, custom_ami=pcluster_copy_ami_id
    )
    # stop compute fleet before updating queue image
    cluster.stop()
    cluster.update(str(updated_config_file), force_update="true")
    instances = cluster.get_cluster_instance_ids(node_type="Compute")
    logging.info(instances)
    _check_instance_ami_id(ec2, instances, pcluster_copy_ami_id)


def _wait_for_image_available(ec2_client, image_id):
    logging.info(f"Waiting for {image_id} to be available")
    waiter = ec2_client.get_waiter("image_available")
    waiter.wait(Filters=[{"Name": "image-id", "Values": [image_id]}], WaiterConfig={"Delay": 60, "MaxAttempts": 10})


def _check_instance_ami_id(ec2, instances, expected_queue_ami):
    for instance_id in instances:
        instance_info = ec2.describe_instances(Filters=[], InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]
        assert_that(instance_info["ImageId"]).is_equal_to(expected_queue_ami)


def _check_instance_type(ec2, instances, expected_instance_type):
    for instance_id in instances:
        instance_info = ec2.describe_instances(Filters=[], InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]
        assert_that(instance_info["InstanceType"]).is_equal_to(expected_instance_type)


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
    ec2 = boto3.client("ec2", region_name=region)
    _wait_for_image_available(ec2, pcluster_copy_ami_id)
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
    assert_lines_in_logs(
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
    assert_lines_in_logs(
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


@pytest.mark.usefixtures("instance")
def test_dynamic_file_systems_update(
    region,
    os,
    pcluster_config_reader,
    ami_copy,
    clusters_factory,
    scheduler_commands_factory,
    request,
    snapshots_factory,
    efs_stack_factory,
    efs_mount_target_stack_factory,
    vpc_stack,
    key_name,
    s3_bucket_factory,
    test_datadir,
    fsx_factory,
    svm_factory,
    open_zfs_volume_factory,
):
    """Test update shared storages."""
    existing_ebs_mount_dir = "/existing_ebs_mount_dir"
    existing_efs_mount_dir = "/existing_efs_mount_dir"
    fsx_lustre_mount_dir = "/existing_fsx_lustre_mount_dir"
    fsx_ontap_mount_dir = "/existing_fsx_ontap_mount_dir"
    fsx_open_zfs_mount_dir = "/existing_fsx_open_zfs_mount_dir"
    new_ebs_mount_dir = "/new_ebs_mount_dir"
    new_raid_mount_dir = "/new_raid_dir"
    new_efs_mount_dir = "/new_efs_mount_dir"
    new_lustre_mount_dir = "/new_lustre_mount_dir"
    ebs_mount_dirs = [new_ebs_mount_dir, existing_ebs_mount_dir]
    efs_mount_dirs = [existing_efs_mount_dir, new_efs_mount_dir]
    fsx_mount_dirs = [new_lustre_mount_dir, fsx_lustre_mount_dir, fsx_open_zfs_mount_dir, fsx_ontap_mount_dir]
    all_mount_dirs = ebs_mount_dirs + [new_raid_mount_dir] + efs_mount_dirs + fsx_mount_dirs

    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "s3_test_file"), "s3_test_file")
    (
        existing_ebs_volume_id,
        existing_efs_id,
        existing_fsx_lustre_fs_id,
        existing_fsx_ontap_volume_id,
        existing_fsx_open_zfs_volume_id,
    ) = _create_shared_storages_resources(
        snapshots_factory,
        request,
        vpc_stack,
        region,
        efs_stack_factory,
        efs_mount_target_stack_factory,
        fsx_factory,
        svm_factory,
        open_zfs_volume_factory,
        bucket_name,
    )

    # Create cluster with initial configuration
    init_config_file = pcluster_config_reader()
    cluster = clusters_factory(init_config_file)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    cluster_nodes = scheduler_commands.get_compute_nodes()
    queue1_nodes = [node for node in cluster_nodes if "queue1" in node]

    # submit a job to queue1
    queue1_job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 3000",  # sleep 3000 to keep the job running
            "nodes": 1,
            "partition": "queue1",
        },
    )

    # Wait for the job to run
    scheduler_commands.wait_job_running(queue1_job_id)

    # update cluster to add ebs, efs, fsx with drain strategy
    update_cluster_config = pcluster_config_reader(
        config_file="pcluster.config.update_drain.yaml",
        volume_id=existing_ebs_volume_id,
        existing_ebs_mount_dir=existing_ebs_mount_dir,
        existing_efs_mount_dir=existing_efs_mount_dir,
        fsx_lustre_mount_dir=fsx_lustre_mount_dir,
        fsx_ontap_mount_dir=fsx_ontap_mount_dir,
        fsx_open_zfs_mount_dir=fsx_open_zfs_mount_dir,
        existing_efs_id=existing_efs_id,
        existing_fsx_lustre_fs_id=existing_fsx_lustre_fs_id,
        fsx_ontap_volume_id=existing_fsx_ontap_volume_id,
        fsx_open_zfs_volume_id=existing_fsx_open_zfs_volume_id,
        bucket_name=bucket_name,
        new_ebs_mount_dir=new_ebs_mount_dir,
        new_raid_mount_dir=new_raid_mount_dir,
        new_lustre_mount_dir=new_lustre_mount_dir,
        new_efs_mount_dir=new_efs_mount_dir,
    )

    cluster.update(str(update_cluster_config))

    # check chef client log contains expected log
    assert_lines_in_logs(
        remote_command_executor,
        ["/var/log/chef-client.log"],
        [
            "All queues will be updated in order to update shared storages",
        ],
    )

    scheduler_commands.assert_job_state(queue1_job_id, "RUNNING")
    # assert all nodes are drain
    assert_compute_node_states(
        scheduler_commands, cluster_nodes, expected_states=["draining", "draining!", "drained*", "drained"]
    )

    # check file systems are visible on the head node just after the update
    _test_shared_storages_mount_on_headnode(
        remote_command_executor,
        cluster,
        region,
        bucket_name,
        scheduler_commands_factory,
        ebs_mount_dirs,
        new_raid_mount_dir,
        efs_mount_dirs,
        fsx_mount_dirs,
    )

    # check newly mounted file systems are not visible on compute nodes that are running jobs
    for node_name in queue1_nodes:
        _test_directory_not_mounted(remote_command_executor, all_mount_dirs, node_type="compute", node_name=node_name)
    for mount_dir in all_mount_dirs:
        verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands, partitions=["queue2"])
    scheduler_commands.cancel_job(queue1_job_id)
    for mount_dir in all_mount_dirs:
        verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands, partitions=["queue1"])

    # update cluster to remove ebs, raid, efs and fsx with compute fleet stop
    cluster.stop()
    wait_for_computefleet_changed(cluster, "STOPPED")
    cluster.update(str(init_config_file))
    cluster.start()
    wait_for_computefleet_changed(cluster, "RUNNING")
    # submit a job to queue2
    queue2_job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 3000",
            "nodes": 1,
            "partition": "queue1",
        },
    )
    scheduler_commands.wait_job_running(queue2_job_id)
    cluster_nodes = scheduler_commands.get_compute_nodes()
    _test_shared_storages_unmount(
        remote_command_executor,
        ebs_mount_dirs,
        new_raid_mount_dir,
        efs_mount_dirs,
        fsx_mount_dirs,
        all_mount_dirs,
        cluster_nodes,
    )

    _test_shared_storage_rollback(
        cluster,
        existing_ebs_volume_id,
        existing_ebs_mount_dir,
        bucket_name,
        new_ebs_mount_dir,
        new_lustre_mount_dir,
        new_efs_mount_dir,
        remote_command_executor,
        pcluster_config_reader,
        scheduler_commands,
        region,
    )


def _create_shared_storages_resources(
    snapshots_factory,
    request,
    vpc_stack,
    region,
    efs_stack_factory,
    efs_mount_target_stack_factory,
    fsx_factory,
    svm_factory,
    open_zfs_volume_factory,
    bucket_name,
):
    """Create existing EBS, EFS, FSX resources for test."""
    # create 1 existing ebs
    ebs_volume_id = snapshots_factory.create_existing_volume(request, vpc_stack.cfn_outputs["PublicSubnetId"], region)

    # create 1 efs
    existing_efs_ids = efs_stack_factory(1)
    efs_mount_target_stack_factory(existing_efs_ids)
    existing_efs_id = existing_efs_ids[0]

    # create 1 fsx lustre
    import_path = "s3://{0}".format(bucket_name)
    export_path = "s3://{0}/export_dir".format(bucket_name)
    existing_fsx_lustre_fs_id = fsx_factory(
        ports=[988],
        ip_protocols=["tcp"],
        num=1,
        file_system_type="LUSTRE",
        StorageCapacity=1200,
        LustreConfiguration=LustreConfiguration(
            title="lustreConfiguration",
            ImportPath=import_path,
            ExportPath=export_path,
            DeploymentType="PERSISTENT_1",
            PerUnitStorageThroughput=200,
        ),
    )[0]

    # create 1 fsx ontap
    fsx_ontap_fs_id = create_fsx_ontap(fsx_factory, num=1)[0]
    fsx_ontap_volume_id = svm_factory(fsx_ontap_fs_id, num_volumes=1)[0]

    # create 1 open zfs
    fsx_open_zfs_root_volume_id = create_fsx_open_zfs(fsx_factory, num=1)[0]
    fsx_open_zfs_volume_id = open_zfs_volume_factory(fsx_open_zfs_root_volume_id, num_volumes=1)[0]

    return (
        ebs_volume_id,
        existing_efs_id,
        existing_fsx_lustre_fs_id,
        fsx_ontap_volume_id,
        fsx_open_zfs_volume_id,
    )


def _test_directory_not_mounted(remote_command_executor, mount_dirs, node_type="head", node_name=None):
    if node_type == "compute":
        result = remote_command_executor.run_remote_command(f"ssh -q {node_name} df -h")
    else:
        result = remote_command_executor.run_remote_command("df -h")
    for mount_dir in mount_dirs:
        assert_that(result.stdout).does_not_contain(mount_dir)


def _test_ebs_not_mounted(remote_command_executor, mount_dirs):
    _test_directory_not_mounted(remote_command_executor, mount_dirs)
    exports_result = remote_command_executor.run_remote_command("cat /etc/exports").stdout
    fstab_result = remote_command_executor.run_remote_command("cat /etc/fstab").stdout
    for mount_dir in mount_dirs:
        assert_that(exports_result).does_not_contain(mount_dir)
        assert_that(fstab_result).does_not_contain(mount_dir)


def _test_raid_not_mount(remote_command_executor, mount_dirs):
    _test_ebs_not_mounted(remote_command_executor, mount_dirs)
    exports_result = remote_command_executor.run_remote_command("cat /etc/mdadm.conf").stdout
    assert_that(exports_result).is_equal_to("")


def _test_shared_storages_unmount(
    remote_command_executor,
    ebs_mount_dirs,
    new_raid_mount_dir,
    efs_mount_dirs,
    fsx_mount_dirs,
    all_mount_dirs,
    node_names,
):
    """Check storages are not on headnode."""
    _test_ebs_not_mounted(remote_command_executor, ebs_mount_dirs)
    _test_raid_not_mount(remote_command_executor, [new_raid_mount_dir])
    _test_directory_not_mounted(remote_command_executor, efs_mount_dirs + fsx_mount_dirs)

    # check storages are not on compute nodes
    for node_name in node_names:
        _test_directory_not_mounted(remote_command_executor, all_mount_dirs, node_type="compute", node_name=node_name)


def _test_shared_storages_mount_on_headnode(
    remote_command_executor,
    cluster,
    region,
    bucket_name,
    scheduler_commands_factory,
    ebs_mount_dirs,
    new_raid_mount_dir,
    efs_mount_dirs,
    fsx_mount_dirs,
):
    """Check storages are mounted on headnode."""
    # ebs
    for ebs_dir in ebs_mount_dirs:
        volume_size = "9.[7,8]" if "existing" in ebs_dir else "35"
        test_ebs_correctly_mounted(remote_command_executor, ebs_dir, volume_size=volume_size)
    # check raid
    test_raid_correctly_configured(remote_command_executor, raid_type="0", volume_size=75, raid_devices=5)
    test_raid_correctly_mounted(remote_command_executor, new_raid_mount_dir, volume_size=74)
    # check efs
    for efs in efs_mount_dirs:
        test_efs_correctly_mounted(remote_command_executor, efs)
        test_efs_correctly_mounted(remote_command_executor, efs)
    # check fsx
    check_fsx(
        cluster,
        region,
        scheduler_commands_factory,
        fsx_mount_dirs,
        bucket_name,
        headnode_only=True,
    )


def _test_shared_storage_rollback(
    cluster,
    existing_ebs_volume_id,
    existing_ebs_mount_dir,
    bucket_name,
    new_ebs_mount_dir,
    new_lustre_mount_dir,
    new_efs_mount_dir,
    remote_command_executor,
    pcluster_config_reader,
    scheduler_commands,
    region,
):
    # update cluster with adding non-existing ebs and skip validator
    problematic_volume_id = "vol-00000000000000000"
    problematic_ebs_mount_dir = "/problematic_ebs_mount_dir"
    problematic_cluster_config = pcluster_config_reader(
        config_file="pcluster.config.update_rollback.yaml",
        volume_id=existing_ebs_volume_id,
        problematic_volume_id=problematic_volume_id,
        problematic_ebs_mount_dir=problematic_ebs_mount_dir,
        existing_ebs_mount_dir=existing_ebs_mount_dir,
        bucket_name=bucket_name,
        new_ebs_mount_dir=new_ebs_mount_dir,
        new_lustre_mount_dir=new_lustre_mount_dir,
        new_efs_mount_dir=new_efs_mount_dir,
    )
    # remove logs from chef-client log in order to test cluster rollback behavior
    remote_command_executor.run_remote_command("sudo truncate -s 0 /var/log/chef-client.log")
    response = cluster.update(
        str(problematic_cluster_config),
        force_update="true",
        raise_on_error=False,
        suppress_validators="ALL",
    )
    assert_that(response["clusterStatus"]).is_equal_to("UPDATE_FAILED")
    # Test rollback update recipe run finished
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))(assert_lines_in_logs)(
        remote_command_executor,
        ["/var/log/chef-client.log"],
        ["Cinc Client finished"],
    )

    # Check shared storages are not on headnode
    ebs_mount_dirs = [existing_ebs_mount_dir, new_ebs_mount_dir, problematic_ebs_mount_dir]
    fs_mount_dirs = [new_lustre_mount_dir, new_efs_mount_dir]
    _test_ebs_not_mounted(remote_command_executor, ebs_mount_dirs)
    _test_directory_not_mounted(remote_command_executor, fs_mount_dirs)

    # check storages are not on compute nodes
    cluster_nodes = scheduler_commands.get_compute_nodes()
    for node_name in cluster_nodes:
        _test_directory_not_mounted(
            remote_command_executor, ebs_mount_dirs + fs_mount_dirs, node_type="compute", node_name=node_name
        )
    # retrieve shared storages id
    failed_share_storages_data = remote_command_executor.run_remote_command(
        "sudo cat /etc/parallelcluster/previous_shared_storages_data.yaml"
    ).stdout
    assert_that(failed_share_storages_data).is_not_empty()
    failed_share_storages = yaml.safe_load(failed_share_storages_data)
    managed_ebs = [
        volume.get("volume_id")
        for volume in failed_share_storages.get("ebs")
        if volume.get("mount_dir") == new_ebs_mount_dir
    ]
    managed_efs = [
        fs.get("efs_fs_id") for fs in failed_share_storages.get("efs") if fs.get("mount_dir") == new_efs_mount_dir
    ]
    managed_fsx = [
        fs.get("fsx_fs_id") for fs in failed_share_storages.get("fsx") if fs.get("mount_dir") == new_lustre_mount_dir
    ]

    # assert the managed EBS is clean up
    logging.info("Checking managed EBS is deleted after stack rollback")
    with pytest.raises(ClientError, match="InvalidVolume.NotFound"):
        boto3.client("ec2", region).describe_volumes(VolumeIds=managed_ebs).get("Volumes")
    # assert the managed EFS is clean up
    logging.info("Checking managed EBS is deleted after stack rollback")
    with pytest.raises(ClientError, match="FileSystemNotFound"):
        boto3.client("efs", region).describe_file_systems(FileSystemId=managed_efs[0])
    # assert the managed FSX is clean up
    logging.info("Checking managed FSX is deleted after stack rollback")
    with pytest.raises(ClientError, match="FileSystemNotFound"):
        boto3.client("fsx", region).describe_file_systems(FileSystemIds=managed_fsx)
