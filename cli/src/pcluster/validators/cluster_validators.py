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
from abc import ABC
from enum import Enum

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.cli.commands.dcv_util import get_supported_dcv_os
from pcluster.constants import (
    CIDR_ALL_IPS,
    PCLUSTER_IMAGE_BUILD_STATUS_TAG,
    PCLUSTER_NAME_MAX_LENGTH,
    PCLUSTER_NAME_REGEX,
    PCLUSTER_TAG_VALUE_REGEX,
    PCLUSTER_VERSION_TAG,
    SCHEDULERS_SUPPORTING_IMDS_SECURED,
    SUPPORTED_OSES,
    SUPPORTED_REGIONS,
)
from pcluster.utils import get_installed_version, get_supported_os_for_architecture, get_supported_os_for_scheduler
from pcluster.validators.common import FailureLevel, Validator

# pylint: disable=C0302
NAME_MAX_LENGTH = 25
SHARED_STORAGE_NAME_MAX_LENGTH = 30
NAME_REGEX = r"^[a-z][a-z0-9\-]*$"

EFA_UNSUPPORTED_ARCHITECTURES_OSES = {"x86_64": [], "arm64": ["centos7"]}

FSX_SUPPORTED_ARCHITECTURES_OSES = {
    "x86_64": SUPPORTED_OSES,
    "arm64": ["ubuntu1804", "ubuntu2004", "alinux2", "centos7"],
}

FSX_MESSAGES = {
    "errors": {
        "unsupported_os": "On {architecture} instance types, FSx Lustre can be used with one of the following operating"
        " systems: {supported_oses}. Please double check the os configuration.",
        "unsupported_architecture": "FSx Lustre can be used only with instance types and AMIs that support these "
        "architectures: {supported_architectures}. Please double check the head node instance type, "
        "compute instance type and/or custom AMI configurations.",
        "unsupported_backup_param": "When restoring an FSx Lustre file system from backup, '{name}' "
        "cannot be specified.",
        "ignored_param_with_fsx_fs_id": "{fsx_param} is ignored when an existing Lustre file system is specified.",
    }
}

HOST_NAME_MAX_LENGTH = 64
# Max fqdn size is 255 characters, the first 64 are used for the hostname (e.g. queuename-st|dy-computeresourcename-N),
# then we need to add an extra ., so we have 190 characters to be used for the clustername + domain-name.
CLUSTER_NAME_AND_CUSTOM_DOMAIN_NAME_MAX_LENGTH = 255 - HOST_NAME_MAX_LENGTH - 1


class ClusterNameValidator(Validator):
    """Cluster name validator."""

    def _validate(self, name):
        if not re.match(PCLUSTER_NAME_REGEX % (PCLUSTER_NAME_MAX_LENGTH - 1), name):
            self._add_failure(
                (
                    "Error: The cluster name can contain only alphanumeric characters (case-sensitive) and hyphens. "
                    "It must start with an alphabetic character and can't be longer "
                    f"than {PCLUSTER_NAME_MAX_LENGTH} characters."
                ),
                FailureLevel.ERROR,
            )


class RegionValidator(Validator):
    """Region validator."""

    def _validate(self, region):
        if region not in SUPPORTED_REGIONS:
            self._add_failure(
                f"Region '{region}' is not yet officially supported by ParallelCluster", FailureLevel.ERROR
            )


class SchedulerOsValidator(Validator):
    """
    scheduler - os validator.

    Validate os and scheduler combination.
    """

    def _validate(self, os, scheduler):
        supported_os = get_supported_os_for_scheduler(scheduler)
        if os not in supported_os:
            self._add_failure(
                f"{scheduler} scheduler supports the following operating systems: {supported_os}.", FailureLevel.ERROR
            )


