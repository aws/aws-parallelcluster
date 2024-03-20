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

import boto3
import pytest
from assertpy import soft_assertions
from remote_command_executor import RemoteCommandExecutor
from utils import check_status, is_dcv_supported, test_cluster_health_metric

from tests.basic.disable_hyperthreading_utils import _test_disable_hyperthreading_settings
from tests.basic.log_rotation_utils import _test_compute_log_rotation, _test_headnode_log_rotation
from tests.basic.structured_log_event_utils import assert_that_event_exists
from tests.cloudwatch_logging.cloudwatch_logging_boto3_utils import get_cluster_log_groups_from_boto3
from tests.common.assertions import (
    assert_no_errors_in_logs,
    wait_for_num_instances_in_queue,
    wait_instance_replaced_or_terminating,
)
from tests.common.utils import fetch_instance_slots, run_system_analyzer


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_essential_features(
    region,
    pcluster_config_reader,
    s3_bucket_factory,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
    os,
    instance,
    scheduler,
    default_threads_per_core,
    request,
):
    """Verify fundamental features for a cluster work as expected."""
    # Create S3 bucket for pre/post install scripts
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "failing_post_install.sh"), "failing_post_install.sh")
    bucket.upload_file(str(test_datadir / "pre_install.sh"), "scripts/pre_install.sh")
    bucket.upload_file(str(test_datadir / "post_install.sh"), "scripts/post_install.sh")

    dcv_enabled = is_dcv_supported(region)

    cluster_config = pcluster_config_reader(bucket_name=bucket_name, dcv_enabled=dcv_enabled)
    cluster = clusters_factory(cluster_config)

    with soft_assertions():
        _test_custom_bootstrap_scripts_args_quotes(cluster)

    # We cannot use soft assertion for this test because "wait_" functions are relying on assertion failures for retries
    _test_replace_compute_on_failure(cluster, region, scheduler_commands_factory)

    _test_logging(cluster, region, scheduler_commands_factory, dcv_enabled, os)

    _test_disable_hyperthreading(
        cluster, region, instance, scheduler, default_threads_per_core, request, scheduler_commands_factory
    )


