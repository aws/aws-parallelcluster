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

import pytest
from assertpy import assert_that

from pcluster.config.cluster_config import (
    CapacityReservationTarget,
    HeadNode,
    HeadNodeNetworking,
    Image,
    SlurmClusterConfig,
    SlurmComputeResource,
    SlurmQueue,
    SlurmQueueNetworking,
    SlurmScheduling,
)
from tests.pcluster.aws.dummy_aws_api import mock_aws_api


class TestUltraserverCapacityBlocks:
    """Test ultraserver capacity block functionality."""

    @pytest.mark.parametrize(
        "compute_resources, expected_dict",
        [
            # No capacity reservations
            (
                [SlurmComputeResource(name="cr1", instance_type="c5.large")],
                {"p6e-gb200": []},
            ),
            # Non-ultraserver capacity reservation
            (
                [
                    SlurmComputeResource(
                        name="cr1",
                        instance_type="c5.large",
                        capacity_reservation_target=CapacityReservationTarget(capacity_reservation_id="cr-123"),
                    )
                ],
                {"p6e-gb200": []},
            ),
            # Single p6e-gb200 capacity block
            (
                [
                    SlurmComputeResource(
                        name="cr1",
                        instance_type="p6e-gb200.36xlarge",
                        capacity_reservation_target=CapacityReservationTarget(capacity_reservation_id="cr-p6e-123"),
                    )
                ],
                {"p6e-gb200": ["cr-p6e-123"]},
            ),
            # Multiple p6e-gb200 capacity blocks
            (
                [
                    SlurmComputeResource(
                        name="cr1",
                        instance_type="p6e-gb200.36xlarge",
                        capacity_reservation_target=CapacityReservationTarget(capacity_reservation_id="cr-p6e-123"),
                    ),
                    SlurmComputeResource(
                        name="cr2",
                        instance_type="p6e-gb200.36xlarge",
                        capacity_reservation_target=CapacityReservationTarget(capacity_reservation_id="cr-p6e-456"),
                    ),
                ],
                {"p6e-gb200": ["cr-p6e-123", "cr-p6e-456"]},
            ),
            # Mixed capacity reservations
            (
                [
                    SlurmComputeResource(
                        name="cr1",
                        instance_type="c5.large",
                        capacity_reservation_target=CapacityReservationTarget(capacity_reservation_id="cr-regular"),
                    ),
                    SlurmComputeResource(
                        name="cr2",
                        instance_type="p6e-gb200.36xlarge",
                        capacity_reservation_target=CapacityReservationTarget(capacity_reservation_id="cr-p6e-123"),
                    ),
                ],
                {"p6e-gb200": ["cr-p6e-123"]},
            ),
        ],
    )
    def test_ultraserver_capacity_block_dict(self, mocker, compute_resources, expected_dict):
        """Test ultraserver_capacity_block_dict property returns correct capacity reservation mapping."""
        mock_aws_api(mocker)

        # Mock describe_capacity_reservations to avoid AWS API calls
        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.describe_capacity_reservations",
            return_value=[],
        )

        # Mock the utility function to return appropriate values
        def mock_get_instance_type_and_reservation_type(cr_id):
            if cr_id.startswith("cr-p6e"):
                return "p6e-gb200.36xlarge", "capacity-block"
            else:
                return "c5.large", "ondemand"

        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.get_instance_type_and_reservation_type_from_capacity_reservation",
            side_effect=mock_get_instance_type_and_reservation_type,
        )

        # Create the scheduling object
        queue = SlurmQueue(
            name="queue1",
            compute_resources=compute_resources,
            networking=SlurmQueueNetworking(subnet_ids=["subnet-12345"]),
        )
        scheduling = SlurmScheduling(queues=[queue])

        # Create cluster config
        cluster_config = SlurmClusterConfig(
            cluster_name="test-cluster",
            image=Image(os="alinux2023"),
            head_node=HeadNode(
                instance_type="t3.micro",
                networking=HeadNodeNetworking(subnet_id="subnet-12345"),
            ),
            scheduling=scheduling,
        )

        # Test the property
        result = cluster_config.ultraserver_capacity_block_dict
        assert_that(result).is_equal_to(expected_dict)

    def test_ultraserver_capacity_block_dict_queue_level_reservation(self, mocker):
        """Test ultraserver_capacity_block_dict with queue-level capacity reservation."""
        mock_aws_api(mocker)

        # Mock describe_capacity_reservations to avoid AWS API calls
        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.describe_capacity_reservations",
            return_value=[],
        )

        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.get_instance_type_and_reservation_type_from_capacity_reservation",
            return_value=("p6e-gb200.36xlarge", "capacity-block"),
        )

        # Create compute resource without capacity reservation
        compute_resource = SlurmComputeResource(
            name="cr1",
            instance_type="p6e-gb200.36xlarge",
        )

        # Create the scheduling object with queue-level capacity reservation
        queue = SlurmQueue(
            name="queue1",
            compute_resources=[compute_resource],
            networking=SlurmQueueNetworking(subnet_ids=["subnet-12345"]),
            capacity_reservation_target=CapacityReservationTarget(capacity_reservation_id="cr-queue-level"),
        )
        scheduling = SlurmScheduling(queues=[queue])

        # Create cluster config
        cluster_config = SlurmClusterConfig(
            cluster_name="test-cluster",
            image=Image(os="alinux2023"),
            head_node=HeadNode(
                instance_type="t3.micro",
                networking=HeadNodeNetworking(subnet_id="subnet-12345"),
            ),
            scheduling=scheduling,
        )

        result = cluster_config.ultraserver_capacity_block_dict
        assert_that(result).is_equal_to({"p6e-gb200": ["cr-queue-level"]})
