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
import os
import os.path as os_path
import re
import time
from collections import defaultdict
from datetime import datetime

import boto3
import pytest
import yaml
from assertpy import assert_that
from botocore.exceptions import ClientError
from cfn_stacks_factory import CfnStack, CfnVpcStack
from constants import REPOSITORY_ROOT
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from s3_common_utils import check_s3_read_resource, check_s3_read_write_resource, get_policy_resources
from time_utils import minutes, seconds
from utils import (
    describe_cluster_instances,
    generate_stack_name,
    get_arn_partition,
    get_root_volume_id,
    is_filecache_supported,
    is_fsx_lustre_supported,
    is_fsx_ontap_supported,
    is_fsx_openzfs_supported,
    random_alphanumeric,
    retrieve_cfn_resources,
    wait_for_computefleet_changed,
)

from tests.common.assertions import assert_instance_config_version_on_ddb, assert_lines_in_logs, assert_no_msg_in_logs
from tests.common.hit_common import (
    assert_compute_node_states,
    assert_initial_conditions,
    get_partition_nodes,
    wait_for_compute_nodes_states,
)
from tests.common.login_nodes_utils import terminate_login_nodes
from tests.common.scaling_common import get_batch_ce, get_batch_ce_max_size, get_batch_ce_min_size
from tests.common.schedulers_common import SlurmCommands
from tests.common.storage.assertions import assert_storage_existence
from tests.common.storage.constants import StorageType
from tests.common.utils import generate_random_string, get_deployed_config_version, retrieve_latest_ami
from tests.storage.storage_common import (
    assert_file_exists,
    check_fsx,
    test_ebs_correctly_mounted,
    test_efs_correctly_mounted,
    test_raid_correctly_configured,
    test_raid_correctly_mounted,
    verify_directory_correctly_shared,
    write_file,
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

    spot_instance_types = ["t3.small", "t3.medium"]
    try:
        boto3.client("ec2").describe_instance_types(InstanceTypes=["t3a.small"])
        spot_instance_types.extend(["t3a.small", "t3a.medium"])
    except Exception:
        pass

    # Create cluster with initial configuration
    init_config_file = pcluster_config_reader(resource_bucket=bucket_name, spot_instance_types=spot_instance_types)
    cluster = clusters_factory(init_config_file)

    # Verify that compute nodes stored the deployed config version on DDB
    assert_instance_config_version_on_ddb(cluster, get_deployed_config_version(cluster))

    # Check update hook is NOT executed at cluster creation time
    assert_that(os_path.exists("/tmp/postupdate_out.txt")).is_false()

    # Update cluster with the same configuration, command should not result any error even if not using force update
    cluster.update(str(init_config_file), force_update="true")

    # Verify that compute and login nodes stored the deployed config version on DDB
    assert_instance_config_version_on_ddb(cluster, get_deployed_config_version(cluster))

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
                            "instance_type": "c5.large",
                        },
                        {
                            "instance_type": "c5n.large",
                        },
                        {
                            "instance_type": "c5d.large",
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
                            "instance_type": instance_type,
                        }
                        for instance_type in spot_instance_types
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
    additional_policy_arn = f"arn:{get_arn_partition(region)}:iam::aws:policy/AWSCloudFormationReadOnlyAccess"
    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update.yaml",
        output_file="pcluster.config.update.successful.yaml",
        resource_bucket=bucket_name,
        additional_policy_arn=additional_policy_arn,
        postupdate_script="updated_postupdate.sh",
        spot_instance_types=spot_instance_types,
    )
    cluster.update(str(updated_config_file), force_update="true")

    # Verify that compute and login nodes stored the deployed config version on DDB
    last_cluster_config_version = get_deployed_config_version(cluster)
    # This check must be retried because the last update added a new static node
    # and the update workflow does not wait for new static nodes to complete their bootstrap, by design.
    # On the other hand, the update workflow waits for existing nodes to complete their update recipes.
    # As a consequence, the stack may reach the UPDATE_COMPLETE state
    # without waiting for new static nodes to complete their bootstrap recipes.
    # We wait at most 6 minutes because we know that compute nodes may take 4/5 minutes to bootstrap.
    retry(wait_fixed=seconds(10), stop_max_delay=minutes(6))(assert_instance_config_version_on_ddb)(
        cluster, last_cluster_config_version
    )

    assert_instance_config_version_on_ddb(cluster, last_cluster_config_version)

    # Here is the expected list of nodes.
    # the cluster:
    # queue1-st-c5large-1
    # queue1-st-c5large-2
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))(assert_initial_conditions)(
        slurm_commands, 2, 0, partition="queue1"
    )
    updated_queues_config = {
        "queue1": {
            "compute_resources": {
                "queue1-i1": {
                    "instances": [
                        {
                            "instance_type": "c5.large",
                        },
                        {
                            "instance_type": "c5n.large",
                        },
                        {
                            "instance_type": "c5d.large",
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
                            "instance_type": instance_type,
                        }
                        for instance_type in spot_instance_types
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
                            "instance_type": "t3.xlarge",
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
    # Add a new dynamic node to queue1-i3
    new_compute_node = _add_compute_nodes(slurm_commands, "queue1", "queue1-i3&dynamic")

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
        spot_instance_types=spot_instance_types,
    )
    cluster.update(str(failed_update_config_file), raise_on_error=False, log_error=False)

    _check_rollback_with_expected_error_message(region, cluster)

    # check new extra json
    _check_extra_json(command_executor, slurm_commands, new_compute_node[0], "test_value")

    # This check must be retried when executed to validate a rollback, because the rollback is a non-blocking operation.
    # In particular, the stack reaches the UPDATE_ROLLBACK_COMPLETE state without waiting for the head node to
    # signal the success to its WaitCondition.
    # As a consequence, there may be some cluster nodes still executing their update recipes.
    retry(wait_fixed=seconds(10), stop_max_delay=minutes(3))(assert_instance_config_version_on_ddb)(
        cluster, last_cluster_config_version
    )


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
    region,
    os,
    pcluster_config_reader,
    s3_bucket_factory,
    ami_copy,
    clusters_factory,
    test_datadir,
    request,
    scheduler_commands_factory,
):
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "failing_post_install.sh"), "failing_post_install.sh")

    ec2 = boto3.client("ec2", region)
    init_config_file = pcluster_config_reader(bucket_name=bucket_name)
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
    _check_instance_type(ec2, instances, "c5d.large")

    # Update cluster with new configuration, adding new instance type with lower price
    updated_config_file = pcluster_config_reader(bucket_name=bucket_name, config_file="pcluster.config.update.yaml")
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
    _check_instance_type(ec2, new_instances, "c5.large")

    # Update cluster removing instance type from the list
    updated_config_file = pcluster_config_reader(
        bucket_name=bucket_name, config_file="pcluster.config.update.remove.yaml"
    )
    response = cluster.update(str(updated_config_file), raise_on_error=False)
    assert_that(response["message"]).is_equal_to("Update failure")
    assert_that(response.get("updateValidationErrors")[0].get("message")).contains("All compute nodes must be stopped")

    # Update with change of instance and compute fleet stopped
    cluster.stop()
    wait_for_computefleet_changed(cluster, "STOPPED")

    updated_config_file = pcluster_config_reader(
        bucket_name=bucket_name, config_file="pcluster.config.update.remove.yaml"
    )
    cluster.update(str(updated_config_file), raise_on_error=False, log_error=False)

    _check_rollback_with_expected_error_message(region, cluster)

    logging.info("Checking for no key error")
    assert_no_msg_in_logs(remote_command_executor, ["/var/log/chef-client.log"], ["KeyError:"])


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
    initial_compute_root_volume_size = 40
    updated_compute_root_volume_size = 45
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

    _test_update_resize(
        scheduler_commands,
        pcluster_config_reader,
        pcluster_ami_id,
        pcluster_copy_ami_id,
        updated_compute_root_volume_size,
        cluster,
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
        config_file="pcluster.config.update_without_running_job.yaml",
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
            r"Queue update strategy is ({0})".format(queue_update_strategy),
            r"Adding queue \(queue1\) to list of queue to be updated",
        ],
    )
    queue1_nodes = scheduler_commands.get_compute_nodes("queue1")
    wait_for_compute_nodes_states(
        scheduler_commands, queue1_nodes, expected_states=["idle", "idle~"], stop_max_delay_secs=600
    )
    # test volume size are expected after update
    instances = cluster.get_cluster_instance_ids(node_type="Compute", queue_name="queue1")
    for instance in instances:
        root_volume_id = get_root_volume_id(instance, region, os)
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
            "command": "srun sleep 3000",
            "nodes": 2,
            "partition": "queue1",
        }
    )

    queue2_job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "srun sleep 3000", "nodes": 2, "partition": "queue2"}
    )
    # Wait for the job to run
    scheduler_commands.wait_job_running(queue1_job_id)
    scheduler_commands.wait_job_running(queue2_job_id)

    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update_with_running_job.yaml",
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
            r"Queue update strategy is ({0})".format(queue_update_strategy),
            r"Adding queue \(queue2\) to list of queue to be updated",
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
        time.sleep(60)
        scheduler_commands.assert_job_state(queue2_job_id, "PENDING")

    # Be sure the queue2 job is running even after the forced termination: we need the nodes active so that we
    # can check the AMI id on the instances
    scheduler_commands.wait_job_running(queue2_job_id)

    # cancel job in queue1
    scheduler_commands.cancel_job(queue1_job_id)

    logging.info("Checking that new compute nodes are using the new AMI")
    _check_queue_ami(cluster, ec2, pcluster_ami_id, "queue1")
    _check_queue_ami(cluster, ec2, pcluster_copy_ami_id, "queue2")
    assert_compute_node_states(scheduler_commands, queue1_nodes, "idle")


