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
import logging

import boto3
import pytest
from assertpy import assert_that
from retrying import retry
from time_utils import minutes
from utils import generate_stack_name

from tests.common.utils import retrieve_latest_ami


@pytest.mark.usefixtures("instance")
def test_iam_roles(
    region,
    os,
    create_roles_stack,
    pcluster_config_reader,
    images_factory,
    test_datadir,
):
    instance_profile, lambda_cleanup_role = _create_image_roles(create_roles_stack)

    image = _build_image(images_factory, instance_profile, lambda_cleanup_role, os, pcluster_config_reader, region)

    cfn_client = boto3.client("cloudformation", region_name=region)
    ec2_client = boto3.client("ec2", region_name=region)
    lambda_client = boto3.client("lambda", region_name=region)

    pcluster_describe_image_result = image.describe()
    logging.info(pcluster_describe_image_result)
    _check_roles(
        cfn_client,
        ec2_client,
        lambda_client,
        pcluster_describe_image_result.get("cloudformationStackArn"),
        instance_profile,
        lambda_cleanup_role,
    )

    # TODO is there a way to complete this check without building an image?
    _wait_build_image_complete(image)


def _build_image(images_factory, instance_profile, lambda_cleanup_role, os, pcluster_config_reader, region):
    # Generate image ID
    image_id = generate_stack_name("integ-tests-build-image", "")
    # Get base AMI
    base_ami = retrieve_latest_ami(region, os, ami_type="pcluster", architecture="x86_64")
    image_config = pcluster_config_reader(
        config_file="image.config.yaml",
        parent_image=base_ami,
        instance_profile=instance_profile,
        lambda_cleanup_role=lambda_cleanup_role,
    )
    image = images_factory(image_id, image_config, region)
    return image


def _create_image_roles(create_roles_stack):
    # Create build image roles
    image_roles_stack = create_roles_stack(
        stack_prefix="integ-tests-iam-image-roles", roles_file="image-roles.cfn.yaml"
    )
    lambda_cleanup_role = image_roles_stack.cfn_outputs["BuildImageLambdaCleanupRole"]
    instance_profile = image_roles_stack.cfn_outputs["BuildImageInstanceProfile"]
    # instance_role = image_roles_stack.cfn_outputs["BuildImageInstanceRole"]
    return instance_profile, lambda_cleanup_role


@retry(wait_fixed=minutes(1), stop_max_delay=minutes(60))
def _wait_build_image_complete(image):
    pcluster_describe_image_result = image.describe()
    logging.info(pcluster_describe_image_result)
    assert_that(image.image_status).is_equal_to("BUILD_COMPLETE")


@retry(wait_fixed=minutes(1), stop_max_delay=minutes(20))
def _get_resources_with_image_resource(cfn_client, stack_name):
    logging.info("Describe stack resources")
    resources = cfn_client.describe_stack_resources(StackName=stack_name)["StackResources"]
    image_resource_exists = False
    logging.info("Checking image resource")
    for resource in resources:
        if resource["ResourceType"] == "AWS::ImageBuilder::Image":
            image_resource_exists = True
            logging.info("The image resource exists!")
            break
    assert_that(image_resource_exists).is_true()
    return resources


def _check_roles(
    cfn_client,
    ec2_client,
    lambda_client,
    stack_name,
    instance_profile,
    lambda_cleanup_role,
):
    """Test roles are attached to EC2 build instance and Lambda cleanup function in the building stack."""
    logging.info("Checking roles are attached to the build instance")
    resources = _get_resources_with_image_resource(cfn_client, stack_name)
    for resource in resources:
        resource_type = resource["ResourceType"]
        # Check that there is no role created in the stack.
        assert_that(resource_type).is_not_equal_to("AWS::IAM::Role")
        if resource_type == "AWS::Lambda::Function":
            # Check the role is attached to the Lambda function
            lambda_function = lambda_client.get_function(FunctionName=resource["PhysicalResourceId"])["Configuration"]
            assert_that(lambda_function["Role"]).is_equal_to(lambda_cleanup_role)
            logging.info("Lambda function role confirmed")
        if resource_type == "AWS::ImageBuilder::Image":
            # Check the instance profile is attached to the EC2 instance
            imagebuilder_image_arn = resource["PhysicalResourceId"]
            logging.info(f"Image builder Image ARN: {imagebuilder_image_arn}")
            instance_profile_arn = (
                ec2_client.describe_instances(
                    Filters=[{"Name": "tag:Ec2ImageBuilderArn", "Values": [imagebuilder_image_arn]}]
                )
                .get("Reservations")[0]
                .get("Instances")[0]
                .get("IamInstanceProfile")
                .get("Arn")
            )
            assert_that(instance_profile_arn).contains(instance_profile)
            logging.info("Image arn confirmed")