def _test_logging(cluster, region, scheduler_commands_factory, dcv_enabled, os):
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    scheduler_commands.submit_command("hostname", nodes=1, partition="bootstrap-scripts-args")
    scheduler_commands.submit_command("hostname", nodes=1, partition="broken-post-install")

    assert_that_event_exists(cluster, r".+\.clustermgtd_events", "invalid-backing-instance-count")
    assert_that_event_exists(cluster, r".+\.clustermgtd_events", "protected-mode-error-count")
    assert_that_event_exists(cluster, r".+\.bootstrap_error_msg", "custom-action-error")
    assert_that_event_exists(cluster, r".+\.clustermgtd_events", "compute-node-idle-time")

    test_cluster_health_metric(["OnNodeConfiguredRunErrors"], cluster.name, region)
    test_cluster_health_metric(["MaxDynamicNodeIdleTime"], cluster.name, region)

    compute_node_ip = cluster.describe_cluster_instances(node_type="Compute", queue_name="rotation")[0].get(
        "privateIpAddress"
    )
    headnode_ip = cluster.describe_cluster_instances(node_type="HeadNode")[0].get("privateIpAddress")
    log_group_name = get_cluster_log_groups_from_boto3(f"/aws/parallelcluster/{cluster.name}")[0].get("logGroupName")

    logging.info("Verifying ParallelCluster log rotation configuration.")
    common_logs = [
        {"log_name": "cloud-init", "log_path": "/var/log/cloud-init.log", "existence": True},
        {"log_name": "supervisord", "log_path": "/var/log/supervisord.log", "existence": True},
        {"log_name": "bootstrap_error_msg", "log_path": "/var/log/parallelcluster/bootstrap_error_msg"},
    ]
    headnode_specified_logs = [
        {
            "log_name": "clustermgtd",
            "log_path": "/var/log/parallelcluster/clustermgtd",
            "existence": True,
            "trigger_new_entries": True,
        },
        {
            "log_name": "clusterstatusmgtd",
            "log_path": "/var/log/parallelcluster/clusterstatusmgtd",
            "existence": True,
            "trigger_new_entries": True,
        },
        {"log_name": "cfn-init", "log_path": "/var/log/cfn-init.log", "existence": True},
        {"log_name": "slurmdbd", "log_path": "/var/log/slurmdbd.log"},
        {"log_name": "slurmctld", "log_path": "/var/log/slurmctld.log", "existence": True, "trigger_new_entries": True},
        {
            "log_name": "compute_console_output",
            "log_path": "/var/log/parallelcluster/compute_console_output.log",
            "existence": True,
        },
        {
            "log_name": "slurm_fleet_status_manager",
            "log_path": "/var/log/parallelcluster/slurm_fleet_status_manager.log",
            "existence": True,
        },
        {
            "log_name": "slurm_suspend",
            "log_path": "/var/log/parallelcluster/slurm_suspend.log",
            "existence": True,
            "trigger_new_entries": True,
        },
        {
            "log_name": "slurm_resume",
            "log_path": "/var/log/parallelcluster/slurm_resume.log",
            "existence": True,
            "trigger_new_entries": True,
        },
        {"log_name": "chef-client", "log_path": "/var/log/chef-client.log", "existence": True},
        {
            "log_name": "clustermgtd_events",
            "log_path": "/var/log/parallelcluster/clustermgtd.events",
            "existence": True,
        },
        {
            "log_name": "slurm_resume_events",
            "log_path": "/var/log/parallelcluster/slurm_resume.events",
            "existence": True,
        },
    ]

    if dcv_enabled:
        headnode_specified_logs.extend(
            [
                {"log_name": "dcv-agent", "log_path": "/var/log/dcv/agent.*.log"},
                {
                    "log_name": "dcv-session-launcher",
                    "log_path": "/var/log/dcv/sessionlauncher.log",
                    "existence": False,
                },
                {"log_name": "Xdcv", "log_path": "/var/log/dcv/Xdcv.*.log"},
                {
                    "log_name": "dcv-server",
                    "log_path": "/var/log/dcv/server.log",
                    "existence": True,
                    "trigger_new_entries": False,
                },
                {"log_name": "dcv-xsession", "log_path": "/var/log/dcv/dcv-xsession.*.log"},
            ]
        )

    compute_specified_logs = [
        {"log_name": "cloud-init-output", "log_path": "/var/log/cloud-init-output.log", "existence": True},
        {
            "log_name": "computemgtd",
            "log_path": "/var/log/parallelcluster/computemgtd",
            "existence": True,
            "trigger_new_entries": True,
        },
        {"log_name": "slurmd", "log_path": "/var/log/slurmd.log", "existence": True},
    ]

    before_log_rotation_message = "test message before log rotation."
    after_log_rotation_message = "test message after log rotation."
    _test_headnode_log_rotation(
        os,
        headnode_specified_logs,
        common_logs,
        remote_command_executor,
        before_log_rotation_message,
        after_log_rotation_message,
        scheduler_commands,
        cluster,
        headnode_ip,
        log_group_name,
    )
    _test_compute_log_rotation(
        os,
        compute_specified_logs,
        common_logs,
        remote_command_executor,
        before_log_rotation_message,
        after_log_rotation_message,
        cluster,
        compute_node_ip,
        log_group_name,
    )


def _test_replace_compute_on_failure(cluster, region, scheduler_commands_factory):
    """
    Test that compute nodes get replaced on userdata failures.

    The failure is caused by a post_install script that exits with errors on compute nodes.
    """
    # submit a job to spin up a compute node that will fail due to post_install script
    queue = "broken-post-install"
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    scheduler_commands.submit_command("sleep 1", partition=queue)

    # Wait for the instance to become running
    instances = wait_for_num_instances_in_queue(cluster.cfn_name, cluster.region, desired=1, queue=queue)

    wait_instance_replaced_or_terminating(instances[0], region)


def _test_custom_bootstrap_scripts_args_quotes(cluster):
    """
    Test pre/post install args with single quote and double quotes.

    The cluster should be created and running.
    """
    # Check head node and compute node status
    check_status(cluster, "CREATE_COMPLETE", head_node_status="running", compute_fleet_status="RUNNING")


def _test_disable_hyperthreading(
    cluster, region, instance, scheduler, default_threads_per_core, request, scheduler_commands_factory
):
    slots_per_instance = fetch_instance_slots(region, instance)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    _test_disable_hyperthreading_settings(
        remote_command_executor,
        scheduler_commands,
        slots_per_instance,
        scheduler,
        hyperthreading_disabled=False,
        partition="bootstrap-scripts-args",
        default_threads_per_core=default_threads_per_core,
    )
    _test_disable_hyperthreading_settings(
        remote_command_executor,
        scheduler_commands,
        slots_per_instance,
        scheduler,
        hyperthreading_disabled=True,
        partition="ht-disabled",
        default_threads_per_core=default_threads_per_core,
    )

    assert_no_errors_in_logs(remote_command_executor, scheduler)
    run_system_analyzer(cluster, scheduler_commands_factory, request)
