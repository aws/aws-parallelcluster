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

from pcluster.validators.efs_validators import EfsMountOptionsValidator, EfsAccessPointOptionsValidator
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "encryption_in_transit, iam_authorization, expected_message",
    [
        (
            False,
            False,
            None,
        ),
        (
            False,
            True,
            "EFS IAM authorization cannot be enabled when encryption in-transit is disabled. "
            "Please either disable IAM authorization or enable encryption in-transit "
            "for file system <name-of-the-file-system>",
        ),
        (
            True,
            False,
            None,
        ),
        (
            True,
            True,
            None,
        ),
    ],
)
def test_efs_mount_options_validator(
    encryption_in_transit, iam_authorization, expected_message
):
    actual_failures = EfsMountOptionsValidator().execute(
        encryption_in_transit, iam_authorization, "<name-of-the-file-system>"
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "access_point_id, file_system_id, expected_message",
    [
        (
            None,
            None,
            None,
        ),
        (
            "<access_point_id>",
            None,
            "An access point can only be specified when using an existing EFS file system. "
            "Please either remove the access point id <access_point_id> "
            "or provide the file system id for the access point",
        ),
        (
            "<access_point_id>",
            "<file-systemd-id>",
            None,
        ),
        (
            None,
            "<file-systemd-id>",
            None,
        ),
    ],
)
def test_efs_access_point_with_filesystem_validator(access_point_id, file_system_id, expected_message):
    actual_failures = EfsAccessPointOptionsValidator().execute(access_point_id, file_system_id)
    assert_failure_messages(actual_failures, expected_message)