def _test_update_resize(
    scheduler_commands,
    pcluster_config_reader,
    pcluster_ami_id,
    pcluster_copy_ami_id,
    updated_compute_root_volume_size,
    cluster,
    queue_update_strategy,
):
    # Submit job in static node, eventually removed with TERMINATE strategy
    queue1_job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "srun sleep 3000",
            "nodes": 1,
            "partition": "queue1",
        }
    )
    # Wait for the job to run
    scheduler_commands.wait_job_running(queue1_job_id)

    # prepare new cluster config with static nodes removed from all queues
    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update_resize.yaml",
        global_custom_ami=pcluster_ami_id,
        custom_ami=pcluster_copy_ami_id,
        updated_compute_root_volume_size=updated_compute_root_volume_size,
        queue_update_strategy=queue_update_strategy,
    )

    if queue_update_strategy == "DRAIN":
        """Test update resize doesn't support DRAIN strategy, update will fail."""
        response = cluster.update(str(updated_config_file), raise_on_error=False)
        assert_that(response["message"]).is_equal_to("Update failure")
        assert_that(response.get("updateValidationErrors")[0].get("message")).contains(
            "All compute nodes must be stopped or QueueUpdateStrategy must be set"
        )
        # assert that job running on static nodes not removed stays running
        scheduler_commands.assert_job_state(queue1_job_id, "RUNNING")
    elif queue_update_strategy == "TERMINATE":
        """Test update resize with TERMINATE strategy, static nodes removed."""
        cluster.update(str(updated_config_file))
        # assert that static nodes are removed
        nodes_in_scheduler = scheduler_commands.get_compute_nodes(all_nodes=True)
        static_nodes, dynamic_nodes = get_partition_nodes(nodes_in_scheduler)
        assert_that(len(static_nodes)).is_equal_to(0)
        assert_that(len(dynamic_nodes)).is_equal_to(4)
        # assert that job running on static nodes removed with the update is re-queued
        scheduler_commands.wait_job_running(queue1_job_id)


