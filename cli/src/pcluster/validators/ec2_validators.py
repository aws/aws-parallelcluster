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
from pcluster import utils
from pcluster.models.param import Param
from pcluster.validators.common import FailureLevel, Validator


class BaseAMIValidator(Validator):
    """Base AMI validator."""

    def validate(self, image: Param):
        """Validate given ami id or image arn."""
        ami_id = utils.get_ami_id(image.value)
        if not Ec2Client().describe_ami_id_offering(ami_id=ami_id):
            self._add_failure(f"The ami id '{ami_id}' is not supported.", FailureLevel.CRITICAL)
        return self._failures


class InstanceTypeValidator(Validator):
    """EC2 Instance type validator."""

    def validate(self, instance_type: Param):
        """Validate given instance type."""
        if instance_type.value not in Ec2Client().describe_instance_type_offerings():
            self._add_failure(f"The instance type '{instance_type.value}' is not supported.", FailureLevel.CRITICAL)
        return self._failures


class InstanceTypeBaseAMICompatibleValidator(Validator):
    """EC2 Instance type and base ami compatible validator."""

    def validate(self, instance_type: Param, parent_image: Param):
        """Validate given instance type and ami id are compatible."""
        ami_id = utils.get_ami_id(parent_image.value)
        ami_architecture = utils.get_info_for_amis([ami_id])[0].get("Architecture")
        instance_architecture = utils.get_supported_architectures_for_instance_type(instance_type.value)
        if instance_architecture != ami_architecture:
            self._add_failure(
                "AMI {0}'s architecture ({1}) is incompatible with the architecture supported by the instance type {2} "
                "chosen ({3}). Use either a different AMI or a different instance type.".format(
                    ami_id, ami_architecture, instance_type.value, instance_architecture
                ),
                FailureLevel.CRITICAL,
            )
        return self._failures
