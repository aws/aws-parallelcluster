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

from pcluster.constants import Feature
from pcluster.validators.feature_validators import FeatureRegionValidator

from .utils import assert_failure_messages


@pytest.mark.parametrize(
    "feature, region, expected_message",
    [
        (Feature.BATCH, "ap-northeast-3", "AWS Batch scheduler is not supported in region 'ap-northeast-3'"),
        (Feature.BATCH, "us-iso-east-1", "AWS Batch scheduler is not supported in region 'us-iso-east-1'"),
        (Feature.BATCH, "us-iso-west-1", "AWS Batch scheduler is not supported in region 'us-iso-west-1'"),
        (Feature.BATCH, "us-isob-east-1", "AWS Batch scheduler is not supported in region 'us-isob-east-1'"),
        (Feature.BATCH, "us-isoWHATEVER", "AWS Batch scheduler is not supported in region 'us-isoWHATEVER'"),
        (Feature.DCV, "us-iso-east-1", "NICE DCV is not supported in region 'us-iso-east-1'"),
        (Feature.DCV, "us-iso-west-1", "NICE DCV is not supported in region 'us-iso-west-1'"),
        (Feature.DCV, "us-isob-east-1", "NICE DCV is not supported in region 'us-isob-east-1'"),
        (Feature.DCV, "us-isoWHATEVER", "NICE DCV is not supported in region 'us-isoWHATEVER'"),
        (Feature.FSX_LUSTRE, "us-iso-east-1", "FSx Lustre is not supported in region 'us-iso-east-1'"),
        (Feature.FSX_LUSTRE, "us-iso-west-1", "FSx Lustre is not supported in region 'us-iso-west-1'"),
        (Feature.FSX_LUSTRE, "us-isob-east-1", "FSx Lustre is not supported in region 'us-isob-east-1'"),
        (Feature.FSX_LUSTRE, "us-isoWHATEVER", "FSx Lustre is not supported in region 'us-isoWHATEVER'"),
        (Feature.FSX_ONTAP, "us-iso-east-1", "FSx ONTAP is not supported in region 'us-iso-east-1'"),
        (Feature.FSX_ONTAP, "us-iso-west-1", "FSx ONTAP is not supported in region 'us-iso-west-1'"),
        (Feature.FSX_ONTAP, "us-isob-east-1", "FSx ONTAP is not supported in region 'us-isob-east-1'"),
        (Feature.FSX_ONTAP, "us-isoWHATEVER", "FSx ONTAP is not supported in region 'us-isoWHATEVER'"),
        (Feature.FSX_OPENZFS, "us-iso-east-1", "FSx OpenZfs is not supported in region 'us-iso-east-1'"),
        (Feature.FSX_OPENZFS, "us-iso-west-1", "FSx OpenZfs is not supported in region 'us-iso-west-1'"),
        (Feature.FSX_OPENZFS, "us-isob-east-1", "FSx OpenZfs is not supported in region 'us-isob-east-1'"),
        (Feature.FSX_OPENZFS, "us-isoWHATEVER", "FSx OpenZfs is not supported in region 'us-isoWHATEVER'"),
        (Feature.SLURM_DATABASE, "us-isoWHATEVER", "SLURM Database is not supported in region 'us-isoWHATEVER'"),
        (Feature.BATCH, "WHATEVER-ELSE", None),
        (Feature.DCV, "WHATEVER-ELSE", None),
        (Feature.FSX_LUSTRE, "WHATEVER-ELSE", None),
        (Feature.FSX_ONTAP, "WHATEVER-ELSE", None),
        (Feature.FSX_OPENZFS, "WHATEVER-ELSE", None),
        (Feature.SLURM_DATABASE, "WHATEVER-ELSE", None),
    ],
)
def test_feature_region_validator(feature, region, expected_message):
    actual_failures = FeatureRegionValidator().execute(feature=feature, region=region)
    assert_failure_messages(actual_failures, expected_message)
