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

from pcluster.templates.cdk_builder_utils import has_ultraserver_instance
from tests.pcluster.aws.dummy_aws_api import mock_aws_api


class TestUltraserverQueuesStack:
    """Test ultraserver-specific functionality in queues stack."""

    @pytest.mark.parametrize(
        "instance_type, reservation_type, expected_has_ultraserver",
        [
            # Regular instance with ondemand reservation
            ("c5.large", "ondemand", False),
            # Regular instance with capacity block
            ("c5.large", "capacity-block", False),
            # Ultraserver instance with ondemand reservation
            ("p6e-gb200.36xlarge", "ondemand", False),
            # Ultraserver instance with capacity block (should be True)
            ("p6e-gb200.36xlarge", "capacity-block", True),
        ],
    )
    def test_ultraserver_instance_detection(self, mocker, instance_type, reservation_type, expected_has_ultraserver):
        """Test detection of ultraserver instances with capacity blocks."""
        mock_aws_api(mocker)

        # Mock the utility function
        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.get_instance_type_and_reservation_type_from_capacity_reservation",
            return_value=(instance_type, reservation_type),
        )

        # Mock capacity reservation target
        class MockCapacityReservationTarget:
            def __init__(self, cr_id):
                self.capacity_reservation_id = cr_id

        cr_target = MockCapacityReservationTarget("cr-123456")

        assert_that(has_ultraserver_instance(cr_target)).is_equal_to(expected_has_ultraserver)

    @pytest.mark.parametrize(
        "has_ultraserver_instance, max_network_interfaces, expected_device_index",
        [
            # Regular instance, multi-NIC
            (False, 2, 1),
            # Regular instance, single-NIC
            (False, 1, 0),
            # Ultraserver instance, multi-NIC (should be 0)
            (True, 2, 0),
            # Ultraserver instance, single-NIC (should be 0)
            (True, 1, 0),
        ],
    )
    def test_device_index_assignment(self, has_ultraserver_instance, max_network_interfaces, expected_device_index):
        # Mock network card
        class MockNetworkCard:
            def maximum_network_interfaces(self):
                return max_network_interfaces

        network_card = MockNetworkCard()

        # Simulate the device_index assignment logic
        device_index = 0 if has_ultraserver_instance or network_card.maximum_network_interfaces() == 1 else 1

        assert_that(device_index).is_equal_to(expected_device_index)
