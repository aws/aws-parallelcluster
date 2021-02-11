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
from common.boto3.common import AWSClientError
from common.boto3.ec2 import Ec2Client
from common.boto3.iam import IamClient
from pcluster import utils
from pcluster.models.common import FailureLevel, Validator
from pcluster.utils import policy_name_to_arn


class BaseAMIValidator(Validator):
    """
    Base AMI validator.

    Validate given ami id or image arn.
    """

    def _validate(self, image: str):
        ami_id = utils.get_ami_id(image)
        if not Ec2Client().describe_ami_id_offering(ami_id=ami_id):
            self._add_failure(f"The ami id '{ami_id}' is not supported.", FailureLevel.ERROR)


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

    def _validate(self, instance_type: str, parent_image: str):
        ami_id = utils.get_ami_id(parent_image)
        ami_architecture = utils.get_info_for_amis([ami_id])[0].get("Architecture")
        instance_architecture = utils.get_supported_architectures_for_instance_type(instance_type)
        if instance_architecture != ami_architecture:
            self._add_failure(
                "AMI {0}'s architecture ({1}) is incompatible with the architecture supported by the instance type {2} "
                "chosen ({3}). Use either a different AMI or a different instance type.".format(
                    ami_id, ami_architecture, instance_type, instance_architecture
                ),
                FailureLevel.ERROR,
            )


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
