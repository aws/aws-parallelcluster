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

from pcluster.utils import (
    ellipsize,
    get_base_additional_iam_policies,
    get_efs_mount_target_id,
    get_file_section_name,
    get_region,
    get_supported_os_for_scheduler,
    paginate_boto3,
    validate_pcluster_version_based_on_ami_name,
)

LOGFILE_LOGGER = logging.getLogger("cli_log_file")

FSX_MESSAGES = {
    "errors": {
        "unsupported_os": "On {architecture} instance types FSX Lustre can be used with one of the following operating "
        "systems: {supported_oses}. Please double check the 'base_os' configuration parameter",
        "unsupported_architecture": "FSX Lustre can be used only with instance types and AMIs that support these "
        "architectures: {supported_architectures}. Please double check the 'master_instance_type', "
        "'compute_instance_type' and/or 'custom_ami' configuration parameters.",
        "unsupported_backup_param": "When restoring an FSx Lustre file system from backup, '{name}' "
        "cannot be specified.",
        "ignored_param_with_fsx_fs_id": "{fsx_param} is ignored when specifying an existing Lustre file system via "
        "fsx_fs_id.",
    }
}

FSX_SUPPORTED_ARCHITECTURES_OSES = {
    "x86_64": ["centos7", "centos8", "ubuntu1604", "ubuntu1804", "alinux", "alinux2"],
    "arm64": ["ubuntu1804", "alinux2", "centos8"],
}

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

# Constants for section labels
LABELS_MAX_LENGTH = 64
LABELS_REGEX = r"^[A-Za-z0-9\-_]+$"


def _get_sts_endpoint():
    """Get regionalized STS endpoint."""
    region = get_region()
    return "https://sts.{0}.{1}".format(region, "amazonaws.com.cn" if region.startswith("cn-") else "amazonaws.com")


def _check_sg_rules_for_port(rule, port_to_check):
    """
    Verify if the security group rule accepts connections on the given port.

    :param rule: The rule to check
    :param port_to_check: The port to check
    :return: True if the rule accepts connection, False otherwise
    """
    from_port = rule.get("FromPort")
    to_port = rule.get("ToPort")
    ip_protocol = rule.get("IpProtocol")

    # if ip_protocol is -1, all ports are allowed
    if ip_protocol == "-1":
        return True
    # tcp == protocol 6,
    # if the ip_protocol is tcp, from_port and to_port must >= 0 and <= 65535
    if (ip_protocol in ["tcp", "6"]) and (from_port <= port_to_check <= to_port):
        return True

    return False


def efs_id_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        # Get head node availability zone
        head_node_avail_zone = pcluster_config.get_head_node_availability_zone()
        head_node_target_id = get_efs_mount_target_id(efs_fs_id=param_value, avail_zone=head_node_avail_zone)
        # If there is an existing mt in the az, need to check the inbound and outbound rules of the security groups
        if head_node_target_id:
            # Get list of security group IDs of the mount target
            sg_ids = (
                boto3.client("efs")
                .describe_mount_target_security_groups(MountTargetId=head_node_target_id)
                .get("SecurityGroups")
            )
            if not _check_in_out_access(sg_ids, port=2049):
                warnings.append(
                    "There is an existing Mount Target {0} in the Availability Zone {1} for EFS {2}, "
                    "but it does not have a security group that allows inbound and outbound rules to support NFS. "
                    "Please modify the Mount Target's security group, to allow traffic on port 2049.".format(
                        head_node_target_id, head_node_avail_zone, param_value
                    )
                )
    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def _check_in_out_access(security_groups_ids, port):
    """
    Verify given list of security groups to check if they allow in and out access on the given port.

    :param security_groups_ids: list of security groups to verify
    :param port: port to verify
    :return true if
    :raise: ClientError if a given security group doesn't exist
    """
    in_out_access = False
    in_access = False
    out_access = False

    for sec_group in boto3.client("ec2").describe_security_groups(GroupIds=security_groups_ids).get("SecurityGroups"):

        # Check all inbound rules
        for rule in sec_group.get("IpPermissions"):
            if _check_sg_rules_for_port(rule, port):
                in_access = True
                break

        # Check all outbound rules
        for rule in sec_group.get("IpPermissionsEgress"):
            if _check_sg_rules_for_port(rule, port):
                out_access = True
                break

        if in_access and out_access:
            in_out_access = True
            break

    return in_out_access


