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
import datetime
import json
import logging
import re
import tarfile
import tempfile
import time

import boto3
import pytest
from assertpy import assert_that, soft_assertions
from botocore.exceptions import ClientError
from cfn_stacks_factory import CfnStack
from dateutil.parser import parse as date_parse
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from troposphere import Template, iam
from utils import generate_stack_name, get_arn_partition, get_gpu_count

from tests.common.assertions import (
    assert_head_node_is_running,
    assert_instance_has_desired_imds_v2_setting,
    assert_instance_has_desired_tags,
    assert_lambda_vpc_settings_are_correct,
    assert_no_msg_in_logs,
)
from tests.common.utils import (
    generate_random_string,
    get_installed_parallelcluster_base_version,
    get_installed_parallelcluster_version,
    retrieve_latest_ami,
)


@pytest.mark.usefixtures("instance")
def test_invalid_config(
    region,
    os,
    pcluster_config_reader,
    architecture,
    s3_bucket_factory,
    build_image_custom_resource,
    images_factory,
):
    # Test validation error
    arm64_ami = retrieve_latest_ami(region, os, architecture="arm64")
    image_id = f"integ-test-build-image-{generate_random_string()}"

    # Get custom S3 bucket
    bucket_name = s3_bucket_factory()
    image_config = pcluster_config_reader(
        config_file="image.config.yaml", parent_image=arm64_ami, bucket_name=bucket_name
    )
    image = images_factory(image_id, image_config, region, raise_on_error=False, log_error=False)

    assert_that(image.configuration_errors).is_length(1)
    assert_that(image.configuration_errors[0]).contains("level")
    assert_that(image.configuration_errors[0]).contains("type")
    assert_that(image.configuration_errors[0]).contains("message")
    assert_that(image.configuration_errors[0]["type"]).is_equal_to("InstanceTypeBaseAMICompatibleValidator")

    # Test Suppression of a validator

    # Get base AMI -- remarkable AMIs are not available for ARM and ubuntu2204, alinux2023 yet
    if os not in ["ubuntu2204", "alinux2023"]:
        base_ami = retrieve_latest_ami(region, os, ami_type="remarkable", architecture=architecture)
    else:
        base_ami = retrieve_latest_ami(region, os, architecture=architecture)

    image_config = pcluster_config_reader(
        config_file="warnings.image.config.yaml", parent_image=base_ami, bucket_name=bucket_name
    )
    suppressed = images_factory(
        image_id,
        image_config,
        region,
        raise_on_error=False,
        log_error=False,
        dryrun=True,
        suppress_validators="type:UrlValidator",
    )
    assert_that(suppressed.message).contains("Request would have succeeded")


