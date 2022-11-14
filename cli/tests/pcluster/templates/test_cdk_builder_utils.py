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
from pcluster.templates.cdk_builder_utils import (
    CdkLaunchTemplateBuilder,
    dict_to_cfn_tags,
    get_cluster_tags,
    get_default_volume_tags,
)


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
