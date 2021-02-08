# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import logging
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError, ParamValidationError

from pcluster.utils import get_region, validate_pcluster_version_based_on_ami_name

LOGFILE_LOGGER = logging.getLogger("cli_log_file")

FSX_PARAM_WITH_DEFAULT = {"drive_cache_type": "NONE"}

EBS_VOLUME_TYPE_TO_VOLUME_SIZE_BOUNDS = {
    "standard": (1, 1024),
    "io1": (4, 16 * 1024),
    "io2": (4, 64 * 1024),
    "gp2": (1, 16 * 1024),
    "gp3": (1, 16 * 1024),
    "st1": (500, 16 * 1024),
    "sc1": (500, 16 * 1024),
}

EBS_VOLUME_IOPS_BOUNDS = {
    "io1": (100, 64000),
    "io2": (100, 256000),
    "gp3": (3000, 16000),
}

EBS_VOLUME_TYPE_TO_IOPS_RATIO = {"io1": 50, "io2": 1000, "gp3": 500}

HEAD_NODE_UNSUPPORTED_INSTANCE_TYPES = []
HEAD_NODE_UNSUPPORTED_MESSAGE = "The instance type '{0}' is not supported as head node."


def _get_sts_endpoint():
    """Get regionalized STS endpoint."""
    region = get_region()
    return "https://sts.{0}.{1}".format(region, "amazonaws.com.cn" if region.startswith("cn-") else "amazonaws.com")


def disable_hyperthreading_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if param_value:
        # Check to see if cfn_scheduler_slots is set
        cluster_section = pcluster_config.get_section("cluster")
        extra_json = cluster_section.get_param_value("extra_json")
        if extra_json and extra_json.get("cluster") and extra_json.get("cluster").get("cfn_scheduler_slots"):
            errors.append("cfn_scheduler_slots cannot be set in addition to disable_hyperthreading = true")

    return errors, warnings


def disable_hyperthreading_architecture_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    supported_architectures = ["x86_64"]

    architecture = pcluster_config.get_section("cluster").get_param_value("architecture")
    if param_value and architecture not in supported_architectures:
        errors.append(
            "disable_hyperthreading is only supported on instance types that support these architectures: {0}".format(
                ", ".join(supported_architectures)
            )
        )

    return errors, warnings


def kms_key_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    try:
        boto3.client("kms").describe_key(KeyId=param_value)
    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def head_node_instance_type_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if param_value in HEAD_NODE_UNSUPPORTED_INSTANCE_TYPES:
        errors.append(HEAD_NODE_UNSUPPORTED_MESSAGE.format(param_value))
    return errors, warnings


def ec2_vpc_id_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        ec2 = boto3.client("ec2")
        ec2.describe_vpcs(VpcIds=[param_value])

        # Check for DNS support in the VPC
        if (
            not ec2.describe_vpc_attribute(VpcId=param_value, Attribute="enableDnsSupport")
            .get("EnableDnsSupport")
            .get("Value")
        ):
            errors.append("DNS Support is not enabled in the VPC %s" % param_value)
        if (
            not ec2.describe_vpc_attribute(VpcId=param_value, Attribute="enableDnsHostnames")
            .get("EnableDnsHostnames")
            .get("Value")
        ):
            errors.append("DNS Hostnames not enabled in the VPC %s" % param_value)

    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def ec2_subnet_id_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        boto3.client("ec2").describe_subnets(SubnetIds=[param_value])
    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def ec2_ami_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    # Make sure AMI exists
    try:
        image_info = boto3.client("ec2").describe_images(ImageIds=[param_value]).get("Images")[0]
        validate_pcluster_version_based_on_ami_name(image_info.get("Name"))
    except ClientError as e:
        errors.append(
            "Unable to get information for AMI {0}: {1}. Check value of parameter {2}.".format(
                param_value, e.response.get("Error").get("Message"), param_key
            )
        )
    except IndexError:
        errors.append("Unable to find AMI {0}. Check value of parameter {1}.".format(param_value, param_key))

    if not errors:
        # Make sure architecture implied by instance types agrees with that implied by AMI
        ami_architecture = image_info.get("Architecture")
        cluster_section = pcluster_config.get_section("cluster")
        if cluster_section.get_param_value("architecture") != ami_architecture:
            errors.append(
                "AMI {0}'s architecture ({1}) is incompatible with the architecture supported by the instance type "
                "chosen for the head node ({2}). Use either a different AMI or a different instance type.".format(
                    param_value, ami_architecture, cluster_section.get_param_value("architecture")
                )
            )

    return errors, warnings


# FIXME moved
def url_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if urlparse(param_value).scheme == "s3":
        errors_s3, warnings_s3 = s3_uri_validator(param_key, param_value, pcluster_config)
        errors += errors_s3
        warnings += warnings_s3

    else:
        try:
            urllib.request.urlopen(param_value)
        except urllib.error.HTTPError as e:
            warnings.append("{0} {1} {2}".format(param_value, e.code, e.reason))
        except urllib.error.URLError as e:
            warnings.append("{0} {1}".format(param_value, e.reason))
        except ValueError:
            errors.append(
                "The value '{0}' used for the parameter '{1}' is not a valid URL".format(param_value, param_key)
            )

    return errors, warnings


