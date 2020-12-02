# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import os

import pytest
from assertpy import assert_that

from pcluster.utils import get_default_instance_type
from tests.common import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.utils.boto3"


@pytest.mark.parametrize(
    "region, free_tier_instance_type, default_instance_type, stub_boto3",
    [
        ("us-east-1", "t2.micro", "t2.micro", True),
        ("eu-north-1", "t3.micro", "t3.micro", True),
        ("us-gov-east-1", None, "t3.micro", True),
        # Retrieving free tier instance type again should use cache to reduce boto3 call
        ("us-east-1", "t2.micro", "t2.micro", False),
        ("eu-north-1", "t3.micro", "t3.micro", False),
        ("us-gov-east-1", None, "t3.micro", False),
    ],
)
@pytest.mark.nomockdefaultinstance
def test_get_default_instance(boto3_stubber, region, free_tier_instance_type, default_instance_type, stub_boto3):
    os.environ["AWS_DEFAULT_REGION"] = region
    if free_tier_instance_type:
        response = {"InstanceTypes": [{"InstanceType": free_tier_instance_type}]}
    else:
        response = {"InstanceTypes": []}
    if stub_boto3:
        mocked_requests = [
            MockedBoto3Request(
                method="describe_instance_types",
                response=response,
                expected_params={
                    "Filters": [
                        {"Name": "free-tier-eligible", "Values": ["true"]},
                        {"Name": "current-generation", "Values": ["true"]},
                    ]
                },
            )
        ]

        boto3_stubber("ec2", mocked_requests)
    assert_that(get_default_instance_type()).is_equal_to(default_instance_type)
