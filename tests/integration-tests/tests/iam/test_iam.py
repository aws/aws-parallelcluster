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
from cfn_stacks_factory import CfnStack, CfnStacksFactory
from cfn_tools import load_yaml
from framework.tests_configuration.config_utils import get_all_regions
from remote_command_executor import RemoteCommandExecutor
from s3_common_utils import check_s3_read_resource, check_s3_read_write_resource, get_policy_resources
from troposphere.iam import ManagedPolicy
from troposphere.template_generator import TemplateGenerator
from utils import generate_stack_name, get_arn_partition, wait_for_computefleet_changed

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
    cluster_config = pcluster_config_reader(
        iam_policies=[f"arn:{get_arn_partition(region)}:iam::aws:policy/AmazonS3ReadOnlyAccess"]
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_s3_access(remote_command_executor, region)

    if scheduler == "awsbatch":
        _test_batch_access(remote_command_executor, region)

    assert_no_errors_in_logs(remote_command_executor, scheduler)


def _test_s3_access(remote_command_executor, region):
    logging.info("Testing S3 Access")
    result = remote_command_executor.run_remote_command(f"sudo aws s3 ls --region {region}").stdout
    # An error occurred (AccessDenied) when calling the ListBuckets operation: Access Denied
    assert_that(result).does_not_contain("AccessDenied")


def _test_batch_access(remote_command_executor, region):
    logging.info("Testing AWS Batch Access")
    result = remote_command_executor.run_remote_command(
        f"aws batch describe-compute-environments --region {region}"
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


@pytest.mark.parametrize("iam_resource_prefix", ["/path-prefix/name-prefix-"])
@pytest.mark.usefixtures("os", "instance")
def test_iam_resource_prefix(
    initialize_resource_prefix_cli_creds,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
    s3_bucket_factory,
    s3_bucket,
    iam_resource_prefix,
):
    cli_credentials = initialize_resource_prefix_cli_creds(
        role_config_file=os_lib.path.join("..", "iam_policies", "user-role.cfn.yaml"),
        iam_resource_prefix=iam_resource_prefix,
    )
    if cli_credentials:
        for region, creds in cli_credentials.items():
            bucket_name = s3_bucket
            cfn_client, _, iam_client, _ = _create_boto3_clients(region)
            create_config, _ = _get_config_create_and_update(test_datadir)
            cluster_config = pcluster_config_reader(
                config_file=create_config, min_count=1, bucket=bucket_name, iam_resource_prefix=iam_resource_prefix
            )

            cluster = clusters_factory(cluster_config, custom_cli_credentials=creds)
            _test_iam_resource_in_cluster(region, cfn_client, iam_client, cluster.name, iam_resource_prefix)


def _update_paramters_and_conditions(parameters, conditions, iam_path, iam_name_prefix):
    """
    Convert Default and Allowed Values property of Parameters and Conditions Section in CFN template to String.
    And Update the Default property of CustomIamPathPrefix and CustomIamNamePrefix
    with test specific path and name prefix.
    """
    for key, _ in parameters.items():
        if key == "CustomIamPathPrefix":
            parameters.get(key).properties.update({"Default": iam_path[1:-1]})
        elif key == "CustomIamNamePrefix":
            parameters.get(key).properties.update({"Default": iam_name_prefix})
        elif isinstance(parameters.get(key).properties.get("Default"), bool):
            parameters.get(key).properties.update({"Default": str(parameters.get(key).properties.get("Default"))})
            parameters.get(key).properties.update(
                {"AllowedValues": list(map(str, parameters.get(key).properties.get("AllowedValues")))}
            )

    for key, value in conditions.items():
        if value.data.get("Fn::Equals"):
            conditions.get(key).data.update(
                {"Fn::Equals": [str(x) if isinstance(x, bool) else x for x in value.data.get("Fn::Equals")]}
            )


def _create_permission_boundary(permission_boundary_name):
    """Create a Permission Boundary for testing IAM Resource Prefix."""
    return ManagedPolicy(
        title=permission_boundary_name,
        Description="Least privileged policy for Resource Prefix",
        PolicyDocument={
            "Statement": [
                {
                    "Action": ["ec2:TerminateInstances"],
                    "Condition": {"StringEquals": {"ec2:ResourceTag/parallelcluster:node-type": "ComputeNode"}},
                    "Effect": "Allow",
                    "Resource": "*",
                },
                {
                    "Action": ["s3:GetObject"],
                    "Effect": "Allow",
                    "Resource": [
                        {"Fn::Sub": "arn:${AWS::Partition}:s3:::${AWS::Region}-aws-parallelcluster/*"},
                        {"Fn::Sub": "arn:${AWS::Partition}:s3:::dcv-license.${AWS::Region}/*"},
                    ],
                },
                {
                    "Action": ["iam:PassRole", "iam:GetRole"],
                    "Effect": "Allow",
                    "Resource": [
                        {"Fn::Sub": "arn:${AWS::Partition}:iam::${AWS::AccountId}:role/${CustomIamPathPrefix}/*"},
                        {"Fn::Sub": "arn:${AWS::Partition}:iam::${AWS::AccountId}:role/${CustomIamNamePrefix}*"},
                    ],
                },
                {"Action": ["cloudformation:*"], "Effect": "Allow", "Resource": "*"},
                {
                    "Action": [
                        "s3:DeleteObject",
                        "s3:DeleteObjectVersion",
                        "s3:ListBucket",
                        "s3:ListBucketVersions",
                        "s3:GetObject",
                        "s3:PutObject",
                        "s3:GetObjectVersion",
                    ],
                    "Effect": "Allow",
                    "Resource": [
                        {"Fn::Sub": "arn:${AWS::Partition}:s3:::parallelcluster-*-v1-do-not-delete"},
                        {"Fn::Sub": "arn:${AWS::Partition}:s3:::parallelcluster-*-v1-do-not-delete/*"},
                    ],
                },
                {
                    "Action": [
                        "iam:DetachRolePolicy",
                        "iam:DeleteRole",
                        "iam:DeleteRolePolicy",
                        "iam:CreateRole",
                        "iam:AttachRolePolicy",
                        "iam:PutRolePermissionsBoundary",
                        "iam:TagRole",
                        "iam:UntagRole",
                        "iam:ListRoleTags",
                        "iam:ListRolePolicies",
                        "iam:GetRolePolicy",
                        "iam:PutRolePolicy",
                        "iam:ListAttachedRolePolicies",
                        "iam:ListInstanceProfiles",
                        "iam:ListInstanceProfilesForRole",
                    ],
                    "Effect": "Allow",
                    "Resource": [
                        {"Fn::Sub": "arn:${AWS::Partition}:iam::${AWS::AccountId}:role/${CustomIamPathPrefix}/*"},
                        {"Fn::Sub": "arn:${AWS::Partition}:iam::${AWS::AccountId}:role/${CustomIamNamePrefix}*"},
                    ],
                },
                {
                    "Action": [
                        "iam:DeleteInstanceProfile",
                        "iam:RemoveRoleFromInstanceProfile",
                        "iam:CreateInstanceProfile",
                        "iam:AddRoleToInstanceProfile",
                        "iam:TagInstanceProfile",
                        "iam:UntagInstanceProfile",
                    ],
                    "Effect": "Allow",
                    "Resource": [
                        {"Fn::Sub": "arn:${AWS::Partition}:iam::${AWS::AccountId}:role/${CustomIamPathPrefix}/*"},
                        {"Fn::Sub": "arn:${AWS::Partition}:iam::${AWS::AccountId}:role/${CustomIamNamePrefix}*"},
                        {
                            "Fn::Sub": "arn:${AWS::Partition}:iam::${AWS::AccountId}:instance-profile/"
                            "${CustomIamPathPrefix}/*"
                        },
                    ],
                },
                {
                    "Action": ["cloudformation:*"],
                    "Effect": "Allow",
                    "Resource": {
                        "Fn::Sub": "arn:${AWS::Partition}:cloudformation:${AWS::Region}:${AWS::AccountId}:stack/*/*"
                    },
                },
                {
                    "Action": ["s3:GetObject"],
                    "Effect": "Allow",
                    "Resource": {"Fn::Sub": "arn:${AWS::Partition}:s3:::ec2imagebuilder*"},
                },
                {
                    "Action": ["ec2:Describe*"],
                    "Condition": {
                        "Fn::If": [
                            "IsMultiRegion",
                            {"Ref": "AWS::NoValue"},
                            {"StringEquals": {"aws:RequestedRegion": [{"Ref": "Region"}]}},
                        ]
                    },
                    "Effect": "Allow",
                    "Resource": "*",
                    "Sid": "EC2Read",
                },
                {
                    "Action": [
                        "ec2:AllocateAddress",
                        "ec2:AssociateAddress",
                        "ec2:AttachNetworkInterface",
                        "ec2:AuthorizeSecurityGroupEgress",
                        "ec2:AuthorizeSecurityGroupIngress",
                        "ec2:CreateLaunchTemplate",
                        "ec2:CreateLaunchTemplateVersion",
                        "ec2:CreateNetworkInterface",
                        "ec2:CreatePlacementGroup",
                        "ec2:CreateSecurityGroup",
                        "ec2:CreateSnapshot",
                        "ec2:CreateTags",
                        "ec2:CreateVolume",
                        "ec2:DeleteLaunchTemplate",
                        "ec2:DeleteNetworkInterface",
                        "ec2:DeletePlacementGroup",
                        "ec2:DeleteSecurityGroup",
                        "ec2:DeleteVolume",
                        "ec2:DisassociateAddress",
                        "ec2:ModifyLaunchTemplate",
                        "ec2:ModifyNetworkInterfaceAttribute",
                        "ec2:ModifyVolume",
                        "ec2:ModifyVolumeAttribute",
                        "ec2:ReleaseAddress",
                        "ec2:RevokeSecurityGroupEgress",
                        "ec2:RevokeSecurityGroupIngress",
                        "ec2:RunInstances",
                        "ec2:TerminateInstances",
                    ],
                    "Condition": {
                        "Fn::If": [
                            "IsMultiRegion",
                            {"Ref": "AWS::NoValue"},
                            {"StringEquals": {"aws:RequestedRegion": [{"Ref": "Region"}]}},
                        ]
                    },
                    "Effect": "Allow",
                    "Resource": "*",
                    "Sid": "EC2Write",
                },
                {
                    "Action": [
                        "dynamodb:DescribeTable",
                        "dynamodb:ListTagsOfResource",
                        "dynamodb:CreateTable",
                        "dynamodb:DeleteTable",
                        "dynamodb:GetItem",
                        "dynamodb:PutItem",
                        "dynamodb:UpdateItem",
                        "dynamodb:Query",
                        "dynamodb:TagResource",
                    ],
                    "Effect": "Allow",
                    "Resource": {
                        "Fn::Sub": "arn:${AWS::Partition}:dynamodb:${Region}:${AWS::AccountId}:table/parallelcluster-*"
                    },
                    "Sid": "DynamoDB",
                },
                {
                    "Action": [
                        "route53:ChangeResourceRecordSets",
                        "route53:ChangeTagsForResource",
                        "route53:CreateHostedZone",
                        "route53:DeleteHostedZone",
                        "route53:GetChange",
                        "route53:GetHostedZone",
                        "route53:ListResourceRecordSets",
                        "route53:ListQueryLoggingConfigs",
                    ],
                    "Effect": "Allow",
                    "Resource": "*",
                    "Sid": "Route53HostedZones",
                },
                {
                    "Action": [
                        "cloudwatch:PutDashboard",
                        "cloudwatch:ListDashboards",
                        "cloudwatch:DeleteDashboards",
                        "cloudwatch:GetDashboard",
                        "cloudwatch:PutMetricAlarm",
                        "cloudwatch:DeleteAlarms",
                        "cloudwatch:DescribeAlarms",
                    ],
                    "Condition": {
                        "Fn::If": [
                            "IsMultiRegion",
                            {"Ref": "AWS::NoValue"},
                            {"StringEquals": {"aws:RequestedRegion": [{"Ref": "Region"}]}},
                        ]
                    },
                    "Effect": "Allow",
                    "Resource": "*",
                    "Sid": "CloudWatch",
                },
                {
                    "Action": [
                        "lambda:CreateFunction",
                        "lambda:TagResource",
                        "lambda:DeleteFunction",
                        "lambda:GetFunctionConfiguration",
                        "lambda:GetFunction",
                        "lambda:InvokeFunction",
                        "lambda:AddPermission",
                        "lambda:RemovePermission",
                        "lambda:UpdateFunctionConfiguration",
                        "lambda:ListTags",
                        "lambda:UntagResource",
                    ],
                    "Effect": "Allow",
                    "Resource": [
                        {
                            "Fn::Sub": "arn:${AWS::Partition}:lambda:${Region}:"
                            "${AWS::AccountId}:function:parallelcluster-*"
                        },
                        {"Fn::Sub": "arn:${AWS::Partition}:lambda:${Region}:${AWS::AccountId}:function:pcluster-*"},
                    ],
                    "Sid": "Lambda",
                },
                {
                    "Action": [
                        "logs:DeleteLogGroup",
                        "logs:PutRetentionPolicy",
                        "logs:DescribeLogGroups",
                        "logs:CreateLogGroup",
                        "logs:TagResource",
                        "logs:UntagResource",
                        "logs:DescribeMetricFilters",
                        "logs:PutMetricFilter",
                        "logs:deleteMetricFilter",
                    ],
                    "Condition": {
                        "Fn::If": [
                            "IsMultiRegion",
                            {"Ref": "AWS::NoValue"},
                            {"StringEquals": {"aws:RequestedRegion": [{"Ref": "Region"}]}},
                        ]
                    },
                    "Effect": "Allow",
                    "Resource": "*",
                    "Sid": "CloudWatchLogs",
                },
                {
                    "Action": [
                        "iam:CreatePolicy",
                        "iam:CreatePolicyVersion",
                        "iam:DeletePolicyVersion",
                        "iam:GetPolicyVersion",
                        "iam:GetPolicy",
                        "iam:DeletePolicy",
                        "iam:ListInstanceProfiles",
                        "iam:ListInstanceProfilesForRole",
                        "iam:ListEntitiesForPolicy",
                        "iam:ListPolicyVersions",
                        "iam:TagPolicy",
                        "iam:UntagPolicy",
                    ],
                    "Effect": "Allow",
                    "Resource": [
                        {"Fn::Sub": "arn:${AWS::Partition}:iam::${AWS::AccountId}:policy/${CustomIamNamePrefix}*"},
                        {"Fn::Sub": "arn:${AWS::Partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"},
                    ],
                },
            ],
            "Version": "2012-10-17",
        },
    )


def _create_iam_user_role_template(cluster_config, iam_resource_prefix):
    """Creates config file by changing the user-role.cfn.yaml to create a user role with permission boundary."""

    iam_path, iam_name_prefix = _split_resource_prefix(iam_resource_prefix)
    with open(cluster_config, "r", encoding="utf-8") as f:
        config_template = TemplateGenerator(load_yaml(f.read()))

    config_template.add_resource(_create_permission_boundary("IamResourcePrefixPermissionBoundary"))
    config_template.resources.get("ParallelClusterUserRole").properties.update(
        {"PermissionsBoundary": {"Ref": "IamResourcePrefixPermissionBoundary"}}
    )
    _update_paramters_and_conditions(config_template.parameters, config_template.conditions, iam_path, iam_name_prefix)
    return config_template.to_yaml()


def _split_resource_prefix(resource_prefix):
    """To split Path and name prefix from Resource Prefix."""
    if resource_prefix:
        split_index = resource_prefix.rfind("/") + 1
        return (
            None
            if split_index == 0
            else resource_prefix
            if split_index == len(resource_prefix)
            else resource_prefix[:split_index],
            None
            if split_index == len(resource_prefix)
            else resource_prefix
            if split_index == 0
            else resource_prefix[split_index:],
        )
    return None, None


def _check_iam_resource_prefix(region, resource_arn_list, iam_resource_prefix):
    """Check the path and name of IAM resource ( Roles, policy and Instance profiles)."""
    iam_path, iam_name_prefix = _split_resource_prefix(iam_resource_prefix)
    for resource in resource_arn_list:
        if f"arn:{get_arn_partition(region)}:iam:" in resource:
            if iam_path:
                assert_that(resource).contains(iam_path)
            else:
                assert_that(resource).contains("/parallelcluster/")
        if iam_name_prefix:
            assert_that(resource).contains(iam_name_prefix)


def _test_iam_resource_in_cluster(region, cfn_client, iam_client, stack_name, iam_resource_prefix):
    """Test IAM resources by checking the path and name prefix in AWS IAM and check cluster is created."""

    # Check for cluster Status

    assert_that(cfn_client.describe_stacks(StackName=stack_name).get("Stacks")[0].get("StackStatus")).is_equal_to(
        "CREATE_COMPLETE"
    )

    resources = cfn_client.describe_stack_resources(StackName=stack_name)["StackResources"]
    resource_arn_list = []

    for resource in resources:
        resource_type = resource["ResourceType"]
        if resource_type == "AWS::IAM::Role":
            resource_arn_list.append(iam_client.get_role(RoleName=resource["PhysicalResourceId"])["Role"]["Arn"])
            resource_arn_list.extend(
                iam_client.list_role_policies(RoleName=resource["PhysicalResourceId"])["PolicyNames"]
            )
        if resource_type == "AWS::IAM::InstanceProfile":
            resource_arn_list.append(
                iam_client.get_instance_profile(InstanceProfileName=resource["PhysicalResourceId"])["InstanceProfile"][
                    "Arn"
                ]
            )
    _check_iam_resource_prefix(region, resource_arn_list, iam_resource_prefix)


@pytest.fixture(scope="class")
def initialize_resource_prefix_cli_creds(request):
    """Create an IAM Role with Permission Boundary for testing Resource Prefix Feature."""

    stack_factory = CfnStacksFactory(request.config.getoption("credential"))

    def _create_resource_prefix_cli_creds(role_config_file, iam_resource_prefix):
        regions = request.config.getoption("regions") or get_all_regions(request.config.getoption("tests_config"))
        stack_template_data = _create_iam_user_role_template(role_config_file, iam_resource_prefix)
        cli_creds = {}
        for region in regions:
            if request.config.getoption("iam_user_role_stack_name"):
                stack_name = request.config.getoption("iam_user_role_stack_name")
                logging.info(f"Using stack {stack_name} in region {region}")
                stack = CfnStack(
                    name=stack_name, region=region, capabilities=["CAPABILITY_IAM"], template=stack_template_data
                )
            else:
                logging.info("Creating IAM roles for pcluster CLI")
                stack_name = generate_stack_name(
                    "integ-tests-iam-rp-user-role", request.config.getoption("stackname_suffix")
                )
                stack = CfnStack(
                    name=stack_name,
                    region=region,
                    capabilities=["CAPABILITY_IAM"],
                    template=stack_template_data,
                )

                stack_factory.create_stack(stack)
            cli_creds[region] = stack.cfn_outputs["ParallelClusterUserRole"]
        return cli_creds

    yield _create_resource_prefix_cli_creds

    if not request.config.getoption("no_delete"):
        stack_factory.delete_all_stacks()
    else:
        logging.warning("Skipping deletion of CFN stacks because --no-delete option is set")
