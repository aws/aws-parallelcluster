# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.

from awacs.aws import Allow, Condition, Policy, Principal, Statement, StringLike
from awacs.sts import AssumeRole
from troposphere import GetAtt, Output, Ref, Sub, Template
from troposphere.iam import PolicyType as IAMPolicy
from troposphere.iam import Role
from utils import (
    filename_without_extension,
    get_resources,
    list_files_in_path,
    random_alphanumeric,
    read_json_file,
    snake_to_camel,
)

SCHEDULERS = ["awsbatch", "slurm"]
POLICY_DOCUMENTS = {
    scheduler: [file for file in list_files_in_path(get_resources("customer_roles", scheduler))]
    for scheduler in SCHEDULERS
}


class PermissionsTemplateBuilder:
    """Build troposphere CFN templates for IAM permissions resources."""

    def __init__(self, description="Permissions built by PermissionsTemplateBuilder"):
        self.__template = Template()
        self.__template.set_version("2010-09-09")
        self.__template.set_description(description)

    def build(self):
        """Build the template."""

        for scheduler in SCHEDULERS:
            self.__build_customer_role_for_scheduler(scheduler)

        return self.__template

    def __build_customer_role_for_scheduler(self, scheduler):
        customer_role = self.__template.add_resource(get_customer_role_for_scheduler(scheduler))

        for policy_document in POLICY_DOCUMENTS[scheduler]:
            self.__template.add_resource(get_policy_from_document(policy_document, customer_role))

        self.__template.add_output(
            Output(
                f"CustomerRole{scheduler.title()}",
                Value=GetAtt(customer_role, "Arn"),
                Description=f"The role used by the customer to manage a cluster with {scheduler}",
            )
        )


def get_customer_role_for_scheduler(scheduler):
    return Role(
        f"CustomerRole{scheduler.title()}",
        AssumeRolePolicyDocument=Policy(
            Statement=[
                Statement(
                    Effect=Allow,
                    Action=[AssumeRole],
                    Principal=Principal("AWS", Sub("arn:aws:iam::${AWS::AccountId}:root")),
                    Condition=Condition(
                        StringLike(
                            {
                                "aws:PrincipalArn": [
                                    Sub(
                                        "arn:${AWS::Partition}:iam::${AWS::AccountId}:role/"
                                        "Jenkins-JenkinsInstanceRole-*"
                                    )
                                ],
                            }
                        )
                    ),
                ),
            ]
        ),
    )


def get_policy_from_document(policy_document, role):
    policy_id = f"CustomerPolicy{snake_to_camel(filename_without_extension(policy_document))}"
    return IAMPolicy(
        policy_id,
        PolicyName=f"{policy_id}{random_alphanumeric()}",
        PolicyDocument=read_json_file(policy_document),
        Roles=[Ref(role)],
    )
