# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import json
import logging
import time

import boto3
import pytest
import yaml
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from tags_utils import (
    convert_tags_dicts_to_tags_list,
    get_compute_node_root_volume_tags,
    get_compute_node_tags,
    get_head_node_root_volume_tags,
    get_head_node_tags,
    get_main_stack_tags,
    get_shared_volume_tags,
)
from time_utils import minutes, seconds
from utils import check_pcluster_list_cluster_log_streams, check_status

from tests.common.assertions import (
    assert_head_node_is_running,
    assert_instance_replaced_or_terminating,
    assert_no_errors_in_logs,
)
from tests.common.utils import get_installed_parallelcluster_version

SCHEDULER_PLUGIN_LOCAL_CONFIGS_DIR = "/opt/parallelcluster/scheduler-plugin/.configs"
PCLUSTER_CLUSTER_CONFIG = f"{SCHEDULER_PLUGIN_LOCAL_CONFIGS_DIR}/cluster-config.yaml"
PCLUSTER_CLUSTER_CONFIG_OLD = f"{SCHEDULER_PLUGIN_LOCAL_CONFIGS_DIR}/previous-cluster-config.yaml"
PCLUSTER_LAUNCH_TEMPLATES = f"{SCHEDULER_PLUGIN_LOCAL_CONFIGS_DIR}/launch-templates-config.json"
PCLUSTER_INSTANCE_TYPES_DATA = f"{SCHEDULER_PLUGIN_LOCAL_CONFIGS_DIR}/instance-types-data.json"
PCLUSTER_SCHEDULER_PLUGIN_CFN_SUBSTACK_OUTPUTS = (
    f"{SCHEDULER_PLUGIN_LOCAL_CONFIGS_DIR}/scheduler-plugin-substack-outputs.json"
)
PCLUSTER_SHARED_SCHEDULER_PLUGIN_DIR = "/opt/parallelcluster/shared/scheduler-plugin"
PCLUSTER_LOCAL_SCHEDULER_PLUGIN_DIR = "/opt/parallelcluster/scheduler-plugin"

SCHEDULER_PLUGIN_LOG_DIR = "/var/log/parallelcluster/"
SCHEDULER_PLUGIN_LOG_OUT_PATH = "/var/log/parallelcluster/scheduler-plugin.out.log"
SCHEDULER_PLUGIN_LOG_ERR_PATH = "/var/log/parallelcluster/scheduler-plugin.err.log"
SCHEDULER_PLUGIN_HOME = "/home/pcluster-scheduler-plugin"
SCHEDULER_PLUGIN_USER = "pcluster-scheduler-plugin"
SCHEDULER_PLUGIN_USERS_LIST = ["user1", "schedulerPluginUser"]

ANOTHER_INSTANCE_TYPE_BY_ARCH = {
    "x86_64": "c5.large",
    "arm64": "m6g.large",
}
OS_MAPPING = {
    "centos7": "centos",
    "alinux2": "ec2-user",
    "ubuntu1804": "ubuntu",
    "ubuntu2004": "ubuntu",
}


