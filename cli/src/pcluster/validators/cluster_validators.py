# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import re

import boto3
from botocore.exceptions import ClientError

from pcluster.constants import CIDR_ALL_IPS
from pcluster.dcv.utils import get_supported_dcv_os
from pcluster.utils import (
    InstanceTypeInfo,
    get_efs_mount_target_id,
    get_supported_architectures_for_instance_type,
    get_supported_os_for_architecture,
    get_supported_os_for_scheduler,
)
from pcluster.validators.common import FailureLevel, Validator

NAME_MAX_LENGTH = 30
NAME_REGEX = r"^[a-z][a-z0-9\-]*$"

EFA_UNSUPPORTED_ARCHITECTURES_OSES = {
    "x86_64": [],
    "arm64": ["centos8"],
}

FSX_SUPPORTED_ARCHITECTURES_OSES = {
    "x86_64": ["centos7", "centos8", "ubuntu1604", "ubuntu1804", "alinux", "alinux2"],
    "arm64": ["ubuntu1804", "alinux2", "centos8"],
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


class SchedulerOsValidator(Validator):
    """
    scheduler - os validator.

    Validate os and scheduler combination.
    """

    def _validate(self, os, scheduler):
        supported_os = get_supported_os_for_scheduler(scheduler)
        if os not in supported_os:
            self._add_failure(
                f"{scheduler} scheduler supports the following Operating Systems: {supported_os}",
                FailureLevel.ERROR,
            )


class ComputeResourceSizeValidator(Validator):
    """
    Slurm compute resource size validator.

    Validate min count and max count combinations.
    """

    def _validate(self, min_count, max_count):
        if max_count < min_count:
            self._add_failure(
                "Max count must be greater than or equal to min count",
                FailureLevel.ERROR,
            )


class SimultaneousMultithreadingArchitectureValidator(Validator):
    """
    Simultaneous Multithreading architecture validator.

    Validate Simultaneous Multithreading and architecture combination.
    """

    def _validate(self, simultaneous_multithreading, architecture: str):
        supported_architectures = ["x86_64"]
        if simultaneous_multithreading and architecture not in supported_architectures:
            self._add_failure(
                "Simultaneous Multithreading is only supported on instance types that support "
                "these architectures: {0}".format(", ".join(supported_architectures)),
                FailureLevel.ERROR,
            )


class EfaOsArchitectureValidator(Validator):
    """OS and architecture combination validator if EFA is enabled."""

    def _validate(self, efa_enabled, os, architecture: str):
        if efa_enabled and os in EFA_UNSUPPORTED_ARCHITECTURES_OSES.get(architecture):
            self._add_failure(
                "EFA currently not supported on {0} for {1} architecture".format(os, architecture),
                FailureLevel.ERROR,
            )


class ArchitectureOsValidator(Validator):
    """
    Validate OS and architecture combination.

    ARM AMIs are only available for a subset of the supported OSes.
    """

    def _validate(self, os, architecture: str):
        allowed_oses = get_supported_os_for_architecture(architecture)
        if os not in allowed_oses:
            self._add_failure(
                "The architecture {0} is only supported for the following operating systems: {1}".format(
                    architecture, allowed_oses
                ),
                FailureLevel.ERROR,
            )


class InstanceArchitectureCompatibilityValidator(Validator):
    """
    Validate instance type and architecture combination.

    Verify that head node and compute instance types imply compatible architectures.
    """

    def _validate(self, instance_type, architecture: str):
        head_node_architecture = architecture
        compute_architectures = get_supported_architectures_for_instance_type(instance_type)
        if head_node_architecture not in compute_architectures:
            self._add_failure(
                "The specified compute instance type ({0}) supports the architectures {1}, none of which are "
                "compatible with the architecture supported by the head node instance type ({2}).".format(
                    instance_type, compute_architectures, head_node_architecture
                ),
                FailureLevel.ERROR,
            )


class NameValidator(Validator):
    """Validate queue name length and format."""

    def _validate(self, name):
        match = re.match(NAME_REGEX, name)
        if not match:
            self._add_failure(
                (
                    f"Invalid name '{name}'. "
                    "Name must begin with a letter and only contain lowercase letters, digits and hyphens."
                ),
                FailureLevel.ERROR,
            )

        if len(name) > NAME_MAX_LENGTH:
            self._add_failure(
                f"Invalid name '{name}'. Name can be at most {NAME_MAX_LENGTH} chars long.",
                FailureLevel.ERROR,
            )

        if re.match("^default$", name):
            self._add_failure(
                f"It is forbidden to use '{name}' as a name.",
                FailureLevel.ERROR,
            )


class DuplicateInstanceTypeValidator(Validator):
    """
    Instance type validator.

    Verify if there are duplicated instance types between compute resources in the same queue.
    """

    def _validate(self, instance_type_list):
        duplicated_instance_types = _find_duplicate_params(instance_type_list)
        if duplicated_instance_types:
            self._add_failure(
                "Instance {0} {1} cannot be specified for multiple Compute Resources in the same Queue".format(
                    "types" if len(duplicated_instance_types) > 1 else "type",
                    ", ".join(instance_type for instance_type in duplicated_instance_types),
                ),
                FailureLevel.ERROR,
            )


# --------------- EFA validators --------------- #


class EfaValidator(Validator):
    """Check if EFA and EFA GDR are supported features in the given instance type."""

    def _validate(self, instance_type, efa_enabled, gdr_support):

        if efa_enabled:
            if not InstanceTypeInfo.init_from_instance_type(instance_type).is_efa_supported():
                self._add_failure(
                    f"Instance type '{instance_type}' does not support EFA.",
                    FailureLevel.WARNING,
                )
        elif gdr_support:
            self._add_failure(
                "The EFA GDR Support can be used only if EFA is enabled.",
                FailureLevel.ERROR,
            )


class EfaPlacementGroupValidator(Validator):
    """Validate placement group if EFA is enabled."""

    def _validate(self, efa_enabled, placement_group_id, placement_group_enabled):
        if efa_enabled and not placement_group_id and not placement_group_enabled:
            self._add_failure(
                "You may see better performance using a Placement Group for the queue.", FailureLevel.WARNING
            )


class EfaSecurityGroupValidator(Validator):
    """Validate Security Group if EFA is enabled."""

    def _validate(self, efa_enabled, security_groups, additional_security_groups):
        if efa_enabled and security_groups:
            # Check security groups associated to the EFA
            efa_sg_found = self._check_in_out_rules(security_groups)
            if additional_security_groups:
                efa_sg_found = efa_sg_found or self._check_in_out_rules(additional_security_groups)

            if not efa_sg_found:
                self._add_failure(
                    "An EFA requires a security group that allows all inbound and outbound traffic "
                    "to and from the security group itself. See "
                    "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start.html#efa-start-security",
                    FailureLevel.ERROR,
                )

    def _check_in_out_rules(self, security_groups):
        efa_sg_found = False
        for security_group in security_groups:
            try:
                sec_group = (
                    boto3.client("ec2").describe_security_groups(GroupIds=[security_group]).get("SecurityGroups")[0]
                )
                allowed_in = False
                allowed_out = False

                # check inbound rules
                for rule in sec_group.get("IpPermissions"):
                    # UserIdGroupPairs is always of length 1, so grabbing 0th object is ok
                    if (
                        rule.get("IpProtocol") == "-1"
                        and rule.get("UserIdGroupPairs")
                        and rule.get("UserIdGroupPairs")[0].get("GroupId") == security_group
                    ):
                        allowed_in = True
                        break

                # check outbound rules
                for rule in sec_group.get("IpPermissionsEgress"):
                    if (
                        rule.get("IpProtocol") == "-1"
                        and rule.get("UserIdGroupPairs")
                        and rule.get("UserIdGroupPairs")[0].get("GroupId") == security_group
                    ):
                        allowed_out = True
                        break

                if allowed_in and allowed_out:
                    efa_sg_found = True
                    break

            except ClientError as e:
                self._add_failure(e.response.get("Error").get("Message"), FailureLevel.WARNING)

        return efa_sg_found


# --------------- Storage validators --------------- #


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


class FsxNetworkingValidator(Validator):
    """
    FSx networking validator.

    Validate file system mount point according to the head node subnet.
    """

    def _validate(self, file_system_id, head_node_subnet_id):
        try:
            ec2 = boto3.client("ec2")

            # Check to see if there is any existing mt on the fs
            file_system = (
                boto3.client("fsx").describe_file_systems(FileSystemIds=[file_system_id]).get("FileSystems")[0]
            )

            vpc_id = ec2.describe_subnets(SubnetIds=[head_node_subnet_id]).get("Subnets")[0].get("VpcId")

            # Check to see if fs is in the same VPC as the stack
            if file_system.get("VpcId") != vpc_id:
                self._add_failure(
                    "Currently only support using FSx file system that is in the same VPC as the stack. "
                    "The file system provided is in {0}".format(file_system.get("VpcId")),
                    FailureLevel.ERROR,
                )

            # If there is an existing mt in the az, need to check the inbound and outbound rules of the security groups
            network_interface_ids = file_system.get("NetworkInterfaceIds")
            if not network_interface_ids:
                self._add_failure(
                    "Unable to validate FSx security groups. The given FSx file system '{0}' doesn't have "
                    "Elastic Network Interfaces attached to it.".format(file_system_id),
                    FailureLevel.ERROR,
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
                    self._add_failure(
                        "The current security group settings on file system '{0}' does not satisfy mounting requirement"
                        ". The file system must be associated to a security group that allows inbound and outbound "
                        "TCP traffic through port 988.".format(file_system_id),
                        FailureLevel.ERROR,
                    )
        except ClientError as e:
            self._add_failure(e.response.get("Error").get("Message"), FailureLevel.ERROR)


class FsxArchitectureOsValidator(Validator):
    """
    FSx networking validator.

    Validate file system mount point according to the head node subnet.
    """

    def _validate(self, architecture: str, os):

        if architecture not in FSX_SUPPORTED_ARCHITECTURES_OSES:
            self._add_failure(
                FSX_MESSAGES["errors"]["unsupported_architecture"].format(
                    supported_architectures=list(FSX_SUPPORTED_ARCHITECTURES_OSES.keys())
                ),
                FailureLevel.ERROR,
            )
        elif os not in FSX_SUPPORTED_ARCHITECTURES_OSES.get(architecture):
            self._add_failure(
                FSX_MESSAGES["errors"]["unsupported_os"].format(
                    architecture=architecture, supported_oses=FSX_SUPPORTED_ARCHITECTURES_OSES.get(architecture)
                ),
                FailureLevel.ERROR,
            )


def _find_duplicate_params(param_list):
    param_set = set()
    duplicated_params = []

    for param in param_list:
        if param in param_set:
            duplicated_params.append(param)
        else:
            param_set.add(param)
    return duplicated_params


class DuplicateMountDirValidator(Validator):
    """
    Mount dir validator.

    Verify if there are duplicated mount dirs between shared storage and ephemeral volumes.
    """

    def _validate(self, mount_dir_list):
        duplicated_mount_dirs = _find_duplicate_params(mount_dir_list)
        if duplicated_mount_dirs:
            self._add_failure(
                "Mount {0} {1} cannot be specified for multiple volumes".format(
                    "directories" if len(duplicated_mount_dirs) > 1 else "directory",
                    ", ".join(mount_dir for mount_dir in duplicated_mount_dirs),
                ),
                FailureLevel.ERROR,
            )


class NumberOfStorageValidator(Validator):
    """
    Number of storage validator.

    Validate the number of storage specified is lower than maximum supported.
    """

    def _validate(self, storage_type: str, max_number: int, storage_count: int):
        if storage_count > max_number:
            self._add_failure(
                "Invalid number of shared storage of {0} type specified. "
                "Currently only supports upto {1}".format(storage_type, max_number),
                FailureLevel.ERROR,
            )


class EfsIdValidator(Validator):  # TODO add tests
    """
    EFS id validator.

    Validate if there are existing mount target in the head node availability zone
    """

    def _validate(self, efs_id, head_node_avail_zone: str):
        try:
            # Get head node availability zone
            head_node_target_id = get_efs_mount_target_id(efs_fs_id=efs_id, avail_zone=head_node_avail_zone)
            # If there is an existing mt in the az, need to check the inbound and outbound rules of the security groups
            if head_node_target_id:
                # Get list of security group IDs of the mount target
                sg_ids = (
                    boto3.client("efs")
                    .describe_mount_target_security_groups(MountTargetId=head_node_target_id)
                    .get("SecurityGroups")
                )
                if not _check_in_out_access(sg_ids, port=2049):
                    self._add_failure(
                        "There is an existing Mount Target {0} in the Availability Zone {1} for EFS {2}, "
                        "but it does not have a security group that allows inbound and outbound rules to support NFS. "
                        "Please modify the Mount Target's security group, to allow traffic on port 2049.".format(
                            head_node_target_id, head_node_avail_zone, efs_id
                        ),
                        FailureLevel.WARNING,
                    )
        except ClientError as e:
            self._add_failure(e.response.get("Error").get("Message"), FailureLevel.ERROR)


# --------------- Third party software validators --------------- #


class DcvValidator(Validator):
    """
    DCV parameters validators.

    Validate instance type, architecture and os when DCV is enabled.
    """

    def _validate(
        self,
        instance_type,
        dcv_enabled,
        allowed_ips,
        port,
        os,
        architecture: str,
    ):
        if dcv_enabled:
            allowed_oses = get_supported_dcv_os(architecture)
            if os not in allowed_oses:
                self._add_failure(
                    "NICE DCV can be used with one of the following operating systems: {0}. "
                    "Please double check the Os configuration parameter".format(allowed_oses),
                    FailureLevel.ERROR,
                )

            if re.search(r"(micro)|(nano)", instance_type):
                self._add_failure(
                    "The packages required for desktop virtualization in the selected instance type '{0}' "
                    "may cause instability of the instance. If you want to use NICE DCV it is recommended "
                    "to use an instance type with at least 1.7 GB of memory.".format(instance_type),
                    FailureLevel.WARNING,
                )

            if allowed_ips == CIDR_ALL_IPS:
                self._add_failure(
                    f"With this configuration you are opening DCV port {port} to the world (0.0.0.0/0). "
                    "It is recommended to restrict access.",
                    FailureLevel.WARNING,
                )


class IntelHpcOsValidator(Validator):
    """Intel HPC OS validator."""

    def _validate(self, os: str):
        allowed_oses = ["centos7", "centos8"]
        if os not in allowed_oses:
            self._add_failure(
                "When enabling intel software, the operating system is required to be set "
                "to one of the following values : {0}".format(allowed_oses),
                FailureLevel.ERROR,
            )


class IntelHpcArchitectureValidator(Validator):
    """Intel HPC architecture validator."""

    def _validate(self, architecture: str):
        allowed_architectures = ["x86_64"]
        if architecture not in allowed_architectures:
            self._add_failure(
                "When enabling intel software, it is required to use head node and compute instance "
                "types and an AMI that support these architectures: {0}".format(allowed_architectures),
                FailureLevel.ERROR,
            )


# --------------- Other validators --------------- #


class TagKeyValidator(Validator):
    """
    Tag key validator.

    Validate the tag key is not a reserved one.
    """

    def _validate(self, key):
        if key == "Version":
            self._add_failure("The tag key 'Version' is a reserved one.", FailureLevel.ERROR)
