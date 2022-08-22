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
import os as os_lib

import pytest
from assertpy import assert_that

from pcluster.aws.resource_groups import ResourceGroupsClient
from tests.utils import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.aws.common.boto3"


@pytest.mark.parametrize(
    "resources, expected_capacity_reservation_ids",
    [
        ([], []),
        (
            [
                {
                    "Identifier": {
                        "ResourceType": "AWS::EC2::CapacityReservation",
                        "ResourceArn": "arn:aws:ec2:us-east-1:123456789123:capacity-reservation/cr-12345612345123456",
                    }
                }
            ],
            ["cr-12345612345123456"],
        ),
        (
            [
                {
                    "Identifier": {
                        "ResourceType": "AWS::EC2::CapacityReservation",
                        "ResourceArn": "arn:aws:ec2:us-east-1:123456789123:capacity-reservation/cr-12345612345123456",
                    }
                },
                {
                    "Identifier": {
                        "ResourceType": "AWS::EC2::CapacityReservation",
                        "ResourceArn": "arn:aws:ec2:us-east-1:123456789123:capacity-reservation/cr-98765612345123456",
                    }
                },
            ],
            ["cr-12345612345123456", "cr-98765612345123456"],
        ),
        (
            [
                {
                    "Identifier": {
                        "ResourceType": "AWS::EC2::CapacityReservation",
                        "ResourceArn": "arn:aws:ec2:us-east-1:123456789123:capacity-reservation/cr-12345612345123456",
                    }
                },
                {"Identifier": {"ResourceType": "AWS::EC2::Other", "ResourceArn": "otherarn"}},
            ],
            ["cr-12345612345123456"],
        ),
    ],
)
def test_capacity_reservation_ids_from_group_resources(boto3_stubber, resources, expected_capacity_reservation_ids):
    os_lib.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    resource_group_name = "mocked_resource_group_name"
    mocked_requests = [
        MockedBoto3Request(
            method="list_group_resources",
            response={"Resources": resources},
            expected_params={"Group": resource_group_name},
        )
    ]
    boto3_stubber("resource-groups", mocked_requests)
    assert_that(
        ResourceGroupsClient().get_capacity_reservation_ids_from_group_resources(resource_group_name)
    ).is_equal_to(expected_capacity_reservation_ids)
