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

from pcluster.validators.scheduler_plugin_validators import SudoPrivilegesValidator
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "grant_sudo_privileges, requires_sudo_privileges, expected_message",
    [
        (True, None, None),
        (True, True, None),
        (True, False, None),
        (False, None, None),
        (
            None,
            True,
            "The scheduler plugin required sudo privileges through RequiresSudoPrivileges=true "
            "but these privileges were not granted because GrantSudoPrivileges was not set or set to false.",
        ),
        (
            False,
            True,
            "The scheduler plugin required sudo privileges through RequiresSudoPrivileges=true "
            "but these privileges were not granted because GrantSudoPrivileges was not set or set to false.",
        ),
    ],
)
def test_instance_type_validator(grant_sudo_privileges, requires_sudo_privileges, expected_message):
    actual_failures = SudoPrivilegesValidator().execute(grant_sudo_privileges, requires_sudo_privileges)
    assert_failure_messages(actual_failures, expected_message)