@pytest.fixture
def external_shared_storage_stack(request, test_datadir, region, vpc_stack: CfnVpcStack, cfn_stacks_factory):
    def create_stack(vpc_stack, bucket_name, file_cache_path):
        template_path = os.path.join(REPOSITORY_ROOT, "cloudformation/storage/storage-stack.yaml")
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
            azs = [az for az in subnets_by_az.keys()]
            one_subnet_per_az = [subnets_by_az[az][0] for az in azs]

            # The EBS volume must be placed in the same AZ where the head node is.
            # The head node is deployed in the public subnet.
            ebs_volume_az = boto3.resource("ec2").Subnet(vpc_stack.get_public_subnet()).availability_zone

            vpc = vpc_stack.cfn_outputs["VpcId"]
            import_path = "s3://{0}".format(bucket_name)
            export_path = "s3://{0}/export_dir".format(bucket_name)

            fsx_lustre_supported = is_fsx_lustre_supported(region)
            fsx_ontap_supported = is_fsx_ontap_supported(region)
            fsx_openzfs_supported = is_fsx_openzfs_supported(region)
            filecache_supported = is_filecache_supported(region)

            params = [
                # Networking
                {"ParameterKey": "Vpc", "ParameterValue": vpc},
                {"ParameterKey": "SubnetOne", "ParameterValue": one_subnet_per_az[0]},
                {"ParameterKey": "SubnetTwo", "ParameterValue": one_subnet_per_az[1]},
                {
                    "ParameterKey": "SubnetThree",
                    "ParameterValue": "" if len(one_subnet_per_az) == 2 else one_subnet_per_az[2],
                },
                # EBS
                {"ParameterKey": "CreateEbs", "ParameterValue": "true"},
                {"ParameterKey": "EbsVolumeAz", "ParameterValue": ebs_volume_az},
                # EFS
                {"ParameterKey": "CreateEfs", "ParameterValue": "true"},
                # FSxLustre
                {"ParameterKey": "CreateFsxLustre", "ParameterValue": str(fsx_lustre_supported).lower()},
                {"ParameterKey": "FsxLustreImportPath", "ParameterValue": import_path},
                {"ParameterKey": "FsxLustreExportPath", "ParameterValue": export_path},
                # FSxOntap
                {"ParameterKey": "CreateFsxOntap", "ParameterValue": str(fsx_ontap_supported).lower()},
                # FSxOpenZfs
                {"ParameterKey": "CreateFsxOpenZfs", "ParameterValue": str(fsx_openzfs_supported).lower()},
                # FileCache
                {"ParameterKey": "CreateFileCache", "ParameterValue": str(filecache_supported).lower()},
                {"ParameterKey": "FileCachePath", "ParameterValue": file_cache_path},
                {"ParameterKey": "FileCacheS3BucketName", "ParameterValue": bucket_name},
            ]
            with open(template_path, encoding="utf-8") as template_file:
                template = template_file.read()
            stack = CfnStack(
                name=generate_stack_name(
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


def remove_none_items(items: list):
    return [item for item in items if item is not None]


@pytest.mark.usefixtures("instance")
def test_dynamic_file_systems_update(
    region,
    os,
    pcluster_config_reader,
    ami_copy,
    clusters_factory,
    scheduler_commands_factory,
    request,
    vpc_stack,
    key_name,
    s3_bucket_factory,
    test_datadir,
    delete_storage_on_teardown,
    external_shared_storage_stack,
):
    """Test update shared storages."""

    # Create cluster without any shared storage.
    init_config_file = pcluster_config_reader(
        config_file="pcluster.config.yaml", output_file="pcluster.config.no-shared-storage.yaml", login_nodes_count=1
    )
    cluster = clusters_factory(init_config_file, wait=False)

    fsx_lustre_supported = is_fsx_lustre_supported(region)
    fsx_ontap_supported = is_fsx_ontap_supported(region)
    fsx_openzfs_supported = is_fsx_openzfs_supported(region)
    filecache_supported = is_filecache_supported(region)

    existing_ebs_mount_dir = "/existing_ebs_mount_dir"
    existing_efs_mount_dir = "/existing_efs_mount_dir"
    existing_fsx_lustre_mount_dir = "/existing_fsx_lustre_mount_dir" if fsx_lustre_supported else None
    existing_fsx_ontap_mount_dir = "/existing_fsx_ontap_mount_dir" if fsx_ontap_supported else None
    existing_fsx_open_zfs_mount_dir = "/existing_fsx_open_zfs_mount_dir" if fsx_openzfs_supported else None
    existing_file_cache_mount_dir = "/existing_file_cache_mount_dir" if filecache_supported else None
    new_ebs_mount_dir = "/new_ebs_mount_dir"
    new_raid_mount_dir = "/new_raid_dir"
    new_efs_mount_dir = "/new_efs_mount_dir"
    new_lustre_mount_dir = "/new_lustre_mount_dir" if fsx_lustre_supported else None

    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "s3_test_file"), "s3_test_file")
    file_cache_path = "/file-cache-path/"
    (
        existing_ebs_volume_id,
        existing_efs_id,
        existing_fsx_lustre_fs_id,
        existing_fsx_ontap_volume_id,
        existing_fsx_open_zfs_volume_id,
        existing_file_cache_id,
    ) = _create_shared_storages_resources(
        request,
        vpc_stack,
        region,
        bucket_name,
        external_shared_storage_stack,
        file_cache_path,
    )

    cluster.wait_cluster_status("CREATE_COMPLETE")

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    # submit a job to queue1
    queue1_job_id = scheduler_commands.submit_command_and_assert_job_accepted(
        submit_command_args={
            "command": "sleep 86400",  # sleep 86400 seconds (1 day) to keep the job running
            "nodes": 1,
            "partition": "queue1",
        },
    )

    # Wait for the job to run
    scheduler_commands.wait_job_running(queue1_job_id)

    # Take note of the running compute and login nodes because we expect them to be retained during the next update.
    compute_nodes_before_update = cluster.get_cluster_instance_ids(node_type="Compute")
    login_nodes_before_update = cluster.get_cluster_instance_ids(node_type="LoginNode")

    # Update cluster to add storage with a live update.
    # In particular, we add here: external EFS/FsxLustre/FsxOntap/FsxOpenZfs/FileCache.
    logging.info("Updating the cluster to mount external EFS/FsxLustre/FsxOntap/FsxOpenZfs/FileCache with live update")
    update_cluster_config = pcluster_config_reader(
        config_file="pcluster.config.update.yaml",
        output_file="pcluster.config.update_add_external_efs_fsx_and_filecache.yaml",
        existing_efs_mount_dir=existing_efs_mount_dir,
        fsx_lustre_mount_dir=existing_fsx_lustre_mount_dir,
        fsx_ontap_mount_dir=existing_fsx_ontap_mount_dir,
        fsx_open_zfs_mount_dir=existing_fsx_open_zfs_mount_dir,
        file_cache_mount_dir=existing_file_cache_mount_dir,
        existing_efs_id=existing_efs_id,
        existing_fsx_lustre_fs_id=existing_fsx_lustre_fs_id,
        fsx_ontap_volume_id=existing_fsx_ontap_volume_id,
        fsx_open_zfs_volume_id=existing_fsx_open_zfs_volume_id,
        existing_file_cache_id=existing_file_cache_id,
        bucket_name=bucket_name,
        queue_update_strategy="DRAIN",
        login_nodes_count=1,
    )

    cluster.update(update_cluster_config)

    # Check that compute and login nodes didn't get replaced as part of the update
    # as the update only contains storage changes supporting live updates.
    compute_nodes_after_update = cluster.get_cluster_instance_ids(node_type="Compute")
    login_nodes_after_update = cluster.get_cluster_instance_ids(node_type="LoginNode")
    assert_that(compute_nodes_after_update).is_equal_to(compute_nodes_before_update)
    assert_that(login_nodes_after_update).is_equal_to(login_nodes_before_update)

    scheduler_commands.assert_job_state(queue1_job_id, "RUNNING")

    # Check that the mounted storage is visible on all cluster nodes right after the update.
    efs_mount_dirs = [existing_efs_mount_dir]
    fsx_mount_dirs = remove_none_items(
        [
            existing_fsx_lustre_mount_dir,
            existing_fsx_open_zfs_mount_dir,
            existing_fsx_ontap_mount_dir,
            existing_file_cache_mount_dir,
        ]
    )
    all_mount_dirs_update_1 = efs_mount_dirs + fsx_mount_dirs
    _test_shared_storages_mount_on_headnode(
        remote_command_executor,
        cluster,
        region,
        bucket_name,
        scheduler_commands_factory,
        ebs_mount_dirs=[],
        new_raid_mount_dir=[],
        efs_mount_dirs=efs_mount_dirs,
        fsx_mount_dirs=fsx_mount_dirs,
        file_cache_path=file_cache_path,
    )
    for mount_dir in all_mount_dirs_update_1:
        verify_directory_correctly_shared(
            remote_command_executor, mount_dir, scheduler_commands, partitions=["queue1", "queue2"]
        )

    # # Update cluster to stop login nodes
    logging.info("Updating the cluster to stop login nodes")
    update_cluster_config = pcluster_config_reader(
        config_file="pcluster.config.update.yaml",
        output_file="pcluster.config.update_login_fleet_stop.yaml",
        existing_efs_mount_dir=existing_efs_mount_dir,
        fsx_lustre_mount_dir=existing_fsx_lustre_mount_dir,
        fsx_ontap_mount_dir=existing_fsx_ontap_mount_dir,
        fsx_open_zfs_mount_dir=existing_fsx_open_zfs_mount_dir,
        file_cache_mount_dir=existing_file_cache_mount_dir,
        existing_efs_id=existing_efs_id,
        existing_fsx_lustre_fs_id=existing_fsx_lustre_fs_id,
        fsx_ontap_volume_id=existing_fsx_ontap_volume_id,
        fsx_open_zfs_volume_id=existing_fsx_open_zfs_volume_id,
        existing_file_cache_id=existing_file_cache_id,
        bucket_name=bucket_name,
        queue_update_strategy="DRAIN",
        login_nodes_count=0,
    )

    cluster.update(update_cluster_config)

    # We forcefully terminate login nodes to save time.
    # In this way, we do not need to wait for them to be terminated by the scale-in operation of the AutoScalingGroup,
    # In fact, the termination would take the grace time period (minimum is 3 minutes) +
    # ~1min for the ASG to perform the actual scale-in operation.
    terminate_login_nodes(cluster)

    # Update cluster to add storage that does not support live updates.
    # In particular, we add here: external EBS, managed EBS/EFS/FsxLustre with DRAIN strategy
    logging.info(
        "Updating the cluster with DRAIN strategy to mount external EBS and managed EBS/EFS/FsxLustre "
        "with DeletionPolicy set to Retain"
    )
    update_cluster_config = pcluster_config_reader(
        config_file="pcluster.config.update.yaml",
        output_file="pcluster.config.update_add_external_ebs_managed_ebs_efs_fsx_lustre_drain.yaml",
        volume_id=existing_ebs_volume_id,
        existing_ebs_mount_dir=existing_ebs_mount_dir,
        existing_efs_mount_dir=existing_efs_mount_dir,
        fsx_lustre_mount_dir=existing_fsx_lustre_mount_dir,
        fsx_ontap_mount_dir=existing_fsx_ontap_mount_dir,
        fsx_open_zfs_mount_dir=existing_fsx_open_zfs_mount_dir,
        file_cache_mount_dir=existing_file_cache_mount_dir,
        existing_efs_id=existing_efs_id,
        existing_fsx_lustre_fs_id=existing_fsx_lustre_fs_id,
        fsx_ontap_volume_id=existing_fsx_ontap_volume_id,
        fsx_open_zfs_volume_id=existing_fsx_open_zfs_volume_id,
        existing_file_cache_id=existing_file_cache_id,
        bucket_name=bucket_name,
        new_ebs_mount_dir=new_ebs_mount_dir,
        new_ebs_deletion_policy="Retain",
        new_raid_mount_dir=new_raid_mount_dir,
        new_raid_deletion_policy="Retain",
        new_lustre_mount_dir=new_lustre_mount_dir,
        new_lustre_deletion_policy="Retain",
        new_efs_mount_dir=new_efs_mount_dir,
        new_efs_deletion_policy="Retain",
        queue_update_strategy="DRAIN",
        login_nodes_count=0,
    )

    cluster.update(update_cluster_config)

    # Retrieve created shared storage ids to remove them at teardown
    logging.info("Retrieve managed storage ids and mark them for deletion on teardown")
    ebs_mount_dirs = [new_ebs_mount_dir, existing_ebs_mount_dir]
    fsx_mount_dirs = remove_none_items(
        [
            new_lustre_mount_dir,
            existing_fsx_lustre_mount_dir,
            existing_fsx_open_zfs_mount_dir,
            existing_fsx_ontap_mount_dir,
            existing_file_cache_mount_dir,
        ]
    )
    existing_ebs_ids = [existing_ebs_volume_id]
    existing_efs_ids = [existing_efs_id]
    existing_fsx_ids = remove_none_items(
        [
            existing_fsx_lustre_fs_id,
            existing_fsx_ontap_volume_id,
            existing_fsx_open_zfs_volume_id,
            existing_file_cache_id,
        ]
    )
    managed_storage_ids = _retrieve_managed_storage_ids(
        cluster,
        existing_ebs_ids,
        existing_efs_ids,
        existing_fsx_ids,
    )
    for storage_type in managed_storage_ids:
        for storage_id in managed_storage_ids[storage_type]["ids"]:
            delete_storage_on_teardown(storage_type, storage_id)

    # check chef client log contains expected log
    assert_lines_in_logs(
        remote_command_executor,
        ["/var/log/chef-client.log"],
        [
            "All queues will be updated in order to update shared storages",
        ],
    )

    scheduler_commands.assert_job_state(queue1_job_id, "RUNNING")

    logging.info("Checking the status of compute nodes in queue1")
    # Compute nodes in queue1 are expected to be in drain
    # because the static compute node has a job running.
    queue1_nodes = scheduler_commands.get_compute_nodes("queue1")
    assert_compute_node_states(
        scheduler_commands, queue1_nodes, expected_states=["draining", "draining!", "drained*", "drained"]
    )

    logging.info("Checking the status of compute nodes in queue2")
    # All compute nodes in queue2 are expected to be in idle or drained
    # because they have not jobs running, hence we expect them to have been replaced (idle)
    # or under replacement (drained, draining).
    queue2_nodes = scheduler_commands.get_compute_nodes("queue2")
    assert_compute_node_states(
        scheduler_commands, queue2_nodes, expected_states=["idle", "drained", "idle%", "drained*", "draining"]
    )

    logging.info("Checking that shared storage is visible on the head node")
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
        file_cache_path,
    )

    all_mount_dirs_update_2 = remove_none_items(
        [
            new_ebs_mount_dir,
            new_raid_mount_dir,
            new_efs_mount_dir,
            new_lustre_mount_dir,
            existing_ebs_mount_dir,
            existing_efs_mount_dir,
            existing_fsx_lustre_mount_dir,
            existing_fsx_ontap_mount_dir,
            existing_fsx_open_zfs_mount_dir,
            existing_file_cache_mount_dir,
        ]
    )

    mount_dirs_requiring_replacement = remove_none_items(
        [
            new_ebs_mount_dir,
            new_raid_mount_dir,
            new_efs_mount_dir,
            existing_ebs_mount_dir,
            new_lustre_mount_dir,
        ]
    )

    logging.info("Checking that previously mounted storage is visible on all compute nodes")
    for mount_dir in all_mount_dirs_update_1:
        verify_directory_correctly_shared(
            remote_command_executor, mount_dir, scheduler_commands, partitions=["queue1", "queue2"]
        )

    logging.info("Checking that newly mounted storage is not visible on compute nodes with jobs running (queue1)")
    for node_name in queue1_nodes:
        _test_directory_not_mounted(
            remote_command_executor, mount_dirs_requiring_replacement, node_type="compute", node_name=node_name
        )

    logging.info("Checking that newly mounted storage is visible on replaced compute nodes (queue2)")
    for mount_dir in all_mount_dirs_update_2:
        verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands, partitions=["queue2"])

    logging.info("Canceling job in queue1 to trigger compute nodes replacement")
    scheduler_commands.cancel_job(queue1_job_id)

    logging.info("Checking that newly mounted storage is visible on replaced compute nodes (queue1)")
    for mount_dir in all_mount_dirs_update_2:
        verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands, partitions=["queue1"])

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
            "command": "sleep 86400",  # sleep 86400 seconds (1 day) to keep the job running
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
        all_mount_dirs_update_2,
        cluster_nodes,
    )

    # Verify that detached managed storage have been retained and delete them.
    logging.info(
        "Checking that retained managed storage resources have been retained and mark them for deletion on teardown"
    )
    for storage_type in managed_storage_ids:
        for storage_id in managed_storage_ids[storage_type]["ids"]:
            assert_storage_existence(
                region,
                storage_type,
                storage_id,
                should_exist=True,
                expected_states=managed_storage_ids[storage_type]["expected_states"],
            )


