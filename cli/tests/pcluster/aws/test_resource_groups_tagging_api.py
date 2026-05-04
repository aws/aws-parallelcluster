# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from pcluster.aws.resource_groups_tagging_api import ResourceGroupsTaggingApiClient
from tests.utils import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.aws.common.boto3"


def test_get_resources_returns_matching_arns(boto3_stubber):
    """Verify get_resources builds the correct request and returns ARNs from the response."""
    dummy_arn_1 = "arn:aws:elasticloadbalancing:us-east-1:111111111111:loadbalancer/net/cluster-1/a"
    dummy_arn_2 = "arn:aws:elasticloadbalancing:us-east-1:111111111111:loadbalancer/net/cluster-1/b"
    mocked_requests = [
        MockedBoto3Request(
            method="get_resources",
            expected_params={
                "TagFilters": [
                    {"Key": "parallelcluster:cluster-name", "Values": ["cluster-1"]},
                    {"Key": "parallelcluster:login-nodes-pool", "Values": ["login"]},
                ],
                "ResourceTypeFilters": ["elasticloadbalancing:loadbalancer"],
            },
            response={
                "ResourceTagMappingList": [
                    {"ResourceARN": dummy_arn_1},
                    {"ResourceARN": dummy_arn_2},
                ],
                "ResponseMetadata": {},
            },
            generate_error=False,
        )
    ]
    boto3_stubber("resourcegroupstaggingapi", mocked_requests)

    return_value = ResourceGroupsTaggingApiClient().get_resources(
        tag_filters={
            "parallelcluster:cluster-name": "cluster-1",
            "parallelcluster:login-nodes-pool": "login",
        },
        resource_type_filters=["elasticloadbalancing:loadbalancer"],
    )
    assert_that(return_value).is_equal_to([dummy_arn_1, dummy_arn_2])


def test_get_resources_without_resource_type_filter(boto3_stubber):
    """Verify get_resources omits ResourceTypeFilters when not provided."""
    dummy_arn = "arn:aws:elasticloadbalancing:us-east-1:111111111111:loadbalancer/net/cluster-1/a"
    mocked_requests = [
        MockedBoto3Request(
            method="get_resources",
            expected_params={
                "TagFilters": [
                    {"Key": "parallelcluster:cluster-name", "Values": ["cluster-1"]},
                ],
            },
            response={
                "ResourceTagMappingList": [{"ResourceARN": dummy_arn}],
                "ResponseMetadata": {},
            },
            generate_error=False,
        )
    ]
    boto3_stubber("resourcegroupstaggingapi", mocked_requests)

    return_value = ResourceGroupsTaggingApiClient().get_resources(
        tag_filters={"parallelcluster:cluster-name": "cluster-1"}
    )
    assert_that(return_value).is_equal_to([dummy_arn])


def test_get_resources_follows_pagination(boto3_stubber):
    """Verify get_resources follows pagination tokens and aggregates ARNs across pages."""
    dummy_arn_1 = "arn:aws:elasticloadbalancing:us-east-1:111111111111:loadbalancer/net/cluster-1/a"
    dummy_arn_2 = "arn:aws:elasticloadbalancing:us-east-1:111111111111:loadbalancer/net/cluster-1/b"
    dummy_token = "next-page-token"
    mocked_requests = [
        MockedBoto3Request(
            method="get_resources",
            expected_params={
                "TagFilters": [{"Key": "parallelcluster:cluster-name", "Values": ["cluster-1"]}],
                "ResourceTypeFilters": ["elasticloadbalancing:loadbalancer"],
            },
            response={
                "ResourceTagMappingList": [{"ResourceARN": dummy_arn_1}],
                "PaginationToken": dummy_token,
                "ResponseMetadata": {},
            },
            generate_error=False,
        ),
        MockedBoto3Request(
            method="get_resources",
            expected_params={
                "TagFilters": [{"Key": "parallelcluster:cluster-name", "Values": ["cluster-1"]}],
                "ResourceTypeFilters": ["elasticloadbalancing:loadbalancer"],
                "PaginationToken": dummy_token,
            },
            response={
                "ResourceTagMappingList": [{"ResourceARN": dummy_arn_2}],
                "ResponseMetadata": {},
            },
            generate_error=False,
        ),
    ]
    boto3_stubber("resourcegroupstaggingapi", mocked_requests)

    return_value = ResourceGroupsTaggingApiClient().get_resources(
        tag_filters={"parallelcluster:cluster-name": "cluster-1"},
        resource_type_filters=["elasticloadbalancing:loadbalancer"],
    )
    assert_that(return_value).is_equal_to([dummy_arn_1, dummy_arn_2])


def test_get_resources_empty_response(boto3_stubber):
    """Verify get_resources returns an empty list when the API returns no matching resources."""
    mocked_requests = [
        MockedBoto3Request(
            method="get_resources",
            expected_params={
                "TagFilters": [{"Key": "parallelcluster:cluster-name", "Values": ["cluster-1"]}],
                "ResourceTypeFilters": ["elasticloadbalancing:loadbalancer"],
            },
            response={"ResourceTagMappingList": [], "ResponseMetadata": {}},
            generate_error=False,
        )
    ]
    boto3_stubber("resourcegroupstaggingapi", mocked_requests)

    return_value = ResourceGroupsTaggingApiClient().get_resources(
        tag_filters={"parallelcluster:cluster-name": "cluster-1"},
        resource_type_filters=["elasticloadbalancing:loadbalancer"],
    )
    assert_that(return_value).is_equal_to([])


def test_get_resources_error(boto3_stubber):
    """Verify get_resources propagates a wrapped error when the API call fails."""
    dummy_message = "dummy error message"
    mocked_requests = [
        MockedBoto3Request(
            method="get_resources",
            expected_params={
                "TagFilters": [{"Key": "parallelcluster:cluster-name", "Values": ["cluster-1"]}],
                "ResourceTypeFilters": ["elasticloadbalancing:loadbalancer"],
            },
            response=dummy_message,
            generate_error=True,
        )
    ]
    boto3_stubber("resourcegroupstaggingapi", mocked_requests)

    with pytest.raises(BaseException, match=dummy_message):
        ResourceGroupsTaggingApiClient().get_resources(
            tag_filters={"parallelcluster:cluster-name": "cluster-1"},
            resource_type_filters=["elasticloadbalancing:loadbalancer"],
        )