@pytest.mark.usefixtures("scheduler")
def test_build_image(
    region,
    os,
    instance,
    pcluster_config_reader,
    architecture,
    s3_bucket_factory,
    build_image_custom_resource,
    images_factory,
    request,
    clusters_factory,
    scheduler_commands_factory,
):
    """
    Test build image for given region and os.

    In the cluster config there is DisableValidateAndTest:False to enable kitchen tests in the validate phase.
    The created AMI is also used for a cluster.
    Also check that the build instance has the desired ImdsSupport setting (v2.0, so IMDSv2 is required).
    """
    image_id = generate_stack_name("integ-tests-build-image", request.config.getoption("stackname_suffix"))

    # Get custom instance role
    instance_role = build_image_custom_resource(image_id=image_id)

    # Get custom S3 bucket
    bucket_name = s3_bucket_factory()
    _set_s3_bucket_policy(bucket_name, get_arn_partition(region), region)

    enable_nvidia = True
    update_os_packages = False
    enable_lustre_client = True
    # Get base AMI
    if os in ["alinux2", "ubuntu2004"]:
        # Test Deep Learning AMIs
        base_ami = retrieve_latest_ami(region, os, ami_type="remarkable", architecture=architecture)
        enable_nvidia = False  # Deep learning AMIs have Nvidia pre-installed
    elif "rhel" in os or "rocky" in os or "ubuntu" in os:
        # Test AMIs from first stage build. Because RHEL/Rocky and Ubuntu have specific requirement of kernel versions.
        try:
            base_ami = retrieve_latest_ami(region, os, ami_type="first_stage", architecture=architecture)
        except IndexError:  # If first stage AMI is not available, use official AMI.
            # Therefore, the test tries to succeed at best effort.
            logging.info("First stage AMI not available, using official AMI instead.")
            base_ami = retrieve_latest_ami(region, os, ami_type="official", architecture=architecture)
            update_os_packages = True
            if os in ["ubuntu2204", "rhel9", "rocky9"]:
                enable_lustre_client = False
    else:
        # Test vanilla AMIs.
        base_ami = retrieve_latest_ami(region, os, ami_type="official", architecture=architecture)
    if os in ["alinux2", "alinux2023"]:
        update_os_packages = True
    image_config = pcluster_config_reader(
        config_file="image.config.yaml",
        parent_image=base_ami,
        instance_role=instance_role,
        bucket_name=bucket_name,
        enable_nvidia=str(enable_nvidia and get_gpu_count(instance) > 0).lower(),
        update_os_packages=str(update_os_packages).lower(),
        enable_lustre_client=str(enable_lustre_client).lower(),
    )

    image = images_factory(image_id, image_config, region)
    _test_build_tag(image)
    _test_image_stack_events(image)

    cfn_client = boto3.client("cloudformation", region_name=region)
    _wait_for_creation_of_delete_stack_function(image.image_id, cfn_client)

    lamda_vpc_config = image.config["DeploymentSettings"]["LambdaFunctionsVpcConfig"]
    assert_lambda_vpc_settings_are_correct(
        image.image_id, region, lamda_vpc_config["SecurityGroupIds"], lamda_vpc_config["SubnetIds"]
    )

    with soft_assertions():
        _test_build_image_success(image)
        _test_build_instances_tags(image, image.config["Build"]["Tags"], region)
        _test_build_imds_settings(image, "required", region)
        _test_image_tag_and_volume(image)
        _test_list_image_log_streams(image)
        _test_get_image_log_events(image)
        _test_list_images(image)
        _test_export_logs(s3_bucket_factory, image, region)
        _test_export_logs(s3_bucket_factory, image, region, True)

    _test_cluster_creation(
        image.ec2_image_id, pcluster_config_reader, region, clusters_factory, scheduler_commands_factory
    )


def _test_cluster_creation(image_id, pcluster_config_reader, region, clusters_factory, scheduler_commands_factory):
    """Create cluster with given image id and verify it's possible to run jobs on it."""
    cluster_config = pcluster_config_reader(custom_ami=image_id)
    cluster = clusters_factory(cluster_config, raise_on_error=True)

    assert_head_node_is_running(region, cluster)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    node_number = 2

    result = scheduler_commands.submit_command(command="uptime", nodes=node_number)
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id, children_number=node_number)

    assert_no_msg_in_logs(remote_command_executor, ["/var/log/slurmctld.log"], ["launch failure"])


@retry(
    retry_on_result=lambda result: result == "CREATE_IN_PROGRESS",
    retry_on_exception=lambda exception: (
        isinstance(exception, ClientError)
        and any(
            message in str(exception) for message in {"Rate exceeded", "Resource DeleteStackFunction does not exist"}
        )
    ),
    wait_fixed=seconds(10),
    stop_max_delay=minutes(30),
)
def _wait_for_creation_of_delete_stack_function(stack_name, cfn_client):
    return (
        cfn_client.describe_stack_resource(StackName=stack_name, LogicalResourceId="DeleteStackFunction")
        .get("StackResourceDetail")
        .get("ResourceStatus")
    )


