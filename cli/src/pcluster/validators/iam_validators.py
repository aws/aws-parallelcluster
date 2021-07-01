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
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.aws.iam import IamClient
from pcluster.utils import policy_name_to_arn
from pcluster.validators.common import FailureLevel, Validator


class RoleValidator(Validator):
    """
    IAM Role validator.

    Verify the given role exists.
    """

    def _validate(self, role_arn: str):
        try:
            AWSApi.instance().iam.get_role(_get_resource_name_from_resource_arn(role_arn))
        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)


class InstanceProfileValidator(Validator):
    """
    IAM Instance Profile validator.

    Verify the given instance profile exists.
    """

    def _validate(self, instance_profile_arn: str):
        try:
            AWSApi.instance().iam.get_instance_profile(_get_resource_name_from_resource_arn(instance_profile_arn))
        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)


class AdditionalIamPolicyValidator(Validator):
    """
    EC2 IAM Policy validator.

    Verify the given policy is correct.
    """

    def _validate(self, policy: str):
        try:
            if policy not in self._get_base_additional_iam_policies():
                IamClient().get_policy(policy)
        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)

    @staticmethod
    def _get_base_additional_iam_policies():
        return [policy_name_to_arn("CloudWatchAgentServerPolicy"), policy_name_to_arn("AWSBatchFullAccess")]


def _get_resource_name_from_resource_arn(resource_arn):
    return resource_arn.rsplit("/", 1)[-1] if resource_arn else ""
