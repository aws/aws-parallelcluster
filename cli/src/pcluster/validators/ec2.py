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

from common.boto3.ec2 import Ec2Client
from pcluster.validators.common import FailureLevel, Validator


class InstanceTypeValidator(Validator):
    """EC2 Instance type validator."""

    def __call__(self, instance_type: str):
        if instance_type not in Ec2Client().describe_instance_type_offerings():
            self._add_failure(f"The instance type '{instance_type}' is not supported.", FailureLevel.CRITICAL)
        return self._failures
