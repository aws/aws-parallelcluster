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
from common import imagebuilder_utils
from common.boto3.common import AWSClientError
from common.boto3.ec2 import Ec2Client
from common.boto3.iam import IamClient
from pcluster import utils
from pcluster.utils import policy_name_to_arn
from pcluster.validators.common import FailureLevel, Validator


class InstanceTypeValidator(Validator):
    """
    EC2 Instance type validator.

    Verify the given instance type is a supported one.
    """

    def _validate(self, instance_type: str):
        if instance_type not in Ec2Client().describe_instance_type_offerings():
            self._add_failure(
                f"The instance type '{instance_type}' is not supported.",
                FailureLevel.ERROR,
            )


class InstanceTypeBaseAMICompatibleValidator(Validator):
    """EC2 Instance type and base ami compatibility validator."""

    def _validate(self, instance_type: str, image: str):
        ami_id, ami_info = self._validate_base_ami(image)
        instance_architectures = self._validate_instance_type(instance_type)
        if ami_id is not None and instance_architectures:
            ami_architecture = ami_info.get("Architecture", "")
            if ami_architecture not in instance_architectures:
                self._add_failure(
                    "AMI {0}'s architecture ({1}) is incompatible with the architecture supported by the "
                    "instance type {2} "
                    "chosen ({3}). Use either a different AMI or a different instance type.".format(
                        ami_id, ami_architecture, instance_type, instance_architectures
                    ),
                    FailureLevel.ERROR,
                )

    def _validate_base_ami(self, image: str):
        try:
            ami_id = imagebuilder_utils.get_ami_id(image)
            ami_info = Ec2Client().describe_image(ami_id=ami_id)
            return ami_id, ami_info
        except AWSClientError:
            self._add_failure(f"Invalid image '{image}'.", FailureLevel.ERROR)
            return None, None

    def _validate_instance_type(self, instance_type: str):
        if instance_type not in Ec2Client().describe_instance_type_offerings():
            self._add_failure(
                f"The instance type '{instance_type}' is not supported.",
                FailureLevel.ERROR,
            )
            return []
        return utils.get_supported_architectures_for_instance_type(instance_type)


class AdditionalIamPolicyValidator(Validator):  # TODO add test
    """
    EC2 IAM Policy validator.

    Verify the given policy is correct.
    """

    def _validate(self, iam_policy: str):
        try:
            if iam_policy not in self._get_base_additional_iam_policies():
                IamClient().get_policy(iam_policy)
        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)

    @staticmethod
    def _get_base_additional_iam_policies():
        return [policy_name_to_arn("CloudWatchAgentServerPolicy"), policy_name_to_arn("AWSBatchFullAccess")]


class KeyPairValidator(Validator):  # TODO add test
    """
    EC2 key pair validator.

    Verify the given key pair is correct.
    """

    def _validate(self, key_name: str):
        try:
            Ec2Client().describe_key_pair(key_name)
        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)


class PlacementGroupIdValidator(Validator):  # TODO: add tests
    """Placement group id validator."""

    def _validate(self, placement_group_id: str):
        if placement_group_id:
            try:
                Ec2Client().describe_placement_group(placement_group_id)
            except AWSClientError as e:
                self._add_failure(str(e), FailureLevel.ERROR)
