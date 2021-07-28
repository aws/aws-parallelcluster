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
import os as os_lib

import pytest
from assertpy import assert_that

from pcluster.aws.iam import IamClient
from tests.utils import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.aws.common.boto3"


def test_get_instance_profile(boto3_stubber):
    os_lib.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    instance_profile_name = "mocked_instance_profile_name"
    response = {
        "InstanceProfile": {
            "InstanceProfileName": instance_profile_name,
            "Path": "/",
            "InstanceProfileId": "SomeIdOfLengthAtLeastSixteen",
            "Arn": f"arn:aws:iam:::instance-profile/{instance_profile_name}",
            "CreateDate": "2021-07-28",
            "Roles": [
                {
                    "Arn": f"arn:aws:iam:::role/{instance_profile_name}",
                    "Path": "/",
                    "RoleName": instance_profile_name,
                    "RoleId": "AnotherIdOfLengthAtLeastSixteen",
                    "CreateDate": "2021-07-28",
                }
            ],
        }
    }
    mocked_requests = [
        MockedBoto3Request(
            method="get_instance_profile",
            response=response,
            expected_params={"InstanceProfileName": instance_profile_name},
        )
    ]
    boto3_stubber("iam", mocked_requests)
    assert_that(IamClient().get_instance_profile(instance_profile_name)).is_equal_to(response)


def test_get_role(boto3_stubber):
    os_lib.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    role_name = "mocked_role_name"
    response = {
        "Role": {
            "RoleName": role_name,
            "Path": "/",
            "RoleId": "SomeIdOfLengthAtLeastSixteen",
            "Arn": f"arn:aws:iam:::role/{role_name}",
            "CreateDate": "2021-07-28",
        }
    }
    mocked_requests = [
        MockedBoto3Request(
            method="get_role",
            response=response,
            expected_params={"RoleName": role_name},
        )
    ]
    boto3_stubber("iam", mocked_requests)
    assert_that(IamClient().get_role(role_name)).is_equal_to(response)


def test_get_policy(boto3_stubber):
    os_lib.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    policy_name = "mocked_policy_name"
    policy_arn = f"arn:aws:iam:::policy/{policy_name}"
    response = {
        "Policy": {
            "PolicyName": policy_name,
            "Path": "/",
            "PolicyId": "SomeIdOfLengthAtLeastSixteen",
            "Arn": policy_arn,
            "CreateDate": "2021-07-28",
        }
    }
    mocked_requests = [
        MockedBoto3Request(
            method="get_policy",
            response=response,
            expected_params={"PolicyArn": policy_arn},
        )
    ]
    boto3_stubber("iam", mocked_requests)
    assert_that(IamClient().get_policy(policy_arn)).is_equal_to(response)