def fsx_architecture_os_validator(section_key, section_label, pcluster_config):
    errors = []
    warnings = []

    cluster_section = pcluster_config.get_section("cluster")
    architecture = cluster_section.get_param_value("architecture")
    base_os = cluster_section.get_param_value("base_os")

    if architecture not in FSX_SUPPORTED_ARCHITECTURES_OSES:
        errors.append(
            FSX_MESSAGES["errors"]["unsupported_architecture"].format(
                supported_architectures=list(FSX_SUPPORTED_ARCHITECTURES_OSES.keys())
            )
        )
    elif base_os not in FSX_SUPPORTED_ARCHITECTURES_OSES.get(architecture):
        errors.append(
            FSX_MESSAGES["errors"]["unsupported_os"].format(
                architecture=architecture, supported_oses=FSX_SUPPORTED_ARCHITECTURES_OSES.get(architecture)
            )
        )

    return errors, warnings


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


def efa_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    cluster_section = pcluster_config.get_section("cluster")

    allowed_instances = _get_efa_enabled_instance_types(errors)
    if pcluster_config.cluster_model.name == "SIT":
        # Specific validations for SIT clusters
        if cluster_section.get_param_value("compute_instance_type") not in allowed_instances:
            errors.append(
                "When using 'enable_efa = {0}' it is required to set the 'compute_instance_type' parameter "
                "to one of the following values : {1}".format(param_value, allowed_instances)
            )
        if cluster_section.get_param_value("placement_group") is None:
            warnings.append("You may see better performance using a cluster placement group.")

    allowed_schedulers = ["sge", "slurm", "torque"]
    if cluster_section.get_param_value("scheduler") not in allowed_schedulers:
        errors.append(
            "When using 'enable_efa = {0}' it is required to set the 'scheduler' parameter "
            "to one of the following values : {1}".format(param_value, allowed_schedulers)
        )

    _validate_efa_sg(pcluster_config, errors)

    return errors, warnings


def efa_gdr_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    cluster_section = pcluster_config.get_section("cluster")
    if param_value and cluster_section.get_param_value("enable_efa") is None:
        errors.append("The parameter '{0}' can be used only in combination with 'enable_efa'".format(param_key))

    return errors, warnings


def _validate_efa_sg(pcluster_config, errors):
    vpc_security_group_id = pcluster_config.get_section("vpc").get_param_value("vpc_security_group_id")
    if vpc_security_group_id:
        try:
            sg = boto3.client("ec2").describe_security_groups(GroupIds=[vpc_security_group_id]).get("SecurityGroups")[0]
            allowed_in = False
            allowed_out = False

            # check inbound rules
            for rule in sg.get("IpPermissions"):
                # UserIdGroupPairs is always of length 1, so grabbing 0th object is ok
                if (
                    rule.get("IpProtocol") == "-1"
                    and rule.get("UserIdGroupPairs")
                    and rule.get("UserIdGroupPairs")[0].get("GroupId") == vpc_security_group_id
                ):
                    allowed_in = True
                    break

            # check outbound rules
            for rule in sg.get("IpPermissionsEgress"):
                if (
                    rule.get("IpProtocol") == "-1"
                    and rule.get("UserIdGroupPairs")
                    and rule.get("UserIdGroupPairs")[0].get("GroupId") == vpc_security_group_id
                ):
                    allowed_out = True
                    break

            if not (allowed_in and allowed_out):
                errors.append(
                    "The VPC Security Group '{0}' set in the vpc_security_group_id parameter "
                    "must allow all traffic in and out from itself. "
                    "See https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start.html#efa-start-security".format(
                        vpc_security_group_id
                    )
                )
        except ClientError as e:
            errors.append(e.response.get("Error").get("Message"))


def ec2_key_pair_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        _describe_ec2_key_pair(param_value)
    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def ec2_iam_policies_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        if param_value:
            for iam_policy in param_value:
                if iam_policy not in get_base_additional_iam_policies():
                    iam = boto3.client("iam")
                    iam.get_policy(PolicyArn=iam_policy.strip())
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


def ec2_security_group_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        boto3.client("ec2").describe_security_groups(GroupIds=[param_value])
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


