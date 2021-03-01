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

from common.boto3.common import AWSExceptionHandler, Boto3Client


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
