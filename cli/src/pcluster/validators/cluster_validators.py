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
import boto3
from botocore.exceptions import ClientError

from pcluster.models.common import DynamicParam, FailureLevel, Param, Validator
from pcluster.utils import get_supported_architectures_for_instance_type, get_supported_os_for_architecture

EFA_UNSUPPORTED_ARCHITECTURES_OSES = {
    "x86_64": [],
    "arm64": ["centos8"],
}


class ComputeResourceValidator(Validator):
    """Slurm compute resource validator."""

    def _validate(self, min_count: Param, max_count: Param):
        """Validate min count and max count combinations."""
        if max_count.value < min_count.value:
            self._add_failure(
                "Max count must be greater than or equal to min count", FailureLevel.ERROR, [min_count, max_count]
            )


class FsxNetworkingValidator(Validator):
    """FSx and networking validator."""

    def _validate(self, file_system_id: Param, head_node_subnet_id: Param):
        """Validate FSx and networking config."""
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
                    FailureLevel.CRITICAL,
                    [file_system_id],
                )

            # If there is an existing mt in the az, need to check the inbound and outbound rules of the security groups
            network_interface_ids = file_system.get("NetworkInterfaceIds")
            if not network_interface_ids:
                self._add_failure(
                    "Unable to validate FSx security groups. The given FSx file system '{0}' doesn't have "
                    "Elastic Network Interfaces attached to it.".format(file_system_id.value),
                    FailureLevel.CRITICAL,
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
                        FailureLevel.CRITICAL,
                        [file_system_id],
                    )
        except ClientError as e:
            self._add_failure(e.response.get("Error").get("Message"), FailureLevel.CRITICAL)

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

    def _check_sg_rules_for_port(self, rule, port_to_check):
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


class SimultaneousMultithreadingArchitectureValidator(Validator):
    """Simultaneous Multithreading architecture validator."""

    def _validate(self, simultaneous_multithreading: Param, architecture: DynamicParam):
        """Validate Simultaneous Multithreading and architecture combination."""
        supported_architectures = ["x86_64"]
        if simultaneous_multithreading.value and architecture.value not in supported_architectures:
            self._add_failure(
                "Simultaneous Multithreading is only supported on instance types that support "
                "these architectures: {0}".format(", ".join(supported_architectures)),
                FailureLevel.ERROR,
                [simultaneous_multithreading]
            )


class EfaOsArchitectureValidator(Validator):
    """OS and architecture combination validator if EFA is enabled."""

    def _validate(self, efa_enabled: Param, os: Param, architecture: DynamicParam):
        """Check os and architecture combination whan efa is enabled."""
        if efa_enabled.value and os.value in EFA_UNSUPPORTED_ARCHITECTURES_OSES.get(architecture.value):
            self._add_failure(
                "EFA currently not supported on {0} for {1} architecture".format(os.value, architecture.value),
                FailureLevel.ERROR,
                [efa_enabled]
            )


class ArchitectureOsValidator(Validator):
    """Validate OS and architecture combination."""

    def _validate(self, os: Param, architecture: DynamicParam):
        """ARM AMIs are only available for  a subset of the supported OSes."""
        allowed_oses = get_supported_os_for_architecture(architecture.value)
        if os.value not in allowed_oses:
            self._add_failure(
                "The architecture {0} is only supported for the following operating systems: {1}".format(
                    architecture.value, allowed_oses
                ),
                FailureLevel.ERROR,
                [os],
            )


class InstanceArchitectureCompatibilityValidator(Validator):
    """Validate instance type and architecture combination."""

    def _validate(self, instance_type: Param, architecture: DynamicParam):
        """Verify that head node and compute instance types imply compatible architectures."""
        head_node_architecture = architecture.value
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
