# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from assertpy import assert_that
from aws_cdk import aws_ec2 as ec2
from aws_cdk.core import CfnTag

from pcluster.config.cluster_config import (
    BaseQueue,
    CapacityReservationTarget,
    RootVolume,
    SlurmComputeResource,
    SlurmQueue,
)
from pcluster.constants import PCLUSTER_CLUSTER_NAME_TAG, PCLUSTER_NODE_TYPE_TAG
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.templates.cdk_builder_utils import (
    CdkLaunchTemplateBuilder,
    dict_to_cfn_tags,
    get_cluster_tags,
    get_default_volume_tags,
)
from pcluster.utils import load_yaml_dict, split_resource_prefix
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket, mock_bucket_object_utils
from tests.pcluster.utils import get_asset_content_with_resource_name


@pytest.mark.parametrize(
    "tags_dict, expected_result",
    [
        ({}, []),
        ({"key1": "value1"}, [CfnTag(key="key1", value="value1")]),
        (
            {"key1": "value1", "key2": "value2"},
            [CfnTag(key="key1", value="value1"), CfnTag(key="key2", value="value2")],
        ),
    ],
)
def test_dict_to_cfn_tags(tags_dict, expected_result):
    """Verify that dict to CfnTag conversion works as expected."""
    assert_that(dict_to_cfn_tags(tags_dict)).is_equal_to(expected_result)


@pytest.mark.parametrize(
    "stack_name, raw_dict, expected_result",
    [
        ("STACK_NAME", True, {PCLUSTER_CLUSTER_NAME_TAG: "STACK_NAME"}),
        ("STACK_NAME", False, [CfnTag(key=PCLUSTER_CLUSTER_NAME_TAG, value="STACK_NAME")]),
    ],
)
def test_get_cluster_tags(stack_name, raw_dict, expected_result):
    """Verify cluster tags."""
    assert_that(get_cluster_tags(stack_name, raw_dict)).is_equal_to(expected_result)


@pytest.mark.parametrize(
    "stack_name, node_type, raw_dict, expected_result",
    [
        ("STACK_NAME", "HeadNode", True, {PCLUSTER_CLUSTER_NAME_TAG: "STACK_NAME", PCLUSTER_NODE_TYPE_TAG: "HeadNode"}),
        ("STACK_NAME", "Compute", True, {PCLUSTER_CLUSTER_NAME_TAG: "STACK_NAME", PCLUSTER_NODE_TYPE_TAG: "Compute"}),
        (
            "STACK_NAME",
            "HeadNode",
            False,
            [
                CfnTag(key=PCLUSTER_CLUSTER_NAME_TAG, value="STACK_NAME"),
                CfnTag(key=PCLUSTER_NODE_TYPE_TAG, value="HeadNode"),
            ],
        ),
        (
            "STACK_NAME",
            "Compute",
            False,
            [
                CfnTag(key=PCLUSTER_CLUSTER_NAME_TAG, value="STACK_NAME"),
                CfnTag(key=PCLUSTER_NODE_TYPE_TAG, value="Compute"),
            ],
        ),
    ],
)
def test_get_default_volume_tags(stack_name, node_type, raw_dict, expected_result):
    """Verify default volume tags."""
    assert_that(get_default_volume_tags(stack_name, node_type, raw_dict)).is_equal_to(expected_result)


