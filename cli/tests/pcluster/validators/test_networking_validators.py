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

from pcluster.validators.networking_validators import SecurityGroupsValidator
from tests.common import MockedBoto3Request
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.validators.networking_validators.boto3"


def test_ec2_security_group_validator(mocker, boto3_stubber):
    describe_security_groups_response = {
        "SecurityGroups": [
            {
                "IpPermissionsEgress": [],
                "Description": "My security group",
                "IpPermissions": [
                    {
                        "PrefixListIds": [],
                        "FromPort": 22,
                        "IpRanges": [{"CidrIp": "203.0.113.0/24"}],
                        "ToPort": 22,
                        "IpProtocol": "tcp",
                        "UserIdGroupPairs": [],
                    }
                ],
                "GroupName": "MySecurityGroup",
                "OwnerId": "123456789012",
                "GroupId": "sg-12345678",
            }
        ]
    }
    mocked_requests = [
        MockedBoto3Request(
            method="describe_security_groups",
            response=describe_security_groups_response,
            expected_params={"GroupIds": ["sg-12345678"]},
        )
    ]
    boto3_stubber("ec2", mocked_requests)

    actual_failures = SecurityGroupsValidator().execute(["sg-12345678"])
    assert_failure_messages(actual_failures, None)