def ec2_placement_group_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if param_value == "DYNAMIC":
        pass
    else:
        try:
            boto3.client("ec2").describe_placement_groups(GroupNames=[param_value])
        except ClientError as e:
            errors.append(e.response.get("Error").get("Message"))

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


def fsx_lustre_auto_import_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    fsx_section = pcluster_config.get_section("fsx")
    fsx_import_path = fsx_section.get_param_value("import_path")
    bucket = get_bucket_name_from_s3_url(fsx_import_path)

    if param_value is not None and param_value != "NONE":
        try:
            s3_bucket_region = boto3.client("s3").get_bucket_location(Bucket=bucket).get("LocationConstraint")
            # Buckets in Region us-east-1 have a LocationConstraint of null
            if s3_bucket_region is None:
                s3_bucket_region = "us-east-1"
            if s3_bucket_region != pcluster_config.region:
                errors.append("AutoImport is not supported for cross-region buckets.")
        except ClientError as client_error:
            if client_error.response.get("Error").get("Code") == "NoSuchBucket":
                errors.append(
                    "The S3 bucket '{0}' does not appear to exist: '{1}'".format(
                        bucket, client_error.response.get("Error").get("Message")
                    )
                )
            elif client_error.response.get("Error").get("Code") == "AccessDenied":
                errors.append(
                    "You do not have access to the S3 bucket '{0}': '{1}'".format(
                        bucket, client_error.response.get("Error").get("Message")
                    )
                )
            else:
                errors.append(
                    "Unexpected error when calling get_bucket_location on S3 bucket '{0}': '{1}'".format(
                        bucket, client_error.response.get("Error").get("Message")
                    )
                )
    return errors, warnings


def ebs_settings_validator(param_key, param_value, pcluster_config):
    """
    Validate the following cases.

    Number of EBS volume specified is lower than maximum supported
    Parameter shared_dir is specified in every EBS section when using more than 1 volume
    User is not specifying /NONE or NONE as shared_dir in EBS sections
    """
    errors = []
    warnings = []

    list_of_shared_dir = []
    for section_label in param_value.split(","):
        section = pcluster_config.get_section("ebs", section_label.strip())
        list_of_shared_dir.append(section.get_param_value("shared_dir"))

    max_number_of_ebs_volumes = 5
    num_volumes_specified = len(list_of_shared_dir)

    if num_volumes_specified > max_number_of_ebs_volumes:
        errors.append(
            "Invalid number of EBS volumes ({0}) specified. Currently only supports upto {1} EBS volumes".format(
                num_volumes_specified, max_number_of_ebs_volumes
            )
        )

    if num_volumes_specified > 1 and None in list_of_shared_dir:
        errors.append("When using more than 1 EBS volume, shared_dir is required under each EBS section")

    return errors, warnings


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


def efs_validator(section_key, section_label, pcluster_config):
    errors = []
    warnings = []

    section = pcluster_config.get_section(section_key, section_label)
    throughput_mode = section.get_param_value("throughput_mode")
    provisioned_throughput = section.get_param_value("provisioned_throughput")

    if throughput_mode != "provisioned" and provisioned_throughput:
        errors.append("When specifying 'provisioned_throughput', the 'throughput_mode' must be set to 'provisioned'")

    if throughput_mode == "provisioned" and not provisioned_throughput:
        errors.append(
            "When specifying 'throughput_mode' to 'provisioned', the 'provisioned_throughput' option must be specified"
        )

    return errors, warnings


def scheduler_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if param_value == "awsbatch":
        if pcluster_config.region in ["ap-northeast-3"]:
            errors.append("'awsbatch' scheduler is not supported in the '{0}' region".format(pcluster_config.region))

    supported_os = get_supported_os_for_scheduler(param_value)
    if pcluster_config.get_section("cluster").get_param_value("base_os") not in supported_os:
        errors.append("'{0}' scheduler supports the following Operating Systems: {1}".format(param_value, supported_os))

    will_be_deprecated = ["sge", "torque"]
    wiki_url = "https://github.com/aws/aws-parallelcluster/wiki/Deprecation-of-SGE-and-Torque-in-ParallelCluster"
    if param_value in will_be_deprecated:
        warnings.append(
            "The job scheduler you are using ({0}) is scheduled to be deprecated in future releases of "
            "ParallelCluster. More information is available here: {1}".format(param_value, wiki_url)
        )

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