class CustomAmiTagValidator(Validator):
    """Custom AMI tag validator to check if the AMI was created by pcluster to avoid runtime baking."""

    def _validate(self, custom_ami: str):
        tags = AWSApi.instance().ec2.describe_image(custom_ami).tags
        tags_dict = {}
        if tags:  # tags can be None if there is no tag
            for tag in tags:
                tags_dict[tag["Key"]] = tag["Value"]
        current_version = get_installed_version()
        if PCLUSTER_VERSION_TAG not in tags_dict:
            self._add_failure(
                (
                    "The custom AMI may not have been created by pcluster. "
                    "You can ignore this warning if the AMI is shared or copied from another pcluster AMI. "
                    "If the AMI is indeed not created by pcluster, cluster creation will fail. "
                    "If the cluster creation fails, please go to "
                    "https://docs.aws.amazon.com/parallelcluster/latest/ug/troubleshooting.html"
                    "#troubleshooting-stack-creation-failures for troubleshooting."
                ),
                FailureLevel.WARNING,
            )
        elif tags_dict[PCLUSTER_VERSION_TAG] != current_version:
            self._add_failure(
                (
                    f"The custom AMI was created with pcluster {tags_dict[PCLUSTER_VERSION_TAG]}, "
                    f"but is trying to be used with pcluster {current_version}. "
                    f"Please either use an AMI created with {current_version} or"
                    f" change your ParallelCluster to {tags_dict[PCLUSTER_VERSION_TAG]}"
                ),
                FailureLevel.ERROR,
            )
        elif PCLUSTER_IMAGE_BUILD_STATUS_TAG not in tags_dict:
            self._add_failure(
                (
                    "The custom AMI did not pass the tests in image builder. "
                    "Cluster created from this AMI may have unexpected behaviors."
                ),
                FailureLevel.ERROR,
            )


class ComputeResourceSizeValidator(Validator):
    """
    Slurm compute resource size validator.

    Validate min count and max count combinations.
    """

    def _validate(self, min_count, max_count):
        if max_count < min_count:
            self._add_failure("Max count must be greater than or equal to min count.", FailureLevel.ERROR)


class DisableSimultaneousMultithreadingArchitectureValidator(Validator):
    """
    Simultaneous Multithreading architecture validator.

    Validate Simultaneous Multithreading and architecture combination.
    """

    def _validate(self, disable_simultaneous_multithreading, architecture: str):
        supported_architectures = ["x86_64"]
        if disable_simultaneous_multithreading and architecture not in supported_architectures:
            self._add_failure(
                "Disabling simultaneous multithreading is only supported on instance types that support "
                "these architectures: {0}.".format(", ".join(supported_architectures)),
                FailureLevel.ERROR,
            )


class EfaOsArchitectureValidator(Validator):
    """OS and architecture combination validator if EFA is enabled."""

    def _validate(self, efa_enabled: bool, os: str, architecture: str):
        if efa_enabled and os in EFA_UNSUPPORTED_ARCHITECTURES_OSES.get(architecture):
            self._add_failure(
                f"EFA is currently not supported on {os} for {architecture} architecture.", FailureLevel.ERROR
            )


class ArchitectureOsValidator(Validator):
    """
    Validate OS and architecture combination.

    ARM AMIs are only available for a subset of the supported OSes.
    """

    def _validate(self, os: str, architecture: str, custom_ami: str, ami_search_filters):
        allowed_oses = get_supported_os_for_architecture(architecture)
        if os not in allowed_oses:
            self._add_failure(
                f"The architecture {architecture} is only supported "
                f"for the following operating systems: {allowed_oses}.",
                FailureLevel.ERROR,
            )
        if custom_ami is None and os == "centos7" and architecture == "arm64" and not ami_search_filters:
            self._add_failure(
                "The aarch64 CentOS 7 OS is not validated for the 6th generation aarch64 instances "
                "(M6g, C6g, etc.). To proceed please provide a custom AMI, "
                "for more info see: https://wiki.centos.org/Cloud/AWS#aarch64_notes",
                FailureLevel.ERROR,
            )


class InstanceArchitectureCompatibilityValidator(Validator):
    """
    Validate instance type and architecture combination.

    Verify that head node and compute instance types imply compatible architectures.
    """

    def _validate(self, instance_type, architecture: str):
        head_node_architecture = architecture
        compute_architectures = AWSApi.instance().ec2.get_supported_architectures(instance_type)
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
                f"Invalid name '{name}'. Name can be at most {NAME_MAX_LENGTH} chars long.", FailureLevel.ERROR
            )

        if re.match("^default$", name):
            self._add_failure(f"It is forbidden to use '{name}' as a name.", FailureLevel.ERROR)


class MaxCountValidator(Validator):
    """Validate whether the number of resource exceeds the limits."""

    def _validate(self, resources_length, max_length, resource_name):

        if resources_length > max_length:
            self._add_failure(
                "Invalid number of {resource_name} ({resources_length}) specified. Currently only supports "
                "up to {max_length} {resource_name}.".format(
                    resource_name=resource_name, resources_length=resources_length, max_length=max_length
                ),
                FailureLevel.ERROR,
            )


