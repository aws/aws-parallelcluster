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
from assertpy import assert_that

from common.boto3.common import AWSClientError
from pcluster.validators.iam_validators import (
    InstanceProfileValidator,
    RoleValidator,
    _get_resource_name_from_resource_arn,
)
from tests.common.dummy_aws_api import mock_aws_api
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "role_arn, side_effect, expected_message",
    [
        (
            "arn:aws:iam::111122223333:role/path/my-custom-role",
            None,
            None,
        ),
        (
            "arn:aws:iam::111122223333:role/no-existent-role",
            AWSClientError(function_name="get_role", message="cannot be found"),
            "cannot be found",
        ),
        (None, AWSClientError(function_name="get_role", message="cannot be found"), "cannot be found"),
        ("no-role", AWSClientError(function_name="get_role", message="cannot be found"), "cannot be found"),
    ],
)
def test_role_validator(mocker, role_arn, side_effect, expected_message):
    mock_aws_api(mocker)
    mocker.patch("common.boto3.iam.IamClient.get_role", side_effect=side_effect)

    actual_failures = RoleValidator().execute(role_arn=role_arn)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "instance_profile_arn, side_effect, expected_message",
    [
        (
            "arn:aws:iam::111122223333:instance-profile/path/my-custom-instance-profile",
            None,
            None,
        ),
        (
            "arn:aws:iam::111122223333:instance-profile/no-existent-instance-profile",
            AWSClientError(function_name="get_instance_profile", message="cannot be found"),
            "cannot be found",
        ),
        (None, AWSClientError(function_name="get_instance_profile", message="cannot be found"), "cannot be found"),
        (
            "no-instance-profile",
            AWSClientError(function_name="get_instance_profile", message="cannot be found"),
            "cannot be found",
        ),
    ],
)
def test_instance_profile_validator(mocker, instance_profile_arn, side_effect, expected_message):
    mock_aws_api(mocker)
    mocker.patch("common.boto3.iam.IamClient.get_instance_profile", side_effect=side_effect)

    actual_failures = InstanceProfileValidator().execute(instance_profile_arn=instance_profile_arn)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "resource_arn, expected_resource_name",
    [
        ("arn:aws:iam::111122223333:role/path/my-custom-role", "my-custom-role"),
        ("arn:aws:iam::111122223333:role/my-custom-role", "my-custom-role"),
        ("arn:aws:iam::111122223333:instance-profile/path/my-custom-instance-profile", "my-custom-instance-profile"),
        ("arn:aws:iam::111122223333:instance-profile/my-custom-instance-profile", "my-custom-instance-profile"),
        ("malformed_arn", "malformed_arn"),
        (None, ""),
    ],
)
def test_get_resource_name_from_resource_arn(resource_arn, expected_resource_name):
    """Verify function that return resource name from resource arn."""
    assert_that(_get_resource_name_from_resource_arn(resource_arn)).is_equal_to(expected_resource_name)
