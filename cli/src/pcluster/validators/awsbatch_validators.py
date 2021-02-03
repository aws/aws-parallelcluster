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

from pcluster.models.common import DynamicParam, FailureLevel, Param, Validator
from pcluster.utils import get_supported_architectures_for_instance_type, is_instance_type_format


class AwsbatchComputeResourceSizeValidator(Validator):
    """Awsbatch compute resource size validator."""

    def _validate(self, min_vcpus: Param, desired_vcpus: Param, max_vcpus: Param):
        """Validate min, desired and max vcpus combination."""
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


class AwsbatchInstancesArchitectureCompatibilityValidator(Validator):
    """Validate instance type and architecture combination."""

    def _validate(self, instance_types: Param, architecture: DynamicParam):
        """
        Verify that head node and compute instance types imply compatible architectures.

        When awsbatch is used as the scheduler, compute_instance_type can contain a CSV list.
        """
        head_node_architecture = architecture.value
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
            if head_node_architecture not in compute_architectures:
                self._add_failure(
                    "The specified compute instance type ({0}) supports the architectures {1}, none of which are "
                    "compatible with the architecture supported by the head node instance type ({2}).".format(
                        instance_type, compute_architectures, head_node_architecture
                    ),
                    FailureLevel.ERROR,
                    [instance_types],
                )
