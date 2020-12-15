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

from pcluster.constants import CIDR_ALL_IPS, FSX_HDD_THROUGHPUT, FSX_SSD_THROUGHPUT
from pcluster.dcv.utils import get_supported_dcv_os
from pcluster.utils import (
    InstanceTypeInfo,
    ellipsize,
    get_base_additional_iam_policies,
    get_ebs_snapshot_info,
    get_efs_mount_target_id,
    get_file_section_name,
    get_partition,
    get_region,
    get_supported_architectures_for_instance_type,
    get_supported_compute_instance_types,
    get_supported_instance_types,
    get_supported_os_for_architecture,
    get_supported_os_for_scheduler,
    is_instance_type_format,
    paginate_boto3,
    validate_pcluster_version_based_on_ami_name,
)

LOGFILE_LOGGER = logging.getLogger("cli_log_file")

DCV_MESSAGES = {
    "warnings": {
        "access_from_world": "With this configuration you are opening dcv port ({port}) to the world (0.0.0.0/0). "
        "It is recommended to use dcv access_from config option to restrict access."
    }
}

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

EFA_UNSUPPORTED_ARCHITECTURES_OSES = {
    "x86_64": [],
    "arm64": ["centos8"],
}

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


def fsx_validator(section_key, section_label, pcluster_config):
    errors = []
    warnings = []

    fsx_section = pcluster_config.get_section(section_key, section_label)
    fsx_import_path = fsx_section.get_param_value("import_path")
    fsx_imported_file_chunk_size = fsx_section.get_param_value("imported_file_chunk_size")
    fsx_export_path = fsx_section.get_param_value("export_path")
    fsx_auto_import_policy = fsx_section.get_param_value("auto_import_policy")
    fsx_deployment_type = fsx_section.get_param_value("deployment_type")
    fsx_kms_key_id = fsx_section.get_param_value("fsx_kms_key_id")
    fsx_per_unit_storage_throughput = fsx_section.get_param_value("per_unit_storage_throughput")
    fsx_daily_automatic_backup_start_time = fsx_section.get_param_value("daily_automatic_backup_start_time")
    fsx_automatic_backup_retention_days = fsx_section.get_param_value("automatic_backup_retention_days")
    fsx_copy_tags_to_backups = fsx_section.get_param_value("copy_tags_to_backups")
    fsx_storage_type = fsx_section.get_param_value("storage_type")
    fsx_drive_cache_type = fsx_section.get_param_value("drive_cache_type")

    validate_s3_options(errors, fsx_import_path, fsx_imported_file_chunk_size, fsx_export_path, fsx_auto_import_policy)
    validate_persistent_options(errors, fsx_deployment_type, fsx_kms_key_id, fsx_per_unit_storage_throughput)
    validate_backup_options(
        errors,
        fsx_automatic_backup_retention_days,
        fsx_daily_automatic_backup_start_time,
        fsx_copy_tags_to_backups,
        fsx_deployment_type,
        fsx_imported_file_chunk_size,
        fsx_import_path,
        fsx_export_path,
        fsx_auto_import_policy,
    ),
    validate_storage_type_options(
        errors, fsx_storage_type, fsx_deployment_type, fsx_per_unit_storage_throughput, fsx_drive_cache_type
    )

    return errors, warnings


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