@pytest.mark.usefixtures("instance", "scheduler")
def test_scheduler_plugin_integration(
    region,
    os,
    architecture,
    instance,
    pcluster_config_reader,
    s3_bucket,
    s3_bucket_key_prefix,
    clusters_factory,
    test_datadir,
):
    """Test usage of a custom scheduler integration."""
    logging.info("Testing plugin scheduler integration.")

    # Setup:
    # Get EC2 client
    ec2_client = boto3.client("ec2", region_name=region)
    # Create bucket and upload resources
    bucket_name = s3_bucket
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    account_id = boto3.client("sts", region_name=region).get_caller_identity().get("Account")
    for file in ["scheduler_plugin_infra.cfn.yaml", "artifact"]:
        bucket.upload_file(str(test_datadir / file), f"{s3_bucket_key_prefix}/scheduler_plugin/{file}")
    run_as_user = OS_MAPPING[os]
    # Create cluster
    another_instance_type = ANOTHER_INSTANCE_TYPE_BY_ARCH[architecture]
    before_update_cluster_config = pcluster_config_reader(
        config_file="pcluster.config.before_update.yaml",
        bucket=bucket_name,
        bucket_key_prefix=s3_bucket_key_prefix,
        another_instance=another_instance_type,
        user1=SCHEDULER_PLUGIN_USERS_LIST[0],
        user2=SCHEDULER_PLUGIN_USERS_LIST[1],
        account_id=account_id,
        run_as_user=run_as_user,
    )
    cluster = clusters_factory(before_update_cluster_config)
    cluster_config = pcluster_config_reader(
        bucket=bucket_name,
        bucket_key_prefix=s3_bucket_key_prefix,
        another_instance=another_instance_type,
        user1=SCHEDULER_PLUGIN_USERS_LIST[0],
        user2=SCHEDULER_PLUGIN_USERS_LIST[1],
        account_id=account_id,
        run_as_user=run_as_user,
    )
    # Command executor
    command_executor = RemoteCommandExecutor(cluster)
    # Test cluster configuration before cluster update
    _test_cluster_config(command_executor, before_update_cluster_config, PCLUSTER_CLUSTER_CONFIG)
    # Test compute fleet status update
    _test_compute_fleet_status_update(cluster, command_executor)
    # Test cluster update
    _test_cluster_update(cluster, cluster_config)
    # Command executor after cluster update
    command_executor = RemoteCommandExecutor(cluster)
    # Test cluster configuration after cluster update
    _test_cluster_config(command_executor, cluster_config, PCLUSTER_CLUSTER_CONFIG)
    # Test PCLUSTER_CLUSTER_CONFIG_OLD content
    _test_cluster_config(command_executor, before_update_cluster_config, PCLUSTER_CLUSTER_CONFIG_OLD)
    # Verify head node is running
    assert_head_node_is_running(region, cluster)
    head_node = _get_ec2_instance_from_id(
        ec2_client, cluster.describe_cluster_instances(node_type="HeadNode")[0].get("instanceId")
    )
    # Start and wait for compute node to setup
    compute_node = _start_compute_node(ec2_client, region, cluster, command_executor)

    # Tests:
    # Test even handler execution
    _test_event_handler_execution(cluster, region, os, architecture, command_executor, head_node, compute_node)
    # Test artifacts are downloaded
    _test_artifacts_download(command_executor)
    # Test artifacts shared from head to compute node
    _test_artifacts_shared_from_head(command_executor, compute_node)
    # Test substack outputs
    _test_subtack_outputs(command_executor)
    # Test users are created
    _test_users(command_executor, compute_node)
    # Test sudoer configuration for users
    _test_sudoer_configuration(command_executor, run_as_user)
    # Test user imds
    _test_imds(command_executor)
    # Test instance types data
    _test_instance_types_data(command_executor, instance, another_instance_type)
    # Test error log
    _test_error_log(command_executor)
    # Test logs are uploaded to CW
    _test_logs_uploaded(cluster, os)
    # Test custom log files in Monitoring configuration
    _test_custom_log(cluster, os)
    # Test scheduler plugin tags
    _test_tags(cluster, os)
    # Test get or update compute fleet_status_script
    _test_update_compute_fleet_status_script(command_executor)
    # Test no errors in log
    _test_no_errors_in_logs(command_executor)
    # Test invoke scheduler plugin event handler script
    _test_invoke_scheduler_plugin_event_handler_script(command_executor, compute_node, run_as_user)
    # Test computes are terminated on cluster deletion
    cluster.delete()
    _test_compute_terminated(compute_node, region)


def _test_no_errors_in_logs(command_executor):
    logging.info("Verifying no error in logs")
    assert_no_errors_in_logs(command_executor, "plugin")


def _get_launch_templates(command_executor):
    """Get LT from head node"""
    launch_templates_config_content = command_executor.run_remote_command(
        f"sudo cat {PCLUSTER_LAUNCH_TEMPLATES}"
    ).stdout
    assert_that(launch_templates_config_content).is_not_empty()
    launch_templates_config = json.loads(launch_templates_config_content)
    launch_templates_list = []
    for queue in launch_templates_config.get("Queues").values():
        for compute_resource in queue.get("ComputeResources").values():
            launch_templates_list.append(compute_resource.get("LaunchTemplate").get("Id"))
    assert_that(launch_templates_list).is_length(3)

    return launch_templates_list


