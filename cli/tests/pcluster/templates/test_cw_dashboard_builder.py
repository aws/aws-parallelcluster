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
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket, mock_bucket_object_utils


@pytest.mark.parametrize(
    "config_file_name",
    [
        "centos7.slurm.full.yaml",
        "rhel8.slurm.full.yaml",
        "alinux2.slurm.conditional_vol.yaml",
        "ubuntu18.slurm.simple.yaml",
        "alinux2.batch.no_head_node_log.yaml",
        "ubuntu18.slurm.no_dashboard.yaml",
        "alinux2.batch.head_node_log.yaml",
    ],
)
def test_cw_dashboard_builder(mocker, test_datadir, config_file_name):
    mock_aws_api(mocker)
    mocker.patch(
        "pcluster.config.cluster_config.HeadNodeNetworking.availability_zone",
        new_callable=PropertyMock(return_value="us-east-1a"),
    )
    # mock bucket initialization parameters
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

        if cluster_config.shared_storage:
            _verify_ec2_metrics_conditions(cluster_config, output_yaml)

        if cluster_config.is_cw_logging_enabled:
            _verify_head_node_logs_conditions(cluster_config, output_yaml)
            _verify_common_error_metrics_graphs(cluster_config, output_yaml)
        else:
            assert_that(output_yaml).does_not_contain("Head Node Logs")
            assert_that(output_yaml).does_not_contain("Cluster Health Metrics")
    else:
        assert_that(output_yaml).does_not_contain("CloudwatchDashboard")
        assert_that(output_yaml).does_not_contain("Head Node EC2 Metrics")


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
        assert_that(output_yaml).contains("NICE DCV integration logs")
        assert_that(output_yaml).contains("dcv-ext-authenticator")
        assert_that(output_yaml).contains("dcv-authenticator")
        assert_that(output_yaml).contains("dcv-agent")
        assert_that(output_yaml).contains("dcv-xsession")
        assert_that(output_yaml).contains("dcv-server")
        assert_that(output_yaml).contains("dcv-session-launcher")
        assert_that(output_yaml).contains("Xdcv")
    else:
        assert_that(output_yaml).does_not_contain("NICE DCV integration logs")

    # Conditional System logs
    if cluster_config.image.os in ["alinux2", "centos7", "rhel8"]:
        assert_that(output_yaml).contains("system-messages")
        assert_that(output_yaml).does_not_contain("syslog")
    elif cluster_config.image.os in ["ubuntu1804"]:
        assert_that(output_yaml).contains("syslog")
        assert_that(output_yaml).does_not_contain("system-messages")

    assert_that(output_yaml).contains("cfn-init")
    assert_that(output_yaml).contains("chef-client")
    assert_that(output_yaml).contains("cloud-init")
    assert_that(output_yaml).contains("supervisord")


def _verify_common_error_metrics_graphs(cluster_config, output_yaml):
    """Verify conditions related to the common error section."""
    scheduler = cluster_config.scheduling.scheduler
    slurm_related_metrics = [
        "IamPolicyErrors",
        "VcpuLimit",
        "VolumeLimit",
        "NodeCapacityInsufficient",
        "OtherLaunchedInstanceFailures",
        "ReplacementTimeoutExpires",
        "ResumeTimeoutExpires",
        "EC2MaintenanceEvent",
        "EC2ScheduledMaintenanceEvent",
        "NoCorrespondingInstanceForNode",
        "SlurmNodeNotResponding",
    ]
    if scheduler == "slurm":
        # Contains error metric title
        assert_that(output_yaml).contains("Cluster Health Metrics")
        for metric in slurm_related_metrics:
            assert_that(output_yaml).contains(metric)
        if cluster_config.has_custom_actions_in_queue:
            assert_that(output_yaml).contains("CannotRetrieveCustomScript")
            assert_that(output_yaml).contains("ErrorWithCustomScript")
        else:
            assert_that(output_yaml).does_not_contain("CannotRetrieveCustomScript")
            assert_that(output_yaml).does_not_contain("ErrorWithCustomScript")
    else:
        for metric in slurm_related_metrics:
            assert_that(output_yaml).does_not_contain(metric)
            assert_that(output_yaml).does_not_contain("Cluster Health Metrics")
            assert_that(output_yaml).does_not_contain("CannotRetrieveCustomScript")
            assert_that(output_yaml).does_not_contain("ErrorWithCustomScript")
