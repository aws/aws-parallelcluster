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
from marshmallow import ValidationError

from pcluster.schemas.cluster_schema import EfsSchema, SharedStorageSchema


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        (
            {"ThroughputMode": "bursting", "ProvisionedThroughput": 1024},
            "When specifying provisioned throughput, the throughput mode must be set to provisioned",
        ),
        (
            {"ThroughputMode": "provisioned"},
            "When specifying throughput mode to provisioned, the provisioned throughput option must be specified",
        ),
        ({"ThroughputMode": "provisioned", "ProvisionedThroughput": 1024}, None),
    ],
)
def test_efs_validator(section_dict, expected_message):
    _load_and_assert_error(EfsSchema(), section_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"MountDir": "NONE"}, "NONE cannot be used as a mount directory"),
        ({"MountDir": "/NONE"}, "/NONE cannot be used as a mount directory"),
        ({"MountDir": "/NONEshared"}, None),
    ],
)
def test_mount_dir_validator(section_dict, expected_message):
    _load_and_assert_error(SharedStorageSchema(), section_dict, expected_message)


def _load_and_assert_error(schema, section_dict, expected_message):
    if expected_message:
        with pytest.raises(ValidationError, match=expected_message):
            schema.load(section_dict)
    else:
        schema.load(section_dict, partial=True)
