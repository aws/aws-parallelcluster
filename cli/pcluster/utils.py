# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with
# the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import absolute_import, print_function

import json
import logging
import os
import sys
import time
import zipfile
from io import BytesIO

import boto3
from botocore.exceptions import ClientError

LOGGER = logging.getLogger("pcluster.pcluster")


def boto3_client(service, aws_client_config):
    return boto3.client(
        service,
        region_name=aws_client_config["region_name"],
        aws_access_key_id=aws_client_config["aws_access_key_id"],
        aws_secret_access_key=aws_client_config["aws_secret_access_key"],
    )


def boto3_resource(service, aws_client_config):
    return boto3.resource(
        service,
        region_name=aws_client_config["region_name"],
        aws_access_key_id=aws_client_config["aws_access_key_id"],
        aws_secret_access_key=aws_client_config["aws_secret_access_key"],
    )


def create_s3_bucket(bucket_name, aws_client_config):
    """
    Create a new S3 bucket.

    Args:
        bucket_name: name of the S3 bucket to create
        aws_client_config: dictionary containing configuration params for boto3 client
    """
    s3_client = boto3_client("s3", aws_client_config)
    """ :type : pyboto3.s3 """
    try:
        region = aws_client_config["region_name"]
        if region != "us-east-1":
            s3_client.create_bucket(Bucket=bucket_name, CreateBucketConfiguration={"LocationConstraint": region})
        else:
            s3_client.create_bucket(Bucket=bucket_name)
    except s3_client.exceptions.BucketAlreadyOwnedByYou:
        print("Bucket already exists")


def delete_s3_bucket(bucket_name, aws_client_config):
    """
    Delete an S3 bucket together with all stored objects.

    Args:
        bucket_name: name of the S3 bucket to delete
        aws_client_config: dictionary containing configuration params for boto3 client
    """
    try:
        bucket = boto3_resource("s3", aws_client_config).Bucket(bucket_name)
        bucket.objects.all().delete()
        bucket.delete()
    except boto3.client("s3").exceptions.NoSuchBucket:
        pass
    except ClientError:
        print("Failed to delete bucket %s. Please delete it manually." % bucket_name)
        pass


def zip_dir(path):
    """
    Create a zip archive containing all files and dirs rooted in path.

    The archive is created in memory and a file handler is returned by the function.
    Args:
        path: directory containing the resources to archive.
    Return:
        file_out: file handler pointing to the compressed archive.
    """
    file_out = BytesIO()
    with zipfile.ZipFile(file_out, "w", zipfile.ZIP_DEFLATED) as ziph:
        for root, _, files in os.walk(path):
            for file in files:
                ziph.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), start=path))
    file_out.seek(0)
    return file_out


def upload_resources_artifacts(bucket_name, root, aws_client_config):
    """
    Upload to the specified S3 bucket the content of the directory rooted in root path.

    All dirs contained in root dir will be uploaded as zip files to $bucket_name/$dir_name/artifacts.zip.
    All files contained in root dir will be uploaded to $bucket_name.
    Args:
        bucket_name: name of the S3 bucket where files are uploaded
        root: root directory containing the resources to upload.
        aws_client_config: dictionary containing configuration params for boto3 client
    """
    bucket = boto3_resource("s3", aws_client_config).Bucket(bucket_name)
    for res in os.listdir(root):
        if os.path.isdir(os.path.join(root, res)):
            bucket.upload_fileobj(zip_dir(os.path.join(root, res)), "%s/artifacts.zip" % res)
        elif os.path.isfile(os.path.join(root, res)):
            bucket.upload_file(os.path.join(root, res), res)


def _get_json_from_s3(region, file_name):
    """
    Get pricing file (if none) and parse content as json.

    :param region: AWS Region
    :param file_name the object name to get
    :return: a json object representing the file content
    :raises ClientError if unable to download the file
    :raises ValueError if unable to decode the file content
    """
    s3 = boto3.resource("s3", region_name=region)
    bucket_name = "{0}-aws-parallelcluster".format(region)

    file_contents = s3.Object(bucket_name, file_name).get()["Body"].read().decode("utf-8")
    return json.loads(file_contents)


