# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the 'License'). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the 'LICENSE.txt' file accompanying this file. This file is distributed on an 'AS IS' BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import pytest
from assertpy import assert_that

from pcluster.aws.elb import ElbClient
from tests.utils import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.aws.common.boto3"


@pytest.mark.parametrize("generate_error", [True, False])
def test_list_load_balancers(boto3_stubber, generate_error):
    """Verify that list_instance_types behaves as expected."""
    dummy_message = "dummy error message"

    dummy_load_balancer = {
        "LoadBalancerArn": "dummy_load_balancer_arn",
        "DNSName": "dummy_dns_name",
        "LoadBalancerName": "dummy-load-balancer",
        "Scheme": "internet-facing",
        "State": {"Code": "active"},
    }

    dummy_load_balancer_2 = {
        "LoadBalancerArn": "dummy_load_balancer_arn_2",
        "DNSName": "dummy_dns_name",
        "LoadBalancerName": "dummy-load-balancer-2",
        "Scheme": "internal",
        "State": {"Code": "provisioning"},
    }

    dummy_next_marker = "next_marker"

    mocked_requests = [
        MockedBoto3Request(
            method="describe_load_balancers",
            expected_params={},
            response={"LoadBalancers": [dummy_load_balancer], "NextMarker": dummy_next_marker, "ResponseMetadata": {}},
            generate_error=False,
        ),
        MockedBoto3Request(
            method="describe_load_balancers",
            expected_params={"Marker": dummy_next_marker},
            response=dummy_message
            if generate_error
            else {"LoadBalancers": [dummy_load_balancer_2], "ResponseMetadata": {}},
            generate_error=generate_error,
        ),
    ]
    boto3_stubber("elbv2", mocked_requests)
    if generate_error:
        with pytest.raises(BaseException, match=dummy_message):
            ElbClient().list_load_balancers()
    else:
        return_value = ElbClient().list_load_balancers()
        assert_that(return_value).is_equal_to([dummy_load_balancer, dummy_load_balancer_2])


@pytest.mark.parametrize("generate_error", [True, False])
def test_describe_tags(boto3_stubber, generate_error):
    """Verify that list_instance_types behaves as expected."""
    dummy_load_balancer_arns = ["dummy_load_balancer_arn", "another_dummy_load_balancer_arn"]
    dummy_message = "dummy error message"
    dummy_tags_description = [
        {
            "ResourceArn": "dummy_load_balancer_arn",
            "Tags": [
                {
                    "Key": "parallelcluster:cluster-name",
                    "Value": "pcluster-name-1",
                },
            ],
        },
        {
            "ResourceArn": "another_dummy_load_balancer_arn",
            "Tags": [
                {
                    "Key": "parallelcluster:cluster-name",
                    "Value": "pcluster-name-2",
                },
            ],
        },
    ]
    mocked_requests = [
        MockedBoto3Request(
            method="describe_tags",
            expected_params={"ResourceArns": dummy_load_balancer_arns},
            response=dummy_message
            if generate_error
            else {"TagDescriptions": dummy_tags_description, "ResponseMetadata": {}},
            generate_error=generate_error,
        )
    ]
    boto3_stubber("elbv2", mocked_requests)
    if generate_error:
        with pytest.raises(BaseException, match=dummy_message):
            ElbClient().describe_tags(dummy_load_balancer_arns)
    else:
        return_value = ElbClient().describe_tags(dummy_load_balancer_arns)
        assert_that(return_value).is_equal_to(dummy_tags_description)


@pytest.mark.parametrize("generate_error", [True, False])
def test_describe_targets_group(boto3_stubber, generate_error):
    """Verify that describe_target_groups behaves as expected."""
    dummy_load_balancer_arn = "dummy_load_balancer_arn"
    dummy_message = "dummy error message"

    dummy_target_groups = [
        {
            "HealthCheckPort": "22",
            "LoadBalancerArns": [dummy_load_balancer_arn],
        },
        {
            "HealthCheckPort": "22",
            "LoadBalancerArns": [dummy_load_balancer_arn],
        },
    ]
    mocked_requests = [
        MockedBoto3Request(
            method="describe_target_groups",
            expected_params={"LoadBalancerArn": dummy_load_balancer_arn},
            response=dummy_message if generate_error else {"TargetGroups": dummy_target_groups, "ResponseMetadata": {}},
            generate_error=generate_error,
        )
    ]
    boto3_stubber("elbv2", mocked_requests)
    if generate_error:
        with pytest.raises(BaseException, match=dummy_message):
            ElbClient().describe_target_groups(dummy_load_balancer_arn)
    else:
        return_value = ElbClient().describe_target_groups(dummy_load_balancer_arn)
        assert_that(return_value).is_equal_to(dummy_target_groups)


@pytest.mark.parametrize("generate_error", [True, False])
def test_describe_target_health(boto3_stubber, generate_error):
    """Verify that describe_target_health behaves as expected."""
    dummy_target_arn = "dummy_target_arn"
    dummy_message = "dummy error message"
    dummy_targets_health = [
        {
            "HealthCheckPort": "22",
            "Target": {
                "Id": "i-123456",
                "Port": 22,
            },
            "TargetHealth": {
                "State": "healthy",
            },
        },
        {
            "HealthCheckPort": "22",
            "Target": {
                "Id": "i-789101",
                "Port": 22,
            },
            "TargetHealth": {
                "State": "healthy",
            },
        },
    ]
    mocked_requests = [
        MockedBoto3Request(
            method="describe_target_health",
            expected_params={"TargetGroupArn": "dummy_target_arn"},
            response=dummy_message
            if generate_error
            else {"TargetHealthDescriptions": dummy_targets_health, "ResponseMetadata": {}},
            generate_error=generate_error,
        )
    ]
    boto3_stubber("elbv2", mocked_requests)
    if generate_error:
        with pytest.raises(BaseException, match=dummy_message):
            ElbClient().describe_target_health(dummy_target_arn)
    else:
        return_value = ElbClient().describe_target_health(dummy_target_arn)
        assert_that(return_value).is_equal_to(dummy_targets_health)
