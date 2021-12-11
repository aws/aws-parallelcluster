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

from pcluster.validators.common import FailureLevel, Validator


class SudoPrivilegesValidator(Validator):
    """Sudo Privileges Validator."""

    def _validate(self, grant_sudo_privileges: bool, requires_sudo_privileges: bool):
        if requires_sudo_privileges and not grant_sudo_privileges:
            self._add_failure(
                "The scheduler plugin required sudo privileges through RequiresSudoPrivileges=true "
                "but these privileges were not granted because GrantSudoPrivileges was not set or set to false.",
                FailureLevel.ERROR,
            )
