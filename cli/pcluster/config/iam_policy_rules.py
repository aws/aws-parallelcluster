# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import abc
import sys

from pcluster.utils import policy_name_to_arn

if sys.version_info >= (3, 4):
    ABC = abc.ABC
else:
    ABC = abc.ABCMeta("ABC", (), {})


class EC2IAMPolicyInclusionRule(ABC):
    """
    Encapsulate logic for conditional inclusion of policies in the EC2IAMPolicies cfn parameter.

    Certain IAM policies must be included in the EC2IAMPolicies CloudFormation parameter based on
    a requested cluster configuration. This class provides an interface for deciding wheter a
    a specific configuration requires a specific policy.
    """

    @classmethod
    @abc.abstractmethod
    def policy_is_required(cls, pcluster_config):
        """Describe whether the policy represented by this class must be included."""
        return cls("Conditional policy inclusion rule not implemented.")

    @classmethod
    @abc.abstractmethod
    def get_policy(cls):
        """Return the ARN for the polciy that must be included."""
        return cls("Policy getter not implemented.")


class CloudWatchAgentServerPolicyInclusionRule(EC2IAMPolicyInclusionRule):
    """Include the CloudWatchServerAgentPolicy when CloudWatch logging is enabled."""

    @classmethod
    def policy_is_required(cls, pcluster_config):
        """Describe whether the policy represented by this class must be included."""
        cw_log_settings = pcluster_config.get_section("cluster").get_param("cw_log_settings")
        if cw_log_settings.value is not None:
            # A cw_log section was referenced from the config file's cluster section.
            # Use that section's "enable" parameter's value
            cw_log_section = pcluster_config.get_section("cw_log", cw_log_settings.value)
            should_include_policy = cw_log_section and cw_log_section.get_param_value("enable")
        else:
            # A cw_log section was not referenced from the config file's cluster section
            should_include_policy = cw_log_settings.referred_section_definition["params"]["enable"]["default"]
        return should_include_policy

    @classmethod
    def get_policy(cls):
        """Return the ARN for the polciy that must be included."""
        return policy_name_to_arn("CloudWatchAgentServerPolicy")


class AWSBatchFullAccessInclusionRule(EC2IAMPolicyInclusionRule):
    """Include the AWSBatchFullAccess when the scheduler is awsbatch."""

    @classmethod
    def policy_is_required(cls, pcluster_config):
        """Describe whether the policy represented by this class must be included."""
        return pcluster_config.get_section("cluster").get_param_value("scheduler") == "awsbatch"

    @classmethod
    def get_policy(cls):
        """Return the ARN for the polciy that must be included."""
        return policy_name_to_arn("AWSBatchFullAccess")
