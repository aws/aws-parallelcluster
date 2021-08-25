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
from pcluster import imagebuilder_utils
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.validators.common import FailureLevel, Validator


class InstanceTypeValidator(Validator):
    """
    EC2 Instance type validator.

    Verify the given instance type is a supported one.
    """

    def _validate(self, instance_type: str):
        if instance_type not in AWSApi.instance().ec2.list_instance_types():
            self._add_failure(f"The instance type '{instance_type}' is not supported.", FailureLevel.ERROR)


class InstanceTypeBaseAMICompatibleValidator(Validator):
    """EC2 Instance type and base ami compatibility validator."""

    def _validate(self, instance_type: str, image: str):
        image_info = self._validate_base_ami(image)
        instance_architectures = self._validate_instance_type(instance_type)
        if image_info and instance_architectures:
            ami_architecture = image_info.architecture
            if ami_architecture not in instance_architectures:
                self._add_failure(
                    "AMI {0}'s architecture ({1}) is incompatible with the architecture supported by the "
                    "instance type {2} chosen ({3}). Use either a different AMI or a different instance type.".format(
                        image_info.id, ami_architecture, instance_type, instance_architectures
                    ),
                    FailureLevel.ERROR,
                )

    def _validate_base_ami(self, image: str):
        try:
            ami_id = imagebuilder_utils.get_ami_id(image)
            image_info = AWSApi.instance().ec2.describe_image(ami_id=ami_id)
            return image_info
        except AWSClientError:
            self._add_failure(f"Invalid image '{image}'.", FailureLevel.ERROR)
            return None

    def _validate_instance_type(self, instance_type: str):
        if instance_type not in AWSApi.instance().ec2.list_instance_types():
            self._add_failure(
                f"The instance type '{instance_type}' is not supported.",
                FailureLevel.ERROR,
            )
            return []
        return AWSApi.instance().ec2.get_supported_architectures(instance_type)


class KeyPairValidator(Validator):
    """
    EC2 key pair validator.

    Verify the given key pair is correct.
    """

    def _validate(self, key_name: str):
        if key_name:
            try:
                AWSApi.instance().ec2.describe_key_pair(key_name)
            except AWSClientError as e:
                self._add_failure(str(e), FailureLevel.ERROR)
        else:
            self._add_failure(
                "If you do not specify a key pair, you can't connect to the instance unless you choose an AMI "
                "that is configured to allow users another way to log in",
                FailureLevel.WARNING,
            )


class PlacementGroupIdValidator(Validator):  # TODO: add tests
    """Placement group id validator."""

    def _validate(self, placement_group_id: str):
        if placement_group_id:
            try:
                AWSApi.instance().ec2.describe_placement_group(placement_group_id)
            except AWSClientError as e:
                self._add_failure(str(e), FailureLevel.ERROR)


class CapacityTypeValidator(Validator):
    """Compute type validator. Verify that specified compute type is compatible with specified instance type."""

    def _validate(self, capacity_type, instance_type):
        compute_type_value = capacity_type.value.lower()
        supported_usage_classes = AWSApi.instance().ec2.get_instance_type_info(instance_type).supported_usage_classes()

        if not supported_usage_classes:
            self._add_failure(
                f"Could not check support for usage class '{compute_type_value}' with instance type '{instance_type}'",
                FailureLevel.WARNING,
            )
        elif compute_type_value not in supported_usage_classes:
            self._add_failure(
                f"Usage type '{compute_type_value}' not supported with instance type '{instance_type}'",
                FailureLevel.ERROR,
            )


class AmiOsCompatibleValidator(Validator):
    """
    node AMI and OS compatibility validator.

    If image has tag of OS, compare AMI OS with cluster OS, else print out a warning message.
    """

    def _validate(self, os: str, image_id: str):
        image_info = AWSApi.instance().ec2.describe_image(ami_id=image_id)
        image_os = image_info.image_os
        if image_os:
            if image_os != os:
                self._add_failure(
                    f"The OS of node AMI {image_id} is {image_os}, it is not compatible with cluster OS {os}.",
                    FailureLevel.ERROR,
                )
        else:
            self._add_failure(
                f"Could not check node AMI {image_id} OS and cluster OS {os} compatibility, please make sure "
                f"they are compatible before cluster creation and update operations.",
                FailureLevel.WARNING,
            )
