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
from collections import defaultdict

import boto3
import pytest
import utils
import yaml
from assertpy import assert_that, fail
from botocore.exceptions import ClientError
from cfn_stacks_factory import CfnStack, CfnVpcStack
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from s3_common_utils import check_s3_read_resource, check_s3_read_write_resource, get_policy_resources
from time_utils import minutes, seconds
from utils import (
    describe_cluster_instances,
    get_instance_profile_from_arn,
    retrieve_cfn_resources,
    wait_for_computefleet_changed,
)

from tests.common.assertions import assert_lines_in_logs, assert_no_msg_in_logs
from tests.common.hit_common import assert_compute_node_states, assert_initial_conditions, wait_for_compute_nodes_states
from tests.common.scaling_common import get_batch_ce, get_batch_ce_max_size, get_batch_ce_min_size
from tests.common.schedulers_common import SlurmCommands
from tests.common.storage.assertions import assert_storage_existence
from tests.common.storage.constants import StorageType
from tests.common.utils import generate_random_string, retrieve_latest_ami
from tests.storage.storage_common import (
    check_fsx,
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
                        },
                        {
                            "instance_type": "c5n.xlarge",
                        },
                        {
                            "instance_type": "c5d.xlarge",
                        },
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
    result = slurm_commands.submit_command("sleep infinity", constraint="static")
    job_id = slurm_commands.assert_job_submitted(result.stdout)

    # Update cluster with new configuration
    additional_policy_arn = (
        f"arn:{utils.get_arn_partition(region)}:iam::aws:policy/service-role/AmazonAppStreamServiceAccess"
    )
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
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))(assert_initial_conditions)(
        slurm_commands, 2, 0, partition="queue1"
    )
    updated_queues_config = {
        "queue1": {
            "compute_resources": {
                "queue1-i1": {
                    "instances": [
                        {
                            "instance_type": "c5.xlarge",
                        },
                        {
                            "instance_type": "c5n.xlarge",
                        },
                        {
                            "instance_type": "c5d.xlarge",
                        },
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
            "compute_type": "ondemand" if "us-iso" in region else "spot",
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
    _check_instance_type(ec2, instances, "c5d.xlarge")

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
    # Check new instance type is the expected one, i.e. the one with lower price.
    _check_instance_type(ec2, new_instances, "c5.xlarge")

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
    # If you are running this test in your personal account, then you must have
    # ParallelCluster AMIs following the official naming convention
    # and set allow_private_ami to True.
    # We allow private AMIs also in US isolated regions to facilitate testing.
    allow_private_ami = True if "us-iso" in region else False
    pcluster_ami_id = retrieve_latest_ami(
        region, os, ami_type="pcluster", request=request, allow_private_ami=allow_private_ami
    )

    logging.info(f"Latest AMI retrieved: {pcluster_ami_id}")

    pcluster_copy_ami_id = ami_copy(
        pcluster_ami_id, "-".join(["test", "update", "computenode", generate_random_string()])
    )

    logging.info(f"Copy of the latest AMI {pcluster_ami_id}: {pcluster_copy_ami_id}")

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
    logging.info(f"Checking that queue {queue_name} is using the expected AMI {ami}")
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

    logging.info(
        f"Checking queue2 node state are in expected status corresponding to the queue strategy {queue_update_strategy}"
    )
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

    logging.info("Checking that new compute nodes are using the new AMI")
    _check_queue_ami(cluster, ec2, pcluster_ami_id, "queue1")
    _check_queue_ami(cluster, ec2, pcluster_copy_ami_id, "queue2")
    assert_compute_node_states(scheduler_commands, queue1_nodes, "idle")


@pytest.fixture
def external_shared_storage_stack(request, test_datadir, region, vpc_stack: CfnVpcStack, cfn_stacks_factory):
    def create_stack(bucket_name):
        template_path = os.path.join(str(test_datadir), "storage-stack.yaml")
        option = "external_shared_storage_stack_name"
        if request.config.getoption(option):
            stack = CfnStack(name=request.config.getoption(option), region=region, template=None)
        else:
            # Choose subnets from different availability zones
            subnet_ids = vpc_stack.get_all_public_subnets() + vpc_stack.get_all_private_subnets()
            subnets = boto3.client("ec2").describe_subnets(SubnetIds=subnet_ids)["Subnets"]
            subnets_by_az = defaultdict(list)
            for subnet in subnets:
                subnets_by_az[subnet["AvailabilityZone"]].append(subnet["SubnetId"])

            utils.render_jinja_template(
                template_path, one_subnet_per_az=[subnets[0] for subnets in subnets_by_az.values()]
            )

            vpc = vpc_stack.cfn_outputs["VpcId"]
            public_subnet_id = vpc_stack.get_public_subnet()
            import_path = "s3://{0}".format(bucket_name)
            export_path = "s3://{0}/export_dir".format(bucket_name)
            params = [
                {"ParameterKey": "vpc", "ParameterValue": vpc},
                {"ParameterKey": "PublicSubnetId", "ParameterValue": public_subnet_id},
                {"ParameterKey": "ImportPathParam", "ParameterValue": import_path},
                {"ParameterKey": "ExportPathParam", "ParameterValue": export_path},
            ]
            with open(template_path, encoding="utf-8") as template_file:
                template = template_file.read()
            stack = CfnStack(
                name=utils.generate_stack_name(
                    "integ-tests-external-shared-storage", request.config.getoption("stackname_suffix")
                ),
                region=region,
                parameters=params,
                template=template,
                capabilities=["CAPABILITY_IAM"],
            )
            cfn_stacks_factory.create_stack(stack)
        return stack

    yield create_stack


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
    vpc_stack,
    key_name,
    s3_bucket_factory,
    test_datadir,
    delete_storage_on_teardown,
    external_shared_storage_stack,
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
        snapshots_factory, request, vpc_stack, region, bucket_name, external_shared_storage_stack
    )

    # Create cluster with initial configuration
    init_config_file = pcluster_config_reader(
        config_file="pcluster.config.yaml", output_file="pcluster.config.init.yaml"
    )
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
    logging.info("Updating the cluster to mount managed storage with DeletionPolicy set to Delete")
    update_cluster_config = pcluster_config_reader(
        config_file="pcluster.config.update_drain.yaml",
        output_file="pcluster.config.update_drain_1.yaml",
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
        new_ebs_deletion_policy="Delete",
        new_raid_mount_dir=new_raid_mount_dir,
        new_raid_deletion_policy="Delete",
        new_lustre_mount_dir=new_lustre_mount_dir,
        new_lustre_deletion_policy="Delete",
        new_efs_mount_dir=new_efs_mount_dir,
        new_efs_deletion_policy="Delete",
    )

    cluster.update(update_cluster_config)

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

    logging.info("Updating the cluster to set DeletionPolicy to Retain for every managed storage")
    update_cluster_config = pcluster_config_reader(
        config_file="pcluster.config.update_drain.yaml",
        output_file="pcluster.config.update_drain_2.yaml",
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
        new_ebs_deletion_policy="Retain",
        new_raid_mount_dir=new_raid_mount_dir,
        new_raid_deletion_policy="Retain",
        new_lustre_mount_dir=new_lustre_mount_dir,
        new_lustre_deletion_policy="Retain",
        new_efs_mount_dir=new_efs_mount_dir,
        new_efs_deletion_policy="Retain",
    )

    cluster.update(update_cluster_config)

    existing_ebs_ids = [existing_ebs_volume_id]
    existing_efs_ids = [existing_efs_id]
    existing_fsx_ids = [existing_fsx_lustre_fs_id, existing_fsx_ontap_volume_id, existing_fsx_open_zfs_volume_id]

    retained_ebs_noraid_volume_ids = [
        id for id in cluster.cfn_outputs["EBSIds"].split(",") if id not in existing_ebs_ids
    ]
    retained_ebs_raid_volume_ids = [
        id for id in cluster.cfn_outputs["RAIDIds"].split(",") if id not in existing_ebs_ids
    ]
    retained_ebs_volume_ids = retained_ebs_noraid_volume_ids + retained_ebs_raid_volume_ids
    retained_efs_filesystem_ids = [id for id in cluster.cfn_outputs["EFSIds"].split(",") if id not in existing_efs_ids]
    retained_fsx_filesystem_ids = [id for id in cluster.cfn_outputs["FSXIds"].split(",") if id not in existing_fsx_ids]

    # update cluster to remove ebs, raid, efs and fsx with compute fleet stop
    logging.info("Updating the cluster to remove all the shared storage (managed storage will be retained)")
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

    # Verify that detached managed storage have been retained and delete them.
    logging.info(
        "Checking that retained managed storage resources have been retained and mark them for deletion on teardown"
    )
    retained_storage = {
        StorageType.STORAGE_EBS: dict(ids=retained_ebs_volume_ids, expected_states=["available"]),
        StorageType.STORAGE_EFS: dict(ids=retained_efs_filesystem_ids, expected_states=["available"]),
        StorageType.STORAGE_FSX: dict(ids=retained_fsx_filesystem_ids, expected_states=["AVAILABLE"]),
    }
    for storage_type in retained_storage:
        for storage_id in retained_storage[storage_type]["ids"]:
            assert_storage_existence(
                region,
                storage_type,
                storage_id,
                should_exist=True,
                expected_states=retained_storage[storage_type]["expected_states"],
            )
            delete_storage_on_teardown(storage_type, storage_id)

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
    snapshots_factory, request, vpc_stack: CfnVpcStack, region, bucket_name, external_shared_storage_stack
):
    """Create existing EBS, EFS, FSX resources for test."""
    # create 1 existing ebs
    ebs_volume_id = snapshots_factory.create_existing_volume(request, vpc_stack.get_public_subnet(), region)

    # create external-shared-storage-stack
    storage_stack = external_shared_storage_stack(bucket_name)

    return (
        ebs_volume_id,
        storage_stack.cfn_outputs["EfsId"],
        storage_stack.cfn_outputs["FsxLustreFsId"],
        storage_stack.cfn_outputs["FsxOntapVolumeId"],
        storage_stack.cfn_outputs["FsxOpenZfsVolumeId"],
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


@pytest.mark.usefixtures("os")
def test_multi_az_create_and_update(
    region, pcluster_config_reader, clusters_factory, odcr_stack, scheduler_commands_factory, test_datadir
):
    """Test creation and then update of a multi-az cluster."""

    # Step 1
    # Create a cluster with two queues
    #  q1 with 2 subnets in different AZ
    #    plus a ReservationGroup with two reservations that ensure hosts are provisioned in both AZs
    #  q2 with 1 subnet in one AZ

    resource_groups_client = boto3.client(service_name="resource-groups", region_name=region)
    odcr_resources = retrieve_cfn_resources(odcr_stack.name, region)
    resource_group_arn = resource_groups_client.get_group(Group=odcr_stack.cfn_resources["multiAzOdcrGroup"])["Group"][
        "GroupArn"
    ]

    init_config_file = pcluster_config_reader(
        config_file="pcluster_create.config.yaml",
        multi_az_capacity_reservation_arn=resource_group_arn,
    )

    cluster = clusters_factory(init_config_file)

    # Retrieves list of cluster instances and checks that
    # at least one instance was launched in each AZ/Reservation
    instances = describe_cluster_instances(cluster.name, region, filter_by_compute_resource_name="compute-resource-1")
    _assert_instance_in_capacity_reservation(instances, odcr_resources["az1Odcr"])
    _assert_instance_in_capacity_reservation(instances, odcr_resources["az2Odcr"])

    # ## First update
    # - add a subnet in Queue2
    # update should succeed without failures or warning messages
    first_update_config = pcluster_config_reader(
        config_file="pcluster_update_1.config.yaml",
        multi_az_capacity_reservation_arn=resource_group_arn,
    )

    response = cluster.update(str(first_update_config))
    assert_that(response["clusterStatus"]).is_equal_to("UPDATE_COMPLETE")

    # Second update
    # - remove a subnet in Queue2
    # update should fail asking to stop the fleet
    second_update_config = pcluster_config_reader(
        config_file="pcluster_update_2.config.yaml",
        multi_az_capacity_reservation_arn=resource_group_arn,
    )

    response = cluster.update(str(second_update_config), raise_on_error=False)
    assert_that(response["message"]).is_equal_to("Update failure")
    assert_that(response["updateValidationErrors"][0]["message"]).contains("All compute nodes must be stopped")

    # Third update
    #  - stops the fleet
    #  - wait until all compute instances are terminated
    # after fully stopping the fleet, the update should succeed

    cluster.stop()
    _wait_until_instances_are_stopped(cluster)

    response = cluster.update(str(second_update_config))
    assert_that(response["computeFleetStatus"]).is_equal_to("STOPPED")
    assert_that(response["clusterStatus"]).is_equal_to("UPDATE_COMPLETE")


@pytest.mark.usefixtures("instance", "os")
def test_resource_changes_in_cluster_with_multiple_queues(
    region, pcluster_config_reader, clusters_factory, scheduler_commands_factory, test_datadir
):
    init_config_file = pcluster_config_reader(
        config_file="pcluster_max_queue.config.yaml",
    )
    cluster = clusters_factory(init_config_file)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # Confirm jobs can run on the static node
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "srun sleep 1",
            "host": "queue-a-st-queue-a-cr-static-1",
            "partition": "queue-a",
        }
    )
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    # Check resources associated with the static node are not deleted/replaced during cluster update
    # Queue is running only the static node
    static_instance_info = describe_cluster_instances(
        cluster.cfn_name, region, filter_by_compute_resource_name="queue-a-cr-static"
    )[0]
    initial_iam_arn = static_instance_info["IamInstanceProfile"]["Arn"]
    expected_instance_profile_name = get_instance_profile_from_arn(initial_iam_arn)
    _assert_instance_profile_exists(expected_instance_profile_name, region)

    # Update cluster to use only the queue with a static node
    single_queue_update_config = pcluster_config_reader(config_file="pcluster_1_queue.config.yaml")
    cluster.stop()
    response = cluster.update(str(single_queue_update_config), force_update="true")
    assert_that(response["clusterStatus"]).is_equal_to("UPDATE_COMPLETE")

    # Confirm the IAM profile was not deleted during the update
    _assert_instance_profile_exists(expected_instance_profile_name, region)

    # Add multiple queues and run update (without compute fleet stop)
    max_queue_update_config = pcluster_config_reader(config_file="pcluster_max_queue.config.yaml")
    cluster.start()
    response = cluster.update(str(max_queue_update_config), force_update="true")
    assert_that(response["clusterStatus"]).is_equal_to("UPDATE_COMPLETE")

    # Confirm the IAM profile was not deleted during the update
    _assert_instance_profile_exists(expected_instance_profile_name, region)

    # Confirm jobs can run on the static node
    job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "srun sleep 1",
            "host": "queue-a-st-queue-a-cr-static-1",
            "partition": "queue-a",
        }
    )
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)


