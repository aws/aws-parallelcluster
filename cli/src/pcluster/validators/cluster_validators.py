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
from typing import List

import boto3
from botocore.exceptions import ClientError

from pcluster.constants import CIDR_ALL_IPS
from pcluster.dcv.utils import get_supported_dcv_os
from pcluster.models.common import FailureLevel, Param, Validator
from pcluster.utils import get_supported_architectures_for_instance_type, get_supported_os_for_architecture

EFA_UNSUPPORTED_ARCHITECTURES_OSES = {
    "x86_64": [],
    "arm64": ["centos8"],
}


class ComputeResourceSizeValidator(Validator):
    """
    Slurm compute resource size validator.

    Validate min count and max count combinations.
    """

    def _validate(self, min_count: Param, max_count: Param):
        if max_count.value < min_count.value:
            self._add_failure(
                "Max count must be greater than or equal to min count", FailureLevel.ERROR, [min_count, max_count]
            )


class SimultaneousMultithreadingArchitectureValidator(Validator):
    """
    Simultaneous Multithreading architecture validator.

    Validate Simultaneous Multithreading and architecture combination.
    """

    def _validate(self, simultaneous_multithreading: Param, architecture: str):
        supported_architectures = ["x86_64"]
        if simultaneous_multithreading.value and architecture not in supported_architectures:
            self._add_failure(
                "Simultaneous Multithreading is only supported on instance types that support "
                "these architectures: {0}".format(", ".join(supported_architectures)),
                FailureLevel.ERROR,
                [simultaneous_multithreading],
            )


class EfaOsArchitectureValidator(Validator):
    """OS and architecture combination validator if EFA is enabled."""

    def _validate(self, efa_enabled: Param, os: Param, architecture: str):
        if efa_enabled.value and os.value in EFA_UNSUPPORTED_ARCHITECTURES_OSES.get(architecture):
            self._add_failure(
                "EFA currently not supported on {0} for {1} architecture".format(os.value, architecture),
                FailureLevel.ERROR,
                [efa_enabled],
            )


class ArchitectureOsValidator(Validator):
    """
    Validate OS and architecture combination.

    ARM AMIs are only available for a subset of the supported OSes.
    """

    def _validate(self, os: Param, architecture: str):
        allowed_oses = get_supported_os_for_architecture(architecture)
        if os.value not in allowed_oses:
            self._add_failure(
                "The architecture {0} is only supported for the following operating systems: {1}".format(
                    architecture, allowed_oses
                ),
                FailureLevel.ERROR,
                [os],
            )


class InstanceArchitectureCompatibilityValidator(Validator):
    """
    Validate instance type and architecture combination.

    Verify that head node and compute instance types imply compatible architectures.
    """

    def _validate(self, instance_type: Param, architecture: str):
        head_node_architecture = architecture
        compute_architectures = get_supported_architectures_for_instance_type(instance_type.value)
        if head_node_architecture not in compute_architectures:
            self._add_failure(
                "The specified compute instance type ({0}) supports the architectures {1}, none of which are "
                "compatible with the architecture supported by the head node instance type ({2}).".format(
                    instance_type.value, compute_architectures, head_node_architecture
                ),
                FailureLevel.ERROR,
                [instance_type],
            )


# --------------- Storage validators --------------- #