class TestCdkLaunchTemplateBuilder:
    @pytest.mark.parametrize(
        "root_volume, image_os, expected_response",
        [
            pytest.param(
                RootVolume(
                    size=10,
                    encrypted=False,
                    volume_type="mockVolumeType",
                    iops=13,
                    throughput=30,
                    delete_on_termination=False,
                ),
                "centos7",
                [
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdba", virtual_name="ephemeral0"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbb", virtual_name="ephemeral1"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbc", virtual_name="ephemeral2"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbd", virtual_name="ephemeral3"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbe", virtual_name="ephemeral4"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbf", virtual_name="ephemeral5"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbg", virtual_name="ephemeral6"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbh", virtual_name="ephemeral7"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbi", virtual_name="ephemeral8"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbj", virtual_name="ephemeral9"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbk", virtual_name="ephemeral10"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbl", virtual_name="ephemeral11"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbm", virtual_name="ephemeral12"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbn", virtual_name="ephemeral13"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbo", virtual_name="ephemeral14"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbp", virtual_name="ephemeral15"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbq", virtual_name="ephemeral16"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbr", virtual_name="ephemeral17"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbs", virtual_name="ephemeral18"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbt", virtual_name="ephemeral19"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbu", virtual_name="ephemeral20"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbv", virtual_name="ephemeral21"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbw", virtual_name="ephemeral22"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbx", virtual_name="ephemeral23"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/sda1",
                        ebs=ec2.CfnLaunchTemplate.EbsProperty(
                            volume_size=10,
                            encrypted=False,
                            volume_type="mockVolumeType",
                            iops=13,
                            throughput=30,
                            delete_on_termination=False,
                        ),
                    ),
                ],
                id="test with all root volume fields populated",
            ),
            pytest.param(
                RootVolume(
                    encrypted=True,
                    volume_type="mockVolumeType",
                    iops=15,
                    throughput=20,
                    delete_on_termination=True,
                ),
                "alinux2",
                [
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdba", virtual_name="ephemeral0"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbb", virtual_name="ephemeral1"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbc", virtual_name="ephemeral2"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbd", virtual_name="ephemeral3"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbe", virtual_name="ephemeral4"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbf", virtual_name="ephemeral5"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbg", virtual_name="ephemeral6"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbh", virtual_name="ephemeral7"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbi", virtual_name="ephemeral8"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbj", virtual_name="ephemeral9"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbk", virtual_name="ephemeral10"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbl", virtual_name="ephemeral11"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbm", virtual_name="ephemeral12"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbn", virtual_name="ephemeral13"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbo", virtual_name="ephemeral14"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbp", virtual_name="ephemeral15"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbq", virtual_name="ephemeral16"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbr", virtual_name="ephemeral17"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbs", virtual_name="ephemeral18"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbt", virtual_name="ephemeral19"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbu", virtual_name="ephemeral20"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbv", virtual_name="ephemeral21"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbw", virtual_name="ephemeral22"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvdbx", virtual_name="ephemeral23"
                    ),
                    ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                        device_name="/dev/xvda",
                        ebs=ec2.CfnLaunchTemplate.EbsProperty(
                            volume_size=None,
                            encrypted=True,
                            volume_type="mockVolumeType",
                            iops=15,
                            throughput=20,
                            delete_on_termination=True,
                        ),
                    ),
                ],
                id="test with missing volume size",
            ),
        ],
    )
    def test_get_block_device_mappings(self, root_volume, image_os, expected_response):
        assert_that(CdkLaunchTemplateBuilder().get_block_device_mappings(root_volume, image_os)).is_equal_to(
            expected_response
        )

    @pytest.mark.parametrize(
        "queue, compute_resource, expected_response",
        [
            pytest.param(
                BaseQueue(name="queue1", capacity_type="spot"),
                SlurmComputeResource(name="compute1", instance_type="t2.medium", spot_price=10.0),
                ec2.CfnLaunchTemplate.InstanceMarketOptionsProperty(
                    market_type="spot",
                    spot_options=ec2.CfnLaunchTemplate.SpotOptionsProperty(
                        spot_instance_type="one-time", instance_interruption_behavior="terminate", max_price="10.0"
                    ),
                ),
                id="test with spot capacity",
            ),
            pytest.param(
                BaseQueue(name="queue2", capacity_type="spot"),
                SlurmComputeResource(name="compute2", instance_type="t2.medium"),
                ec2.CfnLaunchTemplate.InstanceMarketOptionsProperty(
                    market_type="spot",
                    spot_options=ec2.CfnLaunchTemplate.SpotOptionsProperty(
                        spot_instance_type="one-time", instance_interruption_behavior="terminate", max_price=None
                    ),
                ),
                id="test with spot capacity but no spot price",
            ),
            pytest.param(
                BaseQueue(name="queue2", capacity_type="ondemand"),
                SlurmComputeResource(name="compute2", instance_type="t2.medium", spot_price="10.0"),
                None,
                id="test without spot capacity",
            ),
        ],
    )
    def test_get_instance_market_options(self, queue, compute_resource, expected_response):
        assert_that(CdkLaunchTemplateBuilder().get_instance_market_options(queue, compute_resource)).is_equal_to(
            expected_response
        )

    @pytest.mark.parametrize(
        "queue, compute_resource, expected_response",
        [
            pytest.param(
                SlurmQueue(
                    name="queue1",
                    capacity_reservation_target=CapacityReservationTarget(
                        capacity_reservation_resource_group_arn="queue_cr_rg_arn",
                    ),
                    compute_resources=[],
                    networking=None,
                ),
                SlurmComputeResource(
                    name="compute1",
                    instance_type="t2.medium",
                    capacity_reservation_target=CapacityReservationTarget(
                        capacity_reservation_resource_group_arn="comp_res_cr_rg_arn",
                    ),
                ),
                ec2.CfnLaunchTemplate.CapacityReservationSpecificationProperty(
                    capacity_reservation_target=ec2.CfnLaunchTemplate.CapacityReservationTargetProperty(
                        capacity_reservation_id=None,
                        capacity_reservation_resource_group_arn="comp_res_cr_rg_arn",
                    )
                ),
                id="test with queue and compute resource capacity reservation",
            ),
            pytest.param(
                SlurmQueue(
                    name="queue1",
                    capacity_reservation_target=CapacityReservationTarget(
                        capacity_reservation_id="queue_cr_id",
                    ),
                    compute_resources=[],
                    networking=None,
                ),
                SlurmComputeResource(
                    name="compute1",
                    instance_type="t2.medium",
                ),
                ec2.CfnLaunchTemplate.CapacityReservationSpecificationProperty(
                    capacity_reservation_target=ec2.CfnLaunchTemplate.CapacityReservationTargetProperty(
                        capacity_reservation_id="queue_cr_id",
                        capacity_reservation_resource_group_arn=None,
                    )
                ),
                id="test with only queue capacity reservation",
            ),
            pytest.param(
                SlurmQueue(
                    name="queue1",
                    compute_resources=[],
                    networking=None,
                ),
                SlurmComputeResource(
                    name="compute1",
                    instance_type="t2.medium",
                ),
                None,
                id="test with no capacity reservation",
            ),
        ],
    )
    def test_get_capacity_reservation(self, queue, compute_resource, expected_response):
        assert_that(CdkLaunchTemplateBuilder().get_capacity_reservation(queue, compute_resource)).is_equal_to(
            expected_response
        )


