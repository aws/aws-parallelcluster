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
from collections import defaultdict

import pytest

from pcluster.validators.networking_validators import (
    LambdaFunctionsVpcConfigValidator,
    MultiAzPlacementGroupValidator,
    QueueSubnetsValidator,
    SecurityGroupsValidator,
    SingleSubnetValidator,
    SubnetsValidator,
)
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
    "queue_name, queue_subnets, subnet_id_az_mapping, failure_message",
    [
        (
            "good-queue",
            ["subnet-00000000", "subnet-11111111"],
            {"subnet-00000000": "us-east-1a", "subnet-11111111": "us-east-1b"},
            None,
        ),
        (
            "subnets-in-common-az-queue-1",
            ["subnet-00000000", "subnet-11111111"],
            {"subnet-00000000": "us-east-1a", "subnet-11111111": "us-east-1a"},
            "SubnetIds specified in queue subnets-in-common-az-queue-1 contains multiple subnets in the same AZs: "
            "us-east-1a: subnet-00000000, subnet-11111111. "
            "Please make sure all subnets in the queue are in different AZs.",
        ),
        (
            "subnets-in-common-az-queue-2",
            ["subnet-1", "subnet-2", "subnet-3", "subnet-4", "subnet-5"],
            {
                "subnet-1": "us-east-1a",
                "subnet-2": "us-east-1a",
                "subnet-3": "us-east-1b",
                "subnet-4": "us-east-1b",
                "subnet-5": "us-east-1b",
            },
            "SubnetIds specified in queue subnets-in-common-az-queue-2 contains multiple subnets in the same AZs: "
            "us-east-1a: subnet-1, subnet-2; us-east-1b: subnet-3, subnet-4, subnet-5. "
            "Please make sure all subnets in the queue are in different AZs.",
        ),
        (
            "duplicate-subnets-queue",
            ["subnet-00000000", "subnet-00000000", "subnet-11111111", "subnet-11111111", "subnet-11111111"],
            {"subnet-00000000": "us-east-1a", "subnet-11111111": "us-east-1b"},
            "The following subnet ids are specified multiple times in queue duplicate-subnets-queue: "
            "subnet-00000000, subnet-11111111.",
        ),
        # This test should trigger both validation errors for duplicate subnet ids and multiple subnets
        # in the same AZ, that's why it's repeated twice below.
        (
            "duplicate-subnets-queue-1",
            ["subnet-00000000", "subnet-00000000", "subnet-11111111"],
            {"subnet-00000000": "us-east-1a", "subnet-11111111": "us-east-1a"},
            "The following subnet ids are specified multiple times in queue duplicate-subnets-queue-1: "
            "subnet-00000000.",
        ),
        (
            "duplicate-subnets-queue-2",
            ["subnet-00000000", "subnet-00000000", "subnet-11111111"],
            {"subnet-00000000": "us-east-1a", "subnet-11111111": "us-east-1a"},
            "SubnetIds specified in queue duplicate-subnets-queue-2 contains multiple subnets in the same AZs: "
            "us-east-1a: subnet-00000000, subnet-11111111. "
            "Please make sure all subnets in the queue are in different AZs.",
        ),
    ],
)
def test_queue_subnets_validator(mocker, queue_name, queue_subnets, subnet_id_az_mapping, failure_message):
    az_subnet_ids_mapping = defaultdict(list)
    for subnet_id, _az in subnet_id_az_mapping.items():
        az_subnet_ids_mapping[_az].append(subnet_id)
    actual_failure = QueueSubnetsValidator().execute(
        queue_name,
        queue_subnets,
        az_subnet_ids_mapping,
    )
    assert_failure_messages(actual_failure, failure_message)