# FIXME moved
def s3_uri_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    try:
        match = re.match(r"s3://(.*?)/(.*)", param_value)
        if not match or len(match.groups()) < 2:
            raise ValueError("S3 url is invalid.")
        bucket, key = match.group(1), match.group(2)
        boto3.client("s3").head_object(Bucket=bucket, Key=key)

    except ClientError:

        # Check that bucket is in s3_read_resource or s3_read_write_resource.
        cluster_section = pcluster_config.get_section("cluster")
        s3_read_resource = cluster_section.get_param_value("s3_read_resource")
        s3_read_write_resource = cluster_section.get_param_value("s3_read_write_resource")

        if s3_read_resource == "*" or s3_read_write_resource == "*":
            pass
        else:
            # Match after arn prefix until end of line, or * or /.
            match_bucket_from_arn = r"(?<=arn:aws:s3:::)([^*/]*)"
            s3_read_bucket = re.search(match_bucket_from_arn, s3_read_resource).group(0) if s3_read_resource else None
            s3_write_bucket = (
                re.search(match_bucket_from_arn, s3_read_write_resource).group(0) if s3_read_write_resource else None
            )

            if bucket in [s3_read_bucket, s3_write_bucket]:
                pass
            else:
                warnings.append(
                    (
                        "The S3 object does not exist or you do not have access to it.\n"
                        "Please make sure the cluster nodes have access to it."
                    )
                )

    return errors, warnings


def s3_bucket_uri_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if urlparse(param_value).scheme == "s3":
        try:
            bucket = get_bucket_name_from_s3_url(param_value)
            boto3.client("s3").head_bucket(Bucket=bucket)
        except ClientError as client_error:
            _process_generic_s3_bucket_error(client_error, param_value, warnings, errors)
    else:
        errors.append(
            "The value '{0}' used for the parameter '{1}' is not a valid S3 URI.".format(param_value, param_key)
        )

    return errors, warnings


def s3_bucket_validator(param_key, param_value, pcluster_config):
    """Validate S3 bucket can be used to store cluster artifacts."""
    errors = []
    warnings = []
    s3_client = boto3.client("s3")
    try:
        s3_client.head_bucket(Bucket=param_value)
        # Check versioning is enabled on the bucket
        response = s3_client.get_bucket_versioning(Bucket=param_value)
        if response.get("Status") != "Enabled":
            errors.append(
                (
                    "The S3 bucket {0} specified cannot be used by cluster "
                    "because versioning setting is: {1}, not 'Enabled'. Please enable bucket versioning."
                ).format(param_value, response.get("Status"))
            )
    except ClientError as client_error:
        _process_generic_s3_bucket_error(client_error, param_value, warnings, errors)
    except ParamValidationError as validation_error:
        errors.append(
            "Error validating parameter '{0}'. Failed with exception: {1}".format(param_key, str(validation_error))
        )

    return errors, warnings


def _process_generic_s3_bucket_error(client_error, bucket_name, warnings, errors):
    if client_error.response.get("Error").get("Code") == "NoSuchBucket":
        errors.append(
            "The S3 bucket '{0}' does not appear to exist: '{1}'".format(
                bucket_name, client_error.response.get("Error").get("Message")
            )
        )
    elif client_error.response.get("Error").get("Code") == "AccessDenied":
        errors.append(
            "You do not have access to the S3 bucket '{0}': '{1}'".format(
                bucket_name, client_error.response.get("Error").get("Message")
            )
        )
    else:
        errors.append(
            "Unexpected error when calling get_bucket_location on S3 bucket '{0}': '{1}'".format(
                bucket_name, client_error.response.get("Error").get("Message")
            )
        )


def shared_dir_validator(param_key, param_value, pcluster_config):
    """Validate that user is not specifying /NONE or NONE as shared_dir for any filesystem."""
    errors = []
    warnings = []

    if re.match("^/?NONE$", param_value):
        errors.append("{0} cannot be used as a shared directory".format(param_value))

    return errors, warnings


def ec2_volume_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        test = boto3.client("ec2").describe_volumes(VolumeIds=[param_value]).get("Volumes")[0]
        if test.get("State") != "available":
            warnings.append("Volume {0} is in state '{1}' not 'available'".format(param_value, test.get("State")))
    except ClientError as e:
        if e.response.get("Error").get("Message").endswith("parameter volumes is invalid. Expected: 'vol-...'."):
            errors.append("Volume {0} does not exist".format(param_value))
        else:
            errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def intel_hpc_os_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    allowed_oses = ["centos7", "centos8"]

    cluster_section = pcluster_config.get_section("cluster")
    if param_value and cluster_section.get_param_value("base_os") not in allowed_oses:
        errors.append(
            "When using 'enable_intel_hpc_platform = {0}' it is required to set the 'base_os' parameter "
            "to one of the following values : {1}".format(param_value, allowed_oses)
        )

    return errors, warnings


def intel_hpc_architecture_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    allowed_architectures = ["x86_64"]

    architecture = pcluster_config.get_section("cluster").get_param_value("architecture")
    if param_value and architecture not in allowed_architectures:
        errors.append(
            "When using enable_intel_hpc_platform = {0} it is required to use head node and compute instance "
            "types and an AMI that support these architectures: {1}".format(param_value, allowed_architectures)
        )

    return errors, warnings


def get_bucket_name_from_s3_url(import_path):
    return import_path.split("/")[2]
