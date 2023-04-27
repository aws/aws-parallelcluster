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
import logging
import re
from typing import List

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import get_region
from pcluster.validators.common import FailureLevel, Validator

LOGGER = logging.getLogger(__name__)


class AwsBatchComputeResourceSizeValidator(Validator):
    """
    AwsBatch compute resource size validator.

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


class AwsBatchComputeInstanceTypeValidator(Validator):
    """
    AwsBatch compute instance type validator.

    Validate instance types and max vCPUs combination.
    """

    def _validate(self, instance_types: List[str], max_vcpus: int):
        supported_instances = _get_supported_batch_instance_types()
        if supported_instances:
            for instance_type in instance_types:
                if instance_type not in supported_instances:
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

        if len(instance_types) == 1 and "." in instance_types[0]:
            # if the type is not a list, and contains dot (nor optimal, nor a family)
            # validate instance type against max vcpus limit
            vcpus = AWSApi.instance().ec2.get_instance_type_info(instance_types[0]).vcpus_count()
            if vcpus <= 0:
                self._add_failure(
                    f"Unable to get the number of vCPUs for the compute instance type '{instance_types[0]}'. "
                    "Skipping instance type against max vCPUs validation.",
                    FailureLevel.WARNING,
                )
            else:
                if max_vcpus < vcpus:
                    self._add_failure(
                        f"Max vCPUs must be greater than or equal to {vcpus}, that is the number of vCPUs "
                        f"available for the {instance_types[0]} that you selected as compute instance type.",
                        FailureLevel.ERROR,
                    )


def _get_supported_batch_instance_types():
    """
    Get the instance types supported by Batch in the desired region.

    This is done by calling Batch's CreateComputeEnvironment with a bad
    instance type and parsing the error message.
    """
    supported_instance_types = AWSApi.instance().ec2.list_instance_types()
    supported_instance_families = _get_instance_families_from_types(supported_instance_types)
    known_exceptions = ["optimal"]
    supported_instance_types_and_families = supported_instance_types + supported_instance_families + known_exceptions
    try:
        parsed_instance_types_and_families = AWSApi.instance().batch.get_supported_instance_types_and_families()
        if _batch_instance_types_and_families_are_supported(
            parsed_instance_types_and_families, supported_instance_types_and_families
        ):
            supported_batch_types = parsed_instance_types_and_families
        else:
            supported_batch_types = supported_instance_types_and_families
    except Exception as e:
        # When the instance types supported by Batch can't be parsed from an error message,
        # log the reason for the failure and return instead a list of all instance types
        # supported in the region.
        LOGGER.debug(
            "Failed to parse supported Batch instance types from a CreateComputeEnvironment error message: %s", e
        )
        supported_batch_types = supported_instance_types_and_families
    return supported_batch_types


def _get_instance_families_from_types(instance_types):
    """Return a list of instance families represented by the given list of instance types."""
    families = set()
    for instance_type in instance_types:
        match = re.search(r"^([a-z0-9\-]+)\.", instance_type)
        if match:
            families.add(match.group(1))
        else:
            LOGGER.debug("Unable to parse instance family for instance type %s", instance_type)
    return list(families)


def _batch_instance_types_and_families_are_supported(candidate_types_and_families, known_types_and_families):
    """Return a boolean describing whether the instance types and families parsed from Batch API are known."""
    unknowns = [candidate for candidate in candidate_types_and_families if candidate not in known_types_and_families]
    if unknowns:
        LOGGER.debug("Found the following unknown instance types/families: %s", " ".join(unknowns))
    return not unknowns


class AwsBatchInstancesArchitectureCompatibilityValidator(Validator):
    """
    Validate instance type and architecture combination.

    Verify that head node and compute instance types imply compatible architectures.
    With AWS Batch, compute instance type can contain a CSV list.
    """

    def _validate(self, instance_types: List[str], architecture: str):
        for instance_type in instance_types:
            # When awsbatch is used as the scheduler instance families can be used.
            # Don't attempt to validate architectures for instance families, as it would require
            # guessing a valid instance type from within the family.
            if not self._is_instance_type_format(instance_type) and instance_type != "optimal":
                self._add_failure(
                    f"Not validating architecture compatibility for compute instance type {instance_type} "
                    "because it does not have the expected format.",
                    FailureLevel.INFO,
                )
                continue
            compute_architectures = self._get_supported_architectures_for_instance_type(instance_type)
            if architecture not in compute_architectures:
                self._add_failure(
                    f"The specified compute instance type ({instance_type}) supports"
                    f" the architectures {compute_architectures}, none of which is "
                    f"compatible with the architecture ({architecture}) supported by the head node instance type.",
                    FailureLevel.ERROR,
                )

    @staticmethod
    def _get_supported_architectures_for_instance_type(instance_type):
        """Get a list of architectures supported for the given instance type."""
        # "optimal" compute instance type (when using batch) implies the use of instances from the
        # C, M, and R instance families, and thus an x86_64 architecture.
        # see https://docs.aws.amazon.com/batch/latest/userguide/compute_environment_parameters.html
        if instance_type == "optimal":
            return ["x86_64"]

        return AWSApi.instance().ec2.get_supported_architectures(instance_type)

    @staticmethod
    def _is_instance_type_format(candidate):
        """Return a boolean describing whether or not candidate is of the format of an instance type."""
        return re.search(r"^([a-z0-9\-]+)\.", candidate) is not None


class AwsBatchFsxValidator(Validator):
    """
    Validator for FSx and AWS Batch scheduler.

    Fail if using AWS Batch and FSx for Lustre, ONTAP, OpenZFS, File Cache are not supported yet.
    """

    def _validate(self):
        self._add_failure("FSx is not supported when using AWS Batch as scheduler.", FailureLevel.ERROR)
