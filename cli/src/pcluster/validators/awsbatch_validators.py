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

from pcluster.models.common import FailureLevel, Param, Validator
from pcluster.utils import (
    InstanceTypeInfo,
    get_region,
    get_supported_architectures_for_instance_type,
    get_supported_batch_instance_types,
    is_instance_type_format,
)


class AwsbatchRegionValidator(Validator):
    """
    AWS Batch region validator.

    Validate if the region is supported by AWS Batch.
    """

    def _validate(self, region: str):
        # TODO use dryrun
        if region in ["ap-northeast-3"]:
            self._add_failure(f"AWS Batch scheduler is not supported in the '{region}' region", FailureLevel.ERROR)


class AwsbatchComputeResourceSizeValidator(Validator):
    """
    Awsbatch compute resource size validator.

    Validate min, desired and max vcpus combination.
    """

    def _validate(self, min_vcpus: Param, desired_vcpus: Param, max_vcpus: Param):
        if desired_vcpus.value < min_vcpus.value:
            self._add_failure(
                "The number of desired vcpus must be greater than or equal to min vcpus",
                FailureLevel.ERROR,
                [min_vcpus, desired_vcpus],
            )

        if desired_vcpus.value > max_vcpus.value:
            self._add_failure(
                "The number of desired vcpus must be fewer than or equal to max vcpus",
                FailureLevel.ERROR,
                [max_vcpus, desired_vcpus],
            )

        if max_vcpus.value < min_vcpus.value:
            self._add_failure(
                "Max vcpus must be greater than or equal to min vcpus", FailureLevel.ERROR, [max_vcpus, min_vcpus]
            )


class AwsbatchComputeInstanceTypeValidator(Validator):
    """
    Awsbatch compute instance type validator.

    Validate instance types and max vcpus combination.
    """

    def _validate(self, instance_types: Param, max_vcpus: Param):
        supported_instances = get_supported_batch_instance_types()
        if supported_instances:
            for instance_type in instance_types.value.split(","):
                if not instance_type.strip() in supported_instances:
                    self._add_failure(
                        "compute instance type '{0}' is not supported by AWS Batch in region '{1}'".format(
                            instance_type, get_region()
                        ),
                        FailureLevel.ERROR,
                        [instance_types],
                    )
        else:
            self._add_failure(
                "Unable to get instance types supported by awsbatch. Skipping compute_instance_type validation",
                FailureLevel.WARNING,
            )

        if "," not in instance_types.value and "." in instance_types.value:
            # if the type is not a list, and contains dot (nor optimal, nor a family)
            # validate instance type against max vcpus limit
            vcpus = InstanceTypeInfo.init_from_instance_type(instance_types.value).vcpus_count()
            if vcpus <= 0:
                self._add_failure(
                    "Unable to get the number of vcpus for the compute instance type '{0}'. "
                    "Skipping instance type against max vcpus validation".format(instance_types.value),
                    FailureLevel.WARNING,
                )
            else:
                if max_vcpus.value < vcpus:
                    self._add_failure(
                        "max vcpus must be greater than or equal to {0}, that is the number of vcpus "
                        "available for the {1} that you selected as compute instance type".format(
                            vcpus, instance_types.value
                        ),
                        FailureLevel.ERROR,
                        [instance_types, max_vcpus],
                    )


class AwsbatchInstancesArchitectureCompatibilityValidator(Validator):
    """
    Validate instance type and architecture combination.

    Verify that head node and compute instance types imply compatible architectures.
    With AWS Batch, compute instance type can contain a CSV list.
    """

    def _validate(self, instance_types: Param, architecture: str):
        for instance_type in instance_types.value.split(","):
            # When awsbatch is used as the scheduler instance families can be used.
            # Don't attempt to validate architectures for instance families, as it would require
            # guessing a valid instance type from within the family.
            if not is_instance_type_format(instance_type) and instance_type != "optimal":
                self._add_failure(
                    "Not validating architecture compatibility for compute instance type {0} because it does not have "
                    "the expected format".format(instance_type),
                    FailureLevel.INFO,
                )
                continue
            compute_architectures = get_supported_architectures_for_instance_type(instance_type)
            if architecture not in compute_architectures:
                self._add_failure(
                    "The specified compute instance type ({0}) supports the architectures {1}, none of which are "
                    "compatible with the architecture supported by the head node instance type ({2}).".format(
                        instance_type, compute_architectures, architecture
                    ),
                    FailureLevel.ERROR,
                    [instance_types],
                )
