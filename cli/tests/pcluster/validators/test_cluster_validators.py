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
import pytest
from assertpy import assert_that
from munch import DefaultMunch

from pcluster.aws.aws_resources import InstanceTypeInfo
from pcluster.config.cluster_config import PlacementGroup, Tag
from pcluster.constants import PCLUSTER_NAME_MAX_LENGTH
from pcluster.validators.cluster_validators import (
    FSX_MESSAGES,
    FSX_SUPPORTED_ARCHITECTURES_OSES,
    ArchitectureOsValidator,
    ClusterNameValidator,
    ComputeResourceSizeValidator,
    DcvValidator,
    DisableSimultaneousMultithreadingArchitectureValidator,
    DuplicateMountDirValidator,
    EfaOsArchitectureValidator,
    EfaPlacementGroupValidator,
    EfaSecurityGroupValidator,
    EfaValidator,
    ExistingFsxNetworkingValidator,
    FsxArchitectureOsValidator,
    HeadNodeImdsValidator,
    HostedZoneValidator,
    InstanceArchitectureCompatibilityValidator,
    IntelHpcArchitectureValidator,
    IntelHpcOsValidator,
    MaxCountValidator,
    MixedSecurityGroupOverwriteValidator,
    NameValidator,
    NumberOfStorageValidator,
    OverlappingMountDirValidator,
    RegionValidator,
    RootVolumeSizeValidator,
    SchedulableMemoryValidator,
    SchedulerOsValidator,
    SharedStorageMountDirValidator,
    SharedStorageNameValidator,
    _LaunchTemplateValidator,
)
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.validators.utils import assert_failure_messages
from tests.utils import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.aws.common.boto3"


@pytest.mark.parametrize(
    "cluster_name, should_trigger_error",
    [
        ("ThisClusterNameShouldBeRightSize-ContainAHyphen-AndANumber12", False),
        ("ThisClusterNameShouldBeJustOneCharacterTooLongAndShouldntBeOk", True),
        ("2AClusterCanNotBeginByANumber", True),
        ("ClusterCanNotContainUnderscores_LikeThis", True),
        ("ClusterCanNotContainSpaces LikeThis", True),
    ],
)
def test_cluster_name_validator(cluster_name, should_trigger_error):
    expected_message = (
        (
            "Error: The cluster name can contain only alphanumeric characters (case-sensitive) and hyphens. "
            "It must start with an alphabetic character and can't be longer "
            f"than {PCLUSTER_NAME_MAX_LENGTH} characters."
        )
        if should_trigger_error
        else None
    )
    actual_failures = ClusterNameValidator().execute(cluster_name)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "region, expected_message",
    [
        ("invalid-region", "Region 'invalid-region' is not yet officially supported "),
        ("us-east-1", None),
    ],
)
def test_region_validator(region, expected_message):
    actual_failures = RegionValidator().execute(region)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "os, scheduler, expected_message",
    [
        ("centos7", "slurm", None),
        ("ubuntu1804", "slurm", None),
        ("ubuntu2004", "slurm", None),
        ("alinux2", "slurm", None),
        ("centos7", "awsbatch", "scheduler supports the following operating systems"),
        ("ubuntu1804", "awsbatch", "scheduler supports the following operating systems"),
        ("ubuntu2004", "awsbatch", "scheduler supports the following operating systems"),
        ("alinux2", "awsbatch", None),
    ],
)
def test_scheduler_os_validator(os, scheduler, expected_message):
    actual_failures = SchedulerOsValidator().execute(os, scheduler)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "min_count, max_count, expected_message",
    [
        (1, 2, None),
        (1, 1, None),
        (2, 1, "Max count must be greater than or equal to min count"),
    ],
)
def test_compute_resource_size_validator(min_count, max_count, expected_message):
    actual_failures = ComputeResourceSizeValidator().execute(min_count, max_count)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "resource_name, resources_length, max_length, expected_message",
    [
        ("SlurmQueues", 5, 10, None),
        ("SchedulerQueues", 10, 10, None),
        ("ComputeResources", 4, 5, None),
        (
            "SlurmQueues",
            11,
            10,
            "Invalid number of SlurmQueues (11) specified. Currently only supports up to 10 SlurmQueues.",
        ),
        (
            "SchedulerQueues",
            12,
            10,
            "Invalid number of SchedulerQueues (12) specified. Currently only supports up to 10 SchedulerQueues.",
        ),
        (
            "ComputeResources",
            6,
            5,
            "Invalid number of ComputeResources (6) specified. Currently only supports up to 5 ComputeResources.",
        ),
    ],
)
def test_max_count_validator(resource_name, resources_length, max_length, expected_message):
    actual_failures = MaxCountValidator().execute(
        resource_name=resource_name, resources_length=resources_length, max_length=max_length
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "schedulable_memory, ec2memory, instance_type, expected_message",
    [
        (3500, 3600, "dummy_instance_type", None),
        (0, 3600, "dummy_instance_type", "SchedulableMemory must be at least 1 MiB."),
        (
            3700,
            None,
            "dummy_instance_type",
            "SchedulableMemory was set but EC2 memory is not available for selected "
            "instance type dummy_instance_type. Defaulting to 1 MiB.",
        ),
        (
            3700,
            3600,
            "dummy_instance_type",
            "SchedulableMemory cannot be larger than EC2 Memory for selected "
            "instance type dummy_instance_type (3600 MiB).",
        ),
        (
            3000,
            3600,
            "dummy_instance_type",
            "SchedulableMemory was set lower than 95% of EC2 Memory for selected "
            "instance type dummy_instance_type (3600 MiB).",
        ),
    ],
)
def test_schedulable_memory_validator(schedulable_memory, ec2memory, instance_type, expected_message):
    actual_failures = SchedulableMemoryValidator().execute(schedulable_memory, ec2memory, instance_type)
    assert_failure_messages(actual_failures, expected_message)


