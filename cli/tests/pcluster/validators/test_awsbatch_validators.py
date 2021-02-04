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
from assertpy import assert_that

from pcluster.models.common import Param
from pcluster.validators.awsbatch_validators import (
    AwsbatchComputeInstanceTypeValidator,
    AwsbatchComputeResourceSizeValidator,
    AwsbatchInstancesArchitectureCompatibilityValidator,
)

from .utils import assert_failure_messages, mock_instance_type_info


@pytest.mark.parametrize(
    "instance_type, max_vcpus, expected_message",
    [
        ("t2.micro", 2, "max vcpus must be greater than or equal to 4"),
        ("t2.micro", 4, None),
        ("p4d.24xlarge", 4, None),
        ("c4.xlarge", 4, "is not supported"),
        ("t2", 2, None),  # t2 family
        ("optimal", 4, None),
    ],
)
def test_compute_instance_type_validator(mocker, instance_type, max_vcpus, expected_message):
    mocker.patch("pcluster.utils.get_supported_instance_types", return_value=["t2.micro", "p4d.24xlarge"])
    mock_instance_type_info(mocker, instance_type)
    actual_failures = AwsbatchComputeInstanceTypeValidator().execute(Param(instance_type), Param(max_vcpus))
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "min_vcpus, desired_vcpus, max_vcpus, expected_message",
    [
        (1, 2, 3, None),
        (
            3,
            2,
            3,
            "desired vcpus must be greater than or equal to min vcpus",
        ),
        (
            1,
            4,
            3,
            "desired vcpus must be fewer than or equal to max vcpus",
        ),
        (
            4,
            4,
            3,
            "Max vcpus must be greater than or equal to min vcpus",
        ),
    ],
)
def test_awsbatch_compute_resource_size_validator(min_vcpus, desired_vcpus, max_vcpus, expected_message):
    actual_failures = AwsbatchComputeResourceSizeValidator().execute(
        Param(min_vcpus), Param(desired_vcpus), Param(max_vcpus)
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "head_node_architecture, compute_architecture, compute_instance_types, expected_message",
    [
        ("x86_64", "x86_64", "optimal", None),
        # Function to get supported architectures shouldn't be called because compute instance types arg
        # are instance families.
        ("x86_64", None, "m6g", "Not validating architecture"),
        ("x86_64", None, "c5", "Not validating architecture"),
        # The validator must handle the case where compute instance type is a CSV list
        ("arm64", "arm64", "m6g.xlarge,r6g.xlarge", None),
        (
            "x86_64",
            "arm64",
            "m6g.xlarge,r6g.xlarge",
            "none of which are compatible with the architecture supported by the head node instance type",
        ),
    ],
)
def test_awsbatch_instances_architecture_compatibility_validator(
    mocker, head_node_architecture, compute_architecture, compute_instance_types, expected_message
):
    def _internal_is_instance_type(itype):
        return "." in itype or itype == "optimal"

    supported_architectures_patch = mocker.patch(
        "pcluster.validators.awsbatch_validators.get_supported_architectures_for_instance_type",
        return_value=[compute_architecture],
    )
    is_instance_type_patch = mocker.patch(
        "pcluster.validators.awsbatch_validators.is_instance_type_format", side_effect=_internal_is_instance_type
    )

    instance_types = compute_instance_types.split(",")

    actual_failures = AwsbatchInstancesArchitectureCompatibilityValidator().execute(
        Param(compute_instance_types), head_node_architecture
    )
    assert_failure_messages(actual_failures, expected_message)
    if expected_message:
        assert_that(len(actual_failures)).is_equal_to(len(instance_types))

    non_instance_families = [
        instance_type for instance_type in instance_types if _internal_is_instance_type(instance_type)
    ]
    assert_that(supported_architectures_patch.call_count).is_equal_to(len(non_instance_families))
    assert_that(is_instance_type_patch.call_count).is_equal_to(len(instance_types))