def _start_compute_node(ec2_client, region, cluster, command_executor):
    """Start and wait compute node to finish setup"""
    # Get one launch template for compute node
    lt = _get_launch_templates(command_executor)[0]
    run_instance_command = (
        f"aws ec2 run-instances --region {region}" f" --count 1" f" --launch-template LaunchTemplateId={lt}"
    )
    command_executor.run_remote_command(run_instance_command)
    # Wait instance to start
    time.sleep(3)
    compute_nodes = cluster.describe_cluster_instances(node_type="Compute")
    assert_that(compute_nodes).is_length(1)
    compute_node = compute_nodes[0]
    instance_id = compute_node.get("instanceId")
    # Wait instance to go running
    _wait_instance_running(ec2_client, [instance_id])
    # Wait instance to complete cloud-init
    _wait_compute_cloudinit_done(command_executor, compute_node)

    return compute_node


def _wait_instance_running(ec2_client, instance_ids):
    """Wait EC2 instance to go running"""
    logging.info(f"Waiting for {instance_ids} to be running")
    ec2_client.get_waiter("instance_running").wait(
        InstanceIds=instance_ids, WaiterConfig={"Delay": 60, "MaxAttempts": 5}
    )


@retry(wait_fixed=seconds(10), stop_max_delay=minutes(3))
def _wait_compute_cloudinit_done(command_executor, compute_node):
    """Wait till cloud-init complete on a given compute node"""
    compute_node_private_ip = compute_node.get("privateIpAddress")
    compute_cloudinit_status_output = command_executor.run_remote_command(
        f"ssh -q {compute_node_private_ip} sudo cloud-init status"
    ).stdout
    assert_that(compute_cloudinit_status_output).contains("status: done")


def _test_event_handler_execution(cluster, region, os, architecture, command_executor, head_node, compute_node):
    """Test event handler execution and environment"""
    head_scheduler_plugin_log_output = command_executor.run_remote_command(
        f"cat {SCHEDULER_PLUGIN_LOG_OUT_PATH}"
    ).stdout
    python_root = command_executor.run_remote_command(f"sudo su - {SCHEDULER_PLUGIN_USER} -c 'which python'").stdout[
        : -len("/python")
    ]
    # Verify ability to install packages into the python virtual env
    command_executor.run_remote_command(
        f"sudo su - {SCHEDULER_PLUGIN_USER} -c 'pip install aws-parallelcluster-node'", raise_on_error=True
    )
    for event in ["HeadInit", "HeadConfigure", "HeadFinalize", "HeadClusterUpdate"]:
        assert_that(head_scheduler_plugin_log_output).contains(f"[{event}] - INFO: {event} executed")
        _test_event_handler_environment(
            cluster, region, os, architecture, event, head_scheduler_plugin_log_output, head_node, python_root, "head"
        )

    compute_node_private_ip = compute_node.get("privateIpAddress")
    compute_scheduler_plugin_log_output = command_executor.run_remote_command(
        f"ssh -q {compute_node_private_ip} cat {SCHEDULER_PLUGIN_LOG_OUT_PATH}"
    ).stdout
    for event in ["ComputeInit", "ComputeConfigure", "ComputeFinalize"]:
        assert_that(compute_scheduler_plugin_log_output).contains(f"[{event}] - INFO: {event} executed")
        _test_event_handler_environment(
            cluster,
            region,
            os,
            architecture,
            event,
            compute_scheduler_plugin_log_output,
            head_node,
            python_root,
            "compute",
        )


