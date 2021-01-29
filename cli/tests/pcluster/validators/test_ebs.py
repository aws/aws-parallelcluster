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

from pcluster.models.param import Param
from pcluster.schemas.cluster_schema import SharedStorageSchema
from pcluster.validators.ebs_validators import (
    EbsVolumeIopsValidator,
    EbsVolumeTypeSizeValidator,
)
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "section_dict, expected_message",
    [
        ({"VolumeType": "gp3", "Throughput": 125}, None),
        (
            {"VolumeType": "gp3", "Throughput": 100},
            "Throughput must be between 125 MB/s and 1000 MB/s when provisioning gp3 volumes.",
        ),
        (
            {"VolumeType": "gp3", "Throughput": 1001},
            "Throughput must be between 125 MB/s and 1000 MB/s when provisioning gp3 volumes.",
        ),
        ({"VolumeType": "gp3", "Throughput": 125, "Iops": 3000}, None),
        (
            {"VolumeType": "gp3", "Throughput": 760, "Iops": 3000},
            "Throughput to IOPS ratio of .* is too high",
        ),
        ({"VolumeType": "gp3", "Throughput": 760, "Iops": 10000}, None),
        (
            {"VolumeType": "gp3", "Throughput": 1001, "Iops": 2900},
            [
                "IOPS rate must be between 3000 and 16000 when provisioning gp3 volumes.",
                "Throughput must be between 125 MB/s and 1000 MB/s when provisioning gp3 volumes.",
            ],
        ),
    ],
)
def test_ebs_volume_throughput_validator(section_dict, expected_message):
    actual_failures = SharedStorageSchema().load({"MountDir": "/my/mount/point", "EBS": section_dict}).validate()
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "volume_type, volume_size, volume_iops, expected_message",
    [
        ("io1", 20, 120, None),
        ("io1", 20, 90, "IOPS rate must be between 100 and 64000 when provisioning io1 volumes."),
        ("io1", 20, 64001, "IOPS rate must be between 100 and 64000 when provisioning io1 volumes."),
        ("io1", 20, 1001, "IOPS to volume size ratio of .* is too high"),
        ("io2", 20, 120, None),
        ("io2", 20, 90, "IOPS rate must be between 100 and 256000 when provisioning io2 volumes."),
        ("io2", 20, 256001, "IOPS rate must be between 100 and 256000 when provisioning io2 volumes."),
        ("io2", 20, 20001, "IOPS to volume size ratio of .* is too high"),
        ("gp3", 20, 3000, None),
        ("gp3", 20, 2900, "IOPS rate must be between 3000 and 16000 when provisioning gp3 volumes."),
        ("gp3", 20, 16001, "IOPS rate must be between 3000 and 16000 when provisioning gp3 volumes."),
        ("gp3", 20, 10001, "IOPS to volume size ratio of .* is too high"),
    ],
)
def test_ebs_volume_iops_validators(volume_type, volume_size, volume_iops, expected_message):
    actual_failures = EbsVolumeIopsValidator()(Param(volume_type), Param(volume_size), Param(volume_iops))
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "volume_type, volume_size, expected_message",
    [
        ("standard", 15, None),
        ("standard", 0, "The size of standard volumes must be at least 1 GiB"),
        ("standard", 1025, "The size of standard volumes can not exceed 1024 GiB"),
        ("io1", 15, None),
        ("io1", 3, "The size of io1 volumes must be at least 4 GiB"),
        ("io1", 16385, "The size of io1 volumes can not exceed 16384 GiB"),
        ("io2", 15, None),
        ("io2", 3, "The size of io2 volumes must be at least 4 GiB"),
        ("io2", 65537, "The size of io2 volumes can not exceed 65536 GiB"),
        ("gp2", 15, None),
        ("gp2", 0, "The size of gp2 volumes must be at least 1 GiB"),
        ("gp2", 16385, "The size of gp2 volumes can not exceed 16384 GiB"),
        ("gp3", 15, None),
        ("gp3", 0, "The size of gp3 volumes must be at least 1 GiB"),
        ("gp3", 16385, "The size of gp3 volumes can not exceed 16384 GiB"),
        ("st1", 500, None),
        ("st1", 20, "The size of st1 volumes must be at least 500 GiB"),
        ("st1", 16385, "The size of st1 volumes can not exceed 16384 GiB"),
        ("sc1", 500, None),
        ("sc1", 20, "The size of sc1 volumes must be at least 500 GiB"),
        ("sc1", 16385, "The size of sc1 volumes can not exceed 16384 GiB"),
    ],
)
def test_ebs_volume_type_size_validator(volume_type, volume_size, expected_message):
    actual_failures = EbsVolumeTypeSizeValidator()(Param(volume_type), Param(volume_size))
    assert_failure_messages(actual_failures, expected_message)
