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
import io
import logging
import os
import time
from zipfile import ZipFile

import boto3
import pytest
from assertpy import assert_that
from Crypto.PublicKey import RSA
from remote_command_executor import RemoteCommandExecutor
from utils import get_username_for_os

from tests.common.utils import retrieve_latest_ami


@pytest.mark.dimensions("eu-west-1", "c5.xlarge", "*", "*")
@pytest.mark.usefixtures("instance", "scheduler")
def test_create_multi_user_with_active_directory(
    region,
    os,
    pcluster_config_reader,
    s3_bucket_factory,
    clusters_factory,
    architecture,
    vpc_stack,
    test_datadir,
    policy_factory,
    role_factory,
    ssm_parameter_factory,
    dhcp_options_set_factory,
    active_directory_factory,
    lambda_function_factory,
):
    """Test the creation of a cluster whose users are managed by Active Directory."""

    # Create SimpleAD
    vpc_id = vpc_stack.cfn_outputs["VpcId"]
    public_subnet_id = vpc_stack.cfn_outputs["PublicSubnetId"]
    private_subnet_id = vpc_stack.cfn_outputs["PrivateAdditionalCidrSubnetId"]
    directory_id, directory_name, directory_password = active_directory_factory(
        vpc_id, public_subnet_id, private_subnet_id
    )

    response = wait_directory_to_be_active(region, directory_id)
    dns_ip_addresses = response["DirectoryDescriptions"][0]["DnsIpAddrs"]

    # Configure DHCP Option Set for VPC
    dhcp_options_set_factory(
        vpc_id=vpc_id,
        dhcp_configurations=[
            {"Key": "domain-name", "Values": [directory_name]},
            {"Key": "domain-name-servers", "Values": dns_ip_addresses},
        ],
    )

    # SSM Parameters
    domain_name_parameter = ssm_parameter_factory(value=directory_name, type="String")
    domain_password_parameter = ssm_parameter_factory(value=directory_password, type="SecureString")

    # IAM Policy for the head node to interact with Active Directory
    active_directory_policy_arn = create_policy_from_file(
        policy_factory, f"{test_datadir}/active_directory_policy.json"
    )

    # IAM Policy for the Lambda execution role
    get_join_credentials_policy_arn = create_policy_from_file(
        policy_factory, f"{test_datadir}/get_join_credentials_policy.json"
    )

    # IAM role for the Lambda execution role
    lambda_execution_role_name, lambda_execution_role_arn = role_factory(
        trusted_service="lambda",
        policies=["arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole", get_join_credentials_policy_arn],
    )

    # Create resource bucket and upload resources
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "pre_install.sh"), "pre_install.sh")
    bucket.upload_file(str(test_datadir / "post_install.sh"), "post_install.sh")

    # Create Lambda
    _, function_name = lambda_function_factory(
        Runtime="python2.7",
        Role=lambda_execution_role_arn,
        Handler="lambda_handler",
        Code={"ZipFile": make_zip_file_bytes(path=str(test_datadir / "join_domain_lambda"))},
        Timeout=30,
        MemorySize=128,
        Publish=True,
        Environment={
            "Variables": {
                "DOMAIN_NAME_PARAMETER": domain_name_parameter,
                "DOMAIN_PASSWORD_PARAMETER": domain_password_parameter,
            }
        },
    )

    # Create cluster
    custom_ami = retrieve_latest_ami(region, os, ami_type="pcluster", architecture=architecture)
    cluster_config = pcluster_config_reader(
        custom_ami=custom_ami,
        bucket_name=bucket_name,
        active_directory_policy_arn=active_directory_policy_arn,
        lambda_function_name=function_name,
    )
    cluster = clusters_factory(cluster_config, raise_on_error=False)

    _assert_head_node_is_running(region, cluster)

    active_directory_admin_user = "administrator"
    assert_aws_identity_access_is_correct(
        cluster=cluster, users_allow_list={"root": True, "pcluster-admin": True, active_directory_admin_user: False}
    )

    # TODO add assertions about ssh access and job submission
    # assert_ssh_login(cluster=cluster, username=active_directory_admin_user, ssh_key=private_key_path)