def _test_event_handler_environment(
    cluster, region, os, architecture, event, log_output, head_node, python_root, node_type
):
    """Test event handler environment"""
    vars = [
        f"PCLUSTER_CLUSTER_CONFIG={PCLUSTER_CLUSTER_CONFIG}",
        f"PCLUSTER_LAUNCH_TEMPLATES={PCLUSTER_LAUNCH_TEMPLATES}",
        f"PCLUSTER_INSTANCE_TYPES_DATA={PCLUSTER_INSTANCE_TYPES_DATA}",
        f"PCLUSTER_CLUSTER_NAME={cluster.name}",
        f"PCLUSTER_CFN_STACK_ARN={cluster.cfn_stack_arn}",
        f"PCLUSTER_SCHEDULER_PLUGIN_CFN_SUBSTACK_ARN={cluster.cfn_resources.get('SchedulerPluginStack')}",
        f"PCLUSTER_SCHEDULER_PLUGIN_CFN_SUBSTACK_OUTPUTS={PCLUSTER_SCHEDULER_PLUGIN_CFN_SUBSTACK_OUTPUTS}",
        f"PCLUSTER_SHARED_SCHEDULER_PLUGIN_DIR={PCLUSTER_SHARED_SCHEDULER_PLUGIN_DIR}",
        f"PCLUSTER_LOCAL_SCHEDULER_PLUGIN_DIR={PCLUSTER_LOCAL_SCHEDULER_PLUGIN_DIR}",
        f"PCLUSTER_AWS_REGION={region}",
        f"AWS_REGION={region}",
        f"PCLUSTER_OS={os}",
        f"PCLUSTER_ARCH={architecture}",
        f"PCLUSTER_VERSION={get_installed_parallelcluster_version()}",
        f"PCLUSTER_HEADNODE_PRIVATE_IP={head_node.get('PrivateIpAddress')}",
        f"PCLUSTER_HEADNODE_HOSTNAME={head_node.get('PrivateDnsName').split('.')[0]}",
        f"PCLUSTER_PYTHON_ROOT={python_root}",
        f"PATH={python_root}",
        f"PCLUSTER_NODE_TYPE={node_type}"
        # TODO
        # PROXY
    ]
    if event == "HeadClusterUpdate":
        vars.append(f"PCLUSTER_CLUSTER_CONFIG_OLD={PCLUSTER_CLUSTER_CONFIG_OLD}")
    if node_type == "compute":
        # the compute node launched in the test is from the first queue and first compute resource from the launched
        # template, it is from Queue q1 and ComputeResource c1.
        vars.append("PCLUSTER_QUEUE_NAME=q1")
        vars.append("PCLUSTER_COMPUTE_RESOURCE_NAME=c1")

    for var in vars:
        assert_that(log_output).contains(f"[{event}] - INFO: {var}")


def _test_artifacts_download(command_executor):
    """Test artifacts download"""
    home_listing = command_executor.run_remote_command(f"sudo ls {SCHEDULER_PLUGIN_HOME}").stdout
    assert_that(home_listing).contains("aws-parallelcluster-cookbook-3.0.0.tgz", "artifact")


def _test_error_log(command_executor):
    """Test error log is written"""
    head_scheduler_plugin_log_error = command_executor.run_remote_command(f"cat {SCHEDULER_PLUGIN_LOG_ERR_PATH}").stdout
    assert_that(head_scheduler_plugin_log_error).contains("[HeadInit] - ERROR: log to stderr")
    # assert that nothing else is written after the error log
    assert_that(
        head_scheduler_plugin_log_error[head_scheduler_plugin_log_error.find("log to stderr") :]  # noqa: E203
    ).is_equal_to("log to stderr")
    # assert that there is only one error log line
    assert_that(head_scheduler_plugin_log_error.splitlines()).is_length(1)


def _test_artifacts_shared_from_head(command_executor, compute_node):
    """Test artifacts shared from head to compute node"""
    compute_node_private_ip = compute_node.get("privateIpAddress")
    shared_listing = command_executor.run_remote_command(
        f"ssh -q {compute_node_private_ip} ls {PCLUSTER_SHARED_SCHEDULER_PLUGIN_DIR}"
    ).stdout
    assert_that(shared_listing).contains("sharedFromHead")


def _test_subtack_outputs(command_executor):
    """Test substack output is fetched by head node"""
    head_scheduler_plugin_substack_outputs = command_executor.run_remote_command(
        f"sudo cat {PCLUSTER_SCHEDULER_PLUGIN_CFN_SUBSTACK_OUTPUTS}"
    ).stdout
    assert_that(head_scheduler_plugin_substack_outputs).contains('"TestOutput":"TestValue"')


def _test_users(command_executor, compute_node):
    """Test custom scheduler users"""
    compute_node_private_ip = compute_node.get("privateIpAddress")
    for user in SCHEDULER_PLUGIN_USERS_LIST:
        command_executor.run_remote_command(f"getent passwd {user}")
        command_executor.run_remote_command(f"ssh -q {compute_node_private_ip} getent passwd {user}")


def _get_ec2_instance_from_id(ec2, instance_id):
    return ec2.describe_instances(Filters=[], InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]


