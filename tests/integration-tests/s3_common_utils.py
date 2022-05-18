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
import logging

import boto3
from assertpy import assert_that


def check_s3_read_resource(region, cluster, s3_policy_resources):
    check_role_inline_policy(region, cluster, enable_write_access=False, s3_policy_resources=s3_policy_resources)


def check_s3_read_write_resource(region, cluster, s3_policy_resources):
    check_role_inline_policy(region, cluster, enable_write_access=True, s3_policy_resources=s3_policy_resources)


def check_role_inline_policy(region, cluster, enable_write_access, s3_policy_resources):
    iam_client = boto3.client("iam", region_name=region)
    root_role = cluster.cfn_resources["RoleHeadNode"]
    statement = iam_client.get_role_policy(RoleName=root_role, PolicyName="S3Access")["PolicyDocument"]["Statement"]
    sid = "S3ReadWrite" if enable_write_access else "S3Read"
    for stm in statement:
        if stm["Sid"] == sid:
            resource = stm["Resource"]
            if not isinstance(s3_policy_resources, list):
                s3_policy_resources = [s3_policy_resources]
            if not isinstance(resource, list):
                resource = [resource]
            assert_that(resource).is_length(len(s3_policy_resources))
            for expected_resource in s3_policy_resources:
                # actual_resource contains arn:aws:s3 prefix,
                # while expected_resource does not necessarily have the prefix.
                # therefore we use endswith() to make the tests more flexible.
                assert_that(any([actual_resource.endswith(expected_resource) for actual_resource in resource]))


def get_policy_resources(config, enable_write_access):
    s3_access = config["HeadNode"]["Iam"]["S3Access"]
    for access in s3_access:
        if access["EnableWriteAccess"] == enable_write_access:
            bucket_name = access["BucketName"]
            key_name = access.get("KeyName")
            if key_name:
                return f"{bucket_name}/{key_name}"
            else:
                return [f"{bucket_name}", f"{bucket_name}/*"]
    logging.error("Bucket name couldn't be found in the configuration file.")