@pytest.mark.usefixtures("instance")
def test_dynamic_file_systems_update_rollback(
    region,
    os,
    pcluster_config_reader,
    ami_copy,
    clusters_factory,
    scheduler_commands_factory,
    request,
    vpc_stack,
    key_name,
    s3_bucket_factory,
    test_datadir,
    delete_storage_on_teardown,
    external_shared_storage_stack,
):
    """Test the rollback path when the cluster is updated with invalid shared storage."""

    # Create cluster without any shared storage.
    init_config_file = pcluster_config_reader(
        config_file="pcluster.config.yaml", output_file="pcluster.config.no-shared-storage.yaml", login_nodes_count=1
    )
    cluster = clusters_factory(init_config_file, wait=False)

    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "s3_test_file"), "s3_test_file")
    file_cache_path = "/file-cache-path/"

    existing_ebs_mount_dir = "/existing_ebs_mount_dir"
    new_ebs_mount_dir = "/new_ebs_mount_dir"
    new_efs_mount_dir = "/new_efs_mount_dir"
    new_lustre_mount_dir = "/new_lustre_mount_dir" if is_fsx_lustre_supported(region) else None

    (
        existing_ebs_volume_id,
        existing_efs_id,
        existing_fsx_lustre_fs_id,
        existing_fsx_ontap_volume_id,
        existing_fsx_open_zfs_volume_id,
        existing_file_cache_id,
    ) = _create_shared_storages_resources(
        request,
        vpc_stack,
        region,
        bucket_name,
        external_shared_storage_stack,
        file_cache_path,
    )

    cluster.wait_cluster_status("CREATE_COMPLETE")

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

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