def _test_instance_types_data(command_executor, instance_type, another_instance_type):
    """Test instance types data is fetched by head node"""
    instance_types_data_content = command_executor.run_remote_command(f"sudo cat {PCLUSTER_INSTANCE_TYPES_DATA}").stdout
    assert_that(instance_types_data_content).is_not_empty()
    instance_types_data = json.loads(instance_types_data_content)
    assert_that(instance_types_data.get(instance_type).get("InstanceType")).is_equal_to(instance_type)
    assert_that(instance_types_data.get(another_instance_type).get("InstanceType")).is_equal_to(another_instance_type)


def _test_imds(command_executor):
    """Test imds setting for custom scheduler users"""
    # SCHEDULER_PLUGIN_USERS_LIST[0] with EnableImds: false
    result = command_executor.run_remote_command(
        f'sudo su - {SCHEDULER_PLUGIN_USERS_LIST[0]} -c "curl --retry 3 --retry-delay 0 --fail -s'
        " -X PUT 'http://169.254.169.254/latest/api/token'"
        " -H 'X-aws-ec2-metadata-token-ttl-seconds: 300'\"",
        raise_on_error=False,
    )
    assert_that(result.failed).is_equal_to(True)

    # SCHEDULER_PLUGIN_USERS_LIST[1] with EnableImds: true
    result = command_executor.run_remote_command(
        f'sudo su - {SCHEDULER_PLUGIN_USERS_LIST[1]} -c "curl --retry 3 --retry-delay 0  --fail -s'
        " -X PUT 'http://169.254.169.254/latest/api/token'"
        " -H 'X-aws-ec2-metadata-token-ttl-seconds: 300'\""
    )
    assert_that(result.failed).is_equal_to(False)
    assert_that(result.stdout).is_not_empty()


def _test_cluster_config(command_executor, cluster_config, remote_config):
    """Test cluster configuration file is fetched by head node"""
    with open(cluster_config, encoding="utf-8") as cluster_config_file:
        source_config = yaml.safe_load(cluster_config_file)
        assert_that(source_config).is_not_empty()

        target_config_content = command_executor.run_remote_command(f"sudo cat {remote_config}").stdout
        assert_that(target_config_content).is_not_empty()
        target_config = yaml.safe_load(target_config_content)

        assert_that(
            source_config.get("Scheduling").get("SchedulerSettings").get("SchedulerDefinition").get("Events")
        ).is_equal_to(target_config.get("Scheduling").get("SchedulerSettings").get("SchedulerDefinition").get("Events"))
        assert_that(source_config.get("Scheduling").get("SchedulerQeueus")).is_equal_to(
            target_config.get("Scheduling").get("SchedulerQeueus")
        )
        assert_that(
            source_config.get("Scheduling").get("SchedulerSettings").get("SchedulerDefinition").get("SystemUsers")
        ).is_equal_to(
            target_config.get("Scheduling").get("SchedulerSettings").get("SchedulerDefinition").get("SystemUsers")
        )


def _test_tags(cluster, os):
    scheduler_plugin_tags = {"SchedulerPluginTag": "SchedulerPluginTagValue"}
    config_file_tags = {"ConfigFileTag": "ConfigFileTagValue"}

    test_cases = [
        {
            "resource": "Main CloudFormation Stack",
            "tag_getter": get_main_stack_tags,
        },
        {
            "resource": "Head Node",
            "tag_getter": get_head_node_tags,
        },
        {
            "resource": "Head Node Root Volume",
            "tag_getter": get_head_node_root_volume_tags,
            "tag_getter_kwargs": {"cluster": cluster, "os": os},
        },
        {
            "resource": "Compute Node",
            "tag_getter": get_compute_node_tags,
        },
        {
            "resource": "Compute Node Root Volume",
            "tag_getter": get_compute_node_root_volume_tags,
            "tag_getter_kwargs": {"cluster": cluster, "os": os},
        },
        {
            "resource": "Shared EBS Volume",
            "tag_getter": get_shared_volume_tags,
        },
    ]
    for test_case in test_cases:
        logging.info("Verifying tags were propagated to %s", test_case.get("resource"))
        tag_getter = test_case.get("tag_getter")
        # Assume tag getters use lone cluster object arg if none explicitly given
        tag_getter_args = test_case.get("tag_getter_kwargs", {"cluster": cluster})
        observed_tags = tag_getter(**tag_getter_args)
        assert_that(observed_tags).contains(*convert_tags_dicts_to_tags_list([scheduler_plugin_tags, config_file_tags]))


