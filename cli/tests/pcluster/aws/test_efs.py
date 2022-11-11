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


def get_describe_file_systems_mocked_request(efs, avail_zone=None):
    file_system_id = {
        "OwnerId": "1234567890",
        "FileSystemId": efs,
        "LifeCycleState": "available",
        "CreationToken": "quickCreated-123456",
        "CreationTime": "2022-11-11T10:40:19+01:00",
        "NumberOfMountTargets": 1,
        "PerformanceMode": "generalPurpose",
        "Tags": [],
        "SizeInBytes": {
            "Value": 6144,
        },
    }
    if avail_zone:
        file_system_id["AvailabilityZoneName"] = avail_zone

    return MockedBoto3Request(
        method="describe_file_systems",
        response={"FileSystems": [file_system_id]},
        expected_params={"FileSystemId": efs},
    )


def test_is_efs_standard(boto3_stubber):
    efs_standard = "fs-1234567890"
    efs_onezone = "fs-0987654321"
    avail_zone = "eu-west-1c"

    mocked_requests = [
        get_describe_file_systems_mocked_request(efs_standard),
        get_describe_file_systems_mocked_request(efs_onezone, avail_zone),
    ]
    boto3_stubber("efs", mocked_requests)
    boto3_stubber("ec2", [])

    assert_that(AWSApi.instance().efs.is_efs_standard(efs_standard)).is_true()
    assert_that(AWSApi.instance().efs.is_efs_standard(efs_onezone)).is_false()