@pytest.mark.usefixtures("instance")
def test_dynamic_file_systems_update_data_loss(
    region,
    os,
    pcluster_config_reader,
    ami_copy,
    clusters_factory,
    scheduler_commands_factory,
    request,
    vpc_stack,
    key_name,
    s3_bucket_factory,
    test_datadir,
    delete_storage_on_teardown,
    external_shared_storage_stack,
):
    """Test that the dynamic file systems update does not cause any data loss.

    The test executes the following steps:
      1. Creates the external shared storage stack
      2. Creates a cluster with all the external shared storage
      3. Writes a file in every external shared storage mount dir
      4. Updates the cluster to unmount all the external shared storage
      5. Updates the cluster to re-mount all the external shared storage
      6. Verifies that all files previously written where still there
    """

    bucket_name = s3_bucket_factory()
    file_cache_path = "/file-cache-path/"

    existing_ebs_mount_dir = "/shared-storage/ebs/existing-1"
    existing_efs_mount_dir = "/shared-storage/efs/existing-1"
    existing_fsx_lustre_mount_dir = "/shared-storage/fsx-lustre/existing-1"
    existing_fsx_ontap_mount_dir = "/shared-storage/fsx-ontap/existing-1"
    existing_fsx_open_zfs_mount_dir = "/shared-storage/fsx-open-zfs/existing-1"
    existing_file_cache_mount_dir = "/shared-storage/file-cache/existing-1"

    (
        existing_ebs_id,
        existing_efs_id,
        existing_fsx_lustre_id,
        existing_fsx_ontap_id,
        existing_fsx_openzfs_id,
        existing_file_cache_id,
    ) = _create_shared_storages_resources(
        request,
        vpc_stack,
        region,
        bucket_name,
        external_shared_storage_stack,
        file_cache_path,
    )

    logging.info("Creating the cluster with all shared storage")
    cluster_config_all_storage = pcluster_config_reader(
        config_file="pcluster.config.yaml",
        output_file="pcluster.config.all_storage.yaml",
        existing_ebs_mount_dir=existing_ebs_mount_dir,
        existing_ebs_id=existing_ebs_id,
        existing_efs_mount_dir=existing_efs_mount_dir,
        existing_efs_id=existing_efs_id,
        existing_fsx_lustre_mount_dir=existing_fsx_lustre_mount_dir,
        existing_fsx_lustre_id=existing_fsx_lustre_id,
        existing_fsx_ontap_mount_dir=existing_fsx_ontap_mount_dir,
        existing_fsx_ontap_id=existing_fsx_ontap_id,
        existing_fsx_open_zfs_mount_dir=existing_fsx_open_zfs_mount_dir,
        existing_fsx_open_zfs_id=existing_fsx_openzfs_id,
        existing_file_cache_mount_dir=existing_file_cache_mount_dir,
        existing_file_cache_id=existing_file_cache_id,
        bucket_name=bucket_name,
    )
    cluster = clusters_factory(cluster_config_all_storage)

    mount_dirs = [
        existing_ebs_mount_dir,
        existing_efs_mount_dir,
        existing_fsx_lustre_mount_dir,
        existing_fsx_ontap_mount_dir,
        existing_fsx_open_zfs_mount_dir,
        existing_file_cache_mount_dir,
    ]

    test_id = f"{request.node.name}/{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}-{random_alphanumeric()}"
    created_files = []
    for mount_dir in mount_dirs:
        file_name = f"{mount_dir}/{test_id}/test_file.txt"
        created_files.append(file_name)
        write_file(cluster, file_name)

    logging.info("Updating the cluster to remove all the shared storage")
    cluster.stop()
    wait_for_computefleet_changed(cluster, "STOPPED")
    cluster_config_no_storage = pcluster_config_reader(
        config_file="pcluster.config.no-storage.yaml",
        bucket_name=bucket_name,
    )
    cluster.update(cluster_config_no_storage)

    logging.info("Updating the cluster to re-mount all shared storage")
    cluster.update(cluster_config_all_storage)
    cluster.start()
    wait_for_computefleet_changed(cluster, "RUNNING")

    for file_path in created_files:
        assert_file_exists(cluster, file_path)


