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
from pcluster.utils import get_path_n_name_prefix_from_iam_resource_prefix, load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket


@pytest.mark.parametrize(
    "config_file_name",
    [
        "centos7.slurm.full.yaml",
        "alinux2.slurm.conditional_vol.yaml",
        "ubuntu18.slurm.simple.yaml",
        "alinux2.batch.no_head_node_log.yaml",
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
    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)
    print(cluster_config)
    generated_template = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
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


@pytest.mark.parametrize(
    "config_file_name",
    [
        "resourcePrefix.both_path_n_role_prefix.yaml",
        "resourcePrefix.both_path_n_role_prefix_with_s3.yaml",
        "resourcePrefix.no_prefix.yaml",
        "resourcePrefix.only_path_prefix.yaml",
        "resourcePrefix.only_role_prefix.yaml",
    ],
)
def test_iam_resource_prefix_build_in_cdk(mocker, test_datadir, config_file_name):
    """Verify the Path and Role Name for IAM Resources."""
    mock_aws_api(mocker)
    mocker.patch(
        "pcluster.config.cluster_config.HeadNodeNetworking.availability_zone",
        new_callable=PropertyMock(return_value="us-east-1a"),
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)
    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)
    # print("cluster_config",cluster_config)
    generated_template = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    iam_path_prefix, iam_name_prefix = None, None
    if cluster_config.iam and cluster_config.iam.resource_prefix:
        iam_path_prefix, iam_name_prefix = get_path_n_name_prefix_from_iam_resource_prefix(
            cluster_config.iam.resource_prefix
        )

    role_name_ref = generated_template["Resources"]["InstanceProfile15b342af42246b70"]["Properties"]["Roles"][0][
        "Ref"
    ]  # Role15b342af42246b70
    role_name_hn_ref = generated_template["Resources"]["InstanceProfileHeadNode"]["Properties"]["Roles"][0][
        "Ref"
    ]  # RoleHeadNode

    # Checking their Path
    if iam_path_prefix:
        assert_that(iam_path_prefix in generated_template["Resources"][role_name_ref]["Properties"]["Path"]).is_true()
        assert_that(
            iam_path_prefix in generated_template["Resources"][role_name_hn_ref]["Properties"]["Path"]
        ).is_true()
    # Checking their role Name
    if iam_name_prefix:
        assert_that(
            iam_name_prefix in generated_template["Resources"][role_name_ref]["Properties"]["RoleName"]
        ).is_true()
        assert_that(
            iam_name_prefix in generated_template["Resources"][role_name_hn_ref]["Properties"]["RoleName"]
        ).is_true()
    else:
        assert_that(generated_template["Resources"][role_name_ref]["Properties"]).does_not_contain_key("RoleName")
        assert_that(generated_template["Resources"][role_name_hn_ref]["Properties"]).does_not_contain_key("RoleName")

    # Instance Profiles---> Checking Instance Profile Names and Instance profiles Path
    _check_instance_profiles(generated_template, iam_path_prefix, iam_name_prefix)
    # PC Policies
    _check_parallel_cluster_policies(generated_template, role_name_ref, role_name_hn_ref, iam_name_prefix)
    #  Slurm Policies
    _check_slurm_policies(generated_template, iam_name_prefix, role_name_ref, role_name_hn_ref)
    #     CleanupResources
    _check_cleanup_role(
        generated_template,
        iam_name_prefix,
        iam_path_prefix,
        "CleanupResourcesRole",
        "CleanupResourcesFunctionExecutionRole",
    )
    #     CleanupRoute53FunctionExecutionRole
    _check_cleanup_role(
        generated_template,
        iam_name_prefix,
        iam_path_prefix,
        "CleanupRoute53Role",
        "CleanupRoute53FunctionExecutionRole",
    )
    # S3AccessPolicies
    _check_s3_access_policies(cluster_config, generated_template, iam_name_prefix)