def maintain_initial_size_validator(param_key, param_value, pcluster_config):
    errors = []
    cluster_section = pcluster_config.get_section("cluster")
    scheduler = cluster_section.get_param_value("scheduler")
    initial_queue_size = cluster_section.get_param_value("initial_queue_size")

    if param_value:
        if scheduler == "awsbatch":
            errors.append("maintain_initial_size is not supported when using awsbatch as scheduler")
        elif initial_queue_size == 0:
            errors.append("maintain_initial_size cannot be set to true if initial_queue_size is 0")

    return errors, []


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


def tags_validator(param_key, param_value, pcluster_config):
    errors = []

    for key in param_value.keys():
        if key == "Version":
            errors.append(
                "The key 'Version' used in your 'tags' configuration parameter is a reserved one, please change it."
            )
            break

    return errors, []


def queue_settings_validator(param_key, param_value, pcluster_config):
    errors = []
    cluster_section = pcluster_config.get_section("cluster")
    scheduler = cluster_section.get_param_value("scheduler")

    if scheduler != "slurm":
        errors.append("queue_settings is supported only with slurm scheduler")

    for label in param_value.split(","):
        if re.search("[A-Z]", label) or re.match("^default$", label) or "_" in label:
            errors.append(
                (
                    "Invalid queue name '{0}'. Queue section names can be at most 30 chars long, must begin with"
                    " a letter and only contain lowercase letters, digits and hyphens. It is forbidden to use"
                    " 'default' as a queue section name."
                ).format(label)
            )

    return errors, []


def queue_validator(section_key, section_label, pcluster_config):
    errors = []
    warnings = []
    queue_section = pcluster_config.get_section(section_key, section_label)
    compute_resource_labels = str(queue_section.get_param_value("compute_resource_settings") or "").split(",")

    # Check for replicated parameters in cluster and queue sections
    def check_queue_xor_cluster(param_key):
        """Check that the param is not used in both queue and cluster section."""
        # FIXME: Improve the design of the validation mechanism to allow validators to be linked to a specific
        # validation phase (before, after refresh operations)
        config_parser = pcluster_config.config_parser
        if config_parser:
            # This check is performed only if the configuration is loaded from file.
            queue_param_in_config_file = config_parser.has_option(
                get_file_section_name("queue", section_label), param_key
            )
            cluster_param_in_config_file = pcluster_config.get_section("cluster").get_param_value(param_key) is not None

            if cluster_param_in_config_file and queue_param_in_config_file:
                errors.append("Parameter '{0}' can be used only in 'cluster' or in 'queue' section".format(param_key))

    check_queue_xor_cluster("enable_efa")
    check_queue_xor_cluster("enable_efa_gdr")
    check_queue_xor_cluster("disable_hyperthreading")

    # Check for unsupported features in compute resources
    def check_unsupported_feature(compute_resource, feature_name, param_key):
        """Check if a feature enabled in the parent queue section is supported on a given child compute resource."""
        feature_enabled = queue_section.get_param_value(param_key)
        if feature_enabled and not compute_resource.get_param_value(param_key):
            warnings.append(
                "{0} was enabled on queue '{1}', but instance type '{2}' defined in compute resource settings {3} "
                "does not support {0}.".format(feature_name, queue_section.label, instance_type, compute_resource_label)
            )

    instance_types = []
    for compute_resource_label in compute_resource_labels:
        compute_resource = pcluster_config.get_section("compute_resource", compute_resource_label)
        if compute_resource:
            instance_type = compute_resource.get_param_value("instance_type")
            if instance_type in instance_types:
                errors.append(
                    "Duplicate instance type '{0}' found in queue '{1}'. "
                    "Compute resources in the same queue must use different instance types".format(
                        instance_type, section_label
                    )
                )
            else:
                instance_types.append(instance_type)

            check_unsupported_feature(compute_resource, "EFA", "enable_efa")
            check_unsupported_feature(compute_resource, "EFA GDR", "enable_efa_gdr")

    # Check that efa_gdr is used with enable_efa
    if queue_section.get_param_value("enable_efa_gdr") and not queue_section.get_param_value("enable_efa"):
        errors.append("The parameter 'enable_efa_gdr' can be used only in combination with 'enable_efa'")

    return errors, warnings


