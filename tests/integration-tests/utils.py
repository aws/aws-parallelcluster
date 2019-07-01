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
import random
import re
import shlex
import string
import subprocess

import boto3
from retrying import retry

from assertpy import assert_that


def retry_if_subprocess_error(exception):
    """Return True if we should retry (in this case when it's a CalledProcessError), False otherwise"""
    return isinstance(exception, subprocess.CalledProcessError)


def run_command(command, capture_output=True, log_error=True):
    """Execute shell command."""
    if isinstance(command, str):
        command = shlex.split(command)
    logging.info("Executing command: " + " ".join(command))
    result = subprocess.run(command, capture_output=capture_output, universal_newlines=True, encoding="utf-8")
    try:
        result.check_returncode()
    except subprocess.CalledProcessError:
        if log_error:
            logging.error(
                "Command {0} failed with error:\n{1}\nand output:\n{2}".format(
                    " ".join(command), result.stderr, result.stdout
                )
            )
        raise

    return result


def random_alphanumeric(size=16):
    """Generate a random alphanumeric string."""
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(size))


@retry(wait_exponential_multiplier=500, wait_exponential_max=5000, stop_max_attempt_number=5)
def retrieve_cfn_outputs(stack_name, region):
    """Retrieve CloudFormation Stack Outputs from a given stack."""
    logging.debug("Retrieving stack outputs for stack {}".format(stack_name))
    try:
        cfn = boto3.client("cloudformation", region_name=region)
        stack = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0]
        outputs = {}
        for output in stack.get("Outputs", []):
            outputs[output.get("OutputKey")] = output.get("OutputValue")
        return outputs
    except Exception as e:
        logging.warning("Failed retrieving stack outputs for stack {} with exception: {}".format(stack_name, e))
        raise


@retry(wait_exponential_multiplier=500, wait_exponential_max=5000, stop_max_attempt_number=5)
def retrieve_cfn_resources(stack_name, region):
    """Retrieve CloudFormation Stack Resources from a given stack."""
    logging.debug("Retrieving stack resources for stack {}".format(stack_name))
    try:
        cfn = boto3.client("cloudformation", region_name=region)
        stack_resources = cfn.list_stack_resources(StackName=stack_name)["StackResourceSummaries"]
        resources = {}
        for resource in stack_resources:
            resources[resource.get("LogicalResourceId")] = resource.get("PhysicalResourceId")
        return resources
    except Exception as e:
        logging.warning("Failed retrieving stack resources for stack {} with exception: {}".format(stack_name, e))
        raise


def to_snake_case(input):
    """Convert a string into its snake case representation."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", input)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def create_s3_bucket(bucket_name, region):
    """
    Create a new S3 bucket.

    :param bucket_name: name of the S3 bucket to create
    :param region: region where the bucket is created
    """
    s3_client = boto3.client("s3", region_name=region)
    if region != "us-east-1":
        s3_client.create_bucket(Bucket=bucket_name, CreateBucketConfiguration={"LocationConstraint": region})
    else:
        s3_client.create_bucket(Bucket=bucket_name)


@retry(wait_exponential_multiplier=500, wait_exponential_max=5000, stop_max_attempt_number=3)
def delete_s3_bucket(bucket_name, region):
    """
    Delete an S3 bucket together with all stored objects.

    :param bucket_name: name of the S3 bucket to delete
    :param region: region of the bucket
    """
    try:
        bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
        bucket.objects.all().delete()
        bucket.delete()
    except boto3.client("s3").exceptions.NoSuchBucket:
        pass


def set_credentials(region, credential_arg):
    """
    Set credentials for boto3 clients and cli commands

    :param region: region of the bucket
    :param credential_arg: credential list
    """
    if credential_arg:
        # credentials = dict { region1: (endpoint1, arn1, external_id1),
        #                      region2: (endpoint2, arn2, external_id2),
        #                      [...],
        #                    }
        credentials = {
            region: (endpoint, arn, external_id)
            for region, endpoint, arn, external_id in [
                tuple(credential_tuple.strip().split(","))
                for credential_tuple in credential_arg
                if credential_tuple.strip()
            ]
        }

        if region in credentials:
            credential_endpoint, credential_arn, credential_external_id = credentials.get(region)
            aws_credentials = _retrieve_sts_credential(
                credential_endpoint, credential_arn, credential_external_id, region
            )

            # Set credential for all boto3 client
            boto3.setup_default_session(
                aws_access_key_id=aws_credentials["AccessKeyId"],
                aws_secret_access_key=aws_credentials["SecretAccessKey"],
                aws_session_token=aws_credentials["SessionToken"],
            )

            # Set credential for all cli command e.g. pcluster create
            os.environ["AWS_ACCESS_KEY_ID"] = aws_credentials["AccessKeyId"]
            os.environ["AWS_SECRET_ACCESS_KEY"] = aws_credentials["SecretAccessKey"]
            os.environ["AWS_SESSION_TOKEN"] = aws_credentials["SessionToken"]


def _retrieve_sts_credential(credential_endpoint, credential_arn, credential_external_id, region):
    match = re.search(r"https://sts\.(.*?)\.", credential_endpoint)
    endpoint_region = match.group(1)

    assert_that(credential_endpoint and endpoint_region and credential_arn and credential_external_id).is_true()

    sts = boto3.client("sts", region_name=endpoint_region, endpoint_url=credential_endpoint)
    assumed_role_object = sts.assume_role(
        RoleArn=credential_arn, ExternalId=credential_external_id, RoleSessionName=region + "_integration_tests_session"
    )
    aws_credentials = assumed_role_object["Credentials"]

    return aws_credentials


def unset_credentials():
    """Unset credentials"""
    # Unset credential for all boto3 client
    boto3.setup_default_session()
    # Unset credential for cli command e.g. pcluster create
    if "AWS_ACCESS_KEY_ID" in os.environ:
        del os.environ["AWS_ACCESS_KEY_ID"]
    if "AWS_SECRET_ACCESS_KEY" in os.environ:
        del os.environ["AWS_SECRET_ACCESS_KEY"]
    if "AWS_SESSION_TOKEN" in os.environ:
        del os.environ["AWS_SESSION_TOKEN"]
