# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
#
# This module contains all the classes representing the Resources objects.
# These objects are obtained from the configuration file through a conversion based on the Schema classes.
#

import pytest
from assertpy import assert_that

from pcluster.aws.aws_resources import CapacityReservationInfo, InstanceTypeInfo


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.aws.common.boto3"


class TestCapacityReservationInfo:
    @pytest.mark.parametrize(
        ("capacity_reservation_data", "expected_value"),
        [
            ({}, None),
            ({"Tags": []}, None),
            ({"Tags": [{"Key": "test", "Value": "value"}]}, "value"),
            ({"Tags": [{"Key": "test2", "Value": "value2"}, {"Key": "test", "Value": "value"}]}, "value"),
        ],
    )
    def test_get_tags(self, capacity_reservation_data, expected_value):
        assert_that(CapacityReservationInfo(capacity_reservation_data).get_tag("test")).is_equal_to(expected_value)

    @pytest.mark.parametrize(("capacity_reservation_data", "expected_value"), [({}, 0), ({"TotalInstanceCount": 1}, 1)])
    def test_total_instance_count(self, capacity_reservation_data, expected_value):
        assert_that(CapacityReservationInfo(capacity_reservation_data).total_instance_count()).is_equal_to(
            expected_value
        )

    @pytest.mark.parametrize(
        ("capacity_reservation_data", "expected_value"),
        [
            ({}, 0),
            ({"Tags": []}, 0),
            ({"Tags": [{"Key": "aws:ec2capacityreservation:incrementalRequestedQuantity", "Value": "2"}]}, 2),
        ],
    )
    def test_incremental_requested_quantity(self, capacity_reservation_data, expected_value):
        assert_that(CapacityReservationInfo(capacity_reservation_data).incremental_requested_quantity()).is_equal_to(
            expected_value
        )

    @pytest.mark.parametrize(
        ("capacity_reservation_data", "expected_value"),
        [
            ({}, None),
            ({"ReservationType": "capacity-block"}, "capacity-block"),
            (
                {"Tags": [{"Key": "aws:ec2capacityreservation:capacityReservationType", "Value": "capacity-block"}]},
                "capacity-block",
            ),
            # The following should not happen, anyway is just to confirm that ReservationType value is preferred
            (
                {
                    "ReservationType": "on-demand",
                    "Tags": [{"Key": "aws:ec2capacityreservation:capacityReservationType", "Value": "capacity-block"}],
                },
                "on-demand",
            ),
        ],
    )
    def test_reservation_type(self, capacity_reservation_data, expected_value):
        assert_that(CapacityReservationInfo(capacity_reservation_data).reservation_type()).is_equal_to(expected_value)


class TestInstanceTypeInfo:
    @pytest.mark.parametrize(
        ("instance_type_data", "expected_network_cards", "expected_error"),
        [
            # Success cases
            ({"InstanceType": "aInstanceType", "NetworkInfo": {"NetworkCards": []}}, [], None),
            (
                {
                    "InstanceType": "aInstanceType",
                    "NetworkInfo": {"NetworkCards": [{"aField": "aValue"}, {"anotherField": "anotherValue"}]},
                },
                [{"aField": "aValue"}, {"anotherField": "anotherValue"}],
                None,
            ),
            # Error cases
            ({}, None, "Could not determine network cards for instance type unknown."),
            ({"NetworkInfo": {}}, None, "Could not determine network cards for instance type unknown."),
            (
                {"InstanceType": "aInstanceType"},
                None,
                "Could not determine network cards for instance type aInstanceType.",
            ),
            (
                {"InstanceType": "aInstanceType", "NetworkInfo": {}},
                None,
                "Could not determine network cards for instance type aInstanceType.",
            ),
        ],
    )
    def test_network_cards(self, instance_type_data, expected_network_cards, expected_error):
        if expected_error:
            with pytest.raises(RuntimeError, match=expected_error):
                InstanceTypeInfo(instance_type_data).network_cards()
        else:
            assert_that(InstanceTypeInfo(instance_type_data).network_cards()).is_equal_to(expected_network_cards)

    @pytest.mark.parametrize(
        ("instance_type_data", "expected_count", "expected_error"),
        [
            ({"NetworkInfo": {"NetworkCards": []}}, 0, None),
            ({"NetworkInfo": {"NetworkCards": [{"NetworkCardIndex": 0}, {"NetworkCardIndex": 1}]}}, 2, None),
            (
                {
                    "NetworkInfo": {
                        "NetworkCards": [
                            {"NetworkCardIndex": 0},
                            {"NetworkCardIndex": 1},
                            {"NetworkCardIndex": None},
                            {"aField": "aValue"},
                        ]
                    }
                },
                4,
                None,
            ),
        ],
    )
    def test_max_network_cards(self, instance_type_data, expected_count, expected_error):
        if expected_error:
            with pytest.raises(expected_error):
                InstanceTypeInfo(instance_type_data).max_network_cards()
        else:
            assert_that(InstanceTypeInfo(instance_type_data).max_network_cards()).is_equal_to(expected_count)

    @pytest.mark.parametrize(
        ("instance_type_data", "expected_count", "expected_error"),
        [
            ({"NetworkInfo": {"NetworkCards": []}}, 0, None),
            ({"NetworkInfo": {"NetworkCards": [{"NetworkCardIndex": 0}, {"NetworkCardIndex": 1}]}}, 2, None),
            (
                {
                    "NetworkInfo": {
                        "NetworkCards": [
                            {"NetworkCardIndex": 0},
                            {"NetworkCardIndex": 1},
                            {"NetworkCardIndex": None},
                            {"aField": "aValue"},
                        ]
                    }
                },
                2,
                None,
            ),
        ],
    )
    def test_network_cards_list(self, instance_type_data, expected_count, expected_error):
        if expected_error:
            with pytest.raises(expected_error):
                InstanceTypeInfo(instance_type_data).network_cards_list()
        else:
            assert_that(InstanceTypeInfo(instance_type_data).network_cards_list()).is_length(expected_count)