def _check_policy_statement(list_policy_statement, iam_path, cluster_name):
    for statement in list_policy_statement:
        for key, value in statement.items():
            if key == "Sid" and value == "PassRole":
                if iam_path:
                    assert_that(
                        ":role" + iam_path + cluster_name + "/*" in statement["Resource"]["Fn::Join"][1]
                    ).is_true()
                else:
                    assert_that(
                        ":role/parallelcluster/" + cluster_name + "/*" in statement["Resource"]["Fn::Join"][1]
                    ).is_true()


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
    mock_bucket_object_utils(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)
    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)
    generated_template, cdk_assets = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    iam_path_prefix, iam_name_prefix = None, None
    if cluster_config.iam and cluster_config.iam.resource_prefix:
        iam_path_prefix, iam_name_prefix = split_resource_prefix(cluster_config.iam.resource_prefix)
    generated_template = generated_template["Resources"]
    asset_resource = get_asset_content_with_resource_name(cdk_assets, "InstanceProfile15b342af42246b70").get(
        "Resources"
    )
    role_name_ref = asset_resource["InstanceProfile15b342af42246b70"]["Properties"]["Roles"][0][
        "Ref"
    ]  # Role15b342af42246b70
    role_name_hn_ref = generated_template["InstanceProfileHeadNode"]["Properties"]["Roles"][0]["Ref"]  # RoleHeadNode

    # Checking their Path
    _check_instance_roles_n_profiles(asset_resource, iam_path_prefix, iam_name_prefix, role_name_ref, "RoleName")
    _check_instance_roles_n_profiles(generated_template, iam_path_prefix, iam_name_prefix, role_name_hn_ref, "RoleName")

    # Instance Profiles---> Checking Instance Profile Names and Instance profiles Path
    _check_instance_roles_n_profiles(
        generated_template, iam_path_prefix, iam_name_prefix, "InstanceProfileHeadNode", "InstanceProfileName"
    )
    _check_instance_roles_n_profiles(
        asset_resource, iam_path_prefix, iam_name_prefix, "InstanceProfile15b342af42246b70", "InstanceProfileName"
    )
    # PC Policies
    _check_policies(
        asset_resource, iam_name_prefix, "ParallelClusterPolicies15b342af42246b70", "parallelcluster", role_name_ref
    )
    _check_policies(
        generated_template, iam_name_prefix, "ParallelClusterPoliciesHeadNode", "parallelcluster", role_name_hn_ref
    )

    # ParallelClusterPoliciesHeadNode has an inline Policy for PassRole where the path is generated
    _check_policy_statement(
        generated_template["ParallelClusterPoliciesHeadNode"]["Properties"]["PolicyDocument"]["Statement"],
        iam_path_prefix,
        cluster_config.cluster_name,
    )

    _check_policies(
        generated_template,
        iam_name_prefix,
        "ParallelClusterSlurmRoute53Policies",
        "parallelcluster-slurm-route53",
        role_name_hn_ref,
    )
    #  Slurm Policies
    _check_policies(
        asset_resource,
        iam_name_prefix,
        "SlurmPolicies15b342af42246b70",
        "parallelcluster-slurm-compute",
        role_name_ref,
    )
    _check_policies(
        generated_template,
        iam_name_prefix,
        "SlurmPoliciesHeadNode",
        "parallelcluster-slurm-head-node",
        role_name_hn_ref,
    )

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
    if cluster_config.head_node and cluster_config.head_node.iam and cluster_config.head_node.iam.s3_access:
        _check_policies(generated_template, iam_name_prefix, "S3AccessPoliciesHeadNode", "S3Access", role_name_hn_ref)
    if (
        cluster_config.scheduling
        and cluster_config.scheduling.queues[0]
        and cluster_config.scheduling.queues[0].iam
        and cluster_config.scheduling.queues[0].iam.s3_access
    ):
        _check_policies(asset_resource, iam_name_prefix, "S3AccessPolicies15b342af42246b70", "S3Access", role_name_ref)


