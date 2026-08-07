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
import os
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
from utils import generate_stack_name, get_arn_partition, get_gpu_count, run_command

from tests.common.assertions import (
    _assert_build_image_stack_deleted,
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
    upload_github_artifacts_to_s3,
)
from tests.proxy.test_proxy import proxy_stack_factory  # noqa: F401


class ImageNotFound(Exception):
    """Exception when image is not found."""

    pass


def _get_base_ami(region, os, architecture):
    """Select the appropriate base AMI and feature flags based on OS.

    Uses first-stage AMIs for RHEL/Rocky/Ubuntu (kernel version requirements),
    remarkable (Deep Learning) AMIs for ubuntu2204, and official AMIs for everything else.
    Returns (base_ami, feature_flags) where feature_flags is a dict with keys:
      enable_nvidia, update_os_packages, enable_lustre_client.
    """
    enable_nvidia = os not in ["ubuntu2404"]
    update_os_packages = os in ["alinux2023", "rocky9"]
    enable_lustre_client = True

    if os in ["ubuntu2204"]:
        # Test Deep Learning AMIs
        base_ami = retrieve_latest_ami(region, os, ami_type="remarkable", architecture=architecture)
        enable_nvidia = False  # Deep learning AMIs have Nvidia pre-installed
    elif "rhel" in os or "ubuntu" in os or os == "rocky8":
        # Use official AMIs. First stage AMIs must not be used as parent image in this test.
        base_ami = retrieve_latest_ami(region, os, ami_type="official", architecture=architecture)
        update_os_packages = True
        if os in ["ubuntu2204", "rhel9", "ubuntu2404"]:
            enable_lustre_client = False
    else:
        # Test vanilla AMIs.
        base_ami = retrieve_latest_ami(region, os, ami_type="official", architecture=architecture)
        if os in ["rocky9"]:
            enable_lustre_client = False

    feature_flags = {
        "enable_nvidia": enable_nvidia,
        "update_os_packages": update_os_packages,
        "enable_lustre_client": enable_lustre_client,
    }
    return base_ami, feature_flags


@pytest.mark.usefixtures("instance")
def test_build_image_no_internet(
    region,
    os,
    pcluster_config_reader,
    architecture,
    proxy_stack_factory,  # noqa: F811
    images_factory,
    s3_bucket_factory,
    request,
):
    """Test build image in a private subnet with no internet access, only VPC endpoints and a proxy for OS repos."""
    base_ami, _ = _get_base_ami(region, os, architecture)

    # Create proxy stack with build-image mode enabled
    no_internet_proxy_stack = proxy_stack_factory(enable_build_image_proxy=True)

    # Upload dev packages to S3 so the build instance can access them via the S3 VPC endpoint
    # instead of GitHub (which is blocked in the no-internet environment).
    bucket_name = s3_bucket_factory()
    s3_artifacts = upload_github_artifacts_to_s3(bucket_name, region, request)

    # Get the proxy URL from the stack output
    install_http_proxy_address = no_internet_proxy_stack.cfn_outputs["ProxyAddress"]

    image_id = generate_stack_name("integ-tests-build-image-no-internet", request.config.getoption("stackname_suffix"))
    image_config = pcluster_config_reader(
        config_file="image.config.yaml",
        parent_image=base_ami,
        subnet_id=no_internet_proxy_stack.cfn_outputs["PrivateSubnet"],
        security_group_id=no_internet_proxy_stack.cfn_outputs["DefaultSecurityGroupId"],
        chef_cookbook=s3_artifacts["chef_cookbook"],
        node_package=s3_artifacts["node_package"],
        install_http_proxy_address=install_http_proxy_address,
    )

    image = images_factory(image_id, image_config, region)
    _test_build_image_success(image, request.config.getoption("output_dir"))


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

    base_ami = retrieve_latest_ami(region, os, ami_type="remarkable", architecture=architecture)

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


