# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

from unittest.mock import PropertyMock

import pytest
import yaml
from assertpy import assert_that

from pcluster.config.cluster_config import SharedStorageType
from pcluster.constants import Feature
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import is_feature_supported, load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket, mock_bucket_object_utils


@pytest.mark.parametrize(
    "config_file_name, region",
    [
        ("rhel8.slurm.full.yaml", "us-east-1"),
        ("alinux2.slurm.conditional_vol.yaml", "us-east-1"),
        ("ubuntu20.slurm.simple.yaml", "us-east-1"),
        ("alinux2.batch.no_head_node_log.yaml", "us-east-1"),
        ("ubuntu20.slurm.no_dashboard.yaml", "us-east-1"),
        ("alinux2.batch.head_node_log.yaml", "us-east-1"),
        ("ubuntu20.slurm.simple.yaml", "us-iso-WHATEVER"),
    ],
)
def test_cw_dashboard_builder(mocker, test_datadir, set_env, config_file_name, region):
    mock_aws_api(mocker)
    mocker.patch(
        "pcluster.config.cluster_config.HeadNodeNetworking.availability_zone",
        new_callable=PropertyMock(return_value="us-east-1a"),
    )
    set_env("AWS_DEFAULT_REGION", region)
    mock_bucket(mocker)
    mock_bucket_object_utils(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)
    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)
    print(cluster_config)
    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )
    output_yaml = yaml.dump(generated_template, width=float("inf"))
    print(output_yaml)

    if cluster_config.is_cw_dashboard_enabled:
        assert_that(output_yaml).contains("CloudwatchDashboard")
        assert_that(output_yaml).contains("Head Node EC2 Metrics")
        _verify_head_node_instance_metrics_graphs(output_yaml)

        if cluster_config.are_alarms_enabled:
            assert_that(output_yaml).contains("Cluster Alarms")

        if cluster_config.shared_storage:
            _verify_ec2_metrics_conditions(cluster_config, output_yaml)

        if cluster_config.is_cw_logging_enabled:
            _verify_head_node_logs_conditions(cluster_config, output_yaml)
            _verify_common_error_metrics_graphs(cluster_config, output_yaml, region)
        else:
            assert_that(output_yaml).does_not_contain("Head Node Logs")
            assert_that(output_yaml).does_not_contain("Cluster Health Metrics")

        metric_filters = _extract_metric_filters(generated_template)
        _verify_metric_filter_dimensions(metric_filters)
    else:
        assert_that(output_yaml).does_not_contain("CloudwatchDashboard")
        assert_that(output_yaml).does_not_contain("Head Node EC2 Metrics")

    _verify_alarms(output_yaml, cluster_config.are_alarms_enabled)

    if cluster_config.is_cw_logging_enabled:
        assert_that(output_yaml).contains("ClusterCWLogGroup")
    else:
        assert_that(output_yaml).does_not_contain("ClusterCWLogGroup")


def _verify_alarms(output_yaml, alarms_enabled):
    if alarms_enabled:
        assert_that(output_yaml).contains("HeadNodeHealthAlarm")
        assert_that(output_yaml).contains("StatusCheckFailed")

        assert_that(output_yaml).contains("HeadNodeCpuAlarm")
        assert_that(output_yaml).contains("CPUUtilization")

        assert_that(output_yaml).contains("HeadNodeMemAlarm")
        assert_that(output_yaml).contains("mem_used_percent")

        assert_that(output_yaml).contains("HeadNodeDiskAlarm")
        assert_that(output_yaml).contains("disk_used_percent")

    else:
        assert_that(output_yaml).does_not_contain("Cluster Alarms")
        assert_that(output_yaml).does_not_contain("AWS::CloudWatch::Alarm")


def _extract_metric_filters(generated_template):
    return {
        key: val["Properties"]
        for key, val in generated_template["Resources"].items()
        if val["Type"] == "AWS::Logs::MetricFilter"
    }