def get_supported_features(region, feature):
    """
    Get a json object containing the attributes supported by a feature, for example.

    {
        "Features": {
            "efa": {
                "instances": ["c5n.18xlarge", "p3dn.24xlarge", "i3en.24xlarge"],
                "baseos": ["alinux", "centos7"],
                "schedulers": ["sge", "slurm", "torque"]
            },
            "batch": {
                "instances": ["r3.8xlarge", ..., "m5.4xlarge"]
            }
        }
    }

    :param region: AWS Region
    :param feature: the feature to search for, i.e. "efa" "awsbatch"
    :return: json object containing all the attributes supported by feature
    """
    try:
        features = _get_json_from_s3(region, "features/feature_whitelist.json")
        supported_features = features.get("Features").get(feature)
    except (ValueError, ClientError, KeyError):
        print(
            "Failed validate %s. This is probably a bug on our end. Please set sanity_check = false and retry" % feature
        )
        exit(1)

    return supported_features


def get_instance_vcpus(region, instance_type):
    """
    Get number of vcpus for the given instance type.

    :param region: AWS Region
    :param instance_type: the instance type to search for.
    :return: the number of vcpus or -1 if the instance type cannot be found
    or the pricing file cannot be retrieved/parsed
    """
    try:
        instances = _get_json_from_s3(region, "instances/instances.json")
        vcpus = int(instances[instance_type]["vcpus"])
    except (KeyError, ValueError, ClientError):
        vcpus = -1

    return vcpus


def get_supported_os(scheduler):
    """
    Return a tuple of the os supported by parallelcluster for the specific scheduler.

    :param scheduler: the scheduler for which we want to know the supported os
    :return: a tuple of strings of the supported os
    """
    return "alinux" if scheduler == "awsbatch" else "alinux", "centos6", "centos7", "ubuntu1404", "ubuntu1604"


def get_supported_schedulers():
    """
    Return a tuple of the scheduler supported by parallelcluster.

    :return: a tuple of strings of the supported scheduler
    """
    return "sge", "torque", "slurm", "awsbatch"


def get_stack_output_value(stack_outputs, output_key):
    """
    Get output value from Cloudformation Stack Output.

    :param stack_outputs: Cloudformation Stack Outputs
    :param output_key: Output Key
    :return: OutputValue if that output exists, otherwise None
    """
    return next((o.get("OutputValue") for o in stack_outputs if o.get("OutputKey") == output_key), None)


def verify_stack_creation(cfn_client, stack_name):
    """
    Wait for the stack creation to be completed and notify if the stack creation fails.

    :param cfn_client: the CloudFormation client to use to verify stack status
    :param stack_name: the stack name that we should verify
    :return: True if the creation was successful, false otherwise.
    """
    status = cfn_client.describe_stacks(StackName=stack_name).get("Stacks")[0].get("StackStatus")
    resource_status = ""
    while status == "CREATE_IN_PROGRESS":
        status = cfn_client.describe_stacks(StackName=stack_name).get("Stacks")[0].get("StackStatus")
        events = cfn_client.describe_stack_events(StackName=stack_name).get("StackEvents")[0]
        resource_status = ("Status: %s - %s" % (events.get("LogicalResourceId"), events.get("ResourceStatus"))).ljust(
            80
        )
        sys.stdout.write("\r%s" % resource_status)
        sys.stdout.flush()
        time.sleep(5)
    # print the last status update in the logs
    if resource_status != "":
        LOGGER.debug(resource_status)
    if status != "CREATE_COMPLETE":
        LOGGER.critical("\nCluster creation failed.  Failed events:")
        events = cfn_client.describe_stack_events(StackName=stack_name).get("StackEvents")
        for event in events:
            if event.get("ResourceStatus") == "CREATE_FAILED":
                LOGGER.info(
                    "  - %s %s %s",
                    event.get("ResourceType"),
                    event.get("LogicalResourceId"),
                    event.get("ResourceStatusReason"),
                )
        return False
    return True


def get_templates_bucket_path(aws_region_name):
    """Return a string containing the path of bucket."""
    s3_suffix = ".cn" if aws_region_name.startswith("cn") else ""
    return "https://s3.{REGION}.amazonaws.com{S3_SUFFIX}/{REGION}-aws-parallelcluster/templates/".format(
        REGION=aws_region_name, S3_SUFFIX=s3_suffix
    )