@pytest.mark.dimensions("us-east-1", "c5.xlarge", "*", "*")
@pytest.mark.usefixtures("instance", "scheduler")
def test_create_multi_user_with_opsworks(
    region,
    os,
    pcluster_config_reader,
    s3_bucket_factory,
    clusters_factory,
    architecture,
    vpc_stack,
    test_datadir,
    policy_factory,
    role_factory,
    instance_profile_factory,
    user_factory,
    opsworks_stack_factory,
    opsworks_user_profile_factory,
):
    """Test the creation of a cluster whose users are managed with OpsWorks."""

    logging.info("TROUBLESHOOTING log")

    # Create IAM resources required by OpsWorks stack
    opsworks_service_role_policy_arn = create_policy_from_file(
        policy_factory, f"{test_datadir}/opsworks_service_role_policy.json"
    )
    _, opsworks_service_role_arn = role_factory(trusted_service="opsworks", policies=[opsworks_service_role_policy_arn])
    opsworks_instance_profile_arn = instance_profile_factory()

    # Create OpsWorks stack
    vpc_id = vpc_stack.cfn_outputs["VpcId"]
    subnet_id = vpc_stack.cfn_outputs["PublicSubnetId"]
    opsworks_stack_id = opsworks_stack_factory(
        vpc_id, subnet_id, opsworks_service_role_arn, opsworks_instance_profile_arn
    )

    # Create resource bucket and upload scripts
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "post_install.sh"), "post_install.sh")

    # Create cluster
    custom_ami = retrieve_latest_ami(region, os, ami_type="pcluster", architecture=architecture)
    cluster_config = pcluster_config_reader(
        custom_ami=custom_ami, bucket_name=bucket_name, opsworks_stack_id=opsworks_stack_id
    )
    cluster = clusters_factory(cluster_config, raise_on_error=False)

    _assert_head_node_is_running(region, cluster)

    # The opsworks-agent process is run as aws user, so it requires the access to IMDS
    configure_imds_access(cluster, {"aws": True})

    # Create new user credentials
    key = RSA.generate(2048)
    private_key = key.export_key()
    private_key_path = f"{test_datadir}/private.key"
    with (open(private_key_path, "wb")) as file:
        file.write(private_key)
    public_key = key.publickey().export_key().decode("utf-8")

    # Create new user
    user_arn, user_name = user_factory()
    _, ssh_user_name = opsworks_user_profile_factory(user_arn, user_name, public_key)

    time.sleep(120)  # TODO: implement a waiter here

    assert_aws_identity_access_is_correct(
        cluster=cluster, users_allow_list={"root": True, "pcluster-admin": True, ssh_user_name: False}
    )

    # TODO add assertions about ssh access and job submission
    # assert_ssh_login(cluster=cluster, username=ssh_user_name, ssh_key=private_key_path)

    # Need to delete the cluster before deleting OpsWorks stack
    # cluster.delete()


def _get_head_node_instance(cluster):
    return (
        boto3.client("ec2", region_name=cluster.region)
        .describe_instances(Filters=[{"Name": "ip-address", "Values": [cluster.head_node_ip]}])
        .get("Reservations")[0]
        .get("Instances")[0]
        .get("InstanceId")
    )


def configure_imds_access(cluster, users_allow_list):
    username = get_username_for_os(cluster.os)
    remote_command_executor = RemoteCommandExecutor(cluster, username=username)

    for user, allowed in users_allow_list.items():
        logging.info(f"{'Allowing' if allowed else 'Denying'} access to IMDS for user {user}")
        command = f"sudo /opt/parallelcluster/scripts/imds/imds-access.sh --{'allow' if allowed else 'deny'} {user}"
        result = remote_command_executor.run_remote_command(command)
        logging.info(f"result.stdout {result.stdout}")
        logging.info(f"result.stderr {result.stderr}")
        logging.info(f"result.failed {result.failed}")