def _verify_metric_filter_dimensions(metric_filters):
    for name, properties in metric_filters.items():
        dimensions = next(
            property["Dimensions"]
            for property in properties["MetricTransformations"]
            if type(property) is dict and "Dimensions" in property
        )

        expected_dimensions = [{"Key": "ClusterName", "Value": "$.cluster-name"}]

        assert_that(dimensions, description=f"{name} should have dimensions {expected_dimensions}").is_equal_to(
            expected_dimensions
        )


def _verify_head_node_instance_metrics_graphs(output_yaml):
    """Verify CloudWatch graphs within the Head Node Instance Metrics section."""
    assert_that(output_yaml).contains("Head Node Instance Metrics")
    assert_that(output_yaml).contains("CPU Utilization")
    assert_that(output_yaml).contains("Network Packets In/Out")
    assert_that(output_yaml).contains("Network In and Out")
    assert_that(output_yaml).contains("Disk Read/Write Bytes")
    assert_that(output_yaml).contains("Disk Read/Write Ops")
    assert_that(output_yaml).contains("Disk Used Percent")
    assert_that(output_yaml).contains("Memory Used Percent")


def _verify_ec2_metrics_conditions(cluster_config, output_yaml):
    storage_resource = {storage_type: [] for storage_type in SharedStorageType}
    storage_type_title_dict = {
        SharedStorageType.EBS: {"title": "EBS Metrics", "namespace": "AWS/EBS"},
        SharedStorageType.RAID: {"title": "RAID Metrics", "namespace": "AWS/EBS"},
        SharedStorageType.EFS: {"title": "EFS Metrics", "namespace": "AWS/EFS"},
        SharedStorageType.FSX: {"title": "FSx Metrics", "namespace": "AWS/FSx"},
    }

    for storage in cluster_config.shared_storage:
        storage_resource[storage.shared_storage_type].append(storage)

    # Check each section title
    for storage_type, storages in storage_resource.items():
        if len(storages) > 0:
            for field in ["title", "namespace"]:
                assert_that(output_yaml).contains(storage_type_title_dict[storage_type].get(field))
            assert_that(output_yaml).contains("FreeDataStorageCapacity")
            assert_that(output_yaml).contains("StorageCapacity")
            assert_that(output_yaml).contains("UsedStorageCapacity")
            assert_that(output_yaml).contains("Data Read/Write Ops")
            assert_that(output_yaml).contains("Data Read/Write Bytes")
        else:
            assert_that(output_yaml).does_not_contain(storage_type_title_dict[storage_type].get("title"))

    # Conditional EBS and RAID metrics
    ebs_and_raid_storage = storage_resource[SharedStorageType.EBS] + storage_resource[SharedStorageType.RAID]
    if any(storage.volume_type == "io1" for storage in ebs_and_raid_storage):
        assert_that(output_yaml).contains("Consumed Read/Write Ops")
        assert_that(output_yaml).contains("Throughput Percentage")
    else:
        assert_that(output_yaml).does_not_contain("Consumed Read/Write Ops")
        assert_that(output_yaml).does_not_contain("Throughput Percentage")

    burst_balance = any(storage.volume_type in ["gp1", "st1", "sc1"] for storage in ebs_and_raid_storage)
    if burst_balance:
        assert_that(output_yaml).contains("Burst Balance")
    else:
        assert_that(output_yaml).does_not_contain("Burst Balance")

    # conditional EFS metrics
    percent_io_limit = any(
        storage.performance_mode == "generalPurpose" for storage in storage_resource[SharedStorageType.EFS]
    )
    if percent_io_limit:
        assert_that(output_yaml).contains("PercentIOLimit")
    else:
        assert_that(output_yaml).does_not_contain("PercentIOLimit")