def _test_compute_fleet_status_update(cluster, command_executor):
    cluster.stop()
    _check_fleet_status(cluster, "STOPPED")
    # Test get-compute-fleet-status.sh
    _test_get_compute_fleet_status_script(command_executor, "STOPPED")
    home_listing = command_executor.run_remote_command(f"sudo ls {SCHEDULER_PLUGIN_HOME}").stdout
    assert_that(home_listing).contains("stop_failure", "stop_executed")
    assert_that(home_listing).does_not_contain("start_failure", "start_executed")
    cluster.start()
    _check_fleet_status(cluster, "RUNNING")
    # Test get-compute-fleet-status.sh
    _test_get_compute_fleet_status_script(command_executor, "RUNNING")
    home_listing = command_executor.run_remote_command(f"sudo ls {SCHEDULER_PLUGIN_HOME}").stdout
    assert_that(home_listing).contains("start_failure", "start_executed")
    # assert that update event handler is not called multiple times
    assert_that(home_listing).does_not_contain("update_wrong_execution")


@retry(wait_fixed=seconds(10), stop_max_delay=minutes(3))
def _check_fleet_status(cluster, status):
    check_status(cluster, compute_fleet_status=status)


@retry(wait_fixed=seconds(10), stop_max_delay=minutes(3))
def _test_compute_terminated(node, region):
    assert_instance_replaced_or_terminating(instance_id=node.get("instanceId"), region=region)


def _test_custom_log(cluster, os):
    """Verify custom log exist in Cloudwatch log."""
    expected_log_streams = {
        "HeadNode": {"test_cfn_init_cmd.log", "test_amazon_cloudwatch_agent.log"},
        "Compute": {"test_configuration_validation.log", "test_amazon_cloudwatch_agent.log"},
    }

    check_pcluster_list_cluster_log_streams(cluster, os, expected_log_streams=expected_log_streams)


def _test_logs_uploaded(cluster, os):
    """Verify scheduler plugin logs are uploaded to Cloudwatch."""
    expected_log_streams = {
        "HeadNode": {
            "cfn-init",
            "cloud-init",
            "chef-client",
            "scheduler-plugin-err",
            "scheduler-plugin-out",
            "clusterstatusmgtd",
        },
        "Compute": {"syslog" if os.startswith("ubuntu") else "system-messages", "supervisord", "scheduler-plugin-out"},
    }
    check_pcluster_list_cluster_log_streams(cluster, os, expected_log_streams=expected_log_streams)


def _test_sudoer_configuration(command_executor, run_as_user):
    """Verify users are able to run sudo commands without password in SudoerConfiguration."""

    user1 = SCHEDULER_PLUGIN_USERS_LIST[0]
    # Test user1 is able to run "touch" and "ls" commands as {run_as_user}
    command_executor.run_remote_command(f"sudo su {user1} -c 'sudo -u {run_as_user} touch test_user1_touch'")
    result = command_executor.run_remote_command(f"sudo su {user1} -c 'sudo -u {run_as_user} ls'").stdout
    assert_that(result).contains("test_user1_touch")

    # Test user1 is not able to run "mkdir" command as {run_as_user}
    result = command_executor.run_remote_command(
        f"sudo su {user1} -c 'sudo -u {run_as_user} mkdir test_mkdir'", raise_on_error=False
    )
    assert_that(result.failed).is_true()
    # Test user1 is able to run "mkdir" command as root user
    result = command_executor.run_remote_command(f"sudo su {user1} -c 'sudo -u root mkdir test_mkdir'")
    assert_that(result.failed).is_false()

    user2 = SCHEDULER_PLUGIN_USERS_LIST[1]
    # Test user2 is not able to run "mkdir" command as root
    result = command_executor.run_remote_command(
        f"sudo su {user2} -c 'sudo -u root mkdir test_mkdir'", raise_on_error=False
    )
    assert_that(result.failed).is_true()
    # Test user2 is able to run "ls" command as root
    result = command_executor.run_remote_command(f"sudo su {user2} -c 'sudo -u root ls'")
    assert_that(result.failed).is_false()


