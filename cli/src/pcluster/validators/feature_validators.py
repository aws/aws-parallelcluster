# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
#
# This module contains all the classes representing the Resources objects.
# These objects are obtained from the configuration file through a conversion based on the Schema classes.
from pcluster.aws.common import get_region
from pcluster.constants import UNSUPPORTED_FEATURES_MAP, Feature
from pcluster.validators.common import FailureLevel, Validator


class FeatureRegionValidator(Validator):
    """Validate if a feature is supported in the given region."""

    def _validate(self, feature: Feature, region: str):
        if not self._is_feature_supported(feature, region):
            self._add_failure(f"{feature.value} is not supported in region '{region}'.", FailureLevel.ERROR)

    @staticmethod
    def _is_feature_supported(feature: Feature, region: str):
        """
        Check if a feature is supported for the given region.

        If region is None, consider the region set in the environment.
        """
        _region = get_region() if region is None else region
        prefixes_of_unsupported_regions = UNSUPPORTED_FEATURES_MAP.get(feature, [])
        return all(not _region.startswith(region_prefix) for region_prefix in prefixes_of_unsupported_regions)
