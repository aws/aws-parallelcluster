# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import time

import boto3
import pytest
from assertpy import assert_that
from cfn_stacks_factory import CfnStack
from troposphere import Template, iam
from utils import generate_stack_name

from tests.common.utils import generate_random_string, get_installed_parallelcluster_version, retrieve_latest_ami


def test_build_image(
    region,
    instance,
    os,
    pcluster_config_reader,
    architecture,
    s3_bucket_factory,
    build_image_custom_resource,
    images_factory,
):
    """Test build image for given region and os"""
    # Test validation error
    arm64_ami = retrieve_latest_ami(region, os, architecture="arm64")
    image_id = f"integ-test-build-image-{generate_random_string()}"
    # Get custom instance role
    instance_role = build_image_custom_resource(image_id=image_id)

    # Get custom S3 bucket
    bucket_name = s3_bucket_factory()
    image_config = pcluster_config_reader(config_file="image.config.yaml", parent_image=arm64_ami, instance_role=instance_role,
                                          bucket_name=bucket_name)
    image = images_factory(image_id, image_config, region, raise_on_error=False, log_error=False)
    logging.info(image.creation_response)

    exit(1)

    # Get base AMI
    # remarkable AMIs are not available for ARM and ubuntu2004, centos7 yet
    if os not in ["ubuntu2004", "centos7"]:
        base_ami = retrieve_latest_ami(region, os, ami_type="remarkable", architecture=architecture)
    else:
        base_ami = retrieve_latest_ami(region, os, architecture=architecture)

    image_config = pcluster_config_reader(
        config_file="image.config.yaml",
        parent_image=base_ami,
        instance_role=instance_role,
        bucket_name=bucket_name,
    )

    image = images_factory(image_id, image_config, region)

    _assert_build_tag(image)
    _assert_build_image_success(image)
    _assert_image_tag_and_volume(image)


def _assert_build_tag(image):
    logging.info("Check the build tag is present as specified in config file.")
    stack_list = boto3.client("cloudformation").describe_stacks(StackName=image.image_id).get("Stacks")
    logging.info(stack_list)
    assert_that(len(stack_list)).is_equal_to(1)
    stack_tags = stack_list[0].get("Tags")
    logging.info(stack_tags)
    assert_that(stack_tags).contains({"Key": "dummyBuildTag", "Value": "dummyBuildTag"})


def _assert_image_tag_and_volume(image):
    logging.info("Check the image tag is present as specified in config file.")
    image_list = (
        boto3.client("ec2")
        .describe_images(
            ImageIds=[], Filters=[{"Name": "tag:parallelcluster:image_id", "Values": [image.image_id]}], Owners=["self"]
        )
        .get("Images")
    )
    logging.info(image_list)
    assert_that(len(image_list)).is_equal_to(1)
    volume_size = image_list[0].get("BlockDeviceMappings")[0].get("Ebs").get("VolumeSize")
    assert_that(volume_size).is_equal_to(200)
    assert_that(image.image_tags).contains({"key": "dummyImageTag", "value": "dummyImageTag"})


@pytest.fixture()
def build_image_custom_resource(cfn_stacks_factory, region):
    """
    Define a fixture to manage the creation and destruction of build image resource( custom instance role).

    return instance role
    """
    stack_name_post_test = None

    def _custom_resource(image_id):
        nonlocal stack_name_post_test
        # custom resource stack
        custom_resource_stack_name = generate_stack_name("-".join([image_id, "custom", "resource"]), "")
        stack_name_post_test = custom_resource_stack_name
        custom_resource_template = Template()
        custom_resource_template.set_version()
        custom_resource_template.set_description("Create build image custom resource stack")

        # Create a instance role
        managed_policy_arns = [
            "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
            "arn:aws:iam::aws:policy/EC2InstanceProfileForImageBuilder",
        ]

        policy_document = iam.Policy(
            PolicyName="myInstanceRoleInlinePolicy",
            PolicyDocument={
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "ec2:CreateTags",
                            "ec2:ModifyImageAttribute",
                            "s3:GetObject",
                            "cloudformation:ListStacks",
                        ],
                        "Resource": "*",
                    }
                ]
            },
        )
        role_name = "".join(["dummyInstanceRole", generate_random_string()])
        instance_role = iam.Role(
            "CustomInstanceRole",
            AssumeRolePolicyDocument={
                "Statement": [
                    {"Effect": "Allow", "Principal": {"Service": ["ec2.amazonaws.com"]}, "Action": ["sts:AssumeRole"]}
                ]
            },
            Description="custom instance role for build image test.",
            ManagedPolicyArns=managed_policy_arns,
            Path="/myInstanceRole/",
            Policies=[policy_document],
            RoleName=role_name,
        )

        custom_resource_template.add_resource(instance_role)
        custom_resource_stack = CfnStack(
            name=custom_resource_stack_name,
            region=region,
            template=custom_resource_template.to_json(),
            capabilities=["CAPABILITY_NAMED_IAM"],
        )
        cfn_stacks_factory.create_stack(custom_resource_stack)

        instance_role_arn = boto3.client("iam").get_role(RoleName=role_name).get("Role").get("Arn")
        logging.info("Custom instance role arn %s", instance_role_arn)

        return instance_role_arn

    yield _custom_resource
    if stack_name_post_test:
        cfn_stacks_factory.delete_stack(stack_name_post_test, region)