def assert_os_users_existence(cluster, users_existence):
    logging.info("Asserting OS users existence is correct")
    username = get_username_for_os(cluster.os)
    remote_command_executor = RemoteCommandExecutor(cluster, username=username)

    for user, exists in users_existence.items():
        logging.info(f"Asserting OS user {user} {'exists' if exists else 'does not exist'}")
        command = f"sudo id {user}"
        result = remote_command_executor.run_remote_command(command, raise_on_error=False)
        logging.info(f"result.stdout {result.stdout}")
        logging.info(f"result.stderr {result.stderr}")
        logging.info(f"result.failed {result.failed}")
        assert_that(result.failed).is_equal_to(not exists)


def assert_aws_identity_access_is_correct(cluster, users_allow_list):
    logging.info("Asserting access to AWS caller identity is correct")
    username = get_username_for_os(cluster.os)
    remote_command_executor = RemoteCommandExecutor(cluster, username=username)

    for user, allowed in users_allow_list.items():
        logging.info(f"Asserting access to AWS caller identity is {'allowed' if allowed else 'denied'} for user {user}")
        command = f"sudo -u {user} aws sts get-caller-identity"
        result = remote_command_executor.run_remote_command(command, raise_on_error=False)
        logging.info(f"result.stdout {result.stdout}")
        logging.info(f"result.stderr {result.stderr}")
        logging.info(f"result.failed {result.failed}")
        assert_that(result.failed).is_equal_to(not allowed)


def assert_ssh_login(cluster, username, ssh_key):
    remote_command_executor = RemoteCommandExecutor(cluster, username=username, ssh_key=ssh_key)
    command = "echo Hello"
    result = remote_command_executor.run_remote_command(command, raise_on_error=False)
    logging.info(f"result.stdout {result.stdout}")
    logging.info(f"result.stderr {result.stderr}")
    logging.info(f"result.failed {result.failed}")
    assert_that(result.failed).is_equal_to(False)


def wait_directory_to_be_active(region, directory_id):
    ds = boto3.client("ds", region_name=region)

    wait_time_seconds = 60
    attempts = 0
    max_attempts = 5
    while attempts < max_attempts:
        ds_response = ds.describe_directories(DirectoryIds=[directory_id])
        directory_stage = ds_response["DirectoryDescriptions"][0]["Stage"]
        if directory_stage == "Active":
            return ds_response
        time.sleep(wait_time_seconds)
    raise Exception(
        f"Active Directory {directory_id} did not reach status Active "
        f"within the expected time span ({wait_time_seconds*max_attempts} seconds)"
    )


def _assert_head_node_is_running(region, cluster):
    logging.info("Asserting the head node is running")
    head_node_state = (
        boto3.client("ec2", region_name=region)
        .describe_instances(Filters=[{"Name": "ip-address", "Values": [cluster.head_node_ip]}])
        .get("Reservations")[0]
        .get("Instances")[0]
        .get("State")
        .get("Name")
    )
    assert_that(head_node_state).is_equal_to("running")


def create_policy_from_file(policy_factory, file_path):
    with (open(file_path, "r")) as file:
        policy_document = file.read()
    return policy_factory(policy_document)


def files_to_zip(path):
    for root, _, files in os.walk(path):
        for f in files:
            full_path = os.path.join(root, f)
            archive_name = full_path[len(path) + len(os.sep) :]
            yield full_path, archive_name


def make_zip_file_bytes(path):
    buf = io.BytesIO()
    with ZipFile(buf, "w") as z:
        for full_path, archive_name in files_to_zip(path=path):
            z.write(full_path, archive_name)
    return buf.getvalue()
