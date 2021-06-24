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
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket


@pytest.mark.parametrize(
    "config_file_name",
    [
        "centos7.slurm.full.yaml",
        "alinux2.slurm.conditional_vol.yaml",
        "ubuntu18.slurm.simple.yaml",
        "alinux2.batch.no_headnode_log.yaml",
        "ubuntu18.slurm.no_dashboard.yaml",
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

    input_yaml = load_yaml_dict(test_datadir / config_file_name)
    cluster_config = ClusterSchema().load(input_yaml)
    print(cluster_config)
    generated_template = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="parallelcluster-dummyname"
    )
    output_yaml = yaml.dump(generated_template, width=float("inf"))
    print(output_yaml)

    if cluster_config.is_cw_dashboard_enabled:
        if cluster_config.shared_storage:
            _verify_ec2_metrics_conditions(cluster_config, output_yaml)

        if cluster_config.is_cw_logging_enabled:
            _verify_head_node_logs_conditions(cluster_config, output_yaml)
        else:
            assert_that(output_yaml).does_not_contain("Head Node Logs")


def _verify_ec2_metrics_conditions(cluster_config, output_yaml):
    storage_resource = {storage_type: [] for storage_type in SharedStorageType}
    storage_type_title_dict = {
        SharedStorageType.EBS: "EBS Metrics",
        SharedStorageType.RAID: "RAID Metrics",
        SharedStorageType.EFS: "EFS Metrics",
        SharedStorageType.FSX: "FSx Metrics",
    }

    for storage in cluster_config.shared_storage:
        storage_resource[storage.shared_storage_type].append(storage)

    # Check each section title
    for storage_type, storages in storage_resource.items():
        if len(storages) > 0:
            assert_that(output_yaml).contains(storage_type_title_dict[storage_type])
        else:
            assert_that(output_yaml).does_not_contain(storage_type_title_dict[storage_type])

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
    if cluster_config.image.os in ["alinux2", "centos7"]:
        assert_that(output_yaml).contains("system-messages")
        assert_that(output_yaml).does_not_contain("syslog")
    elif cluster_config.image.os in ["ubuntu1804"]:
        assert_that(output_yaml).contains("syslog")
        assert_that(output_yaml).does_not_contain("system-messages")

    assert_that(output_yaml).contains("cfn-init")
    assert_that(output_yaml).contains("chef-client")
    assert_that(output_yaml).contains("cloud-init")
    assert_that(output_yaml).contains("supervisord")
