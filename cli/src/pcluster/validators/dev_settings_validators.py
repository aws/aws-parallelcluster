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
ATTR_IN_PLACE_UPDATE_ON_FLEET_ENABLED = "in_place_update_on_fleet_enabled"


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
        else:
            self._validate_in_place_update_on_fleet_enabled(json.loads(extra_chef_attributes))

    def _validate_in_place_update_on_fleet_enabled(self, extra_chef_attributes: dict = None):
        """Validate attribute cluster.in_place_update_on_fleet_enabled.

        It returns an error if the attribute is set to a non-boolean value.
        It returns a warning if the in-place update is disabled.

        Args:
            extra_chef_attributes: Dictionary of Chef attributes to validate.
        """
        in_place_update_on_fleet_enabled = dig(extra_chef_attributes, "cluster", ATTR_IN_PLACE_UPDATE_ON_FLEET_ENABLED)

        if in_place_update_on_fleet_enabled is None:
            return

        if not is_boolean_string(str(in_place_update_on_fleet_enabled)):
            self._add_failure(
                f"Invalid value in {EXTRA_CHEF_ATTRIBUTES_PATH}: "
                f"attribute '{ATTR_IN_PLACE_UPDATE_ON_FLEET_ENABLED}' must be a boolean value.",
                FailureLevel.ERROR,
            )
            return

        if str_to_bool(str(in_place_update_on_fleet_enabled)) is False:
            self._add_failure(
                "When in-place updates are disabled, cluster updates are applied "
                "by replacing compute and login nodes according to the selected QueueUpdateStrategy.",
                FailureLevel.WARNING,
            )