@pytest.mark.flaky(only_rerun=["ImageNotFound"])
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
    noexec_tmp_ami_factory,
    request,
    clusters_factory,
    scheduler_commands_factory,
):
    """
    Test build image for given region and os.

    In the cluster config there is DisableValidateAndTest:False to enable kitchen tests in the validate phase.
    The created AMI is also used for a cluster.
    Also check that the build instance has the desired ImdsSupport setting (v2.0, so IMDSv2 is required).
    Also check that the build-image stack can be fully self deleted.
    """
    image_id = generate_stack_name("integ-tests-build-image", request.config.getoption("stackname_suffix"))

    # Get custom instance role
    instance_role = build_image_custom_resource(image_id=image_id)

    # Get custom S3 bucket
    bucket_name = s3_bucket_factory()
    _set_s3_bucket_policy(bucket_name, get_arn_partition(region), region)

    # Get base AMI and feature flags
    base_ami, flags = _get_base_ami(region, os, architecture)

    enable_nvidia = flags["enable_nvidia"] and get_gpu_count(instance) > 0
    if not enable_nvidia:
        # Build from an AMI where /tmp is already noexec at boot.
        base_ami = noexec_tmp_ami_factory(base_ami, instance)

    image_config = pcluster_config_reader(
        config_file="image.config.yaml",
        parent_image=base_ami,
        instance_role=instance_role,
        bucket_name=bucket_name,
        enable_nvidia=str(enable_nvidia).lower(),
        update_os_packages=str(flags["update_os_packages"]).lower(),
        enable_lustre_client=str(flags["enable_lustre_client"]).lower(),
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
        _wait_for_build_instance(image, region)
        _test_build_instances_tags(image, image.config["Build"]["Tags"], region)
        _test_build_imds_settings(image, "required", region)

        _test_build_image_success(image, request.config.getoption("output_dir"))

        # Only validate export-image-logs if the build did NOT complete successfully. On a successful
        # build the build-image stack self-deletes, which races the export command and causes
        # intermittent "stack does not exist" failures; a successful build also does not need its logs
        # exported. If the build failed the stack is retained, so the export reliably has its stack.
        #
        # On a successful build we still want evidence that the build logs reached CloudWatch, so we tail
        # the image build log group instead: `aws logs tail` reads the log group directly and has none of
        # export's dependencies (no S3 bucket, no build-image stack), so it cannot hit the deletion race.
        if image.image_status != "BUILD_COMPLETE":
            _test_export_logs(s3_bucket_factory, image, region)
            _test_export_logs(s3_bucket_factory, image, region, True)
        else:
            _test_tail_image_logs(image, region)

        _test_image_tag_and_volume(image)
        _test_list_image_log_streams(image)
        _test_get_image_log_events(image)
        _test_list_images(image)

    _test_cluster_creation(
        image.ec2_image_id, pcluster_config_reader, region, clusters_factory, scheduler_commands_factory
    )
    _assert_build_image_stack_deleted(image.image_id, region, 900, 30)


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


def _test_tail_image_logs(image, region):
    """Assert the image build logs reached CloudWatch by tailing the image build log group.

    Used on a successful build, where export-image-logs is skipped (the build-image stack self-deletes
    and races the export). ``aws logs tail`` reads the log group directly -- no S3 bucket and no
    dependency on the build-image stack -- so it gives race-free evidence that logs are being pushed.
    The image build log group is ``/aws/imagebuilder/ParallelClusterImage-<image_id>``.
    """
    logging.info("Testing that image build logs reached CloudWatch via aws logs tail")
    log_group_name = f"/aws/imagebuilder/ParallelClusterImage-{image.image_id}"
    # `aws logs tail` defaults to only the last 10 minutes; an image build takes much longer, so widen
    # the window with --since so an empty result means "no logs" rather than "no logs in the last 10 min".
    result = run_command(
        ["aws", "logs", "tail", log_group_name, "--since", "1h", "--region", region],
        raise_on_error=True,
    )
    assert_that(result.stdout.strip()).described_as(
        f"no log events found in {log_group_name}; build logs were not pushed to CloudWatch"
    ).is_not_empty()


def _test_export_logs(s3_bucket_factory, image, region, use_pcluster_bucket=False):
    bucket_name = None
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

        ret = image.export_logs(
            bucket=bucket_name,
            output_file=output_file,
            bucket_prefix=bucket_prefix,
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
    if not image_list:
        raise ImageNotFound()
    assert_that(len(image_list)).is_equal_to(1)

    if len(image_list) > 0:
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
    custom_script_file = "custom_script_ubuntu.sh" if os.startswith("ubuntu") else "custom_script.sh"

    # Create S3 bucket for pre install scripts, to remove epel package if it is installed
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    time.sleep(60)
    bucket.upload_file(str(test_datadir / custom_script_file), "scripts/custom_script.sh")

    # Get ParallelCluster AMI as base AMI
    base_ami = retrieve_latest_ami(region, os, ami_type="pcluster", architecture=architecture, request=request)

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

    _test_build_image_success(image, request.config.getoption("output_dir"))


@retry(wait_fixed=seconds(10), stop_max_delay=minutes(10))
def _wait_for_build_instance(image, region):
    """Wait until the ImageBuilder build instance is launched.

    The build instance exists only while the image is being built; it is terminated and the build-image
    stack self-deletes once the image reaches BUILD_COMPLETE. Waiting for it here lets the tag and IMDS
    checks run against a live instance instead of racing the teardown or passing vacuously.
    """
    instance_name = f"Build instance for ParallelClusterImage-{image.image_id}"
    reservations = (
        boto3.client("ec2", region_name=region)
        .describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [instance_name]},
                {"Name": "instance-state-name", "Values": ["running"]},
            ]
        )
        .get("Reservations")
    )
    return [instance for reservation in reservations for instance in reservation.get("Instances", [])]


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