def _test_update_compute_fleet_status_script(command_executor):
    """Test update-compute-fllet-status.sh."""
    result = command_executor.run_remote_command("update-compute-fleet-status.sh --status PROTECTED").stdout
    assert_that(result).is_empty()
    _test_get_compute_fleet_status_script(command_executor, "PROTECTED")


def _test_get_compute_fleet_status_script(command_executor, expected_status):
    """Test get-compute-fleet-status.sh."""
    result = command_executor.run_remote_command("get-compute-fleet-status.sh").stdout
    status = json.loads(result)
    assert_that("lastStatusUpdatedTime" in status and "status" in status).is_true()
    assert_that(status.get("status")).is_equal_to(expected_status)


def _test_cluster_update(cluster, cluster_config):
    """Test cluster update."""
    cluster.stop()
    _check_fleet_status(cluster, "STOPPED")
    cluster.update(str(cluster_config), force_update="true")
    cluster.start()
    _check_fleet_status(cluster, "RUNNING")


def _test_invoke_scheduler_plugin_event_handler_script(command_executor, compute_node, run_as_user):
    """Test invoke-scheduler-plugin-event-handler.sh."""
    # Create a dummy cluster config for test, echo "dummy config {Event} executed" during handler execution.
    cluster_config = "/opt/parallelcluster/shared/cluster-config.yaml"
    dummy_cluster_config = "/opt/parallelcluster/shared/dummy-cluster-config.yaml"
    command_executor.run_remote_command(
        f"sudo sed 's/echo \\\\\"/echo \\\\\"dummy config /g' {cluster_config} | sudo tee "
        f"{dummy_cluster_config} >/dev/null"
    )
    command_executor.run_remote_command(f"sudo sed -i 's/echo \"/echo \"dummy config /g' {dummy_cluster_config}")
    # remove file "start_failure" to make HeadComputeFleetUpdate fail and exit.
    command_executor.run_remote_command(f"sudo rm -rf {SCHEDULER_PLUGIN_HOME}/start_failure").stdout
    compute_node_private_ip = compute_node.get("privateIpAddress")
    for event in ["HeadInit", "HeadConfigure", "HeadFinalize"]:
        command_executor.run_remote_command(
            f"sudo invoke-scheduler-plugin-event-handler.sh --cluster-configuration {dummy_cluster_config}"
            f" --event-name {event}"
        ).stdout
        head_scheduler_plugin_log_output = command_executor.run_remote_command(
            f"cat {SCHEDULER_PLUGIN_LOG_OUT_PATH}"
        ).stdout
        assert_that(head_scheduler_plugin_log_output).contains(f"[{event}] - INFO: dummy config {event} executed")
    for event in ["HeadClusterUpdate", "HeadComputeFleetUpdate"]:
        raise_on_error = False if event == "HeadComputeFleetUpdate" else True
        result = command_executor.run_remote_command(
            f"sudo invoke-scheduler-plugin-event-handler.sh --cluster-configuration {dummy_cluster_config}"
            f" --event-name {event} --previous-cluster-configuration {cluster_config} "
            "--computefleet-status START_REQUESTED",
            raise_on_error=raise_on_error,
        )
        head_scheduler_plugin_log_output = command_executor.run_remote_command(
            f"cat {SCHEDULER_PLUGIN_LOG_OUT_PATH}"
        ).stdout
        if event == "HeadClusterUpdate":
            assert_that(head_scheduler_plugin_log_output).contains(f"[{event}] - INFO: dummy config {event} executed")
        else:
            assert_that(head_scheduler_plugin_log_output).contains(
                f"[{event}] - INFO: dummy config {event} failing the first start execution"
            )
            assert_that(result.failed).is_equal_to(True)
    for event in ["ComputeInit", "ComputeConfigure", "ComputeFinalize"]:
        command_executor.run_remote_command(
            f"ssh -q {compute_node_private_ip} sudo invoke-scheduler-plugin-event-handler.sh --cluster-configuration "
            f"{dummy_cluster_config} --event-name {event} --skip-artifacts-download"
        ).stdout
        compute_scheduler_plugin_log_output = command_executor.run_remote_command(
            f"ssh -q {compute_node_private_ip} cat {SCHEDULER_PLUGIN_LOG_OUT_PATH}"
        ).stdout
        assert_that(compute_scheduler_plugin_log_output).contains(f"[{event}] - INFO: dummy config {event} executed")
