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
# fmt: off
from __future__ import absolute_import, print_function  # isort:skip
from future import standard_library  # isort:skip
standard_library.install_aliases()
# fmt: on

import json
import logging
import os
import sys
import time
import urllib.request
import zipfile
from io import BytesIO

import boto3
import pkg_resources
from botocore.exceptions import ClientError

LOGGER = logging.getLogger(__name__)

PCLUSTER_STACK_PREFIX = "parallelcluster-"


def get_stack_name(cluster_name):
    return PCLUSTER_STACK_PREFIX + cluster_name


def get_region():
    """Get AWS_DEFAULT_REGION from the environment."""
    return os.environ.get("AWS_DEFAULT_REGION")


def get_partition():
    """Get partition for the AWS_DEFAULT_REGION set in the environment."""
    return "aws-us-gov" if get_region().startswith("us-gov") else "aws"


def paginate_boto3(method, **kwargs):
    """
    Return a generator for a boto3 call, this allows pagination over an arbitrary number of responses.

    :param method: boto3 method
    :param kwargs: arguments to method
    :return: generator with boto3 results
    """
    client = method.__self__
    paginator = client.get_paginator(method.__name__)
    for page in paginator.paginate(**kwargs).result_key_iters():
        for result in page:
            yield result


def create_s3_bucket(bucket_name, region):
    """
    Create a new S3 bucket.

    :param bucket_name: name of the S3 bucket to create
    :param region: aws region
    """
    s3_client = boto3.client("s3")
    """ :type : pyboto3.s3 """
    try:
        if region != "us-east-1":
            s3_client.create_bucket(Bucket=bucket_name, CreateBucketConfiguration={"LocationConstraint": region})
        else:
            s3_client.create_bucket(Bucket=bucket_name)
    except s3_client.exceptions.BucketAlreadyOwnedByYou:
        print("Bucket already exists")


def delete_s3_bucket(bucket_name):
    """
    Delete an S3 bucket together with all stored objects.

    :param bucket_name: name of the S3 bucket to delete
    """
    try:
        bucket = boto3.resource("s3").Bucket(bucket_name)
        bucket.objects.all().delete()
        bucket.delete()
    except boto3.client("s3").exceptions.NoSuchBucket:
        pass
    except ClientError:
        print("Failed to delete bucket %s. Please delete it manually." % bucket_name)


def zip_dir(path):
    """
    Create a zip archive containing all files and dirs rooted in path.

    The archive is created in memory and a file handler is returned by the function.
    :param path: directory containing the resources to archive.
    :return file handler pointing to the compressed archive.
    """
    file_out = BytesIO()
    with zipfile.ZipFile(file_out, "w", zipfile.ZIP_DEFLATED) as ziph:
        for root, _, files in os.walk(path):
            for file in files:
                ziph.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), start=path))
    file_out.seek(0)
    return file_out


def upload_resources_artifacts(bucket_name, root):
    """
    Upload to the specified S3 bucket the content of the directory rooted in root path.

    All dirs contained in root dir will be uploaded as zip files to $bucket_name/$dir_name/artifacts.zip.
    All files contained in root dir will be uploaded to $bucket_name.

    :param bucket_name: name of the S3 bucket where files are uploaded
    :param root: root directory containing the resources to upload.
    """
    bucket = boto3.resource("s3").Bucket(bucket_name)
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
    bucket_name = "{0}-aws-parallelcluster".format(region)

    file_contents = boto3.resource("s3").Object(bucket_name, file_name).get()["Body"].read().decode("utf-8")
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
    except (ValueError, ClientError, KeyError) as e:
        if isinstance(e, ClientError):
            code = e.response.get("Error").get("Code")
            if code == "InvalidAccessKeyId":
                error(e.response.get("Error").get("Message"))
        error(
            "Failed validate {0}. This is probably a bug on our end. Please submit an issue "
            "https://github.com/aws/aws-parallelcluster/issues/new/choose".format(feature)
        )

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
    return "alinux" if scheduler == "awsbatch" else "alinux", "centos6", "centos7", "ubuntu1604", "ubuntu1804"


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


def get_templates_bucket_path():
    """Return a string containing the path of bucket."""
    region = get_region()
    s3_suffix = ".cn" if region.startswith("cn") else ""
    return "https://s3.{REGION}.amazonaws.com{S3_SUFFIX}/{REGION}-aws-parallelcluster/templates/".format(
        REGION=region, S3_SUFFIX=s3_suffix
    )


def get_installed_version():
    """Get the version of the installed aws-parallelcluster package."""
    return pkg_resources.get_distribution("aws-parallelcluster").version


def check_if_latest_version():
    """Check if the current package version is the latest one."""
    try:
        latest = json.loads(urllib.request.urlopen("https://pypi.python.org/pypi/aws-parallelcluster/json").read())[
            "info"
        ]["version"]
        if get_installed_version() < latest:
            print("Info: There is a newer version %s of AWS ParallelCluster available." % latest)
    except Exception:
        pass


def warn(message):
    """Print a warning message."""
    print("WARNING: {0}".format(message))


def error(message, fail_on_error=True):
    """Print an error message and Raise SystemExit exception to the stderr if fail_on_error is true."""
    if fail_on_error:
        sys.exit("ERROR: {0}".format(message))
    else:
        print("ERROR: {0}".format(message))


def get_cfn_param(params, key_name):
    """
    Get parameter value from Cloudformation Stack Parameters.

    :param params: Cloudformation Stack Parameters
    :param key_name: Parameter Key
    :return: ParameterValue if that parameter exists, otherwise None
    """
    param_value = next((i.get("ParameterValue") for i in params if i.get("ParameterKey") == key_name), "NONE")
    return param_value.strip()


def get_efs_mount_target_id(efs_fs_id, avail_zone):
    """
    Search for a Mount Target Id in given availability zone for the given EFS file system id.

    :param efs_fs_id: EFS file system Id
    :param avail_zone: Availability zone to verify
    :return: the mount_target_id or None
    """
    mount_target_id = None
    if efs_fs_id:
        mount_targets = boto3.client("efs").describe_mount_targets(FileSystemId=efs_fs_id)

        for mount_target in mount_targets.get("MountTargets"):
            # Check to see if there is an existing mt in the az of the stack
            mount_target_subnet = mount_target.get("SubnetId")
            if avail_zone == get_avail_zone(mount_target_subnet):
                mount_target_id = mount_target.get("MountTargetId")

    return mount_target_id


def get_avail_zone(subnet_id):
    return boto3.client("ec2").describe_subnets(SubnetIds=[subnet_id]).get("Subnets")[0].get("AvailabilityZone")


def get_latest_alinux_ami_id():
    """Get latest alinux ami id."""
    try:
        alinux_ami_id = (
            boto3.client("ssm")
            .get_parameters_by_path(Path="/aws/service/ami-amazon-linux-latest")
            .get("Parameters")[0]
            .get("Value")
        )
    except ClientError as e:
        error("Unable to retrieve Amazon Linux AMI id.\n{0}".format(e.response.get("Error").get("Message")))

    return alinux_ami_id


def list_ec2_instance_types():
    """Return a list of all the instance types available on EC2, independent by the region."""
    return boto3.client("ec2").meta.service_model.shape_for("InstanceType").enum