def _check_instance_profiles(generated_template, iam_path_prefix, iam_name_prefix):
    """Verify the Path and Role Name for instance Profiles on Head Node and Queue."""
    if iam_path_prefix:
        assert_that(
            iam_path_prefix in generated_template["Resources"]["InstanceProfileHeadNode"]["Properties"]["Path"]
        ).is_true()
    else:
        assert_that(
            "/parallelcluster/clustername/"
            in generated_template["Resources"]["InstanceProfileHeadNode"]["Properties"]["Path"]
        ).is_true()

    if iam_name_prefix:
        assert_that(
            iam_name_prefix
            in generated_template["Resources"]["InstanceProfileHeadNode"]["Properties"]["InstanceProfileName"]
        ).is_true()
    else:
        assert_that(generated_template["Resources"]["InstanceProfileHeadNode"]["Properties"]).does_not_contain_key(
            "InstanceProfileName"
        )

    assert_that(
        "RoleHeadNode" in generated_template["Resources"]["InstanceProfileHeadNode"]["Properties"]["Roles"][0]["Ref"]
    ).is_true()

    if iam_path_prefix:
        assert_that(
            iam_path_prefix in generated_template["Resources"]["InstanceProfile15b342af42246b70"]["Properties"]["Path"]
        ).is_true()
    else:
        assert_that(
            "/parallelcluster/clustername/"
            in generated_template["Resources"]["InstanceProfile15b342af42246b70"]["Properties"]["Path"]
        ).is_true()

    if iam_name_prefix:
        assert_that(
            iam_name_prefix
            in generated_template["Resources"]["InstanceProfile15b342af42246b70"]["Properties"]["InstanceProfileName"]
        ).is_true()
    else:
        assert_that(
            generated_template["Resources"]["InstanceProfile15b342af42246b70"]["Properties"]
        ).does_not_contain_key("InstanceProfileName")

    assert_that(
        "Role15b342af42246b70"
        in generated_template["Resources"]["InstanceProfile15b342af42246b70"]["Properties"]["Roles"][0]["Ref"]
    ).is_true()


def _check_parallel_cluster_policies(generated_template, role_name_ref, role_name_hn_ref, iam_name_prefix):
    """Verify the Path and Role Name for Parallel Cluster Policies on Head Node and Queue."""
    assert_that(
        role_name_ref
        in generated_template["Resources"]["ParallelClusterPolicies15b342af42246b70"]["Properties"]["Roles"][0]["Ref"]
    ).is_true()
    if iam_name_prefix:
        assert_that(
            iam_name_prefix
            in generated_template["Resources"]["ParallelClusterPolicies15b342af42246b70"]["Properties"]["PolicyName"]
        ).is_true()
    else:
        assert_that(
            "parallelcluster"
            in generated_template["Resources"]["ParallelClusterPolicies15b342af42246b70"]["Properties"]["PolicyName"]
        ).is_true()

    assert_that(
        role_name_hn_ref
        in generated_template["Resources"]["ParallelClusterPoliciesHeadNode"]["Properties"]["Roles"][0]["Ref"]
    ).is_true()
    if iam_name_prefix:
        assert_that(
            iam_name_prefix
            in generated_template["Resources"]["ParallelClusterPoliciesHeadNode"]["Properties"]["PolicyName"]
        ).is_true()
    else:
        assert_that(
            "parallelcluster"
            in generated_template["Resources"]["ParallelClusterPoliciesHeadNode"]["Properties"]["PolicyName"]
        ).is_true()

    assert_that(
        role_name_hn_ref
        in generated_template["Resources"]["ParallelClusterSlurmRoute53Policies"]["Properties"]["Roles"][0]["Ref"]
    ).is_true()
    if iam_name_prefix:
        assert_that(
            iam_name_prefix
            in generated_template["Resources"]["ParallelClusterSlurmRoute53Policies"]["Properties"]["PolicyName"]
        ).is_true()
    else:
        assert_that(
            "parallelcluster-slurm-route53"
            in generated_template["Resources"]["ParallelClusterSlurmRoute53Policies"]["Properties"]["PolicyName"]
        ).is_true()


