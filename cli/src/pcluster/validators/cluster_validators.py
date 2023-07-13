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
import math
import re
from collections import defaultdict
from enum import Enum
from ipaddress import collapse_addresses, ip_network
from itertools import combinations, product
from typing import List

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.aws_resources import InstanceTypeInfo
from pcluster.aws.common import AWSClientError
from pcluster.cli.commands.dcv_util import get_supported_dcv_os
from pcluster.constants import (
    CIDR_ALL_IPS,
    DELETE_POLICY,
    EFS_PORT,
    FSX_PORTS,
    PCLUSTER_IMAGE_BUILD_STATUS_TAG,
    PCLUSTER_NAME_MAX_LENGTH,
    PCLUSTER_NAME_MAX_LENGTH_SLURM_ACCOUNTING,
    PCLUSTER_NAME_REGEX,
    PCLUSTER_TAG_VALUE_REGEX,
    PCLUSTER_VERSION_TAG,
    RETAIN_POLICY,
    SCHEDULERS_SUPPORTING_IMDS_SECURED,
    SUPPORTED_OSES,
    SUPPORTED_REGIONS,
    SUPPORTED_SCHEDULERS,
)
from pcluster.launch_template_utils import _LaunchTemplateBuilder
from pcluster.utils import (
    get_installed_version,
    get_supported_os_for_architecture,
    get_supported_os_for_scheduler,
    remove_none_values,
)
from pcluster.validators.common import FailureLevel, Validator

# pylint: disable=C0302
NAME_MAX_LENGTH = 25
SHARED_STORAGE_NAME_MAX_LENGTH = 30
NAME_REGEX = r"^[a-z][a-z0-9\-]*$"

EFA_UNSUPPORTED_ARCHITECTURES_OSES = {"x86_64": [], "arm64": ["centos7"]}

EFS_MESSAGES = {
    "errors": {
        "ignored_param_with_efs_fs_id": "{efs_param} cannot be specified when an existing EFS file system is used.",
    }
}

FSX_SUPPORTED_ARCHITECTURES_OSES = {
    "x86_64": SUPPORTED_OSES,
    "arm64": SUPPORTED_OSES,
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
        "ignored_param_with_fsx_fs_id": "{fsx_param} cannot be specified when an existing Lustre file system is used.",
    }
}

HOST_NAME_MAX_LENGTH = 64
# Max fqdn size is 255 characters, the first 64 are used for the hostname (e.g. queuename-st|dy-computeresourcename-N),
# then we need to add an extra ., so we have 190 characters to be used for the clustername + domain-name.
CLUSTER_NAME_AND_CUSTOM_DOMAIN_NAME_MAX_LENGTH = 255 - HOST_NAME_MAX_LENGTH - 1


