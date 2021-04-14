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

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

from common.aws.aws_api import AWSApi
from pcluster.utils import get_region
from pcluster.validators.common import FailureLevel, Validator

LOGGER = logging.getLogger(__name__)


class AwsBatchRegionValidator(Validator):
    """
    AWS Batch region validator.

    Validate if the region is supported by AWS Batch.
    """

    def _validate(self, region: str):
        # TODO use dryrun
        if region in ["ap-northeast-3"]:
            self._add_failure(f"AWS Batch scheduler is not supported in region '{region}'.", FailureLevel.ERROR)


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


class BatchErrorMessageParsingException(Exception):
    """Exception for errors getting supported Batch instance types from CreateComputeEnvironment."""

    pass


class AwsBatchComputeInstanceTypeValidator(Validator):
    """
    AwsBatch compute instance type validator.

    Validate instance types and max vCPUs combination.
    """

    def _validate(self, instance_types, max_vcpus):
        supported_instances = _get_supported_batch_instance_types()
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
            vcpus = AWSApi.instance().ec2.get_instance_type_info(instance_types).vcpus_count()
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
        emsg = _get_cce_emsg_containing_supported_instance_types()
        parsed_instance_types_and_families = _parse_supported_instance_types_and_families_from_cce_emsg(emsg)
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


def _call_create_compute_environment_with_bad_instance_type():
    """
    Call CreateComputeEnvironment with a nonexistent instance type.

    For more information on why this would be done, see the docstring for
    _get_supported_instance_types_create_compute_environment_error_message.
    """
    nonexistent_instance_type = "p8.84xlarge"
    boto3.client("batch").create_compute_environment(
        computeEnvironmentName="dummy",
        type="MANAGED",
        computeResources={
            "type": "EC2",
            "minvCpus": 0,
            "maxvCpus": 0,
            "instanceTypes": [nonexistent_instance_type],
            "subnets": ["subnet-12345"],  # security group, subnet and role aren't checked
            "securityGroupIds": ["sg-12345"],
            "instanceRole": "ecsInstanceRole",
        },
        serviceRole="AWSBatchServiceRole",
    )


def _get_cce_emsg_containing_supported_instance_types():
    """
    Call CreateComputeEnvironment with nonexistent instance type and return error message.

    The returned error message is expected to have a list of supported instance types.
    """
    try:
        _call_create_compute_environment_with_bad_instance_type()
    except ClientError as e:
        # This is the expected behavior
        return e.response.get("Error").get("Message")
    except EndpointConnectionError:
        raise BatchErrorMessageParsingException(
            f"Could not connect to the batch endpoint for region {get_region()}. Probably Batch is not available."
        )
    else:
        # TODO: need to delete the compute environment?
        raise BatchErrorMessageParsingException(
            "Attempting to create a Batch ComputeEnvironment using a nonexistent instance type did not result "
            "in an error as expected."
        )


def _parse_supported_instance_types_and_families_from_cce_emsg(emsg):
    """
    Parse the supported instance types emsg, obtained by calling CreateComputeEnvironment.

    The string is expected to have the following format:
    Instance type can only be one of [r3, r4, m6g.xlarge, r5, optimal, ...]
    """
    match = re.search(r"be\s+one\s+of\s*\[(.*[0-9a-z.\-]+.*,.*)\]", emsg)
    if match:
        parsed_values = [instance_type_token.strip() for instance_type_token in match.group(1).split(",")]
        LOGGER.debug(
            "Parsed the following instance types and families from Batch CCE error message: %s", " ".join(parsed_values)
        )
        return parsed_values

    raise BatchErrorMessageParsingException(f"Could not parse supported instance types from the following: {emsg}")


class AwsBatchInstancesArchitectureCompatibilityValidator(Validator):
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
