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
from pcluster.validators.ebs_validators import (
    EbsVolumeIopsValidator,
    EbsVolumeSizeSnapshotValidator,
    EbsVolumeThroughputIopsValidator,
    EbsVolumeThroughputValidator,
    EbsVolumeTypeSizeValidator,
)
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "volume_type, volume_throughput, expected_message",
    [
        ("standard", 100, None),
        ("gp3", 100, "Throughput must be between 125 MB/s and 1000 MB/s when provisioning gp3 volumes."),
        ("gp3", 1001, "Throughput must be between 125 MB/s and 1000 MB/s when provisioning gp3 volumes."),
        ("gp3", 125, None),
        ("gp3", 760, None),
    ],
)
def test_ebs_volume_throughput_validator(volume_type, volume_throughput, expected_message):
    actual_failures = EbsVolumeThroughputValidator()(Param(volume_type), Param(volume_throughput))
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "volume_type, volume_iops, volume_throughput, expected_message",
    [
        ("standard", 100, 100, None),
        ("gp3", 100, 100, "Throughput to IOPS ratio of .* is too high; maximum is 0.25."),
        ("gp3", 250, 1000, "Throughput to IOPS ratio of .* is too high; maximum is 0.25."),
        ("gp3", 16000, 1000, None),
        ("gp3", 256000, 1000, None),
    ],
)
def test_ebs_volume_throughput_iops_validator(volume_type, volume_iops, volume_throughput, expected_message):
    actual_failures = EbsVolumeThroughputIopsValidator()(
        Param(volume_type), Param(volume_iops), Param(volume_throughput)
    )
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


@pytest.mark.parametrize(
    "volume_size, snapshot_size, state, partition, expected_message, raise_error_when_getting_snapshot_info",
    [
        (
            100,
            50,
            "completed",
            "aws-cn",
            "The specified volume size is larger than snapshot size.*"
            "https://docs.amazonaws.cn/AWSEC2/latest/UserGuide/recognize-expanded-volume-linux.html",
            False,
        ),
        (
            100,
            50,
            "completed",
            "aws-us-gov",
            "The specified volume size is larger than snapshot size.*"
            "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/recognize-expanded-volume-linux.html",
            False,
        ),
        (
            100,
            50,
            "incompleted",
            "aws-us-gov",
            "Snapshot .* is in state 'incompleted' not 'completed'",
            False,
        ),
        (50, 50, "completed", "partition", None, False),
        (
            100,
            120,
            "completed",
            "aws-us-gov",
            "The EBS volume size must not be smaller than 120, because it is the size of the provided snapshot .*",
            False,
        ),
        (
            100,
            None,
            "completed",
            "aws-cn",
            "Unable to get volume size for snapshot .*",
            False,
        ),
        (
            35,
            20,
            "completed",
            "aws",
            "some message",
            True,
        ),
    ],
)
def test_ebs_volume_size_snapshot_validator(
    volume_size,
    snapshot_size,
    state,
    partition,
    mocker,
    expected_message,
    raise_error_when_getting_snapshot_info,
):
    snapshot_id = "snap-1234567890abcdef0"
    describe_snapshots_response = {
        "Description": "This is my snapshot",
        "Encrypted": False,
        "VolumeId": "vol-049df61146c4d7901",
        "State": state,
        "VolumeSize": snapshot_size,
        "StartTime": "2014-02-28T21:28:32.000Z",
        "Progress": "100%",
        "OwnerId": "012345678910",
        "SnapshotId": snapshot_id,
    }

    if raise_error_when_getting_snapshot_info:
        mocker.patch(
            "pcluster.validators.ebs_validators.get_ebs_snapshot_info",
            side_effect=Exception(expected_message),
        )
    else:
        mocker.patch(
            "pcluster.validators.ebs_validators.get_ebs_snapshot_info",
            return_value=describe_snapshots_response,
        )
    mocker.patch(
        "pcluster.validators.ebs_validators.get_partition",
        return_value="aws-cn" if partition == "aws-cn" else "aws-us-gov",
    )

    actual_failures = EbsVolumeSizeSnapshotValidator()(Param(snapshot_id), Param(volume_size))
    assert_failure_messages(actual_failures, expected_message)