def _check_slurm_policies(generated_template, iam_name_prefix, role_name_ref, role_name_hn_ref):
    """Verify the Path and Role Name for Slurm Policies on Head Node and Queue."""
    assert_that(
        role_name_ref
        in generated_template["Resources"]["SlurmPolicies15b342af42246b70"]["Properties"]["Roles"][0]["Ref"]
    ).is_true()
    if iam_name_prefix:
        assert_that(
            iam_name_prefix
            in generated_template["Resources"]["SlurmPolicies15b342af42246b70"]["Properties"]["PolicyName"]
        ).is_true()
    else:
        assert_that(
            "parallelcluster-slurm-compute"
            in generated_template["Resources"]["SlurmPolicies15b342af42246b70"]["Properties"]["PolicyName"]
        ).is_true()

    assert_that(
        role_name_hn_ref in generated_template["Resources"]["SlurmPoliciesHeadNode"]["Properties"]["Roles"][0]["Ref"]
    ).is_true()
    if iam_name_prefix:
        assert_that(
            iam_name_prefix in generated_template["Resources"]["SlurmPoliciesHeadNode"]["Properties"]["PolicyName"]
        ).is_true()
    else:
        assert_that(
            "parallelcluster-slurm-head-node"
            in generated_template["Resources"]["SlurmPoliciesHeadNode"]["Properties"]["PolicyName"]
        ).is_true()


def _check_cleanup_role(generated_template, iam_name_prefix, iam_path_prefix, cleanupresourcenew, cleanupresourceold):
    """Verify the Path and Role Name for Cleanup Lambda Role."""
    if iam_name_prefix and iam_path_prefix:
        assert_that(
            iam_path_prefix in generated_template["Resources"][cleanupresourcenew]["Properties"]["Path"]
        ).is_true()
    elif iam_path_prefix:
        assert_that(
            iam_path_prefix in generated_template["Resources"][cleanupresourceold]["Properties"]["Path"]
        ).is_true()
    elif iam_name_prefix:
        assert_that(
            "/parallelcluster/" in generated_template["Resources"][cleanupresourcenew]["Properties"]["Path"]
        ).is_true()
    else:
        assert_that(
            "/parallelcluster/" in generated_template["Resources"][cleanupresourceold]["Properties"]["Path"]
        ).is_true()

    if iam_name_prefix:
        assert_that(
            iam_name_prefix in generated_template["Resources"][cleanupresourcenew]["Properties"]["RoleName"]
        ).is_true()
    else:
        assert_that(generated_template["Resources"][cleanupresourceold]["Properties"]).does_not_contain_key("RoleName")


def _check_s3_access_policies(cluster_config, generated_template, iam_name_prefix):
    """Verify S3 Policies attached to Head Node or Queue Role."""
    if cluster_config.head_node and cluster_config.head_node.iam and cluster_config.head_node.iam.s3_access:
        if iam_name_prefix:
            assert_that(
                iam_name_prefix
                in generated_template["Resources"]["S3AccessPoliciesHeadNode"]["Properties"]["PolicyName"]
            ).is_true()
        else:
            assert_that(
                "S3Access" in generated_template["Resources"]["S3AccessPoliciesHeadNode"]["Properties"]["PolicyName"]
            ).is_true()

    if (
        cluster_config.scheduling
        and cluster_config.scheduling.queues[0]
        and cluster_config.scheduling.queues[0].iam
        and cluster_config.scheduling.queues[0].iam.s3_access
    ):
        if iam_name_prefix:
            assert_that(
                iam_name_prefix
                in generated_template["Resources"]["S3AccessPolicies15b342af42246b70"]["Properties"]["PolicyName"]
            ).is_true()
        else:
            assert_that(
                "S3Access"
                in generated_template["Resources"]["S3AccessPolicies15b342af42246b70"]["Properties"]["PolicyName"]
            ).is_true()
