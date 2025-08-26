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

import logging

from pcluster.validators.common import FailureLevel, Validator

LOGGER = logging.getLogger(__name__)


class LoginNodesSshKeyNameDeprecatedValidator(Validator):
    """Validator to warn about deprecated LoginNodes SSH KeyName."""

    def _validate(self, key_name: str = None, key_name_explicitly_set: bool = False):
        """Return a deprecation warning when LoginNodes SSH KeyName is explicitly set in the cluster config."""
        if key_name and key_name_explicitly_set:
            self._add_failure(
                "LoginNodes/Pools/Ssh/KeyName is deprecated since ParallelCluster version 3.14.0. "
                "Please remove it from cluster configuration. "
                "The SSH key for the login nodes will be the one used by the head node.",
                FailureLevel.WARNING,
            )
