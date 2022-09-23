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
import os as os_lib
from shutil import copyfile

import boto3
import pytest
import yaml
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from s3_common_utils import check_s3_read_resource, check_s3_read_write_resource, get_policy_resources
from utils import wait_for_computefleet_changed

from tests.common.assertions import assert_no_errors_in_logs
from tests.schedulers.test_awsbatch import _test_job_submission as _test_job_submission_awsbatch


@pytest.mark.usefixtures("os", "instance")
def test_iam_roles(
    region,
    scheduler,
    create_roles_stack,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
):
    is_awsbatch = scheduler == "awsbatch"

    cfn_client, ec2_client, iam_client, lambda_client = _create_boto3_clients(region)

    compute_instance_profile, compute_instance_role, head_instance_role, lambda_role = _create_cluster_roles(
        create_roles_stack, "integ-tests-iam-cluster-roles", "cluster-roles.cfn.yaml", is_awsbatch
    )

    create_config, update_config = _get_config_create_and_update(test_datadir)

    cluster = _test_cluster_create(
        cfn_client,
        clusters_factory,
        compute_instance_profile,
        compute_instance_role,
        create_config,
        ec2_client,
        head_instance_role,
        iam_client,
        is_awsbatch,
        lambda_client,
        lambda_role,
        pcluster_config_reader,
    )

    _test_cluster_update(
        cfn_client,
        cluster,
        compute_instance_profile,
        compute_instance_role,
        create_roles_stack,
        ec2_client,
        head_instance_role,
        iam_client,
        is_awsbatch,
        lambda_client,
        lambda_role,
        pcluster_config_reader,
        update_config,
    )

    _test_cluster_scaling(cluster, is_awsbatch, region, scheduler_commands_factory)


def _get_config_create_and_update(test_datadir):
    # Copy the config file template for reuse in update.
    config_file_name = "pcluster.config.yaml"
    config_file_path = os_lib.path.join(str(test_datadir), config_file_name)
    updated_config_file_name = "pcluster.config.update.yaml"
    updated_config_file_path = os_lib.path.join(str(test_datadir), updated_config_file_name)
    copyfile(config_file_path, updated_config_file_path)
    return config_file_name, updated_config_file_name


def _create_boto3_clients(region):
    # Create boto3 client
    cfn_client = boto3.client("cloudformation", region_name=region)
    ec2_client = boto3.client("ec2", region_name=region)
    iam_client = boto3.client("iam", region_name=region)
    lambda_client = boto3.client("lambda", region_name=region)
    return cfn_client, ec2_client, iam_client, lambda_client


def _test_cluster_create(
    cfn_client,
    clusters_factory,
    compute_instance_profile,
    compute_instance_role,
    config_file_name,
    ec2_client,
    head_instance_role,
    iam_client,
    is_awsbatch,
    lambda_client,
    lambda_role,
    pcluster_config_reader,
):
    cluster_config = pcluster_config_reader(
        config_file=config_file_name,
        head_instance_role=head_instance_role,
        compute_instance_role=compute_instance_role,
        compute_instance_profile=compute_instance_profile,
        iam_lambda_role=lambda_role,
        min_count=1,
    )
    cluster = clusters_factory(cluster_config)
    # Check roles are attached to the resources
    # If scheduler is awsbatch, there will still be IAM roles created.
    _check_roles(
        cfn_client,
        ec2_client,
        iam_client,
        lambda_client,
        cluster.name,
        head_instance_role,
        compute_instance_role,
        lambda_role,
        not is_awsbatch,
    )
    return cluster


def _test_cluster_scaling(cluster, is_awsbatch, region, scheduler_commands_factory):
    remote_command_executor = RemoteCommandExecutor(cluster)
    if is_awsbatch:
        timeout = (
            120 if region.startswith("cn-") else 60
        )  # Longer timeout in china regions due to less reliable networking
        _test_job_submission_awsbatch(
            remote_command_executor, f"awsbsub --vcpus 2 --memory 256 --timeout {timeout} sleep 1"
        )
    else:
        scheduler_commands = scheduler_commands_factory(remote_command_executor)
        job_id = scheduler_commands.submit_command_and_assert_job_accepted(
            submit_command_args={"command": "sleep 1", "nodes": 1}
        )
        scheduler_commands.wait_job_completed(job_id)


def _test_cluster_update(
    cfn_client,
    cluster,
    compute_instance_profile,
    compute_instance_role,
    create_roles_stack,
    ec2_client,
    head_instance_role,
    iam_client,
    is_awsbatch,
    lambda_client,
    lambda_role,
    pcluster_config_reader,
    updated_config_file_name,
):
    (
        another_compute_instance_profile,
        another_compute_instance_role,
        another_head_instance_role,
        another_lambda_role,
    ) = _create_cluster_roles(
        create_roles_stack, "integ-tests-iam-cluster-roles", "cluster-roles.cfn.yaml", is_awsbatch
    )

    assert_that(another_lambda_role == lambda_role).is_false()
    assert_that(another_head_instance_role == head_instance_role).is_false()
    if not is_awsbatch:
        assert_that(another_compute_instance_profile == compute_instance_profile).is_false()
        assert_that(another_compute_instance_role == compute_instance_role).is_false()

    # Update cluster with new roles
    cluster.stop()
    wait_for_computefleet_changed(cluster, "DISABLED" if is_awsbatch else "STOPPED")
    cluster.update(
        str(
            pcluster_config_reader(
                config_file=updated_config_file_name,
                head_instance_role=another_head_instance_role,
                compute_instance_role=another_compute_instance_role,
                compute_instance_profile=another_compute_instance_profile,
                iam_lambda_role=another_lambda_role,
                min_count=0,
            )
        )
    )
    cluster.start()
    wait_for_computefleet_changed(cluster, "ENABLED" if is_awsbatch else "RUNNING")
    # Check new roles are attached to the resources
    _check_roles(
        cfn_client,
        ec2_client,
        iam_client,
        lambda_client,
        cluster.name,
        another_head_instance_role,
        another_compute_instance_role,
        another_lambda_role,
        not is_awsbatch,
    )


