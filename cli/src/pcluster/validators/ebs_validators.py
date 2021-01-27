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

    def validate(self, volume_type, volume_size):
        """Validate given instance type."""
        """
        Validate that the EBS volume size matches the chosen volume type.

        The default value of volume_size for EBS volumes is 20 GiB.
        The volume size of standard ranges from 1 GiB - 1 TiB(1024 GiB)
        The volume size of gp2 and gp3 ranges from 1 GiB - 16 TiB(16384 GiB)
        The volume size of io1 and io2 ranges from 4 GiB - 16 TiB(16384 GiB)
        The volume sizes of st1 and sc1 range from 500 GiB - 16 TiB(16384 GiB)
        """

        volume_type_value = volume_type.value
        volume_size_value = volume_size.value

        if volume_type_value in EBS_VOLUME_TYPE_TO_VOLUME_SIZE_BOUNDS:
            min_size, max_size = EBS_VOLUME_TYPE_TO_VOLUME_SIZE_BOUNDS.get(volume_type_value)
            if volume_size_value > max_size:
                self._add_failure(
                    "The size of {0} volumes can not exceed {1} GiB".format(volume_type_value, max_size),
                    FailureLevel.ERROR,
                    [volume_size],
                )
            elif volume_size_value < min_size:
                self._add_failure(
                    "The size of {0} volumes must be at least {1} GiB".format(volume_type_value, min_size),
                    FailureLevel.ERROR,
                    [volume_size],
                )

        return self._failures


class EbsVolumeThroughputValidator(Validator):
    """EBS volume throughput validator."""

    def validate(self, volume_type, volume_throughput):
        """Validate gp3 throughput."""
        volume_type_value = volume_type.value
        volume_throughput_value = volume_throughput.value

        if volume_type_value == "gp3":
            min_throughput, max_throughput = 125, 1000
            if volume_throughput_value < min_throughput or volume_throughput_value > max_throughput:
                self._add_failure(
                    "Throughput must be between {min_throughput} MB/s and {max_throughput} MB/s when provisioning "
                    "{volume_type} volumes.".format(
                        min_throughput=min_throughput, max_throughput=max_throughput, volume_type=volume_type_value
                    ),
                    FailureLevel.ERROR,
                    [volume_throughput],
                )
        return self._failures


class EbsVolumeThroughputIopsValidator(Validator):
    """EBS volume throughput to iops ratio validator."""

    def validate(self, volume_type, volume_iops, volume_throughput):
        """Validate gp3 throughput."""
        volume_type_value = volume_type.value
        volume_iops_value = volume_iops.value
        volume_throughput_value = volume_throughput.value

        volume_throughput_to_iops_ratio = 0.25

        if volume_type_value == "gp3":
            if (
                volume_throughput_value
                and volume_throughput_value > volume_iops_value * volume_throughput_to_iops_ratio
            ):
                self._add_failure(
                    "Throughput to IOPS ratio of {0} is too high; maximum is 0.25.".format(
                        float(volume_throughput_value) / float(volume_iops_value)
                    ),
                    FailureLevel.ERROR,
                    [volume_throughput],
                )
        return self._failures


class EbsVolumeIopsValidator(Validator):
    """EBS volume IOPS validator."""

    def validate(self, volume_type, volume_size, volume_iops):
        """Validate IOPS value in respect of volume type."""
        if not (volume_type.valid and volume_size.valid):
            # volume_type and volume_size need to be valid to continue this validation.
            return self._failures

        volume_type_value = volume_type.value
        volume_size_value = volume_size.value
        volume_iops_value = volume_iops.value

        if volume_type_value in EBS_VOLUME_IOPS_BOUNDS:
            min_iops, max_iops = EBS_VOLUME_IOPS_BOUNDS.get(volume_type_value)
            if volume_iops_value and (volume_iops_value < min_iops or volume_iops_value > max_iops):
                self._add_failure(
                    f"IOPS rate must be between {min_iops} and {max_iops}"
                    f" when provisioning {volume_type_value} volumes.",
                    FailureLevel.ERROR,
                    [volume_iops],
                )
            if (
                volume_iops_value
                and volume_iops_value > volume_size_value * EBS_VOLUME_TYPE_TO_IOPS_RATIO[volume_type_value]
            ):
                self._add_failure(
                    "IOPS to volume size ratio of {0} is too high; maximum is {1}.".format(
                        float(volume_iops_value) / float(volume_size_value),
                        EBS_VOLUME_TYPE_TO_IOPS_RATIO[volume_type_value],
                    ),
                    FailureLevel.ERROR,
                    [volume_iops],
                )

        return self._failures
