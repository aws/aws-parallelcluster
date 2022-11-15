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

from pcluster.validators.efs_validators import EfsMountOptionsValidator
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
            "IAM Authorization requires Encryption in Transit",
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
def test_efs_mount_options_validator(encryption_in_transit, iam_authorization, expected_message):
    actual_failures = EfsMountOptionsValidator().execute(encryption_in_transit, iam_authorization)
    assert_failure_messages(actual_failures, expected_message)