def _retrieve_managed_storage_ids(cluster, existing_ebs_ids, existing_efs_ids, existing_fsx_ids):
    """Retrieve all the shared storages part of the cluster and exclude provided existing storage ids."""
    managed_ebs_noraid_volume_ids = [
        id for id in cluster.cfn_outputs["EBSIds"].split(",") if id not in existing_ebs_ids
    ]
    managed_ebs_raid_volume_ids = [id for id in cluster.cfn_outputs["RAIDIds"].split(",") if id not in existing_ebs_ids]
    managed_ebs_volume_ids = managed_ebs_noraid_volume_ids + managed_ebs_raid_volume_ids
    managed_efs_filesystem_ids = [id for id in cluster.cfn_outputs["EFSIds"].split(",") if id not in existing_efs_ids]
    managed_fsx_filesystem_ids = [
        id for id in cluster.cfn_outputs.get("FSXIds", "").split(",") if id not in existing_fsx_ids
    ]
    managed_storage = {
        StorageType.STORAGE_EBS: dict(ids=managed_ebs_volume_ids, expected_states=["available"]),
        StorageType.STORAGE_EFS: dict(ids=managed_efs_filesystem_ids, expected_states=["available"]),
        StorageType.STORAGE_FSX: dict(ids=managed_fsx_filesystem_ids, expected_states=["AVAILABLE"]),
    }
    return managed_storage


