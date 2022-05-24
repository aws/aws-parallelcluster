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

import pytest
from assertpy import assert_that

from pcluster.aws.aws_api import AWSApi
from tests.utils import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.aws.common.boto3"


def get_describe_file_systems_mocked_request(fsxs, lifecycle):
    return MockedBoto3Request(
        method="describe_file_systems",
        response={"FileSystems": [{"FileSystemId": fsx, "Lifecycle": lifecycle} for fsx in fsxs]},
        expected_params={"FileSystemIds": fsxs},
    )


def test_get_file_systems_info(boto3_stubber):
    fsx = "fs-12345678"
    additional_fsx = "fs-23456789"
    # The first mocked request and the third are about the same fsx. However, the lifecycle of the fsx changes
    # from CREATING to AVAILABLE. The second mocked request is about another fsx
    mocked_requests = [
        get_describe_file_systems_mocked_request([fsx], "CREATING"),
        get_describe_file_systems_mocked_request([additional_fsx], "CREATING"),
        get_describe_file_systems_mocked_request([fsx], "AVAILABLE"),
    ]
    boto3_stubber("fsx", mocked_requests)
    assert_that(AWSApi.instance().fsx.get_file_systems_info([fsx])[0].file_system_data["Lifecycle"]).is_equal_to(
        "CREATING"
    )

    # Second boto3 call with more fsxs. The fsx already cached should not be included in the boto3 call.
    response = AWSApi.instance().fsx.get_file_systems_info([fsx, additional_fsx])
    assert_that(response).is_length(2)

    # Third boto3 call. The result should be from cache even if the lifecycle of the fsx is different
    assert_that(AWSApi.instance().fsx.get_file_systems_info([fsx])[0].file_system_data["Lifecycle"]).is_equal_to(
        "CREATING"
    )

    # Fourth boto3 call after resetting the AWSApi instance. The latest fsx lifecycle should be retrieved from boto3
    AWSApi.reset()
    assert_that(AWSApi.instance().fsx.get_file_systems_info([fsx])[0].file_system_data["Lifecycle"]).is_equal_to(
        "AVAILABLE"
    )