def _verify_head_node_logs_conditions(cluster_config, output_yaml):
    """Verify conditions related to the Head Node Logs section."""
    assert_that(output_yaml).contains("Head Node Logs")

    # Conditional Scheduler logs
    scheduler = cluster_config.scheduling.scheduler
    if scheduler == "slurm":
        assert_that(output_yaml).contains("clustermgtd")
        assert_that(output_yaml).contains("slurm_resume")
        assert_that(output_yaml).contains("slurm_suspend")
        assert_that(output_yaml).contains("slurmctld")
    else:  # scheduler == "awsbatch"
        assert_that(output_yaml).does_not_contain("clustermgtd")
        assert_that(output_yaml).does_not_contain("slurm_resume")
        assert_that(output_yaml).does_not_contain("slurm_suspend")
        assert_that(output_yaml).does_not_contain("slurmctld")

    # conditional DCV logs
    if cluster_config.head_node.dcv and cluster_config.head_node.dcv.enabled:
        assert_that(output_yaml).contains("Amazon DCV integration logs")
        assert_that(output_yaml).contains("dcv-ext-authenticator")
        assert_that(output_yaml).contains("dcv-authenticator")
        assert_that(output_yaml).contains("dcv-agent")
        assert_that(output_yaml).contains("dcv-xsession")
        assert_that(output_yaml).contains("dcv-server")
        assert_that(output_yaml).contains("dcv-session-launcher")
        assert_that(output_yaml).contains("Xdcv")
    else:
        assert_that(output_yaml).does_not_contain("Amazon DCV integration logs")

    # Conditional System logs
    if cluster_config.image.os in ["alinux2", "rhel8"]:
        assert_that(output_yaml).contains("system-messages")
        assert_that(output_yaml).does_not_contain("syslog")
    elif cluster_config.image.os in ["ubuntu2004"]:
        assert_that(output_yaml).contains("syslog")
        assert_that(output_yaml).does_not_contain("system-messages")

    assert_that(output_yaml).contains("cfn-init")
    assert_that(output_yaml).contains("chef-client")
    assert_that(output_yaml).contains("cloud-init")
    assert_that(output_yaml).contains("supervisord")


def _verify_common_error_metrics_graphs(cluster_config, output_yaml, region):
    """Verify conditions related to the common error section."""
    scheduler = cluster_config.scheduling.scheduler
    slurm_related_metrics = [
        "IamPolicyErrors",
        "VcpuLimitErrors",
        "VolumeLimitErrors",
        "InsufficientCapacityErrors",
        "OtherInstanceLaunchFailures",
        "InstanceBootstrapTimeoutError",
        "EC2HealthCheckErrors",
        "ScheduledEventHealthCheckErrors",
        "NoCorrespondingInstanceErrors",
        "SlurmNodeNotRespondingErrors",
    ]
    custom_action_metrics = [
        "OnNodeStartDownloadErrors",
        "OnNodeStartRunErrors",
        "OnNodeConfiguredDownloadErrors",
        "OnNodeConfiguredRunErrors",
    ]
    health_check_failure_metrics = ["GpuHealthCheckFailures"]
    idle_node_metrics = ["MaxDynamicNodeIdleTime"]
    if scheduler == "slurm" and is_feature_supported(Feature.CLUSTER_HEALTH_METRICS, region):
        # Contains error metric title
        assert_that(output_yaml).contains("Cluster Health Metrics")
        for metric in slurm_related_metrics:
            assert_that(output_yaml).contains(metric)
        for metric in idle_node_metrics:
            assert_that(output_yaml).contains(metric)
        if cluster_config.has_custom_actions_in_queue:
            for metric in custom_action_metrics:
                assert_that(output_yaml).contains(metric)
        else:
            for metric in custom_action_metrics:
                assert_that(output_yaml).does_not_contain(metric)
        _verify_health_check_failure_metrics(cluster_config, output_yaml, health_check_failure_metrics)
    else:
        assert_that(output_yaml).does_not_contain("Cluster Health Metrics")
        for metric in slurm_related_metrics + custom_action_metrics + idle_node_metrics + health_check_failure_metrics:
            assert_that(output_yaml).does_not_contain(metric)


def _verify_health_check_failure_metrics(cluster_config, output_yaml, health_check_failure_metrics):
    if cluster_config.has_gpu_health_checks_enabled:
        for metric in health_check_failure_metrics:
            assert_that(output_yaml).contains(metric)
    else:
        for metric in health_check_failure_metrics:
            assert_that(output_yaml).does_not_contain(metric)
