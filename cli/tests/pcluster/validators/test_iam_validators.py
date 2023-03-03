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

from pcluster.aws.common import AWSClientError
from pcluster.constants import IAM_NAME_PREFIX_LENGTH_LIMIT, IAM_PATH_LENGTH_LIMIT
from pcluster.validators.common import FailureLevel
from pcluster.validators.iam_validators import (
    AdditionalIamPolicyValidator,
    IamResourcePrefixValidator,
    InstanceProfileValidator,
    RoleValidator,
    get_resource_name_from_resource_arn,
)
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.validators.utils import assert_failure_level, assert_failure_messages


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
    mocker.patch("pcluster.aws.iam.IamClient.get_role", side_effect=side_effect)

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
    mocker.patch("pcluster.aws.iam.IamClient.get_instance_profile", side_effect=side_effect)

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
    assert_that(get_resource_name_from_resource_arn(resource_arn)).is_equal_to(expected_resource_name)


@pytest.mark.parametrize(
    "policy_arn, expected_get_policy_side_effect, expected_message",
    [
        (
            "arn:aws:iam::aws:policy/FakePolicy",
            AWSClientError(
                function_name="get_policy", message="Policy arn:aws:iam::aws:policy/FakePolicy was not found."
            ),
            "Policy arn:aws:iam::aws:policy/FakePolicy was not found.",
        ),
        ("arn:aws:iam::aws:policy/AmazonEC2ReadOnlyAccess", None, None),
        ("arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy", None, None),
        ("arn:aws:iam::aws:policy/AWSBatchFullAccess", None, None),
    ],
)
def test_additional_iam_policy_validator(mocker, policy_arn, expected_get_policy_side_effect, expected_message):
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.iam.IamClient.get_policy", side_effect=expected_get_policy_side_effect)
    actual_failures = AdditionalIamPolicyValidator().execute(policy=policy_arn)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "resource_prefix, expected_message,expected_failure_level",
    [
        (
            # TO DO: Analyze
            r"\path-prefix\\",
            "Unsupported format for ResourcePrefix ",
            FailureLevel.ERROR,
        ),
        (
            "/path-prefix",  # This is not pathprefix
            "Unsupported format for ResourcePrefix /path-prefix",
            FailureLevel.ERROR,
        ),
        (
            "/,+.;!^%()*#$@=path-prefix/",
            "Unsupported format for ResourcePrefix /,+.;!^%()*#$@=path-prefix/. "
            "Please refer to our official documentation for further details.",
            FailureLevel.ERROR,
        ),
        (
            "*^%!&:$#()name-prefix",
            "Unsupported format for ResourcePrefix *^%!&:$#()name-prefix. "
            "Please refer to our official documentation for further details.",
            FailureLevel.ERROR,
        ),
        (
            "",
            "Unsupported format for ResourcePrefix ",
            FailureLevel.ERROR,
        ),
        (
            "//",
            "Unsupported format for ResourcePrefix //",
            FailureLevel.ERROR,
        ),
        (
            "/path_.,+@=-prefix/longernameprefix-longernameprefixlongernameprefix-longernameprefix",
            f"Length of Name Prefix longernameprefix-longernameprefixlongernameprefix-longernameprefix "
            f"must be less than {IAM_NAME_PREFIX_LENGTH_LIMIT} characters."
            " Please refer to our official documentation for further details.",
            FailureLevel.ERROR,
        ),
        (
            "/" + "path/" * ((IAM_PATH_LENGTH_LIMIT // len("path/")) + 1),
            f"must be less than {IAM_PATH_LENGTH_LIMIT} characters."
            " Please refer to our official documentation for further details.",
            FailureLevel.ERROR,
        ),
        ("/longerPath/pathprefix/nameprefix", None, None),
        ("longernameprefixlongnameprefix", None, None),
        ("/path-prefix/", None, None),
        ("/path-prefix/name-prefix", None, None),
        ("_.,+@=-name-prefix", None, None),
    ],
)
def test_iam_resource_prefix_validator(resource_prefix, expected_message, expected_failure_level):
    actual_failures = IamResourcePrefixValidator().execute(resource_prefix=resource_prefix)
    assert_failure_messages(actual_failures, expected_message)
    assert_failure_level(actual_failures, expected_failure_level)