def _create_shared_storages_resources(
    request,
    vpc_stack: CfnVpcStack,
    region,
    bucket_name,
    external_shared_storage_stack,
    file_cache_path,
):
    """Create existing EBS, EFS, FSX resources for test."""

    storage_stack = external_shared_storage_stack(vpc_stack, bucket_name, file_cache_path)

    return (
        storage_stack.cfn_outputs.get("EbsId"),
        storage_stack.cfn_outputs.get("EfsId"),
        storage_stack.cfn_outputs.get("FsxLustreFsId"),
        storage_stack.cfn_outputs.get("FsxOntapVolumeId"),
        storage_stack.cfn_outputs.get("FsxOpenZfsVolumeId"),
        storage_stack.cfn_outputs.get("FileCacheId"),
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
    file_cache_path,
):
    """Check storages are mounted on headnode."""
    # ebs
    for ebs_dir in ebs_mount_dirs:
        volume_size = "2.0" if "existing" in ebs_dir else "40"
        test_ebs_correctly_mounted(remote_command_executor, ebs_dir, volume_size=volume_size)
    # check raid
    if new_raid_mount_dir:
        test_raid_correctly_configured(remote_command_executor, raid_type="0", volume_size=75, raid_devices=5)
        test_raid_correctly_mounted(remote_command_executor, new_raid_mount_dir, volume_size=74)
    # check efs
    for efs in efs_mount_dirs:
        test_efs_correctly_mounted(remote_command_executor, efs)
        test_efs_correctly_mounted(remote_command_executor, efs)
    # check fsx
    if fsx_mount_dirs:
        check_fsx(
            cluster,
            region,
            scheduler_commands_factory,
            fsx_mount_dirs,
            bucket_name,
            headnode_only=True,
            file_cache_path=file_cache_path,
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
        queue_update_strategy="TERMINATE",
        login_nodes_count=0,
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
        ["Infra Phase complete"],
    )

    # Check shared storages are not on headnode
    ebs_mount_dirs = [existing_ebs_mount_dir, new_ebs_mount_dir, problematic_ebs_mount_dir]
    fs_mount_dirs = list(filter(lambda item: item is not None, [new_lustre_mount_dir, new_efs_mount_dir]))
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
    managed_fsx = (
        [fs.get("fsx_fs_id") for fs in failed_share_storages.get("fsx") if fs.get("mount_dir") == new_lustre_mount_dir]
        if new_lustre_mount_dir
        else []
    )

    # assert the managed EBS is clean up
    logging.info("Checking managed EBS is deleted after stack rollback")
    with pytest.raises(ClientError, match="InvalidVolume.NotFound"):
        boto3.client("ec2", region).describe_volumes(VolumeIds=managed_ebs).get("Volumes")
    # assert the managed EFS is clean up
    logging.info("Checking managed EBS is deleted after stack rollback")
    with pytest.raises(ClientError, match="FileSystemNotFound"):
        boto3.client("efs", region).describe_file_systems(FileSystemId=managed_efs[0])
    # assert the managed FSX is clean up
    if new_lustre_mount_dir:
        logging.info("Checking managed FSX is deleted after stack rollback")
        with pytest.raises(ClientError, match="FileSystemNotFound"):
            boto3.client("fsx", region).describe_file_systems(FileSystemIds=managed_fsx)


