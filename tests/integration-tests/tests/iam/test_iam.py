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
import os
from shutil import copyfile

import boto3
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor

from tests.common.assertions import assert_no_errors_in_logs


@pytest.mark.usefixtures("os", "instance")
def test_iam_roles(
    region,
    scheduler,
    common_pcluster_policies,
    role_factory,
    pcluster_config_reader,
    clusters_factory,
    cluster_model,
    test_datadir,
):
    is_awsbatch = scheduler == "awsbatch"
    if is_awsbatch:
        instance_policies = common_pcluster_policies["awsbatch_instance_policy"]
        lambda_policies = common_pcluster_policies["awsbatch_lambda_policy"]
    else:
        instance_policies = common_pcluster_policies["traditional_instance_policy"]
        lambda_policies = common_pcluster_policies["traditional_lambda_policy"]
    cluster_role_name = role_factory("ec2", [instance_policies])
    lambda_role_name = role_factory("lambda", [lambda_policies])

    # Copy the config file template for reuse in update.
    config_file_name = cluster_model + ".ini"
    config_file_path = os.path.join(str(test_datadir), config_file_name)
    updated_config_file_name = cluster_model + ".update.ini"
    updated_config_file_path = os.path.join(str(test_datadir), updated_config_file_name)
    copyfile(config_file_path, updated_config_file_path)

    cluster_config = pcluster_config_reader(
        config_file=config_file_name, ec2_iam_role=cluster_role_name, iam_lambda_role=lambda_role_name
    )
    cluster = clusters_factory(cluster_config)

    main_stack_name = "parallelcluster-" + cluster.name
    cfn_client = boto3.client("cloudformation", region_name=region)
    lambda_client = boto3.client("lambda", region_name=region)

    # Check all CloudFormation stacks after creation
    # If scheduler is awsbatch, there will still be IAM roles created.
    _check_lambda_role(cfn_client, lambda_client, main_stack_name, lambda_role_name, not is_awsbatch)

    # Test updating the iam_lambda_role
    updated_lambda_role_name = role_factory("lambda", [lambda_policies])
    assert_that(updated_lambda_role_name == lambda_role_name).is_false()
    cluster.config_file = str(
        pcluster_config_reader(
            config_file=updated_config_file_name,
            ec2_iam_role=cluster_role_name,
            iam_lambda_role=updated_lambda_role_name,
        )
    )
    cluster.update()

    # Check all CloudFormation stacks after update
    _check_lambda_role(cfn_client, lambda_client, main_stack_name, updated_lambda_role_name, not is_awsbatch)


def _check_lambda_role(cfn_client, lambda_client, stack_name, lambda_role_name, check_no_role_is_created):
    """Test lambda role is attached to all Lambda functions in the stack and its substack."""
    resources = cfn_client.describe_stack_resources(StackName=stack_name)["StackResources"]
    for resource in resources:
        resource_type = resource["ResourceType"]
        if check_no_role_is_created:
            # If check_no_role_is_created, check that there is no role created in the stack and its substack.
            assert_that(resource_type).is_not_equal_to("AWS::IAM::Role")
        if resource_type == "AWS::CloudFormation::Stack":
            # Recursively check substacks
            _check_lambda_role(
                cfn_client, lambda_client, resource["PhysicalResourceId"], lambda_role_name, check_no_role_is_created
            )
        if resource_type == "AWS::Lambda::Function":
            # Check the role is attached to the Lambda function
            lambda_function = lambda_client.get_function(FunctionName=resource["PhysicalResourceId"])["Configuration"]
            assert_that(lambda_role_name in lambda_function["Role"]).is_true()


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

    if scheduler == "awsbatch":
        _test_batch_access(remote_command_executor, region)

    assert_no_errors_in_logs(remote_command_executor, scheduler)


def _test_s3_access(remote_command_executor, region):
    logging.info("Testing S3 Access")
    result = remote_command_executor.run_remote_command(f"AWS_DEFAULT_REGION={region} aws s3 ls").stdout
    # An error occurred (AccessDenied) when calling the ListBuckets operation: Access Denied
    assert_that(result).does_not_contain("AccessDenied")


def _test_batch_access(remote_command_executor, region):
    logging.info("Testing AWS Batch Access")
    result = remote_command_executor.run_remote_command(
        f"AWS_DEFAULT_REGION={region} aws batch describe-compute-environments"
    ).stdout
    # An error occurred (AccessDeniedException) when calling the DescribeComputeEnvironments operation: ...
    assert_that(result).does_not_contain("AccessDeniedException")