# ---------------- EFA validators ---------------- #


@pytest.mark.parametrize(
    "instance_type, efa_enabled, gdr_support, efa_supported, expected_message",
    [
        # EFAGDR without EFA
        ("c5n.18xlarge", False, True, True, "GDR Support can be used only if EFA is enabled"),
        # EFAGDR with EFA
        ("c5n.18xlarge", True, True, True, None),
        # EFA without EFAGDR
        ("c5n.18xlarge", True, False, True, None),
        # Unsupported instance type
        ("t2.large", True, False, False, "does not support EFA"),
        ("t2.large", False, False, False, None),
        # EFA not enabled for instance type that supports it
        ("c5n.18xlarge", False, False, True, "supports enhanced networking capabilities using Elastic Fabric Adapter"),
    ],
)
def test_efa_validator(mocker, boto3_stubber, instance_type, efa_enabled, gdr_support, efa_supported, expected_message):
    mock_aws_api(mocker)
    get_instance_type_info_mock = mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_instance_type_info",
        return_value=InstanceTypeInfo(
            {
                "InstanceType": instance_type,
                "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2},
                "NetworkInfo": {"EfaSupported": instance_type == "c5n.18xlarge"},
            }
        ),
    )

    actual_failures = EfaValidator().execute(instance_type, efa_enabled, gdr_support)
    assert_failure_messages(actual_failures, expected_message)
    if efa_enabled:
        get_instance_type_info_mock.assert_called_with(instance_type)