class ClusterNameValidator(Validator):
    """Cluster name validator."""

    def _validate(self, name, scheduling):
        if scheduling.scheduler == "slurm" and scheduling.settings.database is not None:
            if not re.match(PCLUSTER_NAME_REGEX % (PCLUSTER_NAME_MAX_LENGTH_SLURM_ACCOUNTING - 1), name):
                self._add_failure(
                    (
                        "Error: The cluster name can contain only alphanumeric characters (case-sensitive) and "
                        "hyphens. "
                        "It must start with an alphabetic character and when using Slurm accounting it can't be longer "
                        f"than {PCLUSTER_NAME_MAX_LENGTH_SLURM_ACCOUNTING} characters."
                    ),
                    FailureLevel.ERROR,
                )
        else:
            if not re.match(PCLUSTER_NAME_REGEX % (PCLUSTER_NAME_MAX_LENGTH - 1), name):
                self._add_failure(
                    (
                        "Error: The cluster name can contain only alphanumeric characters (case-sensitive) and "
                        "hyphens. "
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
                    "Unable to retrieve custom AMI build status. "
                    "Please check build-image CloudFormation stack for details."
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


class EfaOsArchitectureValidator(Validator):
    """OS and architecture combination validator if EFA is enabled."""

    def _validate(self, efa_enabled: bool, os: str, architecture: str):
        if efa_enabled and os in EFA_UNSUPPORTED_ARCHITECTURES_OSES.get(architecture):
            self._add_failure(
                f"EFA is currently not supported on {os} for {architecture} architecture.", FailureLevel.ERROR
            )


class SchedulableMemoryValidator(Validator):
    """Validate SchedulableMemory parameter passed by user."""

    def _validate(self, schedulable_memory, ec2memory, instance_type):
        if schedulable_memory is not None:
            if schedulable_memory < 1:
                self._add_failure("SchedulableMemory must be at least 1 MiB.", FailureLevel.ERROR)
            if ec2memory is None:
                self._add_failure(
                    f"SchedulableMemory was set but EC2 memory is not available for selected instance type "
                    f"{instance_type}. Defaulting to 1 MiB.",
                    FailureLevel.WARNING,
                )
            else:
                if schedulable_memory > ec2memory:
                    self._add_failure(
                        f"SchedulableMemory cannot be larger than EC2 Memory for selected instance type "
                        f"{instance_type} ({ec2memory} MiB).",
                        FailureLevel.ERROR,
                    )
                if schedulable_memory < math.floor(0.95 * ec2memory):
                    self._add_failure(
                        f"SchedulableMemory was set lower than 95% of EC2 Memory for selected instance type "
                        f"{instance_type} ({ec2memory} MiB).",
                        FailureLevel.INFO,
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

    def _validate(self, instance_type_info_list: List[InstanceTypeInfo], architecture: str):
        head_node_architecture = architecture

        for instance_type_info in instance_type_info_list:
            compute_architectures = instance_type_info.supported_architecture()
            if head_node_architecture not in instance_type_info.supported_architecture():
                self._add_failure(
                    "The specified compute instance type ({0}) supports the architectures {1}, none of which are "
                    "compatible with the architecture supported by the head node instance type ({2}).".format(
                        instance_type_info.instance_type(), compute_architectures, head_node_architecture
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

    def _validate(self, instance_type, efa_enabled, gdr_support, multiaz_enabled):
        instance_type_supports_efa = AWSApi.instance().ec2.get_instance_type_info(instance_type).is_efa_supported()
        if efa_enabled and not instance_type_supports_efa:
            self._add_failure(f"Instance type '{instance_type}' does not support EFA.", FailureLevel.ERROR)
        if instance_type_supports_efa and not efa_enabled and not multiaz_enabled:
            self._add_failure(
                f"The EC2 instance selected ({instance_type}) supports enhanced networking capabilities using "
                "Elastic Fabric Adapter (EFA). EFA enables you to run applications requiring high levels of "
                "inter-node communications at scale on AWS at no additional charge. You can update the cluster's "
                "configuration to enable EFA (https://docs.aws.amazon.com/parallelcluster/latest/ug/efa-v3.html)",
                FailureLevel.WARNING,
            )
        if gdr_support and not efa_enabled:
            self._add_failure("The EFA GDR Support can be used only if EFA is enabled.", FailureLevel.ERROR)


class EfaPlacementGroupValidator(Validator):
    """Validate placement group if EFA is enabled."""

    def _validate(
        self, efa_enabled: bool, placement_group_key: str, placement_group_disabled: bool, multi_az_enabled: bool
    ):
        # if multi_az is enabled suggestions about PlacementGroups will be suppressed
        if efa_enabled and placement_group_disabled and not multi_az_enabled:
            self._add_failure(
                "You may see better performance using a placement group for the queue.", FailureLevel.WARNING
            )
        elif efa_enabled and placement_group_key is None and not multi_az_enabled:
            self._add_failure(
                "The placement group for EFA-enabled compute resources must be explicit. "
                "You may see better performance using a placement group, but if you don't wish to use one please add "
                "'Enabled: false' to the compute resource's configuration section.",
                FailureLevel.ERROR,
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


class EfaMultiAzValidator(Validator):
    """Validate MultiAZ if EFA is enabled."""

    def _validate(
        self, queue_name: str, multi_az_enabled: bool, compute_resource_name: str, compute_resource_efa_enabled: bool
    ):
        if multi_az_enabled and compute_resource_efa_enabled:
            message = (
                f"You have enabled the Elastic Fabric Adapter (EFA) for the '{compute_resource_name}' Compute Resource"
                f" on the '{queue_name}' queue. EFA is not supported across Availability zones. Either disable EFA "
                "to use multiple subnets on the queue or specify only one subnet to enable EFA on "
                "the compute resources."
            )
            self._add_failure(
                message,
                FailureLevel.ERROR,
            )


# --------------- Storage validators --------------- #


def _is_access_allowed(security_groups_ids, subnets, port, security_groups_by_nodes, protocol="tcp"):
    """
    Verify given list of security groups to check if they allow in and out access on the given port.

    :param security_groups_ids: list of security groups to verify
    :param port: port to verify
    :param security_groups_by_nodes: all security groups from cluster. This is a set of frozen sets.
    Each frozen set contains sg combination of a queue.
    :param protocol: the IP protocol to be checked.
    :return: True if both in and out access are allowed
    :raise: ClientError if a given security group doesn't exist
    """
    in_access = False
    out_access = False
    src_ip_ranges = []
    dst_ip_ranges = []
    src_security_groups = set()
    dst_security_groups = set()

    for sec_group in AWSApi.instance().ec2.describe_security_groups(security_groups_ids):
        # Check all inbound rules
        for rule in sec_group.get("IpPermissions"):
            if in_access:
                break
            if _is_port_allowed_by_sg_rule(rule, port, protocol):
                in_access = _populate_allowed_src_or_dst(rule, src_ip_ranges, src_security_groups)

        # Check all outbound rules
        for rule in sec_group.get("IpPermissionsEgress"):
            if out_access:
                break
            if _is_port_allowed_by_sg_rule(rule, port, protocol):
                out_access = _populate_allowed_src_or_dst(rule, dst_ip_ranges, dst_security_groups)

        if in_access and out_access:
            return True
    # If in_access or out_access is still False, check allowed ip ranges and security groups.
    # The in_access or out_access could only have been true, if previous logics had found prefix list in SG rules.
    # Rules of ip ranges have to be checked at the end because the union of all ip ranges may cover the subnets,
    # even when individual ip ranges do not cover the subnets. The same reason applies to allowed security groups.
    in_access = in_access or _are_ip_ranges_and_sg_accessible(
        security_groups_by_nodes, src_ip_ranges, src_security_groups, subnets
    )
    out_access = out_access or _are_ip_ranges_and_sg_accessible(
        security_groups_by_nodes, dst_ip_ranges, dst_security_groups, subnets
    )
    return in_access and out_access


def _are_ip_ranges_and_sg_accessible(security_groups_by_nodes, allowed_ip_ranges, allowed_security_groups, subnets):
    # For all cluster nodes, at least one of the security groups attached need to be in the UserIdGroupPairs.
    return all(
        node_security_groups & allowed_security_groups for node_security_groups in security_groups_by_nodes
    ) or _are_subnets_covered_by_cidrs(allowed_ip_ranges, subnets)


def _populate_allowed_src_or_dst(rule, ip_ranges, allowed_security_groups):
    """
    Collect Ip ranges or security groups allowed by the rule.

    :param rule: A rule of a security group
    :param ip_ranges: A list of ip ranges.
    :param allowed_security_groups: A list of allowed security group.
    :return: True if we can determine the current rule allows connection.
    False if it does not allow connection or cannot be determined.
    """
    if rule.get("PrefixListIds"):
        return True  # Always assume prefix list is properly set for code simplicity
    elif rule.get("IpRanges"):
        ip_ranges.extend(rule.get("IpRanges"))
        return False  # Ip Ranges have to be checked later. Return False because the rule allowance is not determined.
    elif rule.get("UserIdGroupPairs"):
        allowed_security_groups.update(
            {user_id_group_pair.get("GroupId") for user_id_group_pair in rule.get("UserIdGroupPairs")}
        )
        # Security groups have to be checked later. Return False because the rule allowance is not determined.
        return False
    return False


def _is_port_allowed_by_sg_rule(rule, port_to_check, protocol):
    """
    Verify if the security group rule accepts connections on the given port.

    :param rule: The rule to check
    :param port_to_check: The port to check
    :param protocol: the IP protocol to be checked.
    :return: True if the rule accepts connection, False otherwise
    """
    from_port = rule.get("FromPort")
    to_port = rule.get("ToPort")
    ip_protocol = rule.get("IpProtocol")

    # if ip_protocol is -1, all ports are allowed
    if ip_protocol == "-1":
        return True
    # Add protocol number in addition to the protocol name
    if protocol == "tcp":
        expected_protocol = [protocol, "6"]
    elif protocol == "udp":
        expected_protocol = [protocol, "17"]
    else:
        # ToDo: When adding new checks for other protocols, change the code to include the protocol number too.
        expected_protocol = [protocol]

    if (ip_protocol in expected_protocol) and (from_port <= port_to_check <= to_port):
        return True

    return False


def _are_subnets_covered_by_cidrs(ip_ranges, subnets):
    """Verify given list of security groups to check if they allow in and out access on cluster subnet CIDRs."""
    # Collapse ip ranges for better performance and correctness
    collapsed_ip_ranges = list(collapse_addresses([ip_network(ip_range["CidrIp"]) for ip_range in ip_ranges]))

    for subnet in subnets:
        subnet_cidr = ip_network(AWSApi.instance().ec2.get_subnet_cidr(subnet))
        covered = False
        for ip_range in collapsed_ip_ranges:
            if ip_range.supernet_of(subnet_cidr):
                covered = True
                break
        if not covered:
            return False
    return True


class ExistingFsxNetworkingValidator(Validator):
    """
    FSx networking validator.

    Validate file system mount point according to the head node subnet.
    The reason to have this structure is to make boto3 calls as few as possible.
    """

    def _describe_network_interfaces(self, file_systems):
        all_network_interfaces = []
        for file_system in file_systems:
            all_network_interfaces.extend(file_system.network_interface_ids)
        if all_network_interfaces:
            response = AWSApi.instance().ec2.describe_network_interfaces(all_network_interfaces)
            network_interfaces_data = {}
            for network_interface in response:
                network_interfaces_data[network_interface["NetworkInterfaceId"]] = network_interface
            return network_interfaces_data
        else:
            return {}

    def _validate(self, file_storage_ids, subnet_ids, security_groups_by_nodes):
        try:
            file_cache_ids = [file_cache_id for file_cache_id in file_storage_ids if file_cache_id.startswith("fc-")]
            if file_cache_ids:
                file_storage_ids = [id for id in file_storage_ids if id not in file_cache_ids]
                file_caches = AWSApi.instance().fsx.describe_file_caches(file_cache_ids)
                self._check_file_storage(security_groups_by_nodes, file_caches, subnet_ids)

            file_systems = AWSApi.instance().fsx.get_file_systems_info(file_storage_ids)
            self._check_file_storage(security_groups_by_nodes, file_systems, subnet_ids)
        except AWSClientError as e:
            self._add_failure(str(e), FailureLevel.ERROR)

    def _check_file_storage(self, security_groups_by_nodes, file_storages, subnet_ids):
        vpc_id = AWSApi.instance().ec2.get_subnet_vpc(subnet_ids[0])
        network_interfaces_data = self._describe_network_interfaces(file_storages)
        for file_storage in file_storages:
            # Check to see if fs is in the same VPC as the stack
            file_storage_id = file_storage.file_system_id if file_storage.file_system_id else file_storage.file_cache_id
            if file_storage.vpc_id != vpc_id:
                self._add_failure(
                    "Currently only support using FSx file storage that is in the same VPC as the cluster. "
                    f"The file system {file_storage_id} is in {file_storage.vpc_id}.",
                    FailureLevel.ERROR,
                )

            # If there is an existing mt in the az, check the inbound and outbound rules of the security groups
            network_interface_ids = file_storage.network_interface_ids
            if not network_interface_ids:
                self._add_failure(
                    f"Unable to validate FSx security groups. The given FSx file storage '{file_storage_id}'"
                    " doesn't have Elastic Network Interfaces attached to it.",
                    FailureLevel.ERROR,
                )
            else:
                network_interface_responses = []
                for network_interface_id in network_interface_ids:
                    network_interface_responses.append(network_interfaces_data[network_interface_id])

                network_interfaces = [ni for ni in network_interface_responses if ni.get("VpcId") == vpc_id]

                for protocol, ports in FSX_PORTS[file_storage.file_storage_type].items():
                    missing_ports = self._get_missing_ports(
                        security_groups_by_nodes, subnet_ids, network_interfaces, ports, protocol
                    )

                    if missing_ports:
                        self._add_failure(
                            f"The current security group settings on file storage '{file_storage_id}' does not"
                            " satisfy mounting requirement. The file storage must be associated to a security group"
                            f" that allows inbound and outbound {protocol.upper()} traffic through ports {ports}. "
                            f"Missing ports: {missing_ports}",
                            FailureLevel.ERROR,
                        )

    def _get_missing_ports(self, security_groups_by_nodes, subnet_ids, network_interfaces, ports, protocol):
        missing_ports = []
        for port in ports:
            fs_access = False
            for network_interface in network_interfaces:
                # Get list of security group IDs
                sg_ids = [sg.get("GroupId") for sg in network_interface.get("Groups")]
                if _is_access_allowed(
                    sg_ids,
                    subnet_ids,
                    port=port,
                    security_groups_by_nodes=security_groups_by_nodes,
                    protocol=protocol,
                ):
                    fs_access = True
                    break
            if not fs_access:
                missing_ports.append(port)
        return missing_ports


class FsxArchitectureOsValidator(Validator):
    """
    FSx architecture and OS validator.

    Validate that OS and architecture are compatible with FSx.
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


def _find_overlapping_paths(shared_paths_list, local_paths_list):
    overlapping_paths = []
    if shared_paths_list:
        for path1, path2 in list(combinations(shared_paths_list, 2)) + list(
            product(shared_paths_list, local_paths_list)
        ):  # Check all pairs in shared paths list and all pairs between shared paths list and local paths list
            is_overlapping = path1.startswith(path2 + "/") or path2.startswith(path1 + "/")
            if is_overlapping:
                overlapping_paths.extend([path1, path2])

    return overlapping_paths


class DuplicateMountDirValidator(Validator):
    """
    Mount dir validator.

    Verify if there are duplicated mount dirs between shared storage and ephemeral volumes.
    """

    def _validate(self, shared_storage_name_mount_dir_tuple_list, local_mount_dir_instance_types_dict):
        mount_dir_to_names = defaultdict(list)
        for shared_storage_name, shared_mount_dir in shared_storage_name_mount_dir_tuple_list:
            mount_dir_to_names[shared_mount_dir].append(shared_storage_name)
        for mount_dir, names in mount_dir_to_names.items():
            if len(names) > 1:
                self._add_failure(
                    f"The mount directory `{mount_dir}` is used for multiple shared storage: {names}. "
                    "Shared storage mount directories should be unique. "
                    "Please change the mount directory configuration of the shared storage.",
                    FailureLevel.ERROR,
                )
        for local_mount_dir, instance_types in local_mount_dir_instance_types_dict.items():
            shared_storage_names = mount_dir_to_names.get(local_mount_dir)
            if shared_storage_names:
                self._add_failure(
                    f"The mount directory `{local_mount_dir}` used for shared storage {shared_storage_names} "
                    f"clashes with the one used for ephemeral volumes of the instances {list(instance_types)}. "
                    f"Please change the mount directory configuration of either the shared storage or the ephemeral "
                    f"volume of the impacted nodes.",
                    FailureLevel.WARNING,
                )


class OverlappingMountDirValidator(Validator):
    """
    Mount dir validator.

    Verify if there are overlap mount dirs.
    1. Shared storage directories can not overlap with each other.
    2. Shared storage directories can not overlap with ephemeral storage directories.
    3. Ephemeral storage directories can overlap with each other, because they are local to compute nodes.
    Two mount dirs are overlapped if one is contained into the other.
    """

    def _validate(self, shared_mount_dir_list, local_mount_dir_list):
        overlapping_mount_dirs = _find_overlapping_paths(shared_mount_dir_list, local_mount_dir_list)
        if overlapping_mount_dirs:
            self._add_failure(
                "Mount directories {0} cannot overlap".format(
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
                f"Too many {storage_type} shared storage specified in the configuration. "
                f"ParallelCluster supports {max_number} {storage_type}.",
                FailureLevel.ERROR,
            )


class ManagedFsxMultiAzValidator(Validator):
    """
    Managed FSx Storage Vs Multiple Subnets validator.

    Validate if managed storage of type FSx is set when using multiple subnets in queues configuration.
    """

    def _validate(self, compute_subnet_ids, new_storage_count):
        if len(compute_subnet_ids) > 1 and new_storage_count.get("fsx") > 0:
            self._add_failure(
                "Managed FSx storage created by ParallelCluster is not supported when specifying multiple subnet Ids "
                "under the SubnetIds configuration of a queue. Please make sure to provide an existing FSx shared "
                "storage, properly configured to work across the target subnets or remove the managed FSx storage to "
                "use multiple subnets for a queue.",
                FailureLevel.ERROR,
            )


class UnmanagedFsxMultiAzValidator(Validator):
    """
    Unmanaged FSx Storage Vs Multiple Subnets validator.

    Unmanaged FSx volumes can exist in AZ that are different from the ones defined in queues configuration.
    In these cases we notify customers that they may incur in increased latency and costs.
    """

    def _validate(self, queues, fsx_az_list):
        for queue in queues:
            queue_az_set = set(queue.networking.az_list)
            fs_az_set = set(fsx_az_list)
            # we want to ensure that all the az defined in the queue are supported by the FS
            if not queue_az_set.issubset(fs_az_set):
                self._add_failure(
                    "Your configuration for Queue '{0}' includes multiple subnets and external shared storage "
                    "configuration. Accessing a shared storage from different AZs can lead to increased storage "
                    "networking latency and added inter-AZ data transfer costs.".format(queue.name),
                    FailureLevel.INFO,
                )


class EfsIdValidator(Validator):  # TODO add tests
    """
    EFS id validator.

    Validate if there are existing mount target in the cluster (head and computes) availability zone
    """

    def _validate(self, efs_id, avail_zones_mapping: dict, security_groups_by_nodes):
        availability_zones = avail_zones_mapping.keys()
        if len(availability_zones) > 1 and not AWSApi.instance().efs.is_efs_standard(efs_id):
            self._add_failure(
                f"Cluster has subnets located in different availability zones but EFS ({efs_id}) uses OneZone EFS "
                "storage class which works within a single Availability Zone. Please use subnets located in one "
                "Availability Zone or use a standard storage class EFS.",
                FailureLevel.ERROR,
            )

        avail_zones_missing_mount_target_for_efs_standard = []
        for avail_zone, subnets in avail_zones_mapping.items():
            head_node_target_id = AWSApi.instance().efs.get_efs_mount_target_id(efs_id, avail_zone)
            # If there is an existing mt in the az, need to check the inbound and outbound rules of the security groups
            if head_node_target_id:
                # Get list of security group IDs of the mount target
                sg_ids = AWSApi.instance().efs.get_efs_mount_target_security_groups(head_node_target_id)
                if not _is_access_allowed(
                    sg_ids, subnets, port=EFS_PORT, security_groups_by_nodes=security_groups_by_nodes
                ):
                    self._add_failure(
                        "There is an existing Mount Target {0} in the Availability Zone {1} for EFS {2}, "
                        "but it does not have a security group that allows inbound and outbound rules to support NFS. "
                        "Please modify the Mount Target's security group, to allow traffic on port 2049.".format(
                            head_node_target_id, avail_zone, efs_id
                        ),
                        FailureLevel.ERROR,
                    )
            else:
                if AWSApi.instance().efs.is_efs_standard(efs_id):
                    avail_zones_missing_mount_target_for_efs_standard.append(avail_zone)
        if avail_zones_missing_mount_target_for_efs_standard:
            self._add_failure(
                "There is no existing Mount Target for EFS '{0}' in these Availability Zones: '{1}'. "
                "Please create an EFS Mount Target for those availability zones.".format(
                    efs_id, avail_zones_missing_mount_target_for_efs_standard
                ),
                FailureLevel.ERROR,
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


class SharedStorageMountDirValidator(Validator):
    """
    Shared storage mount directory validator.

    Make sure the mount directory is not the same as any reserved directory.
    """

    def _validate(self, mount_dir: str):
        reserved_directories = [
            "/bin",
            "/boot",
            "/dev",
            "/etc",
            "/home",
            "/lib",
            "/lib64",
            "/media",
            "/mnt",
            "/opt",
            "/proc",
            "/root",
            "/run",
            "/sbin",
            "/srv",
            "/sys",
            # A nosec comment is appended to the following line in order to disable the B108 check.
            # It is a false positive since is a list to check folder name
            # [B108:hardcoded_tmp_directory] Probable insecure usage of temp file/directory.
            "/tmp",  # nosec B108
            "/usr",
            "/var",
        ]
        if not mount_dir.startswith("/"):
            mount_dir = "/" + mount_dir
        if mount_dir in reserved_directories:
            self._add_failure(
                f"Error: The shared storage mount directory {mount_dir} is reserved. Please use another directory",
                FailureLevel.ERROR,
            )


class DeletionPolicyValidator(Validator):
    """Print warning message when deletion policy is set to Delete or Retain."""

    def _validate(self, deletion_policy: str, name: str):
        if deletion_policy == DELETE_POLICY:
            self._add_failure(
                f"The DeletionPolicy is set to {DELETE_POLICY}. The storage '{name}' will be deleted when you remove "
                "it from the configuration when performing a cluster update or deleting the cluster.",
                FailureLevel.INFO,
            )
        elif deletion_policy == RETAIN_POLICY:
            self._add_failure(
                f"The DeletionPolicy is set to {RETAIN_POLICY}. The storage '{name}' will be retained when you remove "
                "it from the configuration when performing a cluster update or deleting the cluster.",
                FailureLevel.INFO,
            )


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


class _LaunchTemplateValidator(Validator):
    """Abstract class to contain utility functions used by head node and queue LaunchTemplate validators."""

    def __init__(self):
        super().__init__()
        self._launch_template_builder = DictLaunchTemplateBuilder()

    @staticmethod
    def _build_launch_network_interfaces(
        network_interfaces_count, use_efa, security_group_ids, subnet, use_public_ips=False
    ):
        """Build the needed NetworkInterfaces to launch an instance."""
        network_interfaces = []
        for network_interface_index in range(network_interfaces_count):
            network_interfaces.append(
                {
                    "DeviceIndex": 0,
                    "NetworkCardIndex": network_interface_index,
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
            AWSApi.instance().ec2.run_instances(**remove_none_values(kwargs))
        except AWSClientError as e:
            code = e.error_code
            message = str(e)
            subnet_id = kwargs["NetworkInterfaces"][0]["SubnetId"]
            if code == "InstanceLimitExceeded":
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

    def _validate(self, head_node, root_volume_device_name, ami_id, tags, imds_support):
        try:
            head_node_security_groups = []
            if head_node.networking.security_groups:
                head_node_security_groups.extend(head_node.networking.security_groups)
            if head_node.networking.additional_security_groups:
                head_node_security_groups.extend(head_node.networking.additional_security_groups)

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
                NetworkInterfaces=head_node_network_interfaces,
                DryRun=True,
                TagSpecifications=self._generate_tag_specifications(tags),
                KeyName=head_node.ssh.key_name,
                BlockDeviceMappings=(
                    self._launch_template_builder.get_block_device_mappings(
                        head_node.local_storage.root_volume, root_volume_device_name
                    )
                ),
                MetadataOptions={
                    "HttpTokens": "required" if imds_support == "v2.0" else "optional",
                },
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

    def _validate(self, queue, root_volume_device_name, ami_id, tags, imds_support):
        try:
            # Retrieve network parameters
            queue_subnet_id = queue.networking.subnet_ids[0]
            queue_security_groups = []
            if queue.networking.security_groups:
                queue_security_groups.extend(queue.networking.security_groups)
            if queue.networking.additional_security_groups:
                queue_security_groups.extend(queue.networking.additional_security_groups)

            # Select the "best" compute resource to run dryrun tests against.
            # Resources with multiple NICs are preferred among others.
            # Temporarily limiting dryrun tests to 1 per queue to save boto3 calls.
            dry_run_compute_resource = next(
                (compute_res for compute_res in queue.compute_resources if compute_res.max_network_interface_count > 1),
                queue.compute_resources[0],
            )
            compute_resource_placement_group = (
                dry_run_compute_resource.networking.placement_group or queue.networking.placement_group
            )

            placement_group_name = compute_resource_placement_group.assignment
            # For SlurmFlexibleComputeResource test only the first InstanceType through a RunInstances
            self._test_compute_resource(
                queue=queue,
                root_volume_device_name=root_volume_device_name,
                compute_resource=dry_run_compute_resource,
                use_public_ips=bool(queue.networking.assign_public_ip),
                ami_id=ami_id,
                subnet_id=queue_subnet_id,
                security_groups_ids=queue_security_groups,
                placement_group={"GroupName": placement_group_name} if placement_group_name else {},
                tags=tags,
                imds_support=imds_support,
            )
        except Exception as e:
            self._add_failure(
                f"Unable to validate configuration parameters for queue {queue.name}. {str(e)}", FailureLevel.ERROR
            )

    def _test_compute_resource(
        self,
        queue,
        root_volume_device_name,
        compute_resource,
        use_public_ips,
        ami_id,
        subnet_id,
        security_groups_ids,
        placement_group,
        tags,
        imds_support,
    ):
        """Test Compute Resource Instance Configuration."""
        network_interfaces = self._build_launch_network_interfaces(
            compute_resource.max_network_interface_count,
            compute_resource.efa.enabled,
            security_groups_ids,
            subnet_id,
            use_public_ips,
        )
        self._ec2_run_instance(
            availability_zone=AWSApi.instance().ec2.get_subnet_avail_zone(subnet_id),
            InstanceType=compute_resource.instance_types[0],
            MinCount=1,
            MaxCount=1,
            ImageId=ami_id,
            Placement=placement_group,
            NetworkInterfaces=network_interfaces,
            DryRun=True,
            TagSpecifications=self._generate_tag_specifications(tags),
            InstanceMarketOptions=self._launch_template_builder.get_instance_market_options(queue, compute_resource),
            CapacityReservationSpecification=self._launch_template_builder.get_capacity_reservation(
                queue, compute_resource
            ),
            BlockDeviceMappings=self._launch_template_builder.get_block_device_mappings(
                queue.compute_settings.local_storage.root_volume, root_volume_device_name
            ),
            MetadataOptions={
                "HttpTokens": "required" if imds_support == "v2.0" else "optional",
            },
        )


class RootVolumeSizeValidator(Validator):
    """Verify the root volume size is equal or greater to the size of the snapshot of the AMI."""

    def _validate(self, root_volume_size, ami_volume_size):
        if root_volume_size:
            if root_volume_size < ami_volume_size:
                self._add_failure(
                    f"Root volume size {root_volume_size} GiB must be equal or greater than the volume size of "
                    f"the AMI: {ami_volume_size} GiB.",
                    FailureLevel.ERROR,
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


class SchedulerValidator(Validator):
    """Validate that only supported schedulers are specified."""

    def _validate(self, scheduler):
        if scheduler not in SUPPORTED_SCHEDULERS:
            self._add_failure(
                f"{scheduler} scheduler is not supported. Supported schedulers are: {', '.join(SUPPORTED_SCHEDULERS)}.",
                FailureLevel.ERROR,
            )


class DictLaunchTemplateBuilder(_LaunchTemplateBuilder):
    """Concrete class to build a dict with EC2 run instance properties to simulate our launch templates."""

    def _block_device_mapping_for_ebs(self, device_name, volume):
        return {
            "DeviceName": device_name,
            "Ebs": remove_none_values(
                {
                    "Encrypted": volume.encrypted,
                    "VolumeType": volume.volume_type,
                    "Iops": volume.iops,
                    "Throughput": volume.throughput,
                    "DeleteOnTermination": volume.delete_on_termination,
                    "VolumeSize": volume.size,
                }
            ),
        }

    def _block_device_mapping_for_virt(self, device_name, virtual_name):
        return {"DeviceName": device_name, "VirtualName": virtual_name}

    def _instance_market_option(self, market_type, spot_instance_type, instance_interruption_behavior, max_price):
        return {
            "MarketType": market_type,
            "SpotOptions": remove_none_values(
                {
                    "SpotInstanceType": spot_instance_type,
                    "InstanceInterruptionBehavior": instance_interruption_behavior,
                    "MaxPrice": max_price,
                }
            ),
        }

    def _capacity_reservation(self, cr_target):
        return {
            "CapacityReservationTarget": remove_none_values(
                {
                    "CapacityReservationId": cr_target.capacity_reservation_id,
                    "CapacityReservationResourceGroupArn": cr_target.capacity_reservation_resource_group_arn,
                }
            )
        }


class RootVolumeEncryptionConsistencyValidator(Validator):
    """Verify consistency on the Encryption parameter of all the specified RootVolumes of the queues."""

    def _validate(self, encryption_settings: list):
        reference_queue_name, reference_root_volume_encryption = encryption_settings.pop(0)
        for queue in encryption_settings:
            queue_name, root_volume_encryption = queue
            if reference_root_volume_encryption != root_volume_encryption:
                self._add_failure(
                    f"The Encryption parameter of the root volume of the queue {queue_name} is not consistent "
                    f"with the value set for the queue {reference_queue_name}, and may cause a problem in case "
                    f"of Service Control Policies (SCPs) enforcing encryption.",
                    FailureLevel.WARNING,
                )


class MultiNetworkInterfacesInstancesValidator(Validator):
    """Verify that queues with multi nic compute resources don't auto-assign public IPs or contain subnets that do."""

    def _validate(self, queues):
        multi_nic_queues = [
            queue
            for queue in queues
            for compute_resource in queue.compute_resources
            if compute_resource.max_network_interface_count > 1
        ]

        all_subnets_with_public_ips = {
            subnet.get("SubnetId")
            for subnet in AWSApi.instance().ec2.describe_subnets(
                {subnet_id for queue in multi_nic_queues for subnet_id in queue.networking.subnet_ids}
            )
            if subnet.get("MapPublicIpOnLaunch")
        }

        for queue in multi_nic_queues:
            if queue.networking.assign_public_ip:
                self._add_failure(
                    f"The queue {queue.name} contains an instance type with multiple network interfaces however the "
                    f"AssignPublicIp value is set to true. AWS public IPs can only be assigned to instances launched "
                    f"with a single network interface.",
                    FailureLevel.ERROR,
                )

            queue_subnets_with_public_ips = sorted(
                [subnet_id for subnet_id in queue.networking.subnet_ids if subnet_id in all_subnets_with_public_ips]
            )
            if queue_subnets_with_public_ips:
                self._add_failure(
                    f"The queue {queue.name} contains an instance type with multiple network interfaces however the "
                    f"subnets {queue_subnets_with_public_ips} is configured to automatically assign public IPs. AWS "
                    f"public IPs can only be assigned to instances launched with a single network interface.",
                    FailureLevel.ERROR,
                )


class LoginNodesSchedulerValidator(Validator):
    """Verify that when using LoginNodes, the scheduler must be slurm."""

    def _validate(self, scheduler):
        if scheduler != "slurm":
            self._add_failure(
                "When using LoginNodes, the configured scheduler must be set to Slurm. "
                "Please set the scheduler to Slurm.",
                FailureLevel.ERROR,
            )
