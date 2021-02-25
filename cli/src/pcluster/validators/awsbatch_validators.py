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

from pcluster.utils import (
    InstanceTypeInfo,
    get_region,
    get_supported_architectures_for_instance_type,
    get_supported_batch_instance_types,
    is_instance_type_format,
)
from pcluster.validators.common import FailureLevel, Validator


class AwsbatchRegionValidator(Validator):
    """
    AWS Batch region validator.

    Validate if the region is supported by AWS Batch.
    """

    def _validate(self, region: str):
        # TODO use dryrun
        if region in ["ap-northeast-3"]:
            self._add_failure(f"AWS Batch scheduler is not supported in region '{region}'.", FailureLevel.ERROR)


class AwsbatchComputeResourceSizeValidator(Validator):
    """
    Awsbatch compute resource size validator.

    Validate min, desired and max vCPUs combination.
    """

    def _validate(self, min_vcpus: int, desired_vcpus: int, max_vcpus: int):
        if desired_vcpus < min_vcpus:
            self._add_failure(
                "The number of desired vCPUs must be greater than or equal to min vCPUs.",
                FailureLevel.ERROR,
            )

        if desired_vcpus > max_vcpus:
            self._add_failure(
                "The number of desired vCPUs must be fewer than or equal to max vCPUs.",
                FailureLevel.ERROR,
            )

        if max_vcpus < min_vcpus:
            self._add_failure(
                "Max vCPUs must be greater than or equal to min vCPUs.",
                FailureLevel.ERROR,
            )


class AwsbatchComputeInstanceTypeValidator(Validator):
    """
    Awsbatch compute instance type validator.

    Validate instance types and max vCPUs combination.
    """

    def _validate(self, instance_types, max_vcpus):
        supported_instances = get_supported_batch_instance_types()
        if supported_instances and instance_types:
            for instance_type in instance_types.split(","):
                if not instance_type.strip() in supported_instances:
                    self._add_failure(
                        f"Compute instance type '{instance_type}' is not supported"
                        f" by AWS Batch in region '{get_region()}'.",
                        FailureLevel.ERROR,
                    )
        else:
            self._add_failure(
                "Unable to get instance types supported by AWS Batch. Skipping instance type validation.",
                FailureLevel.WARNING,
            )

        if "," not in instance_types and "." in instance_types:
            # if the type is not a list, and contains dot (nor optimal, nor a family)
            # validate instance type against max vcpus limit
            vcpus = InstanceTypeInfo.init_from_instance_type(instance_types).vcpus_count()
            if vcpus <= 0:
                self._add_failure(
                    f"Unable to get the number of vCPUs for the compute instance type '{instance_types}'. "
                    "Skipping instance type against max vCPUs validation.",
                    FailureLevel.WARNING,
                )
            else:
                if max_vcpus < vcpus:
                    self._add_failure(
                        f"Max vCPUs must be greater than or equal to {vcpus}, that is the number of vCPUs "
                        f"available for the {instance_types} that you selected as compute instance type.",
                        FailureLevel.ERROR,
                    )


class AwsbatchInstancesArchitectureCompatibilityValidator(Validator):
    """
    Validate instance type and architecture combination.

    Verify that head node and compute instance types imply compatible architectures.
    With AWS Batch, compute instance type can contain a CSV list.
    """

    def _validate(self, instance_types, architecture: str):
        if instance_types:
            for instance_type in instance_types.split(","):
                # When awsbatch is used as the scheduler instance families can be used.
                # Don't attempt to validate architectures for instance families, as it would require
                # guessing a valid instance type from within the family.
                if not is_instance_type_format(instance_type) and instance_type != "optimal":
                    self._add_failure(
                        f"Not validating architecture compatibility for compute instance type {instance_type} "
                        "because it does not have the expected format.",
                        FailureLevel.INFO,
                    )
                    continue
                compute_architectures = get_supported_architectures_for_instance_type(instance_type)
                if architecture not in compute_architectures:
                    self._add_failure(
                        f"The specified compute instance type ({instance_type}) supports"
                        f" the architectures {compute_architectures}, none of which is "
                        f"compatible with the architecture ({architecture}) supported by the head node instance type.",
                        FailureLevel.ERROR,
                    )