@pytest.mark.parametrize(
    "efa_enabled, placement_group, expected_message",
    [
        # Efa disabled
        (False, PlacementGroup(enabled=True, id="test"), None),
        (False, PlacementGroup(enabled=True), None),
        (False, PlacementGroup(id="test"), None),
        (False, PlacementGroup(enabled=False), None),
        (False, None, None),
        # Efa enabled
        (True, None, "placement group for EFA-enabled compute resources must be explicit"),
        (True, PlacementGroup(), "placement group for EFA-enabled compute resources must be explicit"),
        (True, PlacementGroup(enabled=True), None),
        (True, PlacementGroup(id="test"), None),
        (True, PlacementGroup(enabled=True, id="test"), None),
        (True, PlacementGroup(enabled=False), "may see better performance using a placement group for the queue"),
        (
            True,
            PlacementGroup(enabled=False, id="test"),
            "may see better performance using a placement group for the queue",
        ),
    ],
)
def test_efa_placement_group_validator(efa_enabled, placement_group, expected_message):
    actual_failures = EfaPlacementGroupValidator().execute(efa_enabled, placement_group)

    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "efa_enabled, security_groups, additional_security_groups, ip_permissions, ip_permissions_egress, expected_message",
    [
        # Efa disabled, no checks on security groups
        (False, [], [], [], [], None),
        # Efa enabled, if not specified SG will be created by the cluster
        (True, [], [], [], [], None),
        (True, [], ["sg-12345678"], [{"IpProtocol": "-1", "UserIdGroupPairs": []}], [], None),
        # Inbound rules only
        (
            True,
            ["sg-12345678"],
            [],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            [],
            "security group that allows all inbound and outbound",
        ),
        # right sg
        (
            True,
            ["sg-12345678"],
            [],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            None,
        ),
        # right sg. Test when UserIdGroupPairs contains more entries
        (
            True,
            ["sg-12345678"],
            [],
            [
                {
                    "IpProtocol": "-1",
                    "UserIdGroupPairs": [
                        {"UserId": "123456789012", "GroupId": "sg-23456789"},
                        {"UserId": "123456789012", "GroupId": "sg-12345678"},
                    ],
                }
            ],
            [
                {
                    "IpProtocol": "-1",
                    "UserIdGroupPairs": [
                        {"UserId": "123456789012", "GroupId": "sg-23456789"},
                        {"UserId": "123456789012", "GroupId": "sg-12345678"},
                    ],
                }
            ],
            None,
        ),
        # Multiple sec groups, one right
        (
            True,
            ["sg-23456789", "sg-12345678"],
            [],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            None,
        ),
        # Multiple sec groups, no one right
        (True, ["sg-23456789", "sg-34567890"], [], [], [], "security group that allows all inbound and outbound"),
        # Wrong rules
        (
            True,
            ["sg-12345678"],
            [],
            [
                {
                    "PrefixListIds": [],
                    "FromPort": 22,
                    "IpRanges": [{"CidrIp": "203.0.113.0/24"}],
                    "ToPort": 22,
                    "IpProtocol": "tcp",
                    "UserIdGroupPairs": [],
                }
            ],
            [],
            "security group that allows all inbound and outbound",
        ),
        # Right SG specified as additional sg
        (
            True,
            ["sg-23456789"],
            ["sg-12345678"],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            None,
        ),
    ],
)
def test_efa_security_group_validator(
    boto3_stubber,
    efa_enabled,
    security_groups,
    additional_security_groups,
    ip_permissions,
    ip_permissions_egress,
    expected_message,
):
    def _append_mocked_describe_sg_request(ip_perm, ip_perm_egress, sec_group):
        describe_security_groups_response = {
            "SecurityGroups": [
                {
                    "IpPermissionsEgress": ip_perm_egress,
                    "Description": "My security group",
                    "IpPermissions": ip_perm,
                    "GroupName": "MySecurityGroup",
                    "OwnerId": "123456789012",
                    "GroupId": sec_group,
                }
            ]
        }
        return MockedBoto3Request(
            method="describe_security_groups",
            response=describe_security_groups_response,
            expected_params={"GroupIds": [security_group]},
        )

    if efa_enabled:
        # Set SG different by sg-12345678 as incomplete. The only full valid SG can be the sg-12345678 one.
        perm = ip_permissions if "sg-12345678" else []
        perm_egress = ip_permissions_egress if "sg-12345678" else []

        mocked_requests = []
        if security_groups:
            for security_group in security_groups:
                mocked_requests.append(_append_mocked_describe_sg_request(perm, perm_egress, security_group))

            # We don't need to check additional sg only if security_group is not a custom one.
            if additional_security_groups:
                for security_group in additional_security_groups:
                    mocked_requests.append(_append_mocked_describe_sg_request(perm, perm_egress, security_group))

        boto3_stubber("ec2", mocked_requests)

    actual_failures = EfaSecurityGroupValidator().execute(efa_enabled, security_groups, additional_security_groups)
    assert_failure_messages(actual_failures, expected_message)


# ---------------- Architecture Validators ---------------- #