@pytest.mark.usefixtures("os", "instance")
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


@pytest.mark.usefixtures("instance", "scheduler")
def test_login_nodes_update(os, pcluster_config_reader, clusters_factory, test_datadir):
    """Test cluster Updates (add, remove LN pools)."""

    # Start a cluster without login nodes
    initial_config = pcluster_config_reader(config_file="pcluster_create_without_login_nodes.config.yaml")
    cluster = clusters_factory(initial_config)

    # Describe cluster, verify the response is without login node section
    cluster_info = cluster.describe_cluster()
    assert_that(cluster_info).is_not_none()
    assert_that(cluster_info).does_not_contain("loginNodes")

    # Update the cluster adding 3 login nodes
    update_config_1 = pcluster_config_reader(config_file="pcluster_update_login_nodes_count_to_3.config.yaml")
    cluster.update(str(update_config_1))

    with open(update_config_1, encoding="utf-8") as file:
        config = yaml.safe_load(file)
    _verify_login_nodes(cluster, config)

    # Update the cluster with count = 1
    update_config_2 = pcluster_config_reader(config_file="pcluster_update_login_nodes_count_to_1.config.yaml")
    cluster.update(str(update_config_2))

    with open(update_config_2, encoding="utf-8") as file:
        config = yaml.safe_load(file)
    _verify_login_nodes(cluster, config)

    # Update the cluster with count = 0
    update_config_3 = pcluster_config_reader(config_file="pcluster_update_login_nodes_count_to_0.config.yaml")
    cluster.update(str(update_config_3))

    with open(update_config_3, encoding="utf-8") as file:
        config = yaml.safe_load(file)
    _verify_login_nodes(cluster, config)

    # Update the cluster to remove LoginNodes section
    cluster.update(str(initial_config))

    # Describe cluster, verify the response doesn't have the login nodes section
    cluster_info = cluster.describe_cluster()
    assert_that(cluster_info).is_not_none()
    assert_that(cluster_info).does_not_contain("loginNodes")


def _verify_login_nodes(cluster, config):
    """
    :param cluster: The cluster object
    :param config: The config dictionary
    :return: This function check the consistency between cluster and config
    """
    logging.info("Verifying login nodes")
    _wait_autoscaling_group_capacity_update(cluster)
    time.sleep(30)
    logging.info("Verifying describe-cluster output")
    cluster_info = cluster.describe_cluster()
    assert_that(cluster_info).is_not_none()
    assert_that(cluster_info).contains("loginNodes")
    total_login_nodes = 0
    for pool in cluster_info["loginNodes"]:
        total_login_nodes += pool["healthyNodes"] + pool["unhealthyNodes"]
        assert_that(pool.get("address")).is_not_none()
    config_total_login_nodes = _total_login_nodes(config)
    assert_that(total_login_nodes).is_equal_to(config_total_login_nodes)
    logging.info("Verifying describe-cluster-instances output")
    instances = cluster.describe_cluster_instances(node_type="LoginNode")
    assert_that(len(instances)).is_equal_to(config_total_login_nodes)
    logging.info("Verifying each login node configuration")
    login_nodes_config = config["LoginNodes"]["Pools"]
    login_nodes_dict = {node["Name"]: node for node in login_nodes_config}
    for login_node in instances:
        logging.info("Verifying login node %s", login_node.get("instanceId"))
        pool_name = login_node.get("poolName")
        login_node_config = login_nodes_dict[pool_name]
        assert_that(login_node.get("instanceType")).is_equal_to(login_node_config.get("InstanceType"))
        if login_node_config.get("GracetimePeriod"):
            command_executor = RemoteCommandExecutor(
                cluster, compute_node_ip=login_node.get("publicIpAddress") or login_node.get("privateIpAddress")
            )
            output = command_executor.run_remote_command("cat /etc/parallelcluster/loginmgtd_config.json").stdout
            assert_that(output).contains(f" {login_node_config.get('GracetimePeriod')} minutes")
    logging.info("Finished verifying login nodes")


@retry(retry_on_result=lambda result: result is False, wait_fixed=seconds(20), stop_max_delay=seconds(700))
def _wait_autoscaling_group_capacity_update(cluster):
    logging.info("Waiting AutoScaling Group Capacity update")
    for logical_id, physical_id in cluster.cfn_resources.items():
        if "AutoScalingGroup" in logical_id:
            asg_response = boto3.client("autoscaling").describe_auto_scaling_groups(
                AutoScalingGroupNames=[physical_id]
            )["AutoScalingGroups"][0]
            for instance in asg_response["Instances"]:
                if "Pending" in instance["LifecycleState"] or "Terminating" in instance["LifecycleState"]:
                    return False
    return True


def _total_login_nodes(config):
    total_login_nodes = 0
    for pool in config["LoginNodes"]["Pools"]:
        total_login_nodes += pool["Count"]
    return total_login_nodes
