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
import re

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.aws.iam import IamClient
from pcluster.constants import IAM_NAME_PREFIX_LENGTH_LIMIT, IAM_PATH_LENGTH_LIMIT
from pcluster.utils import get_resource_name_from_resource_arn, policy_name_to_arn, split_resource_prefix
from pcluster.validators.common import FailureLevel, Validator


class RoleValidator(Validator):
    """
    IAM Role validator.

    Verify the given role exists.
    """

    def _validate(self, role_arn: str):
        try:
            AWSApi.instance().iam.get_role(get_resource_name_from_resource_arn(role_arn))
        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)


class InstanceProfileValidator(Validator):
    """
    IAM Instance Profile validator.

    Verify the given instance profile exists.
    """

    def _validate(self, instance_profile_arn: str):
        try:
            AWSApi.instance().iam.get_instance_profile(get_resource_name_from_resource_arn(instance_profile_arn))
        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)


class IamPolicyValidator(Validator):
    """
    EC2 IAM Policy validator.

    Verify the given policy is correct.
    """

    def _validate(self, policy: str):
        try:
            IamClient().get_policy(policy)
        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)


class IamResourcePrefixValidator(Validator):
    """
    Iam Resource Prefix Validator.

    Verify if the Resource Prefix is compliant with IAM naming conventions
    """

    IAM_PATH_NAME_REGEX = r"^((/[a-zA-Z0-9_.,+@=-]+)+)/"
    IAM_NAME_PREFIX_REGEX = r"^[a-zA-Z0-9_.,+@=-]+$"

    def _validate(self, resource_prefix: str):
        if not (
            re.match(IamResourcePrefixValidator.IAM_PATH_NAME_REGEX, resource_prefix)
            or re.match(IamResourcePrefixValidator.IAM_NAME_PREFIX_REGEX, resource_prefix)
        ):
            self._add_failure(
                f"Unsupported format for ResourcePrefix {resource_prefix}. "
                f"Please refer to our official documentation for further details.",
                FailureLevel.ERROR,
            )
        iam_path, iam_name_prefix = split_resource_prefix(resource_prefix)
        if iam_name_prefix and (len(iam_name_prefix) > IAM_NAME_PREFIX_LENGTH_LIMIT):
            self._add_failure(
                f"Length of Name Prefix {iam_name_prefix} must be less than {IAM_NAME_PREFIX_LENGTH_LIMIT} characters. "
                f"Please refer to our official documentation for further details.",
                FailureLevel.ERROR,
            )
        if iam_path and (len(iam_path) > IAM_PATH_LENGTH_LIMIT):
            self._add_failure(
                f"Length of Path {iam_path} must be less than {IAM_PATH_LENGTH_LIMIT} characters. "
                f"Please refer to our official documentation for further details.",
                FailureLevel.ERROR,
            )


class AdditionalIamPolicyValidator(IamPolicyValidator):
    """
    EC2 IAM Policy validator.

    Verify the given policy is correct.
    """

    def _validate(self, policy: str):
        if policy not in self._get_base_additional_iam_policies():
            super()._validate(policy)

    @staticmethod
    def _get_base_additional_iam_policies():
        return [policy_name_to_arn("CloudWatchAgentServerPolicy")]