# --------------- EFA validators --------------- #


class EfaValidator(Validator):
    """Check if EFA and EFA GDR are supported features in the given instance type."""

    def _validate(self, instance_type, efa_enabled, gdr_support):

        instance_type_supports_efa = AWSApi.instance().ec2.get_instance_type_info(instance_type).is_efa_supported()
        if efa_enabled and not instance_type_supports_efa:
            self._add_failure(f"Instance type '{instance_type}' does not support EFA.", FailureLevel.ERROR)
        if instance_type_supports_efa and not efa_enabled:
            self._add_failure(
                f"Instance type '{instance_type}' supports EFA, but it is not enabled.", FailureLevel.WARNING
            )
        if gdr_support and not efa_enabled:
            self._add_failure("The EFA GDR Support can be used only if EFA is enabled.", FailureLevel.ERROR)


class EfaPlacementGroupValidator(Validator):
    """Validate placement group if EFA is enabled."""

    def _validate(self, efa_enabled, placement_group_enabled, placement_group_config_implicit):
        if efa_enabled and placement_group_config_implicit:
            self._add_failure(
                "The placement group for EFA-enabled compute resources must be explicit. "
                "You may see better performance using a placement group, but if you don't wish to use one please add "
                "'Enabled: false' to the compute resource's configuration section.",
                FailureLevel.ERROR,
            )
        elif efa_enabled and not placement_group_enabled:
            self._add_failure(
                "You may see better performance using a placement group for the queue.", FailureLevel.WARNING
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
                sec_group = AWSApi.instance().ec2.describe_security_group(security_group)
                # check inbound rules
                allowed_in = self._all_traffic_allowed(security_group, sec_group.get("IpPermissions"))
                # check outbound rules
                allowed_out = self._all_traffic_allowed(security_group, sec_group.get("IpPermissionsEgress"))
                if allowed_in and allowed_out:
                    efa_sg_found = True
                    break
            except AWSClientError as e:
                self._add_failure(str(e), FailureLevel.WARNING)
        return efa_sg_found

    def _all_traffic_allowed(self, security_group_id, security_group_permission):
        for rule in security_group_permission:
            if rule.get("IpProtocol") == "-1" and rule.get("UserIdGroupPairs"):
                for group in rule.get("UserIdGroupPairs"):
                    if group.get("GroupId") == security_group_id:
                        return True
        return False


# --------------- Storage validators --------------- #


def _check_in_out_access(security_groups_ids, port):
    """
    Verify given list of security groups to check if they allow in and out access on the given port.

    :param security_groups_ids: list of security groups to verify
    :param port: port to verify
    :return: True if both in and out access are allowed
    :raise: ClientError if a given security group doesn't exist
    """
    in_out_access = False
    in_access = False
    out_access = False

    for sec_group in AWSApi.instance().ec2.describe_security_groups(security_groups_ids).get("SecurityGroups"):

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

            # Check to see if there is any existing mt on the fs
            file_system = AWSApi.instance().fsx.get_filesystem_info(file_system_id).file_system_data

            vpc_id = AWSApi.instance().ec2.get_subnet_vpc(head_node_subnet_id)

            # Check to see if fs is in the same VPC as the stack
            if file_system.get("VpcId") != vpc_id:
                self._add_failure(
                    "Currently only support using FSx file system that is in the same VPC as the cluster. "
                    "The file system provided is in {0}.".format(file_system.get("VpcId")),
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
                network_interface_responses = AWSApi.instance().ec2.describe_network_interfaces(network_interface_ids)

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
        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)


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

    if param_list:
        for param in param_list:
            if param in param_set:
                duplicated_params.append(param)
            else:
                param_set.add(param)
    return duplicated_params


def _find_overlapping_paths(paths_list):
    overlapping_paths = []
    if paths_list:
        for path in paths_list:
            is_overlapping = any(x for x in paths_list if x != path and x.startswith(path + "/"))
            if is_overlapping:
                overlapping_paths.append(path)

    return overlapping_paths


class DuplicateMountDirValidator(Validator):
    """
    Mount dir validator.

    Verify if there are duplicated mount dirs between shared storage and ephemeral volumes.
    """

    def _validate(self, mount_dir_list):
        duplicated_mount_dirs = _find_duplicate_params(mount_dir_list)
        if duplicated_mount_dirs:
            self._add_failure(
                "Mount {0} {1} cannot be specified for multiple file systems".format(
                    "directories" if len(duplicated_mount_dirs) > 1 else "directory",
                    ", ".join(mount_dir for mount_dir in duplicated_mount_dirs),
                ),
                FailureLevel.ERROR,
            )


class OverlappingMountDirValidator(Validator):
    """
    Mount dir validator.

    Verify if there are overlapping mount dirs between shared storage and ephemeral volumes.
    Two mount dirs are overlapped if one is contained into the other.
    """

    def _validate(self, mount_dir_list):
        overlapping_mount_dirs = _find_overlapping_paths(mount_dir_list)
        if overlapping_mount_dirs:
            self._add_failure(
                "Mount {0} {1} cannot contain other mount directories".format(
                    "directories" if len(overlapping_mount_dirs) > 1 else "directory",
                    ", ".join(mount_dir for mount_dir in overlapping_mount_dirs),
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
                f"Invalid number of shared storage of {storage_type} type specified. "
                f"Currently only supports upto {max_number}.",
                FailureLevel.ERROR,
            )


class EfsIdValidator(Validator):  # TODO add tests
    """
    EFS id validator.

    Validate if there are existing mount target in the head node availability zone
    """

    def _validate(self, efs_id, head_node_avail_zone: str):
        # Get head node availability zone
        head_node_target_id = AWSApi.instance().efs.get_efs_mount_target_id(efs_id, head_node_avail_zone)
        # If there is an existing mt in the az, need to check the inbound and outbound rules of the security groups
        if head_node_target_id:
            # Get list of security group IDs of the mount target
            sg_ids = AWSApi.instance().efs.get_efs_mount_target_security_groups(head_node_target_id)
            if not _check_in_out_access(sg_ids, port=2049):
                self._add_failure(
                    "There is an existing Mount Target {0} in the Availability Zone {1} for EFS {2}, "
                    "but it does not have a security group that allows inbound and outbound rules to support NFS. "
                    "Please modify the Mount Target's security group, to allow traffic on port 2049.".format(
                        head_node_target_id, head_node_avail_zone, efs_id
                    ),
                    FailureLevel.WARNING,
                )


class SharedStorageNameValidator(Validator):
    """
    Shared storage name validator.

    Validate if the provided name for the shared storage complies with the acceptable pattern.
    Since the storage name is used as a tag, the provided name must comply with the tag pattern.
    """

    def _validate(self, name: str):
        if not re.match(PCLUSTER_TAG_VALUE_REGEX, name):
            self._add_failure(
                (
                    f"Error: The shared storage name {name} is not valid. "
                    "Allowed characters are letters, numbers and white spaces that can be represented in UTF-8 "
                    "and the following characters: '+' '-' '=' '.' '_' ':' '/', "
                    f"and it can't be longer than 256 characters."
                ),
                FailureLevel.ERROR,
            )
        if len(name) > SHARED_STORAGE_NAME_MAX_LENGTH:
            self._add_failure(
                f"Invalid name '{name}'. Name can be at most {SHARED_STORAGE_NAME_MAX_LENGTH} chars long.",
                FailureLevel.ERROR,
            )

        if re.match("^default$", name):
            self._add_failure(f"It is forbidden to use '{name}' as a name.", FailureLevel.ERROR)


# --------------- Third party software validators --------------- #


class DcvValidator(Validator):
    """
    DCV parameters validators.

    Validate instance type, architecture and os when DCV is enabled.
    """

    def _validate(self, instance_type, dcv_enabled, allowed_ips, port, os, architecture: str):
        if dcv_enabled:
            allowed_oses = get_supported_dcv_os(architecture)
            if os not in allowed_oses:
                self._add_failure(
                    f"NICE DCV can be used with one of the following operating systems "
                    f"when using {architecture} architecture: {allowed_oses}. "
                    "Please double check the os configuration.",
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
        allowed_oses = ["centos7"]
        if os not in allowed_oses:
            self._add_failure(
                "When enabling intel software, the operating system is required to be set "
                f"to one of the following values : {allowed_oses}.",
                FailureLevel.ERROR,
            )


class IntelHpcArchitectureValidator(Validator):
    """Intel HPC architecture validator."""

    def _validate(self, architecture: str):
        allowed_architectures = ["x86_64"]
        if architecture not in allowed_architectures:
            self._add_failure(
                "When enabling Intel software, it is required to use head node and compute instance "
                f"types and an AMI that support these architectures: {allowed_architectures}.",
                FailureLevel.ERROR,
            )


# --------------- Other validators --------------- #


class DuplicateNameValidator(Validator):
    """
    Duplicate name validator.

    Verify if there are duplicated names.
    """

    def _validate(self, name_list, resource_name):
        duplicated_names = _find_duplicate_params(name_list)
        if duplicated_names:
            self._add_failure(
                "{0} {1} {2} must be unique.".format(
                    resource_name,
                    "names" if len(duplicated_names) > 1 else "name",
                    ", ".join(name for name in duplicated_names),
                ),
                FailureLevel.ERROR,
            )


class QueuesSecurityGroupOverwriteStatus(Enum):
    """Define queues security group overwrite status."""

    MIXED = "mixed"
    CUSTOM = "custom"
    MANAGED = "managed"


class MixedSecurityGroupOverwriteValidator(Validator):
    """Warn if some nodes are using custom security groups while others are using managed security groups."""

    def _validate(self, head_node_security_groups, queues):
        compute_security_group_overwrite_status = self._get_queues_security_group_overwrite_status(queues)
        if (
            head_node_security_groups
            and compute_security_group_overwrite_status != QueuesSecurityGroupOverwriteStatus.CUSTOM
        ) or (
            head_node_security_groups is None
            and compute_security_group_overwrite_status != QueuesSecurityGroupOverwriteStatus.MANAGED
        ):
            self._add_failure(
                "Please make sure that all cluster nodes are reachable to each other, "
                "or consider using additional security groups rather than replacing ParallelCluster security groups.",
                FailureLevel.WARNING,
            )

    def _get_queues_security_group_overwrite_status(self, queues):
        """Check if all queues need managed SG, or use custom SG, or are in mixed condition."""
        managed = False
        custom = False
        for queue in queues:
            if queue.networking.security_groups:
                custom = True
            else:
                managed = True
        if custom and managed:
            return QueuesSecurityGroupOverwriteStatus.MIXED
        if custom:
            return QueuesSecurityGroupOverwriteStatus.CUSTOM
        else:
            return QueuesSecurityGroupOverwriteStatus.MANAGED


# --------------- Instance settings validators --------------- #


class _LaunchTemplateValidator(Validator, ABC):
    """Abstract class to contain utility functions used by head node and queue LaunchTemplate validators."""

    def _build_launch_network_interfaces(
        self, network_interfaces_count, use_efa, security_group_ids, subnet, use_public_ips=False
    ):
        """Build the needed NetworkInterfaces to launch an instance."""
        network_interfaces = []
        for device_index in range(network_interfaces_count):
            network_interfaces.append(
                {
                    "DeviceIndex": device_index,
                    "NetworkCardIndex": device_index,
                    "InterfaceType": "efa" if use_efa else "interface",
                    "Groups": security_group_ids,
                    "SubnetId": subnet,
                }
            )

        # If instance types has multiple Network Interfaces we also check for
        if network_interfaces_count > 1 and use_public_ips:
            network_interfaces[0]["AssociatePublicIpAddress"] = True
        return network_interfaces

    def _ec2_run_instance(self, availability_zone: str, **kwargs):  # noqa: C901 FIXME!!!
        """Wrap ec2 run_instance call. Useful since a successful run_instance call signals 'DryRunOperation'."""
        try:
            AWSApi.instance().ec2.run_instances(**kwargs)
        except AWSClientError as e:
            code = e.error_code
            message = str(e)
            subnet_id = kwargs["NetworkInterfaces"][0]["SubnetId"]
            if code == "UnsupportedOperation":
                if "does not support specifying CpuOptions" in message:
                    message.replace("specifying CpuOptions", "disabling simultaneous multithreading")
                self._add_failure(message, FailureLevel.ERROR)
            elif code == "InstanceLimitExceeded":
                self._add_failure(
                    "You've reached the limit on the number of instances you can run concurrently "
                    f"for the configured instance type. {message}",
                    FailureLevel.ERROR,
                )
            elif code == "InsufficientInstanceCapacity":
                self._add_failure(
                    f"There is not enough capacity to fulfill your request. {message}", FailureLevel.ERROR
                )
            elif code == "InsufficientFreeAddressesInSubnet":
                self._add_failure(
                    "The specified subnet does not contain enough free private IP addresses "
                    f"to fulfill your request. {message}",
                    FailureLevel.ERROR,
                )
            elif code == "InvalidParameterCombination":
                if "associatePublicIPAddress" in message:
                    # Instances with multiple Network Interfaces cannot currently take public IPs.
                    # This check is meant to warn users about this problem until services are fixed.
                    self._add_failure(
                        f"The instance type {kwargs['InstanceType']} cannot take public IPs. "
                        f"Please make sure that the subnet with id '{subnet_id}' has the proper routing configuration "
                        "to allow private IPs reaching the Internet (e.g. a NAT Gateway and a valid route table).",
                        FailureLevel.WARNING,
                    )
            elif (
                code == "Unsupported"
                and availability_zone
                not in AWSApi.instance().ec2.get_supported_az_for_instance_type(kwargs["InstanceType"])
            ):
                # If an availability zone without desired instance type is selected, error code is "Unsupported"
                # Therefore, we need to write our own code to tell the specific problem
                qualified_az = AWSApi.instance().ec2.get_supported_az_for_instance_type(kwargs["InstanceType"])
                self._add_failure(
                    f"Your requested instance type ({kwargs['InstanceType']}) is not supported in the "
                    f"Availability Zone ({availability_zone}) of your requested subnet ({subnet_id}). "
                    f"Please retry your request by choosing a subnet in {qualified_az}. ",
                    FailureLevel.ERROR,
                )
            else:
                self._add_failure(
                    f"Unable to validate configuration parameters for instance type {kwargs['InstanceType']}. "
                    f"Please double check your cluster configuration. {message}",
                    FailureLevel.ERROR,
                )

    @staticmethod
    def _generate_tag_specifications(tags):
        """Turn list of Tag objects into tag specifications required by RunInstances."""
        tag_specifications = []
        if tags:
            tag_specifications.append(
                {"ResourceType": "instance", "Tags": [{"Key": tag.key, "Value": tag.value} for tag in tags]}
            )
        return tag_specifications


class HeadNodeLaunchTemplateValidator(_LaunchTemplateValidator):
    """Try to launch the requested instance (in dry-run mode) to verify configuration parameters."""

    def _validate(self, head_node, ami_id, tags):
        try:
            head_node_security_groups = []
            if head_node.networking.security_groups:
                head_node_security_groups.extend(head_node.networking.security_groups)
            if head_node.networking.additional_security_groups:
                head_node_security_groups.extend(head_node.networking.additional_security_groups)

            # Initialize CpuOptions
            head_node_cpu_options = (
                {"CoreCount": head_node.vcpus, "ThreadsPerCore": 1}
                if head_node.pass_cpu_options_in_launch_template
                else {}
            )

            head_node_network_interfaces = self._build_launch_network_interfaces(
                network_interfaces_count=head_node.max_network_interface_count,
                use_efa=False,  # EFA is not supported on head node
                security_group_ids=head_node_security_groups,
                subnet=head_node.networking.subnet_id,
            )

            # Test Head Node Instance Configuration
            self._ec2_run_instance(
                availability_zone=head_node.networking.availability_zone,
                InstanceType=head_node.instance_type,
                MinCount=1,
                MaxCount=1,
                ImageId=ami_id,
                CpuOptions=head_node_cpu_options,
                NetworkInterfaces=head_node_network_interfaces,
                DryRun=True,
                TagSpecifications=self._generate_tag_specifications(tags),
            )
        except Exception as e:
            self._add_failure(
                f"Unable to validate configuration parameters for the head node. {str(e)}", FailureLevel.ERROR
            )


class HeadNodeImdsValidator(Validator):
    """
    Head Node IMDS configuration validator.

    Verify if the Head Node IMDs configuration is compatible with other configurations.
    """

    def _validate(self, imds_secured: bool, scheduler: str):
        if scheduler is None:
            self._add_failure("Cannot validate IMDS configuration if scheduler is not set.", FailureLevel.ERROR)
        elif imds_secured is None:
            self._add_failure("Cannot validate IMDS configuration if IMDS Secured is not set.", FailureLevel.ERROR)
        elif imds_secured and scheduler not in SCHEDULERS_SUPPORTING_IMDS_SECURED:
            # TODO move validation for Imds parameter in the schema
            self._add_failure(
                f"IMDS Secured cannot be enabled when using scheduler {scheduler}. Please, disable IMDS Secured.",
                FailureLevel.ERROR,
            )


class ComputeResourceLaunchTemplateValidator(_LaunchTemplateValidator):
    """Try to launch the requested instances (in dry-run mode) to verify configuration parameters."""

    def _validate(self, queue, ami_id, tags):
        try:
            # Retrieve network parameters
            queue_subnet_id = queue.networking.subnet_ids[0]
            queue_security_groups = []
            if queue.networking.security_groups:
                queue_security_groups.extend(queue.networking.security_groups)
            if queue.networking.additional_security_groups:
                queue_security_groups.extend(queue.networking.additional_security_groups)

            # Initialize CpuOptions
            queue_placement_group_id = queue.networking.placement_group.id if queue.networking.placement_group else None
            queue_placement_group = {"GroupName": queue_placement_group_id} if queue_placement_group_id else {}

            # Select the "best" compute resource to run dryrun tests against.
            # Resources with multiple NICs are preferred among others.
            # Temporarily limiting dryrun tests to 1 per queue to save boto3 calls.
            dry_run_compute_resource = next(
                (compute_res for compute_res in queue.compute_resources if compute_res.max_network_interface_count > 1),
                queue.compute_resources[0],
            )
            self._test_compute_resource(
                compute_resource=dry_run_compute_resource,
                use_public_ips=bool(queue.networking.assign_public_ip),
                ami_id=ami_id,
                subnet_id=queue_subnet_id,
                security_groups_ids=queue_security_groups,
                placement_group=queue_placement_group,
                tags=tags,
            )
        except Exception as e:
            self._add_failure(
                f"Unable to validate configuration parameters for queue {queue.name}. {str(e)}", FailureLevel.ERROR
            )

    def _test_compute_resource(
        self, compute_resource, use_public_ips, ami_id, subnet_id, security_groups_ids, placement_group, tags
    ):
        """Test Compute Resource Instance Configuration."""
        compute_cpu_options = (
            {"CoreCount": compute_resource.vcpus, "ThreadsPerCore": 1}
            if compute_resource.disable_simultaneous_multithreading_via_cpu_options
            else {}
        )
        network_interfaces = self._build_launch_network_interfaces(
            compute_resource.max_network_interface_count,
            compute_resource.efa.enabled,
            security_groups_ids,
            subnet_id,
            use_public_ips,
        )
        self._ec2_run_instance(
            availability_zone=AWSApi.instance().ec2.get_subnet_avail_zone(subnet_id),
            InstanceType=compute_resource.instance_type,
            MinCount=1,
            MaxCount=1,
            ImageId=ami_id,
            CpuOptions=compute_cpu_options,
            Placement=placement_group,
            NetworkInterfaces=network_interfaces,
            DryRun=True,
            TagSpecifications=self._generate_tag_specifications(tags),
        )


class HostedZoneValidator(Validator):
    """Validate custom private domain in the same VPC as head node."""

    def _validate(self, hosted_zone_id, cluster_vpc, cluster_name):
        if AWSApi.instance().route53.is_hosted_zone_private(hosted_zone_id):
            vpc_ids = AWSApi.instance().route53.get_hosted_zone_vpcs(hosted_zone_id)
            if cluster_vpc not in vpc_ids:
                self._add_failure(
                    f"Private Route53 hosted zone {hosted_zone_id} need to be associated with "
                    f"the VPC of the cluster: {cluster_vpc}. "
                    f"The VPCs associated with hosted zone are {vpc_ids}.",
                    FailureLevel.ERROR,
                )
        else:
            self._add_failure(
                f"Hosted zone {hosted_zone_id} cannot be used. "
                f"Public Route53 hosted zone is not officially supported by ParallelCluster.",
                FailureLevel.ERROR,
            )

        domain_name = AWSApi.instance().route53.get_hosted_zone_domain_name(hosted_zone_id)
        total_length = len(cluster_name) + len(domain_name)
        if total_length > CLUSTER_NAME_AND_CUSTOM_DOMAIN_NAME_MAX_LENGTH:
            self._add_failure(
                (
                    "Error: When specifying HostedZoneId, "
                    f"the total length of cluster name {cluster_name} and domain name {domain_name} can not be "
                    f"longer than {CLUSTER_NAME_AND_CUSTOM_DOMAIN_NAME_MAX_LENGTH} character, "
                    f"current length is {total_length}"
                ),
                FailureLevel.ERROR,
            )