@pytest.mark.parametrize(
    "disable_simultaneous_multithreading, architecture, expected_message",
    [
        (True, "x86_64", None),
        (False, "x86_64", None),
        (
            True,
            "arm64",
            "Disabling simultaneous multithreading is only supported"
            " on instance types that support these architectures",
        ),
        (False, "arm64", None),
    ],
)
def test_disable_simultaneous_multithreading_architecture_validator(
    disable_simultaneous_multithreading, architecture, expected_message
):
    actual_failures = DisableSimultaneousMultithreadingArchitectureValidator().execute(
        disable_simultaneous_multithreading, architecture
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "efa_enabled, os, architecture, expected_message",
    [
        (True, "alinux2", "x86_64", None),
        (True, "alinux2", "arm64", None),
        (True, "ubuntu1804", "x86_64", None),
        (True, "ubuntu1804", "arm64", None),
        (True, "ubuntu2004", "x86_64", None),
        (True, "ubuntu2004", "arm64", None),
    ],
)
def test_efa_os_architecture_validator(efa_enabled, os, architecture, expected_message):
    actual_failures = EfaOsArchitectureValidator().execute(efa_enabled, os, architecture)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "os, architecture, custom_ami, ami_search_filters, expected_message",
    [
        # All OSes supported for x86_64
        ("alinux2", "x86_64", None, None, None),
        ("alinux2", "x86_64", "custom-ami", None, None),
        ("centos7", "x86_64", None, None, None),
        ("centos7", "x86_64", "custom-ami", None, None),
        ("ubuntu1804", "x86_64", None, None, None),
        ("ubuntu2004", "x86_64", None, None, None),
        # All OSes supported for x86_64
        ("alinux2", "arm64", None, None, None),
        ("alinux2", "arm64", "custom-ami", None, None),
        (
            "centos7",
            "arm64",
            None,
            None,
            "The aarch64 CentOS 7 OS is not validated for the 6th generation aarch64 instances",
        ),
        ("centos7", "arm64", None, {"ami_search_filters"}, None),
        ("centos7", "arm64", "custom-ami", None, None),
        ("ubuntu1804", "arm64", None, None, None),
        ("ubuntu2004", "arm64", None, None, None),
    ],
)
def test_architecture_os_validator(os, architecture, custom_ami, ami_search_filters, expected_message):
    """Verify that the correct set of OSes is supported for each supported architecture."""
    actual_failures = ArchitectureOsValidator().execute(os, architecture, custom_ami, ami_search_filters)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "head_node_architecture, compute_architecture, compute_instance_type, expected_message",
    [
        ("x86_64", "x86_64", "c5.xlarge", None),
        (
            "x86_64",
            "arm64",
            "m6g.xlarge",
            "none of which are compatible with the architecture supported by the head node instance type",
        ),
        (
            "arm64",
            "x86_64",
            "c5.xlarge",
            "none of which are compatible with the architecture supported by the head node instance type",
        ),
        ("arm64", "arm64", "m6g.xlarge", None),
    ],
)
def test_instance_architecture_compatibility_validator(
    mocker, head_node_architecture, compute_architecture, compute_instance_type, expected_message
):
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.get_supported_architectures", return_value=[compute_architecture])
    actual_failures = InstanceArchitectureCompatibilityValidator().execute(
        compute_instance_type, head_node_architecture
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "name, expected_message",
    [
        ("default", "forbidden"),
        ("1queue", "must begin with a letter"),
        ("queue_1", "only contain lowercase letters, digits and hyphens"),
        ("aQUEUEa", "only contain lowercase letters, digits and hyphens"),
        ("queue1!2", "only contain lowercase letters, digits and hyphens"),
        ("my-default-queue2", None),
        ("queue-123456789abcdefghijk", "can be at most 25 chars long"),
        ("queue-123456789abcdefghij", None),
    ],
)
def test_queue_name_validator(name, expected_message):
    actual_failures = NameValidator().execute(name)
    assert_failure_messages(actual_failures, expected_message)


# -------------- Storage validators -------------- #


