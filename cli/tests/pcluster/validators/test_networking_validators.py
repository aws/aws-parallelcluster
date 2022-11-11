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
import os

import pytest

from pcluster.validators.networking_validators import SecurityGroupsValidator, SingleSubnetValidator, SubnetsValidator
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.validators.utils import assert_failure_messages


def test_ec2_security_group_validator(mocker):
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    describe_security_group_mock = mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_security_group",
        return_value={
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
        },
    )

    actual_failures = SecurityGroupsValidator().execute(["sg-12345678"])
    assert_failure_messages(actual_failures, None)
    describe_security_group_mock.assert_called_with("sg-12345678")


def test_ec2_subnet_id_validator(mocker):
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.is_enable_dns_support", return_value=True)
    mocker.patch("pcluster.aws.ec2.Ec2Client.is_enable_dns_hostnames", return_value=True)

    # TODO test with invalid key
    actual_failures = SubnetsValidator().execute(["subnet-12345678", "subnet-23456789"])
    assert_failure_messages(actual_failures, None)


@pytest.mark.parametrize(
    "queues, failure_message",
    [
        (
            [
                ["subnet-11111111"],
                ["subnet-00000000"],
            ],
            "The SubnetId used for all of the queues should be the same",
        ),
        (
            [
                ["subnet-00000000"],
                ["subnet-00000000"],
            ],
            None,
        ),
    ],
)
def test_single_subnet_validator(queues, failure_message):
    actual_failure = SingleSubnetValidator().execute(queues)

    assert_failure_messages(actual_failure, failure_message)