@pytest.mark.usefixtures("instance", "scheduler")
def test_kernel4_build_image_run_cluster(
    region,
    os,
    pcluster_config_reader,
    architecture,
    images_factory,
    request,
    scheduler_commands_factory,
    clusters_factory,
):
    """
    Test build image for given region and os and run a job in a new cluster created from the new images.

    Also check that the build instance has the desired ImdsSupport setting (IMDSv2, v1.0 is optional).

    Note: This test has been introduced to verify the build-image with Amazon Linux based on kernel 4,
    because the base AMI for Amazon Linux were based on kernel 5.10.

    At the moment this test is no longer relevant,
    kernel 5.10 in Amazon Linux 2 has been introduced on Nov 2021 and kernel 4.14 is now EOL.
    """
    # Get base AMI from kernel4
    base_ami = retrieve_latest_ami(region, os, ami_type="kernel4", architecture=architecture)

    image_config = pcluster_config_reader(config_file="image.config.yaml", parent_image=base_ami, region=region)

    image_id = generate_stack_name("integ-tests-build-image", request.config.getoption("stackname_suffix"))
    image = images_factory(image_id, image_config, region, **{"rollback-on-failure": False})
    _test_build_image_success(image)
    _test_build_imds_settings(image, "required", region)
    _test_list_images(image)

    _test_cluster_creation(
        image.ec2_image_id, pcluster_config_reader, region, clusters_factory, scheduler_commands_factory
    )


def _test_list_images(image):
    images = image.list_images(region=image.region, image_status="AVAILABLE")["images"]
    matches = [img for img in images if img["imageId"] == image.image_id]
    assert_that(matches).is_length(1)
    assert_that(matches[0]["imageId"]).is_equal_to(image.image_id)
    assert_that(matches[0]["region"]).is_equal_to(image.region)
    image.describe()
    assert_that(matches[0]["ec2AmiInfo"]["amiId"]).is_equal_to(image.ec2_image_id)
    assert_that(matches[0]["imageBuildStatus"]).is_equal_to("BUILD_COMPLETE")
    assert_that(matches[0]).contains("version")


def _test_image_stack_events(image):
    stack_events_resp = image.get_stack_events()
    assert_that(stack_events_resp).is_not_none()
    assert_that(stack_events_resp).contains("events")
    assert_that(stack_events_resp["events"]).is_not_empty()

    first_event = stack_events_resp["events"][0]
    assert_that(first_event).contains("eventId")
    assert_that(first_event).contains("logicalResourceId")
    assert_that(first_event).contains("physicalResourceId")
    assert_that(first_event).contains("stackId")
    assert_that(first_event).contains("timestamp")


def _test_list_image_log_streams(image):
    logging.info("Testing that pcluster list-image-log-streams is working as expected")
    list_streams_result = image.list_log_streams()
    streams = list_streams_result["logStreams"]

    stream_names = {stream["logStreamName"] for stream in streams}
    expected_log_stream = f"{get_installed_parallelcluster_base_version()}/1"
    assert_that(stream_names).contains(expected_log_stream)


def _test_get_image_log_events(image):
    """Test pcluster get-image-log-events functionality."""
    logging.info("Testing that pcluster get-image-log-events is working as expected")
    log_stream_name = f"{get_installed_parallelcluster_base_version()}/1"

    # Get the first event to establish time boundary for testing
    initial_events = image.get_log_events(log_stream_name, limit=1, start_from_head=True)
    first_event = initial_events["events"][0]
    first_event_time_str = first_event["timestamp"]
    first_event_time = date_parse(first_event_time_str)
    before_first = (first_event_time - datetime.timedelta(seconds=1)).isoformat()
    after_first = (first_event_time + datetime.timedelta(seconds=1)).isoformat()

    # args, expect_first, expect_count
    test_cases = [
        ({}, None, None),
        ({"limit": 1}, False, 1),
        ({"limit": 2, "start_from_head": True}, True, 2),
        ({"limit": 1, "start_time": before_first, "end_time": after_first, "start_from_head": True}, True, 1),
        ({"limit": 1, "end_time": before_first}, None, 0),
        ({"limit": 1, "start_time": after_first, "start_from_head": True}, False, 1),
        ({"limit": 1, "next_token": initial_events["nextToken"]}, False, 1),
        ({"limit": 1, "next_token": initial_events["nextToken"], "start_from_head": True}, False, 1),
    ]

    for args, expect_first, expect_count in test_cases:
        events = image.get_log_events(log_stream_name, **args)["events"]

        if expect_count is not None:
            assert_that(events).is_length(expect_count)

        if expect_first is True:
            assert_that(events[0]["message"]).contains(first_event["message"])

        if expect_first is False:
            assert_that(events[0]["message"]).does_not_contain(first_event["message"])


