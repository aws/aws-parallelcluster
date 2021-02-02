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

from pcluster.schemas.cluster_schema import (
    AwsbatchComputeResourceSchema, EfsSchema, FsxSchema, SharedStorageSchema, SlurmComputeResourceSchema,
)

DUMMY_COMPUTE_RESOURCE = {"InstanceType": "test"}


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"MinCount": -1}, "Must be greater than or equal"),
        ({"MinCount": 0}, None),
        ({"SpotPrice": -1.1}, "Must be greater than or equal"),
        ({"SpotPrice": 0}, None),
        ({"MaxCount": 0}, "Must be greater than or equal"),
        ({"MaxCount": 1}, None),
    ],
)
def test_slurm_compute_resource_validator(section_dict, expected_message):
    section_dict.update(DUMMY_COMPUTE_RESOURCE)
    _load_and_assert_error(SlurmComputeResourceSchema(), section_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"MinvCpus": -1}, "Must be greater than or equal"),
        ({"MinvCpus": 0}, None),
        ({"DesiredvCpus": -1}, "Must be greater than or equal"),
        ({"DesiredvCpus": 0}, None),
        ({"MaxvCpus": 0}, "Must be greater than or equal"),
        ({"MaxvCpus": 1}, None),
    ],
)
def test_awsbatch_compute_resource_validator(section_dict, expected_message):
    section_dict.update(DUMMY_COMPUTE_RESOURCE)
    _load_and_assert_error(AwsbatchComputeResourceSchema(), section_dict, expected_message)


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


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"FileSystemId": "fs-0123456789abcdef0"}, None),
        (
            {"FileSystemId": "fs-0123456789abcdef0", "StorageCapacity": 3600},
            "storage_capacity is ignored when specifying an existing Lustre file system",
        ),
    ],
)
def test_fsx_ignored_parameters_validator(section_dict, expected_message):
    _load_and_assert_error(FsxSchema(), section_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        (
            {"ImportedFileChunkSize": 0},
            "has a minimum size of 1 MiB, and max size of 512,000 MiB",
        ),
        (
            {"ImportedFileChunkSize": 1},
            None,
        ),
        (
            {"ImportedFileChunkSize": 10},
            None,
        ),
        (
            {"ImportedFileChunkSize": 512000},
            None,
        ),
        (
            {"ImportedFileChunkSize": 512001},
            "has a minimum size of 1 MiB, and max size of 512,000 MiB",
        ),
    ],
)
def test_fsx_imported_file_chunk_size_validator(section_dict, expected_message):
    _load_and_assert_error(FsxSchema(), section_dict, expected_message)


def _load_and_assert_error(schema, section_dict, expected_message):
    if expected_message:
        with pytest.raises(ValidationError, match=expected_message):
            schema.load(section_dict)
    else:
        schema.load(section_dict, partial=True)