def _create_cluster_roles(create_roles_stack, stack_prefix, roles_file, is_awsbatch):
    cluster_roles_stack = create_roles_stack(stack_prefix=stack_prefix, roles_file=roles_file)
    if is_awsbatch:
        head_instance_role = cluster_roles_stack.cfn_outputs["HeadNodeRoleBatch"]
        lambda_role = cluster_roles_stack.cfn_outputs["CustomLambdaResourcesRoleBatch"]
        compute_instance_role = ""
        compute_instance_profile = ""
    else:
        head_instance_role = cluster_roles_stack.cfn_outputs["HeadNodeRoleSlurm"]
        compute_instance_profile = cluster_roles_stack.cfn_outputs["ComputeNodeInstanceProfileSlurm"]
        compute_instance_role = cluster_roles_stack.cfn_outputs["ComputeNodeRoleSlurm"]
        lambda_role = cluster_roles_stack.cfn_outputs["CustomLambdaResourcesRoleSlurm"]
    return compute_instance_profile, compute_instance_role, head_instance_role, lambda_role


def _check_roles(
    cfn_client,
    ec2_client,
    iam_client,
    lambda_client,
    stack_name,
    head_instance_role,
    compute_instance_role,
    lambda_role,
    check_no_role_is_created,
):
    """Test roles are attached to EC2 instances and Lambda functions."""
    resources = cfn_client.describe_stack_resources(StackName=stack_name)["StackResources"]
    for resource in resources:
        resource_type = resource["ResourceType"]
        if check_no_role_is_created:
            # If check_no_role_is_created, check that there is no role created in the stack.
            assert_that(resource_type).is_not_equal_to("AWS::IAM::Role")
        if resource_type == "AWS::Lambda::Function":
            # Check the role is attached to the Lambda function
            lambda_function = lambda_client.get_function(FunctionName=resource["PhysicalResourceId"])["Configuration"]
            assert_that(lambda_function["Role"]).is_equal_to(lambda_role)
        if resource_type == "AWS::EC2::Instance":
            # Check the role is attached to the EC2 instance
            instance_profile_arn = (
                ec2_client.describe_instances(InstanceIds=[resource["PhysicalResourceId"]])
                .get("Reservations")[0]
                .get("Instances")[0]
                .get("IamInstanceProfile")
                .get("Arn")
            )

            instance_roles_list = [
                role.get("Arn")
                for role in (
                    iam_client.get_instance_profile(
                        InstanceProfileName=_get_resource_name_from_resource_arn(instance_profile_arn)
                    )
                    .get("InstanceProfile")
                    .get("Roles")
                )
            ]

            if resource["LogicalResourceId"] == "HeadNode":
                assert_that(instance_roles_list).contains(head_instance_role)
            elif resource["LogicalResourceId"] == "ComputeNode":
                assert_that(instance_roles_list).contains(compute_instance_role)


def _get_resource_name_from_resource_arn(resource_arn):
    return resource_arn.rsplit("/", 1)[-1] if resource_arn else ""


@pytest.mark.usefixtures("os", "instance")
def test_iam_policies(region, scheduler, pcluster_config_reader, clusters_factory):
    """Test IAM Policies"""
    cluster_config = pcluster_config_reader(iam_policies=["arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"])
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_s3_access(remote_command_executor, region)

    if scheduler == "awsbatch":
        _test_batch_access(remote_command_executor, region)

    assert_no_errors_in_logs(remote_command_executor, scheduler)


def _test_s3_access(remote_command_executor, region):
    logging.info("Testing S3 Access")
    result = remote_command_executor.run_remote_command(f"AWS_DEFAULT_REGION={region} sudo aws s3 ls").stdout
    # An error occurred (AccessDenied) when calling the ListBuckets operation: Access Denied
    assert_that(result).does_not_contain("AccessDenied")


def _test_batch_access(remote_command_executor, region):
    logging.info("Testing AWS Batch Access")
    result = remote_command_executor.run_remote_command(
        f"AWS_DEFAULT_REGION={region} aws batch describe-compute-environments"
    ).stdout
    # An error occurred (AccessDeniedException) when calling the DescribeComputeEnvironments operation: ...
    assert_that(result).does_not_contain("AccessDeniedException")


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_s3_read_write_resource(region, pcluster_config_reader, s3_bucket_factory, clusters_factory, test_datadir):
    # Create S3 bucket for testing s3_read_resource and s3_read_write_resource
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    logging.info("bucket is {0}".format(bucket_name))
    bucket.upload_file(str(test_datadir / "s3_test_file"), "read_only/s3_test_file")
    bucket.upload_file(str(test_datadir / "s3_test_file"), "read_and_write/s3_test_file")

    cluster_config = pcluster_config_reader(bucket=bucket_name)
    cluster = clusters_factory(cluster_config)

    with open(cluster_config, encoding="utf-8") as conf_file:
        config = yaml.safe_load(conf_file)

    # Check S3 resources
    check_s3_read_resource(region, cluster, get_policy_resources(config, enable_write_access=False))
    check_s3_read_write_resource(region, cluster, get_policy_resources(config, enable_write_access=True))
