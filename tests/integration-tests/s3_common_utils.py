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
    check_role_inline_policy(region, cluster, "S3Read", s3_arn)


def check_s3_read_write_resource(region, cluster, s3_arn):
    check_role_inline_policy(region, cluster, "S3ReadWrite", s3_arn)


def check_role_inline_policy(region, cluster, policy_name, policy_statement):
    iam_client = boto3.client("iam", region_name=region)
    root_role = cluster.cfn_resources.get("RootRole")

    statement = (
        iam_client.get_role_policy(RoleName=root_role, PolicyName=policy_name)
        .get("PolicyDocument")
        .get("Statement")[0]
        .get("Resource")[0]
    )
    assert_that(statement).is_equal_to(policy_statement)