@pytest.mark.parametrize(
    "fsx_file_system_type, fsx_vpc, ip_permissions, are_all_security_groups_customized, network_interfaces, "
    "expected_message",
    [
        (  # working case, right vpc and sg, multiple network interfaces
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            True,
            ["eni-09b9460295ddd4e5f", "eni-001b3cef7c78b45c4"],
            None,
        ),
        (  # working case, right vpc and sg, single network interface
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            True,
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # working case (LUSTRE) CIDR specified in the security group through ip ranges
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
            False,
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # working case (OPENZFS), CIDR specified in the security group through ip ranges
            "OPENZFS",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
            False,
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # working case (ONTAP), CIDR specified in the security group through ip ranges
            "ONTAP",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
            False,
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # working case, CIDR specified in the security group through prefix list
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "PrefixListIds": [{"PrefixListId": "pl-12345"}]}],
            False,
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # not working case, wrong security group. Lustre
            # Security group without CIDR cannot work with clusters containing pcluster created security group.
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            False,
            ["eni-09b9460295ddd4e5f"],
            "The current security group settings on file system .* does not satisfy mounting requirement. "
            "The file system must be associated to a security group that "
            r"allows inbound and outbound TCP traffic through ports \[988\].",
        ),
        (  # not working case, wrong security group. OpenZFS
            # Security group without CIDR cannot work with clusters containing pcluster created security group.
            "OPENZFS",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            False,
            ["eni-09b9460295ddd4e5f"],
            "The current security group settings on file system .* does not satisfy mounting requirement. "
            "The file system must be associated to a security group that "
            r"allows inbound and outbound TCP traffic through ports \[111, 2049, 20001, 20002, 20003\].",
        ),
        (  # not working case, wrong security group. Ontap
            # Security group without CIDR cannot work with clusters containing pcluster created security group.
            "ONTAP",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            False,
            ["eni-09b9460295ddd4e5f"],
            "The current security group settings on file system .* does not satisfy mounting requirement. "
            "The file system must be associated to a security group that "
            r"allows inbound and outbound TCP traffic through ports \[111, 635, 2049, 4046\].",
        ),
        (  # not working case --> no network interfaces
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            True,
            [],
            "doesn't have Elastic Network Interfaces attached",
        ),
        (  # not working case --> wrong vpc
            "LUSTRE",
            "vpc-06e4ab6c6ccWRONG",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            True,
            ["eni-09b9460295ddd4e5f"],
            "only support using FSx file system that is in the same VPC as the cluster",
        ),
        (  # not working case --> wrong ip permissions in security group
            "LUSTRE",
            "vpc-06e4ab6c6cWRONG",
            [
                {
                    "PrefixListIds": [],
                    "FromPort": 22,
                    "IpRanges": [{"CidrIp": "203.0.113.0/24"}],
                    "ToPort": 22,
                    "IpProtocol": "tcp",
                    "UserIdGroupPairs": [],
                }
            ],
            True,
            ["eni-09b9460295ddd4e5f"],
            [
                "only support using FSx file system that is in the same VPC as the cluster",
                "does not satisfy mounting requirement",
            ],
        ),
    ],
)
def test_fsx_network_validator(
    boto3_stubber,
    fsx_file_system_type,
    fsx_vpc,
    ip_permissions,
    are_all_security_groups_customized,
    network_interfaces,
    expected_message,
):
    describe_file_systems_response = {
        "FileSystems": [
            {
                "VpcId": fsx_vpc,
                "NetworkInterfaceIds": network_interfaces,
                "SubnetIds": ["subnet-12345678"],
                "FileSystemType": fsx_file_system_type,
                "CreationTime": 1567636453.038,
                "ResourceARN": "arn:aws:fsx:us-west-2:111122223333:file-system/fs-0ff8da96d57f3b4e3",
                "StorageCapacity": 3600,
                "FileSystemId": "fs-0ff8da96d57f3b4e3",
                "DNSName": "fs-0ff8da96d57f3b4e3.fsx.us-west-2.amazonaws.com",
                "OwnerId": "059623208481",
                "Lifecycle": "AVAILABLE",
            }
        ]
    }
    fsx_mocked_requests = [
        MockedBoto3Request(
            method="describe_file_systems",
            response=describe_file_systems_response,
            expected_params={"FileSystemIds": ["fs-0ff8da96d57f3b4e3"]},
        )
    ]
    boto3_stubber("fsx", fsx_mocked_requests)

    describe_subnets_response = {
        "Subnets": [
            {
                "AvailabilityZone": "us-east-2c",
                "AvailabilityZoneId": "use2-az3",
                "AvailableIpAddressCount": 248,
                "CidrBlock": "10.0.1.0/24",
                "DefaultForAz": False,
                "MapPublicIpOnLaunch": False,
                "State": "available",
                "SubnetId": "subnet-12345678",
                "VpcId": "vpc-06e4ab6c6cEXAMPLE",
                "OwnerId": "111122223333",
                "AssignIpv6AddressOnCreation": False,
                "Ipv6CidrBlockAssociationSet": [],
                "Tags": [{"Key": "Name", "Value": "MySubnet"}],
                "SubnetArn": "arn:aws:ec2:us-east-2:111122223333:subnet/subnet-12345678",
            }
        ]
    }
    ec2_mocked_requests = [
        MockedBoto3Request(
            method="describe_subnets",
            response=describe_subnets_response,
            expected_params={"SubnetIds": ["subnet-12345678"]},
        )
    ]

    if network_interfaces:
        network_interfaces_in_response = []
        for network_interface in network_interfaces:
            network_interfaces_in_response.append(
                {
                    "Association": {
                        "AllocationId": "eipalloc-01564b674a1a88a47",
                        "AssociationId": "eipassoc-02726ee370e175cea",
                        "IpOwnerId": "111122223333",
                        "PublicDnsName": "ec2-34-248-114-123.eu-west-1.compute.amazonaws.com",
                        "PublicIp": "34.248.114.123",
                    },
                    "Attachment": {
                        "AttachmentId": "ela-attach-0cf98331",
                        "DeleteOnTermination": False,
                        "DeviceIndex": 1,
                        "InstanceOwnerId": "amazon-aws",
                        "Status": "attached",
                    },
                    "AvailabilityZone": "eu-west-1a",
                    "Description": "Interface for NAT Gateway nat-0a8b0e0d28266841f",
                    "Groups": [{"GroupName": "default", "GroupId": "sg-12345678"}],
                    "InterfaceType": "nat_gateway",
                    "Ipv6Addresses": [],
                    "MacAddress": "0a:e5:8a:82:fd:24",
                    "NetworkInterfaceId": network_interface,
                    "OwnerId": "111122223333",
                    "PrivateDnsName": "ip-10-0-124-85.eu-west-1.compute.internal",
                    "PrivateIpAddress": "10.0.124.85",
                    "PrivateIpAddresses": [
                        {
                            "Association": {
                                "AllocationId": "eipalloc-01564b674a1a88a47",
                                "AssociationId": "eipassoc-02726ee370e175cea",
                                "IpOwnerId": "111122223333",
                                "PublicDnsName": "ec2-34-248-114-123.eu-west-1.compute.amazonaws.com",
                                "PublicIp": "34.248.114.123",
                            },
                            "Primary": True,
                            "PrivateDnsName": "ip-10-0-124-85.eu-west-1.compute.internal",
                            "PrivateIpAddress": "10.0.124.85",
                        }
                    ],
                    "RequesterId": "036872051663",
                    "RequesterManaged": True,
                    "SourceDestCheck": False,
                    "Status": "in-use",
                    "SubnetId": "subnet-12345678",
                    "TagSet": [],
                    "VpcId": fsx_vpc,
                }
            )
        describe_network_interfaces_response = {"NetworkInterfaces": network_interfaces_in_response}
        ec2_mocked_requests.append(
            MockedBoto3Request(
                method="describe_network_interfaces",
                response=describe_network_interfaces_response,
                expected_params={"NetworkInterfaceIds": network_interfaces},
            )
        )

        if fsx_vpc == "vpc-06e4ab6c6cEXAMPLE":
            # the describe security group is performed only if the VPC of the network interface is the same of the FSX
            describe_security_groups_response = {
                "SecurityGroups": [
                    {
                        "IpPermissionsEgress": ip_permissions,
                        "Description": "My security group",
                        "IpPermissions": ip_permissions,
                        "GroupName": "MySecurityGroup",
                        "OwnerId": "123456789012",
                        "GroupId": "sg-12345678",
                    }
                ]
            }
            ec2_mocked_requests.append(
                MockedBoto3Request(
                    method="describe_security_groups",
                    response=describe_security_groups_response,
                    expected_params={"GroupIds": ["sg-12345678"]},
                )
            )

    boto3_stubber("ec2", ec2_mocked_requests)

    actual_failures = ExistingFsxNetworkingValidator().execute(
        ["fs-0ff8da96d57f3b4e3"], "subnet-12345678", are_all_security_groups_customized
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "architecture, os, expected_message",
    [
        # Supported combinations
        ("x86_64", "alinux2", None),
        ("x86_64", "centos7", None),
        ("x86_64", "ubuntu1804", None),
        ("x86_64", "ubuntu2004", None),
        ("arm64", "ubuntu1804", None),
        ("arm64", "ubuntu2004", None),
        ("arm64", "alinux2", None),
        # Unsupported combinations
        (
            "UnsupportedArchitecture",
            "alinux2",
            FSX_MESSAGES["errors"]["unsupported_architecture"].format(
                supported_architectures=list(FSX_SUPPORTED_ARCHITECTURES_OSES.keys())
            ),
        ),
    ],
)
def test_fsx_architecture_os_validator(architecture, os, expected_message):
    actual_failures = FsxArchitectureOsValidator().execute(architecture, os)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "shared_mount_dir_list, local_mount_dir_list, expected_message",
    [
        (
            ["dir1"],
            [],
            None,
        ),
        (
            ["dir1", "dir2"],
            [],
            None,
        ),
        (
            ["dir1", "dir2", "dir3"],
            [],
            None,
        ),
        (
            ["dir1", "dir1", "dir2"],
            [],
            "Mount directory dir1 cannot be specified for multiple file systems",
        ),
        (
            ["dir1", "dir2", "dir3", "dir2", "dir1"],
            [],
            "Mount directories dir2, dir1 cannot be specified for multiple file systems",
        ),
        (
            ["dir1", "dir2", "/scratch"],
            [],
            None,
        ),
        (
            ["dir1", "dir2", "/scratch"],
            ["/scratch"],
            "Ephemeral drive mount directory `/scratch` is overwritten by shared storage mount directory. "
            "Please consider changing either directory to avoid the overwrite.",
        ),
    ],
)
def test_duplicate_mount_dir_validator(shared_mount_dir_list, local_mount_dir_list, expected_message):
    actual_failures = DuplicateMountDirValidator().execute(shared_mount_dir_list, local_mount_dir_list)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "shared_mount_dir_list, local_mount_dir_list, expected_message",
    [
        (
            ["dir1"],
            [],
            None,
        ),
        (
            ["dir1", "dir2"],
            ["/scratch"],
            None,
        ),
        (
            ["dir1", "dir2", "dir3"],
            ["/scratch", "/scratch/compute"],  # local mount dirs on different nodes can overlap.
            None,
        ),
        (
            ["dir1", "dir1/subdir", "dir2"],
            [],
            "Mount directories dir1, dir1/subdir cannot overlap",
        ),
        (
            ["dir1", "dir1/subdir", "dir2", "dir2/subdir", "dir3"],
            [],
            "Mount directories dir1, dir1/subdir, dir2, dir2/subdir cannot overlap",
        ),
        (
            ["dir1", "dir2", "dir3"],
            ["dir1/subdir", "dir2/subdir"],
            "Mount directories dir1, dir1/subdir, dir2, dir2/subdir cannot overlap",
        ),
        (
            ["dir", "dir1"],
            [],
            None,
        ),
    ],
)
def test_overlapping_mount_dir_validator(shared_mount_dir_list, local_mount_dir_list, expected_message):
    actual_failures = OverlappingMountDirValidator().execute(shared_mount_dir_list, local_mount_dir_list)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "storage_type, max_number, storage_count, expected_message",
    [
        ("fsx", 1, 0, None),
        ("efs", 1, 1, None),
        ("ebs", 5, 6, "Invalid number of shared storage of ebs type specified. Currently only supports upto 5"),
    ],
)
def test_number_of_storage_validator(storage_type, max_number, storage_count, expected_message):
    actual_failures = NumberOfStorageValidator().execute(storage_type, max_number, storage_count)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "name, expected_message",
    [
        ("default", "It is forbidden"),
        ("shared-ebs_1", None),
        ("1aFsxa", None),
        ("efs!2", "Allowed characters are letters, numbers and white spaces"),
        ("my-default-ebs", None),
        ("myefs-123456789abcdefghijklmnop", "can be at most 30 chars long"),
        ("myfsx-123456789abcdefghijklmno", None),
    ],
)
def test_shared_storage_name_validator(name, expected_message):
    actual_failures = SharedStorageNameValidator().execute(name)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "mount_dir, expected_message",
    [
        ("default", None),
        ("shared_ebs_1", None),
        ("shared", None),
        ("/shared", None),
        ("home", "mount directory .* is reserved"),
    ],
)
def test_shared_storage_mount_dir_validator(mount_dir, expected_message):
    actual_failures = SharedStorageMountDirValidator().execute(mount_dir)
    assert_failure_messages(actual_failures, expected_message)