def _set_s3_bucket_policy(bucket_name, partition, region):
    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": "s3:GetBucketAcl",
                "Effect": "Allow",
                "Resource": f"arn:{partition}:s3:::{bucket_name}",
                "Principal": {"Service": f"logs.{region}.amazonaws.com"},
            },
            {
                "Action": "s3:PutObject",
                "Effect": "Allow",
                "Resource": f"arn:{partition}:s3:::{bucket_name}/*",
                "Condition": {"StringEquals": {"s3:x-amz-acl": "bucket-owner-full-control"}},
                "Principal": {"Service": f"logs.{region}.amazonaws.com"},
            },
        ],
    }
    boto3.client("s3").put_bucket_policy(Bucket=bucket_name, Policy=json.dumps(bucket_policy))


def _test_export_logs(s3_bucket_factory, image, region, use_pcluster_bucket=False):
    if not use_pcluster_bucket:
        bucket_name = s3_bucket_factory()
        logging.info("bucket is %s", bucket_name)

        # set bucket permissions
        partition = get_arn_partition(region)
        _set_s3_bucket_policy(bucket_name, partition, image.region)
    else:
        logging.info("Using default pcluster bucket.")

    with tempfile.TemporaryDirectory() as tempdir:
        output_file = f"{tempdir}/testfile.tar.gz"
        bucket_prefix = "test_prefix"

        if not use_pcluster_bucket:
            ret = retry(wait_fixed=seconds(20), stop_max_delay=minutes(10))(image.export_logs)(
                bucket=bucket_name, output_file=output_file, bucket_prefix=bucket_prefix
            )
        else:
            ret = retry(wait_fixed=seconds(20), stop_max_delay=minutes(10))(image.export_logs)(
                output_file=output_file, bucket_prefix=bucket_prefix
            )

        assert_that(ret["path"]).contains(output_file)

        rexp = rf"{image.image_id}-logs.*/cloudwatch-logs/{get_installed_parallelcluster_base_version()}-1"
        with tarfile.open(output_file) as archive:
            match = any(re.match(rexp, logfile.name) for logfile in archive)
        assert_that(match).is_true()


def _test_build_tag(image):
    logging.info("Check the build tag is present as specified in config file.")
    stack_list = boto3.client("cloudformation").describe_stacks(StackName=image.image_id).get("Stacks")
    logging.info(stack_list)
    assert_that(len(stack_list)).is_equal_to(1)
    stack_tags = stack_list[0].get("Tags")
    logging.info(stack_tags)
    assert_that(stack_tags).contains({"Key": "dummyBuildTag", "Value": "dummyBuildTag"})


def _test_image_tag_and_volume(image):
    logging.info("Check the image tag is present as specified in config file.")
    image_list = (
        boto3.client("ec2")
        .describe_images(
            ImageIds=[], Filters=[{"Name": "tag:parallelcluster:image_id", "Values": [image.image_id]}], Owners=["self"]
        )
        .get("Images")
    )
    logging.info(f"Image List: {image_list}, length {len(image_list)}")
    assert_that(len(image_list)).is_equal_to(1)

    created_image = image_list[0]
    volume_size = created_image.get("BlockDeviceMappings")[0].get("Ebs").get("VolumeSize")
    assert_that(volume_size).is_equal_to(200)
    assert_that(created_image["Tags"]).contains({"Key": "dummyImageTag", "Value": "dummyImageTag"})