def test_build_image_custom_components(
    region, os, instance, test_datadir, pcluster_config_reader, architecture, s3_bucket_factory, images_factory
):
    """Test custom components and base AMI is ParallelCluster AMI"""
    # Custom script
    custom_script_file = "custom_script_ubuntu.sh" if os in ["ubuntu1804", "ubuntu2004"] else "custom_script.sh"

    # Create S3 bucket for pre install scripts, to remove epel package if it is installed
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / custom_script_file), "scripts/custom_script.sh")

    # Get ParallelCluster AMI as base AMI
    base_ami = retrieve_latest_ami(region, os, ami_type="pcluster", architecture=architecture)

    image_id = f"integ-test-build-image-custom-components-{generate_random_string()}"
    image_config = pcluster_config_reader(
        config_file="image.config.yaml",
        parent_image=base_ami,
        instance_type=instance,
        bucket_name=bucket_name,
        region=region,
    )

    image = images_factory(image_id, image_config, region)

    _assert_build_image_success(image)


def _assert_build_image_success(image):
    logging.info("Test build image process for image %s.", image.image_id)

    pcluster_describe_image_result = image.describe()
    logging.info(pcluster_describe_image_result)

    while image.image_status == "BUILD_IN_PROGRESS":
        time.sleep(600)
        pcluster_describe_image_result = image.describe()
        logging.info(pcluster_describe_image_result)
    if image.image_status != "BUILD_COMPLETE":
        image.keep_logs = True
    assert_that(image.image_status).is_equal_to("BUILD_COMPLETE")


def test_build_image_wrong_pcluster_version(
    region, os, instance, pcluster_config_reader, architecture, pcluster_ami_without_standard_naming, images_factory
):
    """Test error message when AMI provided was baked by a pcluster whose version is different from current version"""
    current_version = get_installed_parallelcluster_version()
    wrong_version = "2.8.1"
    logging.info("Asserting wrong_version is different from current_version")
    assert_that(current_version != wrong_version).is_true()
    # Retrieve an AMI without 'aws-parallelcluster-<version>' in its name.
    # Therefore, we can bypass the version check in CLI and test version check of .bootstrapped file in Cookbook.
    wrong_ami = pcluster_ami_without_standard_naming(wrong_version)

    image_config = pcluster_config_reader(
        config_file="image.config.yaml",
        parent_image=wrong_ami,
        instance_type=instance,
    )
    image_id = f"integ-test-build-image-wrong-version-{generate_random_string()}"

    image = images_factory(image_id, image_config, region)

    _assert_build_image_failed(image)
    assert_that(image.get_log_events()).matches(fr"AMI was created.+{wrong_version}.+is.+used.+{current_version}")


def _assert_build_image_failed(image):
    logging.info("Test build image process for image %s.", image.image_id)

    pcluster_describe_image_result = image.describe()
    logging.info(pcluster_describe_image_result)

    while image.image_status == "BUILD_IN_PROGRESS":
        time.sleep(600)
        pcluster_describe_image_result = image.describe()
        logging.info(pcluster_describe_image_result)

    if image.image_status == "BUILD_FAILED":
        image.keep_logs = True

    assert_that(image.image_status).is_equal_to("BUILD_FAILED")
