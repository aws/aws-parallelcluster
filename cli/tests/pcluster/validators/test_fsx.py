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

from pcluster.schemas.cluster_schema import FsxSchema
from pcluster.validators.common import ConfigValidationError


@pytest.mark.parametrize(
    "section_dict, expected_error",
    [
        (
            {"StorageCapacity": 1, "DeploymentType": "SCRATCH_1"},
            "Capacity for FSx SCRATCH_1 filesystem is 1,200 GB, 2,400 GB or increments of 3,600 GB",
        ),
        (
            {"StorageCapacity": 3600, "DeploymentType": "SCRATCH_2"},
            "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB",
        ),
        (
            {"StorageCapacity": 3600, "DeploymentType": "PERSISTENT_1", "PerUnitStorageThroughput": 50},
            "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB",
        ),
        (
            {"StorageCapacity": 3601, "DeploymentType": "PERSISTENT_1", "PerUnitStorageThroughput": 50},
            "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB",
        ),
        (
            {"DeploymentType": "SCRATCH_1"},
            "When specifying 'fsx' section, the 'StorageCapacity' option must be specified",
        ),
        (
            {
                "StorageType": "HDD",
                "DeploymentType": "PERSISTENT_1",
                "StorageCapacity": 1801,
                "PerUnitStorageThroughput": 40,
            },
            "Capacity for FSx PERSISTENT HDD 40 MB/s/TiB file systems is increments of 1,800 GiB",
        ),
        (
            {
                "StorageType": "HDD",
                "DeploymentType": "PERSISTENT_1",
                "StorageCapacity": 6001,
                "PerUnitStorageThroughput": 12,
            },
            "Capacity for FSx PERSISTENT HDD 12 MB/s/TiB file systems is increments of 6,000 GiB",
        ),
    ],
)
def test_fsx_storage_capacity_validator(section_dict, expected_error):
    with pytest.raises(ConfigValidationError, match=expected_error):
        fsx_config = FsxSchema().load(section_dict)
        fsx_config.validate(raise_on_error=True)