def _assert_instance_profile_exists(expected_instance_profile_name, region):
    iam = boto3.client("iam", region_name=region)
    try:
        iam_profile = iam.get_instance_profile(InstanceProfileName=expected_instance_profile_name)
        assert_that(iam_profile).is_not_empty()
    except iam.exceptions.NoSuchEntityException:
        fail(f"IAM Profile {expected_instance_profile_name} does not exist")


def _assert_instance_in_capacity_reservation(instances, expected_reservation):
    if any(
        instance["CapacityReservationId"] == expected_reservation
        for instance in instances
        if "CapacityReservationId" in instance
    ):
        logging.info("Instances found in reservation: %s", expected_reservation)
    else:
        logging.error("No instances found in reservation: %s", expected_reservation)
        pytest.fail("No instances found in the reservation")


@retry(retry_on_result=lambda result: result is False, wait_fixed=seconds(20), stop_max_delay=seconds(360))
def _wait_until_instances_are_stopped(cluster):
    instances = cluster.describe_cluster_instances()
    n_compute_instances = len(instances) - 1  # Do not count the HeadNode
    if n_compute_instances <= 1:
        logging.info("All compute instances were stopped.")
    else:
        logging.info("Still found %2d compute instances in the cluster. Waiting... ", n_compute_instances)

    return n_compute_instances <= 1