@pytest.fixture()
def build_image_custom_resource(cfn_stacks_factory, region, request):
    """
    Define a fixture to manage the creation and destruction of build image resource( custom instance role).

    return instance role
    """
    stack_name_post_test = None

    def _custom_resource(image_id):
        nonlocal stack_name_post_test
        # custom resource stack
        custom_resource_stack_name = generate_stack_name(
            "-".join([image_id, "custom", "resource"]), request.config.getoption("stackname_suffix")
        )
        stack_name_post_test = custom_resource_stack_name
        custom_resource_template = Template()
        custom_resource_template.set_version()
        custom_resource_template.set_description("Create build image custom resource stack")

        # Create a instance role
        partition = get_arn_partition(region)
        managed_policy_arns = [
            f"arn:{partition}:iam::aws:policy/AmazonSSMManagedInstanceCore",
            f"arn:{partition}:iam::aws:policy/EC2InstanceProfileForImageBuilder",
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
        instance_role = iam.Role(
            "CustomInstanceRole",
            AssumeRolePolicyDocument={
                "Statement": [
                    {"Effect": "Allow", "Principal": {"Service": ["ec2.amazonaws.com"]}, "Action": ["sts:AssumeRole"]}
                ]
            },
            Description="custom instance role for build image test.",
            ManagedPolicyArns=managed_policy_arns,
            Path="/parallelcluster/",
            Policies=[policy_document],
        )

        custom_resource_template.add_resource(instance_role)
        custom_resource_stack = CfnStack(
            name=custom_resource_stack_name,
            region=region,
            template=custom_resource_template.to_json(),
            capabilities=["CAPABILITY_NAMED_IAM"],
        )
        cfn_stacks_factory.create_stack(custom_resource_stack)

        role_name = custom_resource_stack.cfn_resources["CustomInstanceRole"]
        instance_role_arn = boto3.client("iam").get_role(RoleName=role_name).get("Role").get("Arn")
        logging.info("Custom instance role arn %s", instance_role_arn)

        return instance_role_arn

    yield _custom_resource
    if stack_name_post_test and not request.config.getoption("no_delete"):
        cfn_stacks_factory.delete_stack(stack_name_post_test, region)
    else:
        logging.warning("Skipping deletion of CFN image stacks because --no-delete option is set")


def test_build_image_custom_components(
    region, os, instance, test_datadir, pcluster_config_reader, architecture, s3_bucket_factory, images_factory, request
):
    """Test custom components and base AMI is ParallelCluster AMI"""
    # Custom script
    custom_script_file = "custom_script_ubuntu.sh" if os in ["ubuntu2004"] else "custom_script.sh"

    # Create S3 bucket for pre install scripts, to remove epel package if it is installed
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    time.sleep(60)
    bucket.upload_file(str(test_datadir / custom_script_file), "scripts/custom_script.sh")

    # Get ParallelCluster AMI as base AMI
    base_ami = retrieve_latest_ami(region, os, ami_type="pcluster", architecture=architecture)

    image_id = generate_stack_name(
        "integ-tests-build-image-custom-components", request.config.getoption("stackname_suffix")
    )
    image_config = pcluster_config_reader(
        config_file="image.config.yaml",
        parent_image=base_ami,
        instance_type=instance,
        bucket_name=bucket_name,
        region=region,
    )

    image = images_factory(image_id, image_config, region)

    _test_build_image_success(image)


def _test_build_imds_settings(image, status, region):
    logging.info(f"Checking that the ImageBuilder instances have IMDSv2 {status}")

    instance_names = [
        f"Build instance for ParallelClusterImage-{image.image_id}",
        f"Test instance for ParallelClusterImage-{image.image_id}",
    ]

    describe_response = boto3.client("ec2", region_name=region).describe_instances(
        Filters=[{"Name": "tag:Name", "Values": instance_names}]
    )

    for reservations in describe_response.get("Reservations"):
        for instance in reservations.get("Instances"):
            assert_instance_has_desired_imds_v2_setting(instance, status)


def _test_build_instances_tags(image, build_tags, region):
    logging.info("Checking that the ImageBuilder instances have the build tags")

    instance_names = [
        f"Build instance for ParallelClusterImage-{image.image_id}",
        f"Test instance for ParallelClusterImage-{image.image_id}",
    ]

    describe_response = boto3.client("ec2", region_name=region).describe_instances(
        Filters=[{"Name": "tag:Name", "Values": instance_names}]
    )

    for reservations in describe_response.get("Reservations"):
        for instance in reservations.get("Instances"):
            assert_instance_has_desired_tags(instance, build_tags)


def _test_build_image_success(image):
    logging.info("Test build image process for image %s.", image.image_id)

    pcluster_describe_image_result = image.describe()
    logging.info(pcluster_describe_image_result)

    while image.image_status.endswith("_IN_PROGRESS"):  # e.g. BUILD_IN_PROGRESS, DELETE_IN_PROGRESS
        time.sleep(600)
        pcluster_describe_image_result = image.describe()
        logging.info(pcluster_describe_image_result)
    if image.image_status != "BUILD_COMPLETE":
        image.keep_logs = True
        _keep_recent_logs(image)
    assert_that(image.image_status).is_equal_to("BUILD_COMPLETE")


@pytest.mark.usefixtures("os")
def test_build_image_wrong_pcluster_version(
    region,
    instance,
    pcluster_config_reader,
    architecture,
    pcluster_ami_without_standard_naming,
    images_factory,
    request,
):
    """Test error message when AMI provided was baked by a pcluster whose version is different from current version"""
    current_version = get_installed_parallelcluster_version()
    wrong_version = "3.9.3"
    logging.info("Asserting wrong_version is different from current_version")
    assert_that(current_version != wrong_version).is_true()
    # Retrieve an AMI without 'aws-parallelcluster-<version>' in its name.
    # Therefore, we can bypass the version check in CLI and test version check of .bootstrapped file in Cookbook.
    wrong_ami = pcluster_ami_without_standard_naming(wrong_version)

    image_config = pcluster_config_reader(
        config_file="image.config.yaml", parent_image=wrong_ami, instance_type=instance
    )
    image_id = generate_stack_name(
        "integ-tests-build-image-wrong-version", request.config.getoption("stackname_suffix")
    )

    image = images_factory(image_id, image_config, region)

    _test_build_image_failed(image)
    log_stream_name = f"{get_installed_parallelcluster_base_version()}/1"
    log_data = " ".join(log["message"] for log in image.get_log_events(log_stream_name, limit=100)["events"])
    assert_that(log_data).matches(rf"AMI was created.+{wrong_version}.+is.+used.+{current_version}")


def _test_build_image_failed(image):
    logging.info("Test build image process for image %s.", image.image_id)

    pcluster_describe_image_result = image.describe()
    logging.info(pcluster_describe_image_result)

    while image.image_status.endswith("_IN_PROGRESS"):  # e.g. BUILD_IN_PROGRESS, DELETE_IN_PROGRESS
        time.sleep(600)
        pcluster_describe_image_result = image.describe()
        logging.info(pcluster_describe_image_result)

    if image.image_status == "BUILD_FAILED":
        image.keep_logs = True
        _keep_recent_logs(image)
    assert_that(image.image_status).is_equal_to("BUILD_FAILED")


def _keep_recent_logs(image):
    """Keep several lines of recent log to the console when creating an image fails."""
    log_stream_name = f"{get_installed_parallelcluster_base_version()}/1"
    failure_logs = image.get_log_events(log_stream_name, start_from_head=False, query="events[*]", limit=100)
    logging.info(f"Image built failed for {image.image_id}, the last 100 lines of the log are: {failure_logs}")
