# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import boto3
from assertpy import assert_that


def check_s3_read_resource(region, cluster, s3_arn):
    check_role_inline_policy(region, cluster, enable_write_access=False, policy_statement=s3_arn)


def check_s3_read_write_resource(region, cluster, s3_arn):
    check_role_inline_policy(region, cluster, enable_write_access=True, policy_statement=s3_arn)


def check_role_inline_policy(region, cluster, enable_write_access, policy_statement):
    iam_client = boto3.client("iam", region_name=region)
    root_role = cluster.cfn_resources["RoleHeadNode"]
    statement = iam_client.get_role_policy(RoleName=root_role, PolicyName="S3Access")["PolicyDocument"]["Statement"]
    sid = "S3ReadWrite" if enable_write_access else "S3Read"
    for stm in statement:
        if stm["Sid"] == sid:
            assert_that(policy_statement in stm["Resource"]).is_true()
            return