class FsxNetworkingValidator(Validator):
    """
    FSx networking validator.

    Validate file system mount point according to the head node subnet.
    """

    def _validate(self, file_system_id: Param, head_node_subnet_id: Param):
        try:
            ec2 = boto3.client("ec2")

            # Check to see if there is any existing mt on the fs
            file_system = (
                boto3.client("fsx").describe_file_systems(FileSystemIds=[file_system_id.value]).get("FileSystems")[0]
            )

            vpc_id = ec2.describe_subnets(SubnetIds=[head_node_subnet_id.value]).get("Subnets")[0].get("VpcId")

            # Check to see if fs is in the same VPC as the stack
            if file_system.get("VpcId") != vpc_id:
                self._add_failure(
                    "Currently only support using FSx file system that is in the same VPC as the stack. "
                    "The file system provided is in {0}".format(file_system.get("VpcId")),
                    FailureLevel.ERROR,
                    [file_system_id],
                )

            # If there is an existing mt in the az, need to check the inbound and outbound rules of the security groups
            network_interface_ids = file_system.get("NetworkInterfaceIds")
            if not network_interface_ids:
                self._add_failure(
                    "Unable to validate FSx security groups. The given FSx file system '{0}' doesn't have "
                    "Elastic Network Interfaces attached to it.".format(file_system_id.value),
                    FailureLevel.ERROR,
                    [file_system_id],
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
                    if self._check_in_out_access(sg_ids, port=988):
                        fs_access = True
                        break
                if not fs_access:
                    self._add_failure(
                        "The current security group settings on file system '{0}' does not satisfy mounting requirement"
                        ". The file system must be associated to a security group that allows inbound and outbound "
                        "TCP traffic through port 988.".format(file_system_id.value),
                        FailureLevel.ERROR,
                        [file_system_id],
                    )
        except ClientError as e:
            self._add_failure(e.response.get("Error").get("Message"), FailureLevel.ERROR)

    def _check_in_out_access(self, security_groups_ids, port):
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

        for sec_group in (
            boto3.client("ec2").describe_security_groups(GroupIds=security_groups_ids).get("SecurityGroups")
        ):

            # Check all inbound rules
            for rule in sec_group.get("IpPermissions"):
                if self._check_sg_rules_for_port(rule, port):
                    in_access = True
                    break

            # Check all outbound rules
            for rule in sec_group.get("IpPermissionsEgress"):
                if self._check_sg_rules_for_port(rule, port):
                    out_access = True
                    break

            if in_access and out_access:
                in_out_access = True
                break

        return in_out_access

    @staticmethod
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


class DuplicateMountDirValidator(Validator):
    """
    Mount dir validator.

    Verify if there are duplicated mount dirs between shared storage and ephemeral volumes.
    """

    def _validate(self, mount_dir_list: List[Param]):
        mount_dirs_set = set()
        duplicated_mount_dirs = []

        for param in mount_dir_list:
            if param.value in mount_dirs_set:
                duplicated_mount_dirs.append(param)
            else:
                mount_dirs_set.add(param.value)

        if len(mount_dir_list) != len(mount_dirs_set):
            self._add_failure(
                "Mount {0} {1} cannot be specified for multiple volumes".format(
                    "directories" if len(duplicated_mount_dirs) > 1 else "directory",
                    ", ".join(mount_dir.value for mount_dir in duplicated_mount_dirs),
                ),
                FailureLevel.ERROR,
                duplicated_mount_dirs,
            )


class NumberOfStorageValidator(Validator):
    """
    Number of storage validator.

    Validate the number of storage specified is lower than maximum supported.
    """

    def _validate(self, storage_type, max_number, storage_count):
        if storage_count > max_number:
            self._add_failure(
                "Invalid number of shared storage of {0} type specified. "
                "Currently only supports upto {1}".format(storage_type, max_number),
                FailureLevel.ERROR,
            )


# --------------- Third party software validators --------------- #


class DcvValidator(Validator):
    """
    DCV parameters validators.

    Validate instance type, architecture and os when DCV is enabled.
    """

    def _validate(
        self,
        instance_type: Param,
        dcv_enabled: Param,
        allowed_ips: Param,
        port: Param,
        os: Param,
        architecture: str,
    ):
        if dcv_enabled.value:
            allowed_oses = get_supported_dcv_os(architecture)
            if os.value not in allowed_oses:
                self._add_failure(
                    "NICE DCV can be used with one of the following operating systems: {0}. "
                    "Please double check the Os configuration parameter".format(allowed_oses),
                    FailureLevel.ERROR,
                    [dcv_enabled],
                )

            if re.search(r"(micro)|(nano)", instance_type.value):
                self._add_failure(
                    "The packages required for desktop virtualization in the selected instance type '{0}' "
                    "may cause instability of the instance. If you want to use NICE DCV it is recommended "
                    "to use an instance type with at least 1.7 GB of memory.".format(instance_type.value),
                    FailureLevel.WARNING,
                )

            if allowed_ips.value == CIDR_ALL_IPS:
                self._add_failure(
                    f"With this configuration you are opening DCV port {port.value} to the world (0.0.0.0/0). "
                    "It is recommended to restrict access.",
                    FailureLevel.WARNING,
                )