def _check_instance_roles_n_profiles(generated_template, iam_path_prefix, iam_name_prefix, resource_name, key_name):
    """Verify the Path and Key Name(RoleName or ProfileName) for instance Profiles and Roles on Head Node and Queue."""
    if iam_path_prefix:
        assert_that(iam_path_prefix in generated_template[resource_name]["Properties"]["Path"]).is_true()
    else:
        assert_that(
            "/parallelcluster/clustername/" in generated_template[resource_name]["Properties"]["Path"]
        ).is_true()

    if iam_name_prefix:
        assert_that(iam_name_prefix in generated_template[resource_name]["Properties"][key_name]).is_true()
    else:
        assert_that(generated_template[resource_name]["Properties"]).does_not_contain_key(key_name)


def _check_policies(generated_template, iam_name_prefix, resource_name, policy_name, role_name):
    """Verify the Policy Name and Role Name for Policies on Head Node and Queue."""
    assert_that(role_name in generated_template[resource_name]["Properties"]["Roles"][0]["Ref"]).is_true()
    if iam_name_prefix:
        assert_that(iam_name_prefix in generated_template[resource_name]["Properties"]["PolicyName"]).is_true()
    else:
        assert_that(policy_name in generated_template[resource_name]["Properties"]["PolicyName"]).is_true()


def _check_cleanup_role(
    generated_template, iam_name_prefix, iam_path_prefix, cleanup_resource_new, cleanup_resource_old
):
    """Verify the Path and Role Name for Cleanup Lambda Role."""
    if iam_name_prefix and iam_path_prefix:
        assert_that(iam_path_prefix in generated_template[cleanup_resource_new]["Properties"]["Path"]).is_true()

        assert_that(iam_name_prefix in generated_template[cleanup_resource_new]["Properties"]["RoleName"]).is_true()

    elif iam_path_prefix:
        assert_that(iam_path_prefix in generated_template[cleanup_resource_old]["Properties"]["Path"]).is_true()
    elif iam_name_prefix:
        assert_that(iam_name_prefix in generated_template[cleanup_resource_new]["Properties"]["RoleName"]).is_true()

        assert_that("/parallelcluster/" in generated_template[cleanup_resource_new]["Properties"]["Path"]).is_true()
    else:
        assert_that("/parallelcluster/" in generated_template[cleanup_resource_old]["Properties"]["Path"]).is_true()

        assert_that(generated_template[cleanup_resource_old]["Properties"]).does_not_contain_key("RoleName")
