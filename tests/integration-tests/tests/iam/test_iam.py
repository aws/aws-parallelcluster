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
import configparser
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor

from tests.common.assertions import assert_no_errors_in_logs


@pytest.mark.regions(["ap-northeast-2"])
@pytest.mark.schedulers(["slurm", "awsbatch"])
@pytest.mark.oss(["alinux2"])
@pytest.mark.usefixtures("os", "instance")
def test_iam_policies(region, scheduler, pcluster_config_reader, clusters_factory):
    """Test IAM Policies"""
    cluster_config = pcluster_config_reader(
        iam_policies="arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess, arn:aws:iam::aws:policy/AWSBatchFullAccess"
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_s3_access(remote_command_executor, region)
    _test_batch_access(remote_command_executor, region)

    assert_no_errors_in_logs(remote_command_executor, scheduler)


def _test_s3_access(remote_command_executor, region):
    logging.info("Testing S3 Access")
    result = remote_command_executor.run_remote_command("AWS_DEFAULT_REGION={0} aws s3 ls".format(region)).stdout
    # An error occurred (AccessDenied) when calling the ListBuckets operation: Access Denied
    assert_that(result).does_not_contain("AccessDenied")


def _test_batch_access(remote_command_executor, region):
    logging.info("Testing AWS Batch Access")
    result = remote_command_executor.run_remote_command(
        "AWS_DEFAULT_REGION={0} aws batch describe-compute-environments".format(region)
    ).stdout
    # An error occurred (AccessDeniedException) when calling the DescribeComputeEnvironments operation: ...
    assert_that(result).does_not_contain("AccessDeniedException")


@pytest.mark.regions(["us-east-1"])
@pytest.mark.schedulers(["slurm", "awsbatch"])
@pytest.mark.oss(["ubuntu1804"])
@pytest.mark.usefixtures("os", "instance")
def test_s3_read_write_resource(
        region,
        pcluster_config_reader,
        clusters_factory,
        s3_bucket_factory,
        test_datadir,
):
    # Create S3 bucket for testing s3_read_resource and s3_read_write_resource
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    logging.info("bucket is {0}".format(bucket_name))
    bucket.upload_file(str(test_datadir / "s3_test_file"), "read_only/s3_test_file")
    bucket.upload_file(str(test_datadir / "s3_test_file"), "read_and_write/s3_test_file")

    cluster_config = pcluster_config_reader(bucket=bucket_name)
    cluster = clusters_factory(cluster_config)

    config = configparser.ConfigParser()
    config.read(cluster_config)
    # Check S3 resources
    _check_s3_read_resource(region, cluster, config.get("cluster default", "s3_read_resource"))
    _check_s3_read_write_resource(region, cluster, config.get("cluster default", "s3_read_write_resource"))


def _check_s3_read_resource(region, cluster, s3_arn):
    _check_role_inline_policy(region, cluster, "S3Read", s3_arn)


def _check_s3_read_write_resource(region, cluster, s3_arn):
    _check_role_inline_policy(region, cluster, "S3ReadWrite", s3_arn)


def _check_role_inline_policy(region, cluster, policy_name, policy_statement):
    iam_client = boto3.client("iam", region_name=region)
    root_role = cluster.cfn_resources.get("RootRole")

    statement = (
        iam_client.get_role_policy(RoleName=root_role, PolicyName=policy_name)
            .get("PolicyDocument")
            .get("Statement")[0]
            .get("Resource")[0]
    )
    assert_that(statement).is_equal_to(policy_statement)