def _test_build_image_success(image, output_dir):
    logging.info("Test build image process for image %s.", image.image_id)

    pcluster_describe_image_result = image.describe()
    logging.info(pcluster_describe_image_result)

    # Poll every 5 minutes so BUILD_COMPLETE is detected close to when it happens. The build-image stack
    # self-deletes on build success, so detecting completion sooner reduces the export-image-logs race window.
    while image.image_status.endswith("_IN_PROGRESS"):  # e.g. BUILD_IN_PROGRESS, DELETE_IN_PROGRESS
        time.sleep(300)
        pcluster_describe_image_result = image.describe()
        logging.info(pcluster_describe_image_result)
    if image.image_status != "BUILD_COMPLETE":
        _export_image_logs(image, output_dir)
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
    s3_bucket_factory,
    request,
):
    """Test error message when AMI provided was baked by a pcluster whose version is different from current version"""
    current_version = get_installed_parallelcluster_version()
    # Compute a wrong version that is 2 minor versions before the current one, with patch set to 0.
    # For example, if the current version is 3.15.1, the wrong_version is 3.13.0.
    major, minor, _ = (int(part) for part in current_version.split("."))
    wrong_version = f"{major}.{minor - 2}.0"
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

    _test_build_image_failed(image, request.config.getoption("output_dir"))

    # This build deterministically fails, so the build-image stack is retained (it does not
    # self-delete). That makes it a reliable place to validate export-image-logs end to end, for
    # both a custom bucket and the default pcluster bucket.
    _test_export_logs(s3_bucket_factory, image, region)
    _test_export_logs(s3_bucket_factory, image, region, True)

    log_stream_name = f"{get_installed_parallelcluster_base_version()}/1"
    log_data = " ".join(log["message"] for log in image.get_log_events(log_stream_name, limit=100)["events"])
    assert_that(log_data).matches(rf"AMI was created.+{wrong_version}.+is.+used.+{current_version}")


def _test_build_image_failed(image, output_dir):
    logging.info("Test build image process for image %s.", image.image_id)

    pcluster_describe_image_result = image.describe()
    logging.info(pcluster_describe_image_result)

    while image.image_status.endswith("_IN_PROGRESS"):  # e.g. BUILD_IN_PROGRESS, DELETE_IN_PROGRESS
        time.sleep(600)
        pcluster_describe_image_result = image.describe()
        logging.info(pcluster_describe_image_result)

    if image.image_status == "BUILD_FAILED":
        _export_image_logs(image, output_dir)
        _keep_recent_logs(image)
    assert_that(image.image_status).is_equal_to("BUILD_FAILED")


def _export_image_logs(image, output_dir):
    """Export the full image build log archive to the test output directory using pcluster export-image-logs."""
    log_dir = os.path.join(output_dir, "image_build_logs")
    os.makedirs(log_dir, exist_ok=True)
    output_file = os.path.join(log_dir, f"{image.image_id}-logs.tar.gz")
    try:
        ret = image.export_logs(output_file=output_file)
        logging.info(f"Full image build log exported to {ret.get('path', output_file)}")
    except Exception as e:
        logging.error(f"Failed to export image build logs for {image.image_id}: {e}")


def _keep_recent_logs(image):
    """Keep several lines of recent log to the console when creating an image fails."""
    log_stream_name = f"{get_installed_parallelcluster_base_version()}/1"
    nlines = 200
    log_events = image.get_log_events(log_stream_name, start_from_head=False, query="events[*]", limit=nlines)
    log_messages = [event["message"] for event in log_events]
    logging.info(
        f"Image built failed for {image.image_id}, the last {nlines} lines of the log are:\n" + "\n".join(log_messages)
    )
