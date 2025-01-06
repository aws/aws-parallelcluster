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

from pcluster.constants import Feature
from pcluster.validators.feature_validators import FeatureRegionValidator

from .utils import assert_failure_messages


@pytest.mark.parametrize(
    "feature, supported, expected_message",
    [
        (Feature.BATCH, True, None),
        (Feature.BATCH, False, "AWS Batch scheduler is not supported in region 'WHATEVER-REGION'"),
        (Feature.FSX_LUSTRE, True, None),
        (Feature.FSX_LUSTRE, False, "FSx Lustre is not supported in region 'WHATEVER-REGION'"),
        (Feature.FSX_ONTAP, True, None),
        (Feature.FSX_ONTAP, False, "FSx ONTAP is not supported in region 'WHATEVER-REGION'"),
        (Feature.FSX_OPENZFS, True, None),
        (Feature.FSX_OPENZFS, False, "FSx OpenZfs is not supported in region 'WHATEVER-REGION'"),
        (Feature.SLURM_DATABASE, True, None),
        (Feature.SLURM_DATABASE, False, "SLURM Database is not supported in region 'WHATEVER-REGION'"),
        (Feature.CAPACITY_BLOCK, True, None),
        (Feature.CAPACITY_BLOCK, False, "Capacity Block is not supported in region 'WHATEVER-REGION'"),
        (Feature.CLUSTER_HEALTH_METRICS, True, None),
        (Feature.CLUSTER_HEALTH_METRICS, False, "Cluster Health Metrics is not supported in region 'WHATEVER-REGION'"),
        (Feature.NLB_SECURITY_GROUP, True, None),
        (
            Feature.NLB_SECURITY_GROUP,
            False,
            "Network Load Balancer Security Group is not supported in region 'WHATEVER-REGION'",
        ),
    ],
)
def test_feature_region_validator(mocker, feature, supported, expected_message):
    is_feature_supported = mocker.patch("pcluster.utils.is_feature_supported", return_value=supported)
    actual_failures = FeatureRegionValidator().execute(feature=feature, region="WHATEVER-REGION")
    is_feature_supported.assert_called_once()
    if supported:
        assert_that(actual_failures).is_empty()
    else:
        assert_failure_messages(actual_failures, expected_message)
