# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import json

from pcluster.validators.common import FailureLevel, Validator
from pcluster.validators.utils import dig, is_boolean_string, str_to_bool

EXTRA_CHEF_ATTRIBUTES_PATH = "DevSettings/Cookbook/ExtraChefAttributes"
ATTR_RECONFIGURE_TIMEOUT = "cluster.slurm.reconfigure_timeout"
ATTR_CLUSTER_READINESS_CHECK_ENABLED = "cluster.cluster_readiness_check_enabled"
ATTR_CLUSTER_READINESS_CHECK_IGNORE_FAILURE = "cluster.cluster_readiness_check_ignore_failure"
MIN_SLURM_RECONFIGURE_TIMEOUT = 300

CLI_ATTRIBUTE_OVERRIDES_PATH = "DevSettings/CliAttributeOverrides"


class CliAttributeOverridesValidator(Validator):
    """Validate DevSettings/CliAttributeOverrides is a well-formed JSON object."""

    def _validate(self, cli_attribute_overrides: str = None):
        if not cli_attribute_overrides:
            return
        try:
            attrs = json.loads(cli_attribute_overrides)
        except ValueError:
            self._add_failure(
                f"Invalid value in {CLI_ATTRIBUTE_OVERRIDES_PATH}: must be a valid JSON string.",
                FailureLevel.ERROR,
            )
            return
        if not isinstance(attrs, dict):
            self._add_failure(
                f"Invalid value in {CLI_ATTRIBUTE_OVERRIDES_PATH}: must be a JSON object.",
                FailureLevel.ERROR,
            )


class ExtraChefAttributesValidator(Validator):
    """Validate DevSettings/Cookbook/ExtraChefAttributes."""

    def _validate(self, extra_chef_attributes: str = None):
        """Validate extra Chef attributes.

        Args:
            extra_chef_attributes: JSON string containing Chef attributes.
                                 Schema validation ensures this is valid JSON.
        """
        if not extra_chef_attributes:
            return

        attrs = json.loads(extra_chef_attributes)
        self._validate_slurm_reconfigure_timeout(attrs)
        self._validate_cluster_readiness_check_enabled(attrs)
        self._validate_cluster_readiness_check_ignore_failure(attrs)

    def _validate_cluster_readiness_check_enabled(self, extra_chef_attributes: dict = None):
        """Validate attribute cluster.cluster_readiness_check_enabled.

        It returns an error if the attribute is set to a non-boolean value.
        It returns a warning if the cluster readiness check is disabled.

        Args:
            extra_chef_attributes: Dictionary of Chef attributes to validate.
        """
        value = dig(extra_chef_attributes, *ATTR_CLUSTER_READINESS_CHECK_ENABLED.split("."))

        if value is None:
            return

        if not is_boolean_string(str(value)):
            self._add_failure(
                f"Invalid value in {EXTRA_CHEF_ATTRIBUTES_PATH}: "
                f"attribute '{ATTR_CLUSTER_READINESS_CHECK_ENABLED}' must be a boolean value.",
                FailureLevel.ERROR,
            )
            return

        if str_to_bool(str(value)) is False:
            self._add_failure(
                "Cluster readiness check is disabled. Cluster creation and cluster update can succeed "
                "even if there are cluster nodes that did not complete the deployment of the expected configuration.",
                FailureLevel.WARNING,
            )

    def _validate_cluster_readiness_check_ignore_failure(self, extra_chef_attributes: dict = None):
        """Validate attribute cluster.cluster_readiness_check_ignore_failure.

        It returns an error if the attribute is set to a non-boolean value.
        It returns a warning if the cluster readiness check failures are ignored.

        Args:
            extra_chef_attributes: Dictionary of Chef attributes to validate.
        """
        value = dig(extra_chef_attributes, *ATTR_CLUSTER_READINESS_CHECK_IGNORE_FAILURE.split("."))

        if value is None:
            return

        if not is_boolean_string(str(value)):
            self._add_failure(
                f"Invalid value in {EXTRA_CHEF_ATTRIBUTES_PATH}: "
                f"attribute '{ATTR_CLUSTER_READINESS_CHECK_IGNORE_FAILURE}' must be a boolean value.",
                FailureLevel.ERROR,
            )
            return

        if str_to_bool(str(value)) is True:
            self._add_failure(
                "Cluster readiness check failures are ignored. Cluster creation and cluster update can succeed "
                "even if there are cluster nodes that did not complete the deployment of the expected configuration.",
                FailureLevel.WARNING,
            )

    def _validate_slurm_reconfigure_timeout(self, extra_chef_attributes: dict = None):
        """Validate attribute cluster.slurm.reconfigure-timeout.

        Must be an integer greater than 300.

        Args:
            extra_chef_attributes: Dictionary of Chef attributes to validate.
        """
        reconfigure_timeout = dig(extra_chef_attributes, *ATTR_RECONFIGURE_TIMEOUT.split("."))

        if reconfigure_timeout is None:
            return

        # Reject booleans explicitly (bool is subclass of int in Python)
        if isinstance(reconfigure_timeout, bool) or not isinstance(reconfigure_timeout, int):
            self._add_failure(
                f"Invalid value in {EXTRA_CHEF_ATTRIBUTES_PATH}: "
                f"attribute '{ATTR_RECONFIGURE_TIMEOUT}' must be an integer.",
                FailureLevel.ERROR,
            )
            return

        if reconfigure_timeout <= MIN_SLURM_RECONFIGURE_TIMEOUT:
            self._add_failure(
                f"Invalid value in {EXTRA_CHEF_ATTRIBUTES_PATH}: "
                f"attribute '{ATTR_RECONFIGURE_TIMEOUT}' "
                f"must be greater than {MIN_SLURM_RECONFIGURE_TIMEOUT}.",
                FailureLevel.ERROR,
            )