def fsx_id_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    try:
        ec2 = boto3.client("ec2")

        # Check to see if there is any existing mt on the fs
        file_system = boto3.client("fsx").describe_file_systems(FileSystemIds=[param_value]).get("FileSystems")[0]

        subnet_id = pcluster_config.get_section("vpc").get_param_value("master_subnet_id")
        vpc_id = ec2.describe_subnets(SubnetIds=[subnet_id]).get("Subnets")[0].get("VpcId")

        # Check to see if fs is in the same VPC as the stack
        if file_system.get("VpcId") != vpc_id:
            errors.append(
                "Currently only support using FSx file system that is in the same VPC as the stack. "
                "The file system provided is in {0}".format(file_system.get("VpcId"))
            )

        # If there is an existing mt in the az, need to check the inbound and outbound rules of the security groups
        network_interface_ids = file_system.get("NetworkInterfaceIds")
        if not network_interface_ids:
            errors.append(
                "Unable to validate FSx security groups. The given FSx file system '{0}' doesn't have "
                "Elastic Network Interfaces attached to it.".format(param_value)
            )
        else:
            network_interface_responses = ec2.describe_network_interfaces(
                NetworkInterfaceIds=network_interface_ids
            ).get("NetworkInterfaces")

            fs_access = False
            network_interfaces = [ni for ni in network_interface_responses if ni.get("VpcId") == vpc_id]
            for network_interface in network_interfaces:
                # Get list of security group IDs
                sg_ids = [sg.get("GroupId") for sg in network_interface.get("Groups")]
                if _check_in_out_access(sg_ids, port=988):
                    fs_access = True
                    break
            if not fs_access:
                errors.append(
                    "The current security group settings on file system '{0}' does not satisfy mounting requirement. "
                    "The file system must be associated to a security group that allows inbound and outbound "
                    "TCP traffic through port 988.".format(param_value)
                )
    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def fsx_storage_capacity_validator(section_key, section_label, pcluster_config):
    errors = []
    warnings = []

    fsx_section = pcluster_config.get_section(section_key, section_label)
    storage_capacity = fsx_section.get_param_value("storage_capacity")
    deployment_type = fsx_section.get_param_value("deployment_type")
    storage_type = fsx_section.get_param_value("storage_type")
    per_unit_storage_throughput = fsx_section.get_param_value("per_unit_storage_throughput")
    if fsx_section.get_param_value("fsx_fs_id") or fsx_section.get_param_value("fsx_backup_id"):
        # if fsx_fs_id is provided, don't validate storage_capacity
        # if fsx_backup_id is provided, validation for storage_capacity will be done in fsx_lustre_backup_validator.
        return errors, warnings
    elif not storage_capacity:
        # if fsx_fs_id is not provided, storage_capacity must be provided
        errors.append("When specifying 'fsx' section, the 'storage_capacity' option must be specified")
    elif deployment_type == "SCRATCH_1":
        if not (storage_capacity == 1200 or storage_capacity == 2400 or storage_capacity % 3600 == 0):
            errors.append("Capacity for FSx SCRATCH_1 filesystem is 1,200 GB, 2,400 GB or increments of 3,600 GB")
    elif deployment_type == "PERSISTENT_1" and storage_type == "HDD":
        if per_unit_storage_throughput == 12 and not (storage_capacity % 6000 == 0):
            errors.append("Capacity for FSx PERSISTENT HDD 12 MB/s/TiB file systems is increments of 6,000 GiB")
        elif per_unit_storage_throughput == 40 and not (storage_capacity % 1800 == 0):
            errors.append("Capacity for FSx PERSISTENT HDD 40 MB/s/TiB file systems is increments of 1,800 GiB")
    elif deployment_type in ["SCRATCH_2", "PERSISTENT_1"]:
        if not (storage_capacity == 1200 or storage_capacity % 2400 == 0):
            errors.append(
                "Capacity for FSx SCRATCH_2 and PERSISTENT_1 filesystems is 1,200 GB or increments of 2,400 GB"
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


def extra_json_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if param_value and param_value.get("cluster") and param_value.get("cluster").get("cfn_scheduler_slots"):
        warnings.append(
            "It is highly recommended to use the disable_hyperthreading parameter in order to control the "
            "hyper-threading configuration in the cluster rather than using cfn_scheduler_slots in extra_json"
        )

    return errors, warnings


def dcv_enabled_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    cluster_section = pcluster_config.get_section("cluster")
    if param_value == "master":

        architecture = cluster_section.get_param_value("architecture")
        allowed_oses = get_supported_dcv_os(architecture)
        if cluster_section.get_param_value("base_os") not in allowed_oses:
            errors.append(
                "NICE DCV can be used with one of the following operating systems: {0}. "
                "Please double check the 'base_os' configuration parameter".format(allowed_oses)
            )

        head_node_instance_type = cluster_section.get_param_value("master_instance_type")
        if re.search(r"(micro)|(nano)", head_node_instance_type):
            warnings.append(
                "The packages required for desktop virtualization in the selected instance type '{0}' "
                "may cause instability of the head node instance. If you want to use NICE DCV it is recommended "
                "to use an instance type with at least 1.7 GB of memory.".format(head_node_instance_type)
            )

        if pcluster_config.get_section("dcv").get_param_value("access_from") == CIDR_ALL_IPS:
            LOGFILE_LOGGER.warning(
                DCV_MESSAGES["warnings"]["access_from_world"].format(
                    port=pcluster_config.get_section("dcv").get_param_value("port")
                )
            )

    return errors, warnings


def fsx_imported_file_chunk_size_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if not 1 <= int(param_value) <= 512000:
        errors.append("'{0}' has a minimum size of 1 MiB, and max size of 512,000 MiB".format(param_key))

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


# FIXME moved
def ec2_instance_type_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if param_value not in get_supported_instance_types():
        errors.append(
            "The instance type '{0}' used for the '{1}' parameter is not supported by AWS ParallelCluster.".format(
                param_value, param_key
            )
        )
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


def cluster_validator(section_key, section_label, pcluster_config):
    errors = []
    warnings = []

    section = pcluster_config.get_section(section_key, section_label)
    if section.get_param_value("scheduler") == "awsbatch":
        min_size = section.get_param_value("min_vcpus")
        desired_size = section.get_param_value("desired_vcpus")
        max_size = section.get_param_value("max_vcpus")

        if desired_size < min_size:
            errors.append("desired_vcpus must be greater than or equal to min_vcpus")

        if desired_size > max_size:
            errors.append("desired_vcpus must be fewer than or equal to max_vcpus")

        if max_size < min_size:
            errors.append("max_vcpus must be greater than or equal to min_vcpus")
    else:
        min_size = (
            section.get_param_value("initial_queue_size") if section.get_param_value("maintain_initial_size") else 0
        )
        desired_size = section.get_param_value("initial_queue_size")
        max_size = section.get_param_value("max_queue_size")

        if desired_size > max_size:
            errors.append("initial_queue_size must be fewer than or equal to max_queue_size")

        if max_size < min_size:
            errors.append("max_queue_size must be greater than or equal to initial_queue_size")

    return errors, warnings


def instances_architecture_compatibility_validator(param_key, param_value, pcluster_config):
    """Verify that head node and compute instance types imply compatible architectures."""
    errors = []
    warnings = []

    head_node_architecture = pcluster_config.get_section("cluster").get_param_value("architecture")
    # When awsbatch is used as the scheduler, compute_instance_type can contain a CSV list.
    compute_instance_types = param_value.split(",")
    for compute_instance_type in compute_instance_types:
        # When awsbatch is used as the scheduler instance families can be used.
        # Don't attempt to validate architectures for instance families, as it would require
        # guessing a valid instance type from within the family.
        if not is_instance_type_format(compute_instance_type) and compute_instance_type != "optimal":
            LOGFILE_LOGGER.debug(
                "Not validating architecture compatibility for compute_instance_type {0} because it does not have the "
                "expected format".format(compute_instance_type)
            )
            continue
        compute_architectures = get_supported_architectures_for_instance_type(compute_instance_type)
        if head_node_architecture not in compute_architectures:
            errors.append(
                "The specified compute_instance_type ({0}) supports the architectures {1}, none of which are "
                "compatible with the architecture supported by the master_instance_type ({2}).".format(
                    compute_instance_type, compute_architectures, head_node_architecture
                )
            )

    return errors, warnings


def compute_instance_type_validator(param_key, param_value, pcluster_config):
    """Validate compute instance type, calling ec2_instance_type_validator if the scheduler is not awsbatch."""
    errors = []
    warnings = []

    cluster_config = pcluster_config.get_section("cluster")
    scheduler = cluster_config.get_param_value("scheduler")
    if scheduler == "awsbatch":
        supported_instances = get_supported_compute_instance_types(scheduler)
        if supported_instances:
            for instance in param_value.split(","):
                if not instance.strip() in supported_instances:
                    errors.append(
                        "compute_instance_type '{0}' is not supported by awsbatch in region '{1}'".format(
                            instance, pcluster_config.region
                        )
                    )
        else:
            warnings.append(
                "Unable to get instance types supported by awsbatch. Skipping compute_instance_type validation"
            )

        if "," not in param_value and "." in param_value:
            # if the type is not a list, and contains dot (nor optimal, nor a family)
            # validate instance type against max_vcpus limit
            vcpus = InstanceTypeInfo.init_from_instance_type(param_value).vcpus_count()
            if vcpus <= 0:
                warnings.append(
                    "Unable to get the number of vcpus for the compute_instance_type '{0}'. "
                    "Skipping instance type against max_vcpus validation".format(param_value)
                )
            else:
                if cluster_config.get_param_value("max_vcpus") < vcpus:
                    errors.append(
                        "max_vcpus must be greater than or equal to {0}, that is the number of vcpus "
                        "available for the {1} that you selected as compute_instance_type".format(vcpus, param_value)
                    )
    else:
        errors, warnings = ec2_instance_type_validator(param_key, param_value, pcluster_config)

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


def architecture_os_validator(param_key, param_value, pcluster_config):
    """ARM AMIs are only available for  a subset of the supported OSes."""
    errors = []
    warnings = []

    architecture = pcluster_config.get_section("cluster").get_param_value("architecture")
    allowed_oses = get_supported_os_for_architecture(architecture)
    if param_value not in allowed_oses:
        errors.append(
            "The architecture {0} is only supported for the following operating systems: {1}".format(
                architecture, allowed_oses
            )
        )

    return errors, warnings


def base_os_validator(param_key, param_value, pcluster_config):
    warnings = []

    eol_2020 = ["alinux"]
    if param_value in eol_2020:
        warnings.append(
            "The operating system you are using ({0}) will reach end-of-life in late 2020. It will be deprecated in "
            "future releases of ParallelCluster".format(param_value)
        )

    return [], warnings


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


def compute_resource_validator(section_key, section_label, pcluster_config):
    errors = []
    section = pcluster_config.get_section(section_key, section_label)

    min_count = section.get_param_value("min_count")
    max_count = section.get_param_value("max_count")
    initial_count = section.get_param_value("initial_count")

    if min_count < 0:
        errors.append("Parameter 'min_count' must be 0 or greater than 0")

    if max_count < 1:
        errors.append("Parameter 'max_count' must be 1 or greater than 1")

    if section.get_param_value("max_count") < min_count:
        errors.append("Parameter 'max_count' must be greater than or equal to min_count")

    if initial_count < min_count:
        errors.append("Parameter 'initial_count' must be greater than or equal to 'min_count'")

    if initial_count > max_count:
        errors.append("Parameter 'initial_count' must be lower than or equal to 'max_count'")

    if section.get_param_value("spot_price") < 0:
        errors.append("Parameter 'spot_price' must be 0 or greater than 0")

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


def ebs_volume_type_size_validator(section_key, section_label, pcluster_config):
    """
    Validate that the EBS volume size matches the chosen volume type.

    The default value of volume_size for EBS volumes is 20 GiB.
    The volume size of standard ranges from 1 GiB - 1 TiB(1024 GiB)
    The volume size of gp2 and gp3 ranges from 1 GiB - 16 TiB(16384 GiB)
    The volume size of io1 and io2 ranges from 4 GiB - 16 TiB(16384 GiB)
    The volume sizes of st1 and sc1 range from 500 GiB - 16 TiB(16384 GiB)
    """
    errors = []
    warnings = []

    section = pcluster_config.get_section(section_key, section_label)
    volume_size = section.get_param_value("volume_size")
    volume_type = section.get_param_value("volume_type")

    if volume_type in EBS_VOLUME_TYPE_TO_VOLUME_SIZE_BOUNDS:
        min_size, max_size = EBS_VOLUME_TYPE_TO_VOLUME_SIZE_BOUNDS.get(volume_type)
        if volume_size > max_size:
            errors.append("The size of {0} volumes can not exceed {1} GiB".format(volume_type, max_size))
        elif volume_size < min_size:
            errors.append("The size of {0} volumes must be at least {1} GiB".format(volume_type, min_size))

    return errors, warnings


def ebs_volume_iops_validator(section_key, section_label, pcluster_config):
    errors = []
    warnings = []

    section = pcluster_config.get_section(section_key, section_label)
    volume_size = section.get_param_value("volume_size")
    volume_type = section.get_param_value("volume_type")
    volume_type_to_iops_ratio = {"io1": 50, "io2": 1000, "gp3": 500}
    volume_iops = section.get_param_value("volume_iops")

    if volume_type in EBS_VOLUME_IOPS_BOUNDS:
        min_iops, max_iops = EBS_VOLUME_IOPS_BOUNDS.get(volume_type)
        if volume_iops and (volume_iops < min_iops or volume_iops > max_iops):
            errors.append(
                "IOPS rate must be between {min_iops} and {max_iops} when provisioning {volume_type} volumes.".format(
                    min_iops=min_iops, max_iops=max_iops, volume_type=volume_type
                )
            )
        if volume_iops and volume_iops > volume_size * volume_type_to_iops_ratio[volume_type]:
            errors.append(
                "IOPS to volume size ratio of {0} is too high; maximum is {1}.".format(
                    float(volume_iops) / float(volume_size), volume_type_to_iops_ratio[volume_type]
                )
            )

    return errors, warnings


def get_bucket_name_from_s3_url(import_path):
    return import_path.split("/")[2]


def validate_s3_options(errors, fsx_import_path, fsx_imported_file_chunk_size, fsx_export_path, fsx_auto_import_policy):
    if fsx_imported_file_chunk_size and not fsx_import_path:
        errors.append("When specifying 'imported_file_chunk_size', the 'import_path' option must be specified")

    if fsx_export_path and not fsx_import_path:
        errors.append("When specifying 'export_path', the 'import_path' option must be specified")

    if fsx_auto_import_policy and not fsx_import_path:
        errors.append("When specifying 'auto_import_policy', the 'import_path' option must be specified")


def validate_persistent_options(errors, fsx_deployment_type, fsx_kms_key_id, fsx_per_unit_storage_throughput):
    if fsx_deployment_type == "PERSISTENT_1":
        if not fsx_per_unit_storage_throughput:
            errors.append("'per_unit_storage_throughput' must be specified when 'deployment_type = PERSISTENT_1'")
    else:
        if fsx_kms_key_id:
            errors.append("'fsx_kms_key_id' can only be used when 'deployment_type = PERSISTENT_1'")
        if fsx_per_unit_storage_throughput:
            errors.append("'per_unit_storage_throughput' can only be used when 'deployment_type = PERSISTENT_1'")


def validate_backup_options(
    errors,
    fsx_automatic_backup_retention_days,
    fsx_daily_automatic_backup_start_time,
    fsx_copy_tags_to_backups,
    fsx_deployment_type,
    fsx_imported_file_chunk_size,
    fsx_import_path,
    fsx_export_path,
    fsx_auto_import_policy,
):
    if not fsx_automatic_backup_retention_days and fsx_daily_automatic_backup_start_time:
        errors.append(
            "When specifying 'daily_automatic_backup_start_time', "
            "the 'automatic_backup_retention_days' option must be specified"
        )
    if not fsx_automatic_backup_retention_days and fsx_copy_tags_to_backups is not None:
        errors.append(
            "When specifying 'copy_tags_to_backups', the 'automatic_backup_retention_days' option must be specified"
        )
    if fsx_deployment_type != "PERSISTENT_1" and fsx_automatic_backup_retention_days:
        errors.append("FSx automatic backup features can be used only with 'PERSISTENT_1' file systems")
    if (
        fsx_imported_file_chunk_size or fsx_import_path or fsx_export_path or fsx_auto_import_policy
    ) and fsx_automatic_backup_retention_days:
        errors.append("Backups cannot be created on S3-linked file systems")


def ebs_volume_size_snapshot_validator(section_key, section_label, pcluster_config):
    """
    Validate the following cases.

    The EBS snapshot is in "completed" state if it is specified
    If users specify the volume size, the volume must be not smaller than the volume size of the EBS snapshot
    """
    errors = []
    warnings = []

    section = pcluster_config.get_section(section_key, section_label)
    if section.get_param_value("ebs_snapshot_id"):
        try:
            ebs_snapshot_id = section.get_param_value("ebs_snapshot_id")
            snapshot_response_dict = get_ebs_snapshot_info(ebs_snapshot_id, raise_exceptions=True)
            # validate that the input volume size is larger than the volume size of the EBS snapshot
            snapshot_volume_size = snapshot_response_dict.get("VolumeSize")
            volume_size = section.get_param_value("volume_size")
            if snapshot_volume_size is None:
                errors.append(
                    "Unable to get volume size for snapshot {snapshot_id}".format(snapshot_id=ebs_snapshot_id)
                )
            elif volume_size < snapshot_volume_size:
                errors.append(
                    "The EBS volume size of the section '{section_label}' must not be smaller than "
                    "{snapshot_volume_size}, because it is the size of the provided snapshot {ebs_snapshot_id}".format(
                        section_label=section_label,
                        snapshot_volume_size=snapshot_volume_size,
                        ebs_snapshot_id=ebs_snapshot_id,
                    )
                )
            elif volume_size > snapshot_volume_size:
                warnings.append(
                    "The specified volume size is larger than snapshot size. In order to use the full capacity of the "
                    "volume, you'll need to manually resize the partition "
                    "according to this doc: "
                    "https://{partition_url}/AWSEC2/latest/UserGuide/recognize-expanded-volume-linux.html".format(
                        partition_url="docs.amazonaws.cn" if get_partition() == "aws-cn" else "docs.aws.amazon.com"
                    )
                )

                # validate that the state of ebs snapshot
            if snapshot_response_dict.get("State") != "completed":
                warnings.append(
                    "Snapshot {0} is in state '{1}' not 'completed'".format(
                        ebs_snapshot_id, snapshot_response_dict.get("State")
                    )
                )
        except Exception as exception:
            if isinstance(exception, ClientError) and exception.response.get("Error").get("Code") in [
                "InvalidSnapshot.NotFound",
                "InvalidSnapshot.Malformed",
            ]:
                errors.append(
                    "The snapshot {0} does not appear to exist: {1}".format(
                        ebs_snapshot_id, exception.response.get("Error").get("Message")
                    )
                )
            else:
                errors.append(
                    "Issue getting info for snapshot {0}: {1}".format(
                        ebs_snapshot_id,
                        exception.response.get("Error").get("Message")
                        if isinstance(exception, ClientError)
                        else exception,
                    )
                )
    return errors, warnings


def validate_storage_type_options(
    errors, fsx_storage_type, fsx_deployment_type, fsx_per_unit_storage_throughput, fsx_drive_cache_type
):
    if fsx_storage_type == "HDD":
        if fsx_deployment_type != "PERSISTENT_1":
            errors.append("For HDD filesystems, 'deployment_type' must be 'PERSISTENT_1'")
        if fsx_per_unit_storage_throughput not in FSX_HDD_THROUGHPUT:
            errors.append(
                "For HDD filesystems, 'per_unit_storage_throughput' can only have the following values: {0}".format(
                    FSX_HDD_THROUGHPUT
                )
            )
    else:  # SSD or None
        if fsx_drive_cache_type != "NONE":
            errors.append("'drive_cache_type' features can be used only with HDD filesystems")
        if fsx_per_unit_storage_throughput and fsx_per_unit_storage_throughput not in FSX_SSD_THROUGHPUT:
            errors.append(
                "For SSD filesystems, 'per_unit_storage_throughput' can only have the following values: {0}".format(
                    FSX_SSD_THROUGHPUT
                )
            )


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


def efa_os_arch_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    cluster_section = pcluster_config.get_section("cluster")
    architecture = cluster_section.get_param_value("architecture")
    base_os = cluster_section.get_param_value("base_os")

    if base_os in EFA_UNSUPPORTED_ARCHITECTURES_OSES.get(architecture):
        errors.append("EFA currently not supported on {0} for {1} architecture".format(base_os, architecture))

    return errors, warnings


def ebs_volume_throughput_validator(section_key, section_label, pcluster_config):
    errors = []
    warnings = []

    section = pcluster_config.get_section(section_key, section_label)
    volume_type = section.get_param_value("volume_type")
    volume_iops = section.get_param_value("volume_iops")
    volume_throughput = section.get_param_value("volume_throughput")
    volume_throughput_to_iops_ratio = 0.25

    if volume_type == "gp3":
        min_throughput, max_throughput = 125, 1000
        if volume_throughput < min_throughput or volume_throughput > max_throughput:
            errors.append(
                "Throughput must be between {min_throughput} MB/s and {max_throughput} MB/s when provisioning "
                "{volume_type} volumes.".format(
                    min_throughput=min_throughput, max_throughput=max_throughput, volume_type=volume_type
                )
            )
        if volume_throughput and volume_throughput > volume_iops * volume_throughput_to_iops_ratio:
            errors.append(
                "Throughput to IOPS ratio of {0} is too high; maximum is 0.25.".format(
                    float(volume_throughput) / float(volume_iops)
                )
            )

    return errors, warnings