@pytest.mark.parametrize(
    "multi_az_enabled, placement_group_enabled, expected_message",
    [
        (True, False, None),
        (False, True, None),
        (False, False, None),
        (
            True,
            True,
            "Multiple subnets configuration does not support specifying Placement Group. "
            "Either specify a single subnet or remove the Placement Group configuration.",
        ),
    ],
)
def test_multi_az_placement_group_validator(multi_az_enabled, placement_group_enabled, expected_message):
    actual_failures = MultiAzPlacementGroupValidator().execute(multi_az_enabled, placement_group_enabled)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "queue_name, subnet_ids, failure_message",
    [
        (
            "multi-subnet-queue",
            [
                ["subnet-00000000"],
                ["subnet-11111111"],
            ],
            "At least one compute resource in queue multi-subnet-queue uses a single instance type. "
            "Multiple subnets configuration is not supported for single instance type, "
            "please use the Instances configuration parameter for multiple instance type "
            "allocation.",
        ),
        (
            "single-subnet-queue",
            [
                ["subnet-00000000"],
            ],
            None,
        ),
    ],
)
def test_single_subnet_validator(queue_name, subnet_ids, failure_message):
    actual_failure = SingleSubnetValidator().execute(queue_name, subnet_ids)

    assert_failure_messages(actual_failure, failure_message)


@pytest.mark.parametrize(
    "security_group_ids, subnet_ids, existing_security_groups, existing_subnets, expected_response",
    [
        pytest.param(
            ["sg-test"],
            ["subnet-test"],
            [{"GroupId": "sg-test", "VpcId": "vpc-test"}],
            [{"SubnetId": "subnet-test", "VpcId": "vpc-test"}],
            "",
            id="successful case",
        ),
        pytest.param(
            ["sg-test1", "sg-test2"],
            ["subnet-test"],
            [{"GroupId": "sg-test1", "VpcId": "vpc-test1"}, {"GroupId": "sg-test2", "VpcId": "vpc-test2"}],
            [{"SubnetId": "subnet-test", "VpcId": "vpc-test"}],
            "The security groups associated to the Lambda are required to be in the same VPC.",
            id="security groups with different VPCs",
        ),
        pytest.param(
            ["sg-test"],
            ["subnet-test1", "subnet-test2"],
            [{"GroupId": "sg-test", "VpcId": "vpc-test"}],
            [{"SubnetId": "subnet-test1", "VpcId": "vpc-test1"}, {"SubnetId": "subnet-test2", "VpcId": "vpc-test2"}],
            "The subnets associated to the Lambda are required to be in the same VPC.",
            id="subnets with different VPCs",
        ),
        pytest.param(
            ["sg-test"],
            ["subnet-test"],
            [{"GroupId": "sg-test", "VpcId": "vpc-test1"}],
            [{"SubnetId": "subnet-test", "VpcId": "vpc-test2"}],
            "The security groups and subnets associated to the Lambda are required to be in the same VPC.",
            id="security groups and subnets with different VPCs",
        ),
        pytest.param(
            ["sg-test2", "sg-test3", "sg-test1"],
            ["subnet-test"],
            [
                {"GroupId": "sg-test2", "VpcId": "vpc-test"},
                {"GroupId": "sg-test4", "VpcId": "vpc-test"},
                {"GroupId": "sg-test5", "VpcId": "vpc-test"},
                {"GroupId": "sg-test6", "VpcId": "vpc-test"},
            ],
            [{"SubnetId": "subnet-test", "VpcId": "vpc-test"}],
            "Some security groups associated to the Lambda are not present in the account: ['sg-test1', 'sg-test3'].",
            id="missing security groups",
        ),
        pytest.param(
            ["sg-test"],
            ["subnet-test2", "subnet-test3", "subnet-test1"],
            [{"GroupId": "sg-test", "VpcId": "vpc-test"}],
            [
                {"SubnetId": "subnet-test2", "VpcId": "vpc-test"},
                {"SubnetId": "subnet-test4", "VpcId": "vpc-test"},
                {"SubnetId": "subnet-test5", "VpcId": "vpc-test"},
                {"SubnetId": "subnet-test6", "VpcId": "vpc-test"},
            ],
            "Some subnets associated to the Lambda are not present in the account: ['subnet-test1', 'subnet-test3'].",
            id="missing subnets",
        ),
    ],
)
def test_lambda_functions_vpc_config_validator(
    aws_api_mock, security_group_ids, subnet_ids, existing_security_groups, existing_subnets, expected_response
):
    aws_api_mock.ec2.describe_security_groups.return_value = existing_security_groups
    aws_api_mock.ec2.describe_subnets.return_value = existing_subnets

    actual_response = LambdaFunctionsVpcConfigValidator().execute(security_group_ids, subnet_ids)
    assert_failure_messages(actual_response, expected_response)
