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

from botocore.exceptions import ClientError, EndpointConnectionError

from pcluster.aws.common import AWSExceptionHandler, Boto3Client, get_region

LOGGER = logging.getLogger(__name__)


class BatchClient(Boto3Client):
    """Batch Boto3 client."""

    def __init__(self):
        super().__init__("batch")

    @AWSExceptionHandler.handle_client_exception
    def enable_compute_environment(self, ce_name: str, min_vcpus: int, max_vcpus: int, desired_vcpus: int):
        """Enable compute environment."""
        self._client.update_compute_environment(
            computeEnvironment=ce_name,
            state="ENABLED",
            computeResources={
                "minvCpus": min_vcpus,
                "maxvCpus": max_vcpus,
                "desiredvCpus": desired_vcpus,
            },
        )

    @AWSExceptionHandler.handle_client_exception
    def disable_compute_environment(self, ce_name: str):
        """Disable compute environment."""
        self._client.update_compute_environment(computeEnvironment=ce_name, state="DISABLED")

    @AWSExceptionHandler.handle_client_exception
    def get_compute_environment_state(self, ce_name: str):
        """Get the state (ENABLED/DISABLED) of a compute environment."""
        return self._client.describe_compute_environments(computeEnvironments=[ce_name])["computeEnvironments"][0][
            "state"
        ]

    @AWSExceptionHandler.handle_client_exception
    def get_compute_environment_capacity(self, ce_name: str):
        """Describe compute environment and return ."""
        return (
            self._client.describe_compute_environments(computeEnvironments=[ce_name])
            .get("computeEnvironments")[0]
            .get("computeResources")
            .get("desiredvCpus")
        )

    def _get_cce_emsg_containing_supported_instance_types(self):
        """
        Call CreateComputeEnvironment with nonexistent instance type and return error message.

        The returned error message is expected to have a list of supported instance types.
        """
        try:
            self._call_create_compute_environment_with_bad_instance_type()
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

    def _call_create_compute_environment_with_bad_instance_type(self):
        """
        Call CreateComputeEnvironment with a nonexistent instance type.

        For more information on why this would be done, see the docstring for
        _get_supported_instance_types_create_compute_environment_error_message.
        """
        nonexistent_instance_type = "p8.84xlarge"
        self._client.create_compute_environment(
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

    def get_supported_instance_types_and_families(self):
        """
        Parse the supported instance types emsg, obtained by calling CreateComputeEnvironment.

        The string is expected to have the following format:
        Instance type can only be one of [r3, r4, m6g.xlarge, r5, optimal, ...]
        """
        emsg = self._get_cce_emsg_containing_supported_instance_types()
        match = re.search(r"be\s+one\s+of\s*\[(.*[0-9a-z.\-]+.*,.*)\]", emsg)
        if match:
            parsed_values = [instance_type_token.strip() for instance_type_token in match.group(1).split(",")]
            LOGGER.debug(
                "Parsed the following instance types and families from Batch CCE error message: %s",
                " ".join(parsed_values),
            )
            return parsed_values

        raise BatchErrorMessageParsingException(f"Could not parse supported instance types from the following: {emsg}")


class BatchErrorMessageParsingException(Exception):
    """Exception for errors getting supported Batch instance types from CreateComputeEnvironment."""

    pass