# -------------- Third party software validators -------------- #


@pytest.mark.parametrize(
    "dcv_enabled, os, instance_type, allowed_ips, port, expected_message",
    [
        (True, "centos7", "t2.medium", None, None, None),
        (True, "ubuntu1804", "t2.medium", None, None, None),
        (True, "ubuntu1804", "t2.medium", None, "1.2.3.4/32", None),
        (True, "ubuntu2004", "t2.medium", None, None, None),
        (True, "centos7", "t2.medium", "0.0.0.0/0", 8443, "port 8443 to the world"),
        (True, "alinux2", "t2.medium", None, None, None),
        (True, "alinux2", "t2.nano", None, None, "is recommended to use an instance type with at least"),
        (True, "alinux2", "t2.micro", None, None, "is recommended to use an instance type with at least"),
        (False, "alinux2", "t2.micro", None, None, None),  # doesn't fail because DCV is disabled
        (True, "ubuntu1804", "m6g.xlarge", None, None, None),
        (True, "alinux2", "m6g.xlarge", None, None, None),
        (True, "ubuntu2004", "m6g.xlarge", None, None, "Please double check the os configuration"),
    ],
)
def test_dcv_validator(dcv_enabled, os, instance_type, allowed_ips, port, expected_message):
    actual_failures = DcvValidator().execute(
        instance_type,
        dcv_enabled,
        allowed_ips,
        port,
        os,
        "x86_64" if instance_type.startswith("t2") else "arm64",
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "architecture, expected_message",
    [
        ("x86_64", []),
        ("arm64", ["instance types and an AMI that support these architectures"]),
        # TODO migrate the parametrizations below to unit test for the whole model
        # (False, "x86_64", []),
        # (False, "arm64", []),
    ],
)
def test_intel_hpc_architecture_validator(architecture, expected_message):
    actual_failures = IntelHpcArchitectureValidator().execute(architecture)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "os, expected_message",
    [
        ("centos7", None),
        ("alinux2", "the operating system is required to be set"),
        ("ubuntu1804", "the operating system is required to be set"),
        ("ubuntu2004", "the operating system is required to be set"),
        # TODO migrate the parametrization below to unit test for the whole model
        # intel hpc disabled, you can use any os
        # ({"enable_intel_hpc_platform": "false", "base_os": "alinux"}, None),
    ],
)
def test_intel_hpc_os_validator(os, expected_message):
    actual_failures = IntelHpcOsValidator().execute(os)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "imds_secured, scheduler, expected_message",
    [
        (None, "slurm", "Cannot validate IMDS configuration if IMDS Secured is not set."),
        (True, "slurm", None),
        (False, "slurm", None),
        (None, "awsbatch", "Cannot validate IMDS configuration if IMDS Secured is not set."),
        (False, "awsbatch", None),
        (
            True,
            "awsbatch",
            "IMDS Secured cannot be enabled when using scheduler awsbatch. Please, disable IMDS Secured.",
        ),
        (None, None, "Cannot validate IMDS configuration if scheduler is not set."),
        (True, None, "Cannot validate IMDS configuration if scheduler is not set."),
        (False, None, "Cannot validate IMDS configuration if scheduler is not set."),
    ],
)
def test_head_node_imds_validator(imds_secured, scheduler, expected_message):
    actual_failures = HeadNodeImdsValidator().execute(imds_secured=imds_secured, scheduler=scheduler)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "vpcs, is_private_zone, domain_name, expected_message",
    [
        (
            None,
            False,
            "domain.com",
            "Hosted zone 12345Z cannot be used",
        ),
        (
            [{"VPCRegion": "us-east-1", "VPCId": "vpc-123"}, {"VPCRegion": "us-east-1", "VPCId": "vpc-456"}],
            True,
            "domain.com",
            None,
        ),
        (
            [{"VPCRegion": "us-east-1", "VPCId": "vpc-456"}],
            True,
            "domain.com",
            "Private Route53 hosted zone 12345Z need to be associated with the VPC of the cluster",
        ),
        (
            [{"VPCRegion": "us-east-1", "VPCId": "vpc-123"}, {"VPCRegion": "us-east-1", "VPCId": "vpc-456"}],
            True,
            "a_long_name_together_with_stackname_longer_than_190_"
            "characters_0123456789_0123456789_0123456789_0123456789_"
            "0123456789_0123456789_0123456789_0123456789_0123456789_"
            "0123456789.com",
            "Error: When specifying HostedZoneId, ",
        ),
    ],
    ids=[
        "Public hosted zone",
        "Private hosted zone associated with cluster VPC",
        "Private hosted zone not associated with cluster VPC",
        "Hosted zone name and cluster name exceeds lengths",
    ],
)
def test_hosted_zone_validator(mocker, vpcs, is_private_zone, domain_name, expected_message):
    get_hosted_zone_info = {
        "HostedZone": {"Name": domain_name, "Config": {"PrivateZone": is_private_zone}},
        "VPCs": vpcs,
    }
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.route53.Route53Client.get_hosted_zone", return_value=get_hosted_zone_info)
    actual_failures = HostedZoneValidator().execute(
        hosted_zone_id="12345Z",
        cluster_vpc="vpc-123",
        cluster_name="ThisClusterNameShouldBeRightSize-ContainAHyphen-AndANumber12",
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "input_tags",
    [
        [],
        [{"key": "SomeKey", "value": "SomeValue"}],
    ],
)
def test_generate_tag_specifications(input_tags):
    """Verify function to generate tag specifications for dry runs of RunInstances works as expected."""
    input_tags = [Tag(tag.get("key"), tag.get("value")) for tag in input_tags]
    if input_tags:
        expected_output_tags = [
            {"ResourceType": "instance", "Tags": [{"Key": tag.key, "Value": tag.value} for tag in input_tags]}
        ]
    else:
        expected_output_tags = []
    assert_that(_LaunchTemplateValidator._generate_tag_specifications(input_tags)).is_equal_to(expected_output_tags)