def settings_validator(param_key, param_value, pcluster_config):
    errors = []
    if param_value:
        for label in param_value.split(","):
            label = label.strip()
            match = re.match(LABELS_REGEX, label)
            if not match:
                errors.append(
                    "Invalid label '{0}' in param '{1}'. Section labels can only contain alphanumeric characters, "
                    "dashes or underscores.".format(ellipsize(label, 20), param_key)
                )
            else:
                if len(label) > LABELS_MAX_LENGTH:
                    errors.append(
                        "Invalid label '{0}' in param '{1}'. The maximum length allowed for section labels is "
                        "{2} characters".format(ellipsize(label, 20), param_key, LABELS_MAX_LENGTH)
                    )
    return errors, []


def _get_efa_enabled_instance_types(errors):
    instance_types = []

    try:
        for response in paginate_boto3(
            boto3.client("ec2").describe_instance_types,
            Filters=[{"Name": "network-info.efa-supported", "Values": ["true"]}],
        ):
            instance_types.append(response.get("InstanceType"))
    except ClientError as e:
        errors.append(
            "Failed retrieving efa enabled instance types: {0}".format(e.response.get("Error").get("Message"))
        )

    return instance_types


def fsx_lustre_backup_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    try:
        boto3.client("fsx").describe_backups(BackupIds=[param_value]).get("Backups")[0]
    except ClientError as e:
        errors.append(
            "Failed to retrieve backup with Id '{0}': {1}".format(param_value, e.response.get("Error").get("Message"))
        )

    fsx_section = pcluster_config.get_section("fsx")
    unsupported_config_param_names = [
        "deployment_type",
        "per_unit_storage_throughput",
        "storage_capacity",
        "import_path",
        "export_path",
        "imported_file_chunk_size",
        "fsx_kms_key_id",
    ]

    for config_param_name in unsupported_config_param_names:
        if fsx_section.get_param_value(config_param_name) is not None:
            errors.append(FSX_MESSAGES["errors"]["unsupported_backup_param"].format(name=config_param_name))

    return errors, warnings


def fsx_ignored_parameters_validator(section_key, section_label, pcluster_config):
    """Return errors for parameters in the FSx config section that would be ignored."""
    errors = []
    warnings = []

    fsx_section = pcluster_config.get_section(section_key, section_label)

    # If fsx_fs_id is specified, all parameters besides shared_dir are ignored.
    relevant_when_using_existing_fsx = ["fsx_fs_id", "shared_dir"]
    if fsx_section.get_param_value("fsx_fs_id") is not None:
        for fsx_param in fsx_section.params:
            if fsx_param not in relevant_when_using_existing_fsx and FSX_PARAM_WITH_DEFAULT.get(
                fsx_param, None
            ) != fsx_section.get_param_value(fsx_param):
                errors.append(FSX_MESSAGES["errors"]["ignored_param_with_fsx_fs_id"].format(fsx_param=fsx_param))
    return errors, warnings


def _describe_ec2_key_pair(key_pair_name):
    """Return information about the provided ec2 key pair."""
    return boto3.client("ec2").describe_key_pairs(KeyNames=[key_pair_name])


def get_bucket_name_from_s3_url(import_path):
    return import_path.split("/")[2]


def duplicate_shared_dir_validator(section_key, section_label, pcluster_config):
    errors = []
    warnings = []
    config_parser = pcluster_config.config_parser
    section = pcluster_config.get_section(section_key, section_label)
    if config_parser:
        shared_dir_in_cluster = config_parser.has_option(get_file_section_name("cluster", section_label), "shared_dir")
        ebs_settings_in_cluster = config_parser.has_option(
            get_file_section_name("cluster", section_label), "ebs_settings"
        )
        if shared_dir_in_cluster and ebs_settings_in_cluster:
            list_of_ebs_sections = []
            for ebs_section_label in section.get_param_value("ebs_settings").split(","):
                ebs_section = pcluster_config.get_section("ebs", ebs_section_label.strip())
                list_of_ebs_sections.append(ebs_section)
            # if there is only one EBS section configured, check whether "shared_dir" is in the EBS section
            if len(list_of_ebs_sections) == 1 and list_of_ebs_sections[0].get_param_value("shared_dir"):
                errors.append("'shared_dir' can not be specified both in cluster section and EBS section")
            # if there are multiple EBS sections configured, provide an error message
            elif len(list_of_ebs_sections) > 1:
                errors.append("'shared_dir' can not be specified in cluster section when using multiple EBS volumes")

    return errors, warnings
