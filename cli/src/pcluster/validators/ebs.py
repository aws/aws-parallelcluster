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
from pcluster.config.validators import (
    EBS_VOLUME_IOPS_BOUNDS,
    EBS_VOLUME_TYPE_TO_IOPS_RATIO,
    EBS_VOLUME_TYPE_TO_VOLUME_SIZE_BOUNDS,
)
from pcluster.validators.common import FailureLevel, Validator


class EbsVolumeTypeSizeValidator(Validator):
    """EBS volume type and size validator."""

    def __call__(self, volume_type, volume_size):
        """Validate given instance type."""
        """
        Validate that the EBS volume size matches the chosen volume type.

        The default value of volume_size for EBS volumes is 20 GiB.
        The volume size of standard ranges from 1 GiB - 1 TiB(1024 GiB)
        The volume size of gp2 and gp3 ranges from 1 GiB - 16 TiB(16384 GiB)
        The volume size of io1 and io2 ranges from 4 GiB - 16 TiB(16384 GiB)
        The volume sizes of st1 and sc1 range from 500 GiB - 16 TiB(16384 GiB)
        """

        if volume_type in EBS_VOLUME_TYPE_TO_VOLUME_SIZE_BOUNDS:
            min_size, max_size = EBS_VOLUME_TYPE_TO_VOLUME_SIZE_BOUNDS.get(volume_type)
            if volume_size > max_size:
                self._add_failure(
                    "The size of {0} volumes can not exceed {1} GiB".format(volume_type, max_size), FailureLevel.ERROR
                )
            elif volume_size < min_size:
                self._add_failure(
                    "The size of {0} volumes must be at least {1} GiB".format(volume_type, min_size), FailureLevel.ERROR
                )

        return self._failures


class EbsVolumeThroughputValidator(Validator):
    """EBS volume throughput validator."""

    def __call__(self, volume_type, volume_iops, volume_throughput):
        """Validate gp3 throughput."""
        volume_throughput_to_iops_ratio = 0.25

        if volume_type == "gp3":
            min_throughput, max_throughput = 125, 1000
            if volume_throughput < min_throughput or volume_throughput > max_throughput:
                self._add_failure(
                    "Throughput must be between {min_throughput} MB/s and {max_throughput} MB/s when provisioning "
                    "{volume_type} volumes.".format(
                        min_throughput=min_throughput, max_throughput=max_throughput, volume_type=volume_type
                    ),
                    FailureLevel.ERROR,
                )
            if volume_throughput and volume_throughput > volume_iops * volume_throughput_to_iops_ratio:
                self._add_failure(
                    "Throughput to IOPS ratio of {0} is too high; maximum is 0.25.".format(
                        float(volume_throughput) / float(volume_iops)
                    ),
                    FailureLevel.ERROR,
                )
        return self._failures


class EbsVolumeIopsValidator(Validator):
    """EBS volume IOPS validator."""

    def __call__(self, volume_type, volume_size, volume_iops):
        """Validate IOPS value in respect of volume type."""
        if volume_type in EBS_VOLUME_IOPS_BOUNDS:
            min_iops, max_iops = EBS_VOLUME_IOPS_BOUNDS.get(volume_type)
            if volume_iops and (volume_iops < min_iops or volume_iops > max_iops):
                self._add_failure(
                    f"IOPS rate must be between {min_iops} and {max_iops} when provisioning {volume_type} volumes.",
                    FailureLevel.ERROR,
                )
            if volume_iops and volume_iops > volume_size * EBS_VOLUME_TYPE_TO_IOPS_RATIO[volume_type]:
                self._add_failure(
                    "IOPS to volume size ratio of {0} is too high; maximum is {1}.".format(
                        float(volume_iops) / float(volume_size), EBS_VOLUME_TYPE_TO_IOPS_RATIO[volume_type]
                    ),
                    FailureLevel.ERROR,
                )

        return self._failures