@pytest.mark.parametrize(
    "head_node_security_groups, queues, expect_warning",
    [
        [None, [{"networking": {"security_groups": None}}, {"networking": {"security_groups": None}}], False],
        [None, [{"networking": {"security_groups": "sg-123456"}}, {"networking": {"security_groups": None}}], True],
        [
            None,
            [{"networking": {"security_groups": "sg-123456"}}, {"networking": {"security_groups": "sg-123456"}}],
            True,
        ],
        ["sg-123456", [{"networking": {"security_groups": None}}, {"networking": {"security_groups": None}}], True],
        [
            "sg-123456",
            [{"networking": {"security_groups": "sg-123456"}}, {"networking": {"security_groups": None}}],
            True,
        ],
        [
            "sg-123456",
            [{"networking": {"security_groups": "sg-123456"}}, {"networking": {"security_groups": "sg-123456"}}],
            False,
        ],
    ],
)
def test_mixed_security_group_overwrite_validator(head_node_security_groups, queues, expect_warning):
    """Verify validator for mixed security group."""
    queues = DefaultMunch.fromDict(queues)
    actual_failures = MixedSecurityGroupOverwriteValidator().execute(
        head_node_security_groups=head_node_security_groups,
        queues=queues,
    )
    expected_message = "make sure.*cluster nodes are reachable" if expect_warning else None
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "root_volume_size, ami_size, expected_message",
    [
        (65, 50, None),
        (
            25,
            50,
            "Root volume size 25 GiB must be equal or greater than .* 50 GiB.",
        ),
    ],
)
def test_root_volume_size_validator(mocker, root_volume_size, ami_size, expected_message):
    mock_aws_api(mocker)
    actual_failures = RootVolumeSizeValidator().execute(root_volume_size, ami_size)
    assert_failure_messages(actual_failures, expected_message)
