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
import os

import pytest
from assertpy import assert_that
from munch import DefaultMunch

from pcluster.aws.aws_resources import InstanceTypeInfo
from pcluster.aws.common import AWSClientError
from pcluster.config.cluster_config import (
    AwsBatchScheduling,
    BaseQueue,
    CapacityReservationTarget,
    Database,
    RootVolume,
    SharedEbs,
    SlurmComputeResource,
    SlurmQueue,
    SlurmQueueNetworking,
    SlurmScheduling,
    SlurmSettings,
    Tag,
)
from pcluster.constants import PCLUSTER_NAME_MAX_LENGTH, PCLUSTER_NAME_MAX_LENGTH_SLURM_ACCOUNTING
from pcluster.validators.cluster_validators import (
    FSX_MESSAGES,
    FSX_SUPPORTED_ARCHITECTURES_OSES,
    ArchitectureOsValidator,
    ClusterNameValidator,
    ComputeResourceSizeValidator,
    DcvValidator,
    DeletionPolicyValidator,
    DictLaunchTemplateBuilder,
    DuplicateMountDirValidator,
    EfaMultiAzValidator,
    EfaOsArchitectureValidator,
    EfaPlacementGroupValidator,
    EfaSecurityGroupValidator,
    EfaValidator,
    EfsIdValidator,
    ExistingFsxNetworkingValidator,
    FsxArchitectureOsValidator,
    HeadNodeImdsValidator,
    HostedZoneValidator,
    InstanceArchitectureCompatibilityValidator,
    IntelHpcArchitectureValidator,
    IntelHpcOsValidator,
    ManagedFsxMultiAzValidator,
    MaxCountValidator,
    MixedSecurityGroupOverwriteValidator,
    MultiNetworkInterfacesInstancesValidator,
    NameValidator,
    NumberOfStorageValidator,
    OverlappingMountDirValidator,
    RegionValidator,
    RootVolumeEncryptionConsistencyValidator,
    RootVolumeSizeValidator,
    SchedulableMemoryValidator,
    SchedulerOsValidator,
    SharedStorageMountDirValidator,
    SharedStorageNameValidator,
    UnmanagedFsxMultiAzValidator,
    _are_subnets_covered_by_cidrs,
    _LaunchTemplateValidator,
)
from pcluster.validators.common import FailureLevel
from pcluster.validators.ebs_validators import (
    MultiAzEbsVolumeValidator,
    MultiAzRootVolumeValidator,
    SharedEbsVolumeIdValidator,
)
from pcluster.validators.slurm_settings_validator import (
    SLURM_SETTINGS_DENY_LIST,
    CustomSlurmNodeNamesValidator,
    CustomSlurmSettingLevel,
    CustomSlurmSettingsIncludeFileOnlyValidator,
    CustomSlurmSettingsValidator,
    SlurmNodePrioritiesWarningValidator,
)
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.validators.utils import assert_failure_level, assert_failure_messages
from tests.utils import MockedBoto3Request


@pytest.fixture
def get_region(mocker):
    mocker.patch("pcluster.config.cluster_config.get_region", return_value="WHATEVER_REGION")


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.aws.common.boto3"


@pytest.mark.parametrize(
    "cluster_name, scheduling, should_trigger_error",
    [
        ("ThisClusterNameShouldBeRightSize-ContainAHyphen-AndANumber12", SlurmScheduling(queues=None), False),
        ("ThisClusterNameShouldBeJustOneCharacterTooLongAndShouldntBeOk", SlurmScheduling(queues=None), True),
        ("2AClusterCanNotBeginByANumber", SlurmScheduling(queues=None), True),
        ("ClusterCanNotContainUnderscores_LikeThis", SlurmScheduling(queues=None), True),
        ("ClusterCanNotContainSpaces LikeThis", SlurmScheduling(queues=None), True),
        ("ThisClusterNameShouldBeRightSize-ContainAHyphen-AndANumber12", AwsBatchScheduling(queues=None), False),
        ("ThisClusterNameShouldBeJustOneCharacterTooLongAndShouldntBeOk", AwsBatchScheduling(queues=None), True),
        ("2AClusterCanNotBeginByANumber", AwsBatchScheduling(queues=None), True),
        ("ClusterCanNotContainUnderscores_LikeThis", AwsBatchScheduling(queues=None), True),
        ("ClusterCanNotContainSpaces LikeThis", AwsBatchScheduling(queues=None), True),
    ],
)
def test_cluster_name_validator(cluster_name, scheduling, should_trigger_error):
    expected_message = (
        (
            "Error: The cluster name can contain only alphanumeric characters (case-sensitive) and hyphens. "
            "It must start with an alphabetic character and can't be longer "
            f"than {PCLUSTER_NAME_MAX_LENGTH} characters."
        )
        if should_trigger_error
        else None
    )
    actual_failures = ClusterNameValidator().execute(cluster_name, scheduling)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "cluster_name, scheduling, should_trigger_error",
    [
        (
            "ClusterNameWith40------------------Chars",
            SlurmScheduling(
                queues=None,
                settings=SlurmSettings(
                    database=Database(
                        uri="database.uri.com",
                        user_name="database_admin",
                        password_secret_arn="aws_secret_arn",
                    ),
                ),
            ),
            False,
        ),
        (
            "ClusterNameWith41-------------------Chars",
            SlurmScheduling(
                queues=None,
                settings=SlurmSettings(
                    database=Database(
                        uri="database_uri",
                        user_name="database_admin",
                        password_secret_arn="aws_secret_arn",
                    ),
                ),
            ),
            True,
        ),
        (
            "ClusterNameWith40------------------Chars",
            SlurmScheduling(
                queues=None,
                settings=SlurmSettings(
                    database=None,
                ),
            ),
            False,
        ),
        (
            "ClusterNameWith41-------------------Chars",
            SlurmScheduling(
                queues=None,
                settings=SlurmSettings(
                    settings=SlurmSettings(
                        database=None,
                    ),
                ),
            ),
            False,
        ),
    ],
)
def test_cluster_name_validator_slurm_accounting(cluster_name, scheduling, should_trigger_error):
    expected_message = (
        (
            "Error: The cluster name can contain only alphanumeric characters (case-sensitive) and hyphens. "
            "It must start with an alphabetic character and when using Slurm accounting it can't be longer "
            f"than {PCLUSTER_NAME_MAX_LENGTH_SLURM_ACCOUNTING} characters."
        )
        if should_trigger_error
        else None
    )
    actual_failures = ClusterNameValidator().execute(cluster_name, scheduling)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "description, custom_settings, deny_list, settings_level, expected_message",
    [
        (
            "No error when custom settings are not in the deny_list",
            [{"Allowed1": "Value1"}, {"Allowed2": "Value2"}],
            SLURM_SETTINGS_DENY_LIST["SlurmConf"],  # keep the deny-list lowercase
            CustomSlurmSettingLevel.SLURM_CONF,
            "",
        ),
        (
            "Fails when custom settings at SlurmConf level are in the deny_list, invalid parameters are reported",
            [{"SlurmctldParameters": "SubPar1,Subpar2=1"}, {"CommunicationParameters": "SubPar1"}],
            SLURM_SETTINGS_DENY_LIST["SlurmConf"]["Global"],  # keep the deny-list lowercase
            CustomSlurmSettingLevel.SLURM_CONF,
            "Using the following custom Slurm settings at SlurmConf level is not allowed: "
            "CommunicationParameters,SlurmctldParameters",
        ),
        (
            "When defining custom partitions or nodelists with parameters that exist also at global level and are"
            "deny-listed there (e.g. SuspendTime), the validation should not fail",
            [{"PartitionName": "external", "Nodes": "external-nodes-[1-10]", "State": "UP", "SuspendTime": "INFINITE"}],
            SLURM_SETTINGS_DENY_LIST["SlurmConf"]["Global"],  # keep the deny-list lowercase
            CustomSlurmSettingLevel.SLURM_CONF,
            "",
        ),
        (
            "No error when custom settings are not in the deny_list",
            [{"Allowed1": "Value1", "Allowed2": "Value2"}],
            ["denied1", "denied2"],  # keep the deny-list lowercase
            CustomSlurmSettingLevel.QUEUE,
            "",
        ),
        (
            "Fails when custom settings are in the deny_list, invalid parameters are reported",
            [{"Denied1": "Value1", "Denied2": "Value2"}],
            ["denied1", "denied2"],
            CustomSlurmSettingLevel.QUEUE,
            "Using the following custom Slurm settings at Queue level is not allowed: Denied1,Denied2",
        ),
        (
            "No error when custom settings are not in the deny_list",
            [{"Allowed1": "Value1", "Allowed2": "Value2"}],
            ["denied1", "denied2"],
            CustomSlurmSettingLevel.COMPUTE_RESOURCE,
            "",
        ),
        (
            "Fails when custom settings are in the deny_list, invalid parameters are reported",
            [{"Denied1": "Value1", "Denied2": "Value2"}],
            ["denied1", "denied2"],
            CustomSlurmSettingLevel.COMPUTE_RESOURCE,
            "Using the following custom Slurm settings at ComputeResource level is not allowed: Denied1,Denied2",
        ),
        (
            "Case doesn't affect the result and duplicates are avoided, but only the first occurrence is reported",
            [{"Denied1": "Value1", "Denied2": "Value2", "dEnIeD1": "Value1", "deNIeD2": "Value2"}],
            ["denied1", "denied2"],
            CustomSlurmSettingLevel.COMPUTE_RESOURCE,
            "Using the following custom Slurm settings at ComputeResource level is not allowed: Denied1,Denied2",
        ),
    ],
)
def test_custom_slurm_settings_validator(description, custom_settings, deny_list, settings_level, expected_message):
    actual_failures = CustomSlurmSettingsValidator().execute(custom_settings, deny_list, settings_level)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "custom_slurm_settings, expected_message",
    [
        # Generic case without custom Slurm nodes
        ([{"Param1": "Value1"}, {"Param2": "Value2"}], ""),
        # Generic case with custom Slurm nodes
        ([{"NodeName": "test-node[1-100]", "CPUs": "16"}], ""),
        # Generic case with custom Slurm nodes with bad name
        (
            [{"NodeName": "test-st-node[1-100]", "CPUs": "16"}],
            "Substrings '-st-' and '-dy-' in node names are reserved for nodes managed by ParallelCluster. "
            "Please rename the following custom Slurm nodes: test-st-node[1-100]",
        ),
        # Generic case with custom Slurm nodes with bad name
        (
            [{"NodeName": "test-dy-node[1-100]", "CPUs": "16"}],
            "Substrings '-st-' and '-dy-' in node names are reserved for nodes managed by ParallelCluster. "
            "Please rename the following custom Slurm nodes: test-dy-node[1-100]",
        ),
        # Generic case with multiple custom Slurm nodelists with bad node name
        (
            [{"NodeName": "test-st-node[1-100]", "CPUs": "16"}, {"NodeName": "test-dy-node[1-100]", "CPUs": "16"}],
            "Substrings '-st-' and '-dy-' in node names are reserved for nodes managed by ParallelCluster. "
            "Please rename the following custom Slurm nodes: test-dy-node[1-100], test-st-node[1-100]",
        ),
        # Unrealistic corner case with custom Slurm nodes with names defined multiple times
        (
            [{"NodeName": "test-dy-node[1-100]", "CPUs": "16", "nodename": "test-node[1-100]"}],
            "Substrings '-st-' and '-dy-' in node names are reserved for nodes managed by ParallelCluster. "
            "Please rename the following custom Slurm nodes: test-dy-node[1-100]",
        ),
    ],
)
def test_custom_slurm_node_names_validator(custom_slurm_settings, expected_message):
    actual_failures = CustomSlurmNodeNamesValidator().execute(custom_slurm_settings)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "custom_slurm_settings, custom_slurm_settings_include_file, expected_message",
    [
        ([{"Param1": "Value1"}, {"Param2": "Value2"}], "", ""),
        ([], "s3://test", ""),
        (
            [{"Param1": "Value1"}, {"Param2": "Value2"}],
            "s3://test",
            "CustomSlurmsettings and CustomSlurmSettingsIncludeFile cannot be used together under SlurmSettings.",
        ),
    ],
)
def test_custom_slurm_settings_include_file_only_validator(
    custom_slurm_settings, custom_slurm_settings_include_file, expected_message
):
    actual_failures = CustomSlurmSettingsIncludeFileOnlyValidator().execute(
        custom_slurm_settings,
        custom_slurm_settings_include_file,
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "queue_name, compute_resources, expected_message",
    [
        pytest.param(
            "queue1",
            [
                SlurmComputeResource(name="cr1", instance_type="t2.small", min_count=5),
                SlurmComputeResource(name="cr2", instance_type="t2.small", min_count=5),
            ],
            None,
            id="Case with default priorities",
        ),
        pytest.param(
            "queue1",
            [
                SlurmComputeResource(name="cr1", instance_type="t2.small", min_count=5, dynamic_node_priority=120),
                SlurmComputeResource(name="cr2", instance_type="t2.small", min_count=5, static_node_priority=100),
            ],
            None,
            id="Case with good custom priorities",
        ),
        pytest.param(
            "queue1",
            [
                SlurmComputeResource(name="cr1", instance_type="t2.small", min_count=0, dynamic_node_priority=100),
                SlurmComputeResource(name="cr2", instance_type="t2.small", min_count=0, static_node_priority=120),
            ],
            None,
            id="Case with bad custom priorities, but no static nodes, so no issue",
        ),
        pytest.param(
            "queue1",
            [
                SlurmComputeResource(name="cr1", instance_type="t2.small", min_count=10, dynamic_node_priority=100),
                SlurmComputeResource(name="cr2", instance_type="t2.small", min_count=10, static_node_priority=120),
            ],
            None,
            id="Case with bad custom priorities, but no dynamic nodes, so no issue",
        ),
        pytest.param(
            "queue1",
            [
                SlurmComputeResource(name="cr1", instance_type="t2.small", min_count=5, dynamic_node_priority=100),
                SlurmComputeResource(name="cr2", instance_type="t2.small", min_count=5, static_node_priority=120),
            ],
            "Some compute resources in queue queue1 have static nodes with higher or equal priority than "
            "other dynamic nodes in the same queue. "
            "The following static node priorities are higher than or equal to the minimum dynamic priority "
            "(100): {'cr2': 120}. "
            "The following dynamic node priorities are lower than or equal to the maximum static priority "
            "(120): {'cr1': 100}.",
            id="Case with problematic priorities",
        ),
        pytest.param(
            "queue1",
            [
                SlurmComputeResource(name="cr1", instance_type="t2.small", min_count=5, dynamic_node_priority=100),
                SlurmComputeResource(name="cr2", instance_type="t2.small", min_count=5, static_node_priority=100),
            ],
            "Some compute resources in queue queue1 have static nodes with higher or equal priority than "
            "other dynamic nodes in the same queue. "
            "The following static node priorities are higher than or equal to the minimum dynamic priority "
            "(100): {'cr2': 100}. "
            "The following dynamic node priorities are lower than or equal to the maximum static priority "
            "(100): {'cr1': 100}.",
            id="Case with equal static and dynamic priorities (problematic due to alphabetical sorting)",
        ),
        pytest.param(
            "queue1",
            [
                SlurmComputeResource(
                    name="cr1",
                    instance_type="t2.small",
                    min_count=5,
                    static_node_priority=10,
                    dynamic_node_priority=100,
                ),
                SlurmComputeResource(
                    name="cr2", instance_type="t2.small", min_count=5, static_node_priority=99, dynamic_node_priority=1
                ),
            ],
            "Some compute resources in queue queue1 have static nodes with higher or equal priority than "
            "other dynamic nodes in the same queue. "
            "The following static node priorities are higher than or equal to the minimum dynamic priority "
            "(1): {'cr1': 10, 'cr2': 99}. "
            "The following dynamic node priorities are lower than or equal to the maximum static priority "
            "(99): {'cr2': 1}.",
            id="Case with dynamic priority even lower than or equal to the range of static priorities",
        ),
        pytest.param(
            "queue1",
            [
                SlurmComputeResource(name="cr0", instance_type="t2.small", min_count=5, static_node_priority=100),
                SlurmComputeResource(name="cr1", instance_type="t2.small", min_count=5, static_node_priority=120),
                SlurmComputeResource(name="cr2", instance_type="t2.small", min_count=5, static_node_priority=140),
                SlurmComputeResource(name="cr3", instance_type="t2.small", min_count=5, static_node_priority=160),
                SlurmComputeResource(name="cr4", instance_type="t2.small", min_count=5, static_node_priority=180),
                SlurmComputeResource(name="cr5", instance_type="t2.small", min_count=5, dynamic_node_priority=150),
                SlurmComputeResource(name="cr6", instance_type="t2.small", min_count=5, dynamic_node_priority=150),
                SlurmComputeResource(name="cr7", instance_type="t2.small", min_count=5, dynamic_node_priority=170),
                SlurmComputeResource(name="cr8", instance_type="t2.small", min_count=5, dynamic_node_priority=190),
                SlurmComputeResource(name="cr9", instance_type="t2.small", min_count=5, dynamic_node_priority=210),
            ],
            "Some compute resources in queue queue1 have static nodes with higher or equal priority than "
            "other dynamic nodes in the same queue. "
            "The following static node priorities are higher than or equal to the minimum dynamic priority "
            "(150): {'cr3': 160, 'cr4': 180}. "
            "The following dynamic node priorities are lower than or equal to the maximum static priority "
            "(180): {'cr5': 150, 'cr6': 150, 'cr7': 170}.",
            id="Case with many compute resources with problematic priorities",
        ),
    ],
)
def test_slurm_node_weights_warning_validator(queue_name, compute_resources, expected_message):
    actual_failures = SlurmNodePrioritiesWarningValidator().execute(queue_name, compute_resources)
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
        ("rhel8", "slurm", None),
        ("centos7", "awsbatch", "scheduler supports the following operating systems"),
        ("rhel8", "awsbatch", "scheduler supports the following operating systems"),
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
        ("ComputeResources", 4, 5, None),
        (
            "SlurmQueues",
            11,
            10,
            "Invalid number of SlurmQueues (11) specified. Currently only supports up to 10 SlurmQueues.",
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
    "instance_type, efa_enabled, gdr_support, efa_supported, multiaz_enabled, expected_message",
    [
        # EFAGDR without EFA
        ("c5n.18xlarge", False, True, True, False, "GDR Support can be used only if EFA is enabled"),
        # EFAGDR with EFA
        ("c5n.18xlarge", True, True, True, False, None),
        # EFA without EFAGDR
        ("c5n.18xlarge", True, False, True, False, None),
        # Unsupported instance type
        ("t2.large", True, False, False, False, "does not support EFA"),
        ("t2.large", False, False, False, False, None),
        # EFA not enabled for instance type that supports it
        (
            "c5n.18xlarge",
            False,
            False,
            True,
            False,
            "supports enhanced networking capabilities using Elastic Fabric Adapter",
        ),
        ("c5n.18xlarge", False, False, True, True, None),
    ],
)
def test_efa_validator(
    mocker, boto3_stubber, instance_type, efa_enabled, gdr_support, efa_supported, multiaz_enabled, expected_message
):
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

    actual_failures = EfaValidator().execute(instance_type, efa_enabled, gdr_support, multiaz_enabled)
    assert_failure_messages(actual_failures, expected_message)
    if efa_enabled:
        get_instance_type_info_mock.assert_called_with(instance_type)


@pytest.mark.parametrize(
    "efa_enabled, placement_group_key, placement_group_disabled, multi_az_enabled, expected_message",
    [
        # Efa disabled
        (False, "test", False, False, None),
        (False, "test", True, False, None),
        (False, None, False, False, None),
        (False, None, True, False, None),
        # Efa enabled
        (
            True,
            None,
            False,
            False,
            "The placement group for EFA-enabled compute resources must be explicit. "
            "You may see better performance using a placement group, "
            "but if you don't wish to use one please add "
            "'Enabled: false' to the compute resource's configuration section.",
        ),
        (True, None, True, False, "You may see better performance using a placement group for the queue."),
        (True, "test", False, False, None),
        (True, "test", True, False, "You may see better performance using a placement group for the queue."),
        # EFA and MultiAZ enabled
        (True, "test", False, True, None),
        (True, "test", True, True, None),
    ],
)
def test_efa_placement_group_validator(
    efa_enabled, placement_group_key, placement_group_disabled, multi_az_enabled, expected_message
):
    actual_failures = EfaPlacementGroupValidator().execute(
        efa_enabled, placement_group_key, placement_group_disabled, multi_az_enabled
    )

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
    "efa_enabled, os, architecture, expected_message",
    [
        (True, "alinux2", "x86_64", None),
        (True, "alinux2", "arm64", None),
        (True, "ubuntu1804", "x86_64", None),
        (True, "ubuntu1804", "arm64", None),
        (True, "ubuntu2004", "x86_64", None),
        (True, "ubuntu2004", "arm64", None),
        (True, "rhel8", "x86_64", None),
        (True, "rhel8", "arm64", None),
    ],
)
def test_efa_os_architecture_validator(efa_enabled, os, architecture, expected_message):
    actual_failures = EfaOsArchitectureValidator().execute(efa_enabled, os, architecture)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "multi_az_enabled, efa_enabled, expected_message",
    [
        (True, False, None),
        (False, True, None),
        (False, False, None),
        (
            True,
            True,
            "You have enabled the Elastic Fabric Adapter (EFA) for the 'compute' Compute Resource on the 'queue' queue."
            " EFA is not supported across Availability zones. Either disable EFA to use multiple subnets on the queue "
            "or specify only one subnet to enable EFA on the compute resources.",
        ),
    ],
)
def test_efa_multi_az_validator(multi_az_enabled, efa_enabled, expected_message):
    actual_failures = EfaMultiAzValidator().execute("queue", multi_az_enabled, "compute", efa_enabled)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "os, architecture, custom_ami, ami_search_filters, expected_message",
    [
        # All OSes supported for x86_64
        ("alinux2", "x86_64", None, None, None),
        ("alinux2", "x86_64", "custom-ami", None, None),
        ("rhel8", "x86_64", None, None, None),
        ("rhel8", "x86_64", "custom-ami", None, None),
        ("centos7", "x86_64", None, None, None),
        ("centos7", "x86_64", "custom-ami", None, None),
        ("ubuntu1804", "x86_64", None, None, None),
        ("ubuntu2004", "x86_64", None, None, None),
        # All OSes supported for ARM
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
        ("rhel8", "arm64", None, None, None),
        ("rhel8", "arm64", "custom-ami", None, None),
    ],
)
def test_architecture_os_validator(os, architecture, custom_ami, ami_search_filters, expected_message):
    """Verify that the correct set of OSes is supported for each supported architecture."""
    actual_failures = ArchitectureOsValidator().execute(os, architecture, custom_ami, ami_search_filters)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "head_node_architecture, compute_instance_type_info_list, expected_message",
    [
        (
            "x86_64",
            [InstanceTypeInfo({"InstanceType": "c4.xlarge", "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]}})],
            None,
        ),
        (
            "x86_64",
            [InstanceTypeInfo({"InstanceType": "m6g.xlarge", "ProcessorInfo": {"SupportedArchitectures": ["arm64"]}})],
            "none of which are compatible with the architecture supported by the head node instance type",
        ),
        (
            "arm64",
            [InstanceTypeInfo({"InstanceType": "c5.xlarge", "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]}})],
            "none of which are compatible with the architecture supported by the head node instance type",
        ),
        (
            "arm64",
            [InstanceTypeInfo({"InstanceType": "m6g.xlarge", "ProcessorInfo": {"SupportedArchitectures": ["arm64"]}})],
            None,
        ),
    ],
)
def test_instance_architecture_compatibility_validator(
    mocker, head_node_architecture, compute_instance_type_info_list, expected_message
):
    mock_aws_api(mocker)
    actual_failures = InstanceArchitectureCompatibilityValidator().execute(
        compute_instance_type_info_list, head_node_architecture
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
    "fsx_file_system_type, fsx_vpc, ip_permissions, nodes_security_groups, network_interfaces, " "expected_message",
    [
        (  # working case, right vpc and sg, multiple network interfaces
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            {frozenset({"sg-12345678"}), frozenset({"sg-12345678", "sg-23456789"})},
            ["eni-09b9460295ddd4e5f", "eni-001b3cef7c78b45c4"],
            None,
        ),
        (  # working case, right vpc and sg, single network interface
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            {frozenset({"sg-12345678"}), frozenset({"sg-12345678", "sg-23456789"})},
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # working case (LUSTRE) CIDR specified in the security group through ip ranges
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
            {frozenset({None}), frozenset({None})},
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # working case (LUSTRE) CIDR specified in the security group through ip ranges.
            # This is more complex than above because the union of the sg rules cover the subnet but individual rules
            # do not cover the subnet
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [
                {"IpProtocol": "-1", "IpRanges": [{"CidrIp": "10.0.1.0/25"}]},
                {"IpProtocol": "tcp", "FromPort": 988, "ToPort": 988, "IpRanges": [{"CidrIp": "10.0.1.128/25"}]},
            ],
            {frozenset({None}), frozenset({None})},
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # working case (LUSTRE) CIDR specified in the security group through ip ranges.
            # The CIDR does not cover the subnet, but security group is right
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [
                {"IpProtocol": "-1", "IpRanges": [{"CidrIp": "10.1.1.0/25"}]},
                {"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]},
            ],
            {frozenset({"sg-12345678"}), frozenset({"sg-12345678", "sg-23456789"})},
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # working case (LUSTRE) CIDR specified in the security group through ip ranges.
            # The security group is wrong, but the CIDR covers the subnet
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [
                {"IpProtocol": "-1", "IpRanges": [{"CidrIp": "10.0.0.0/23"}]},
                {"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-34567890"}]},
            ],
            {frozenset({"sg-12345678"}), frozenset({"sg-12345678", "sg-23456789"})},
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # working case (OPENZFS), CIDR specified in the security group through ip ranges
            "OPENZFS",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
            {frozenset({None}), frozenset({None})},
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # working case (ONTAP), CIDR specified in the security group through ip ranges
            "ONTAP",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
            {frozenset({None}), frozenset({None})},
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # working case, CIDR specified in the security group through prefix list
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "PrefixListIds": [{"PrefixListId": "pl-12345"}]}],
            {frozenset({None}), frozenset({None})},
            ["eni-09b9460295ddd4e5f"],
            None,
        ),
        (  # not working case, wrong security group. Lustre
            # Security group without CIDR/prefix cannot work with clusters containing pcluster created security group.
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            {frozenset({None}), frozenset({None})},
            ["eni-09b9460295ddd4e5f"],
            "The current security group settings on file storage .* does not satisfy mounting requirement. "
            "The file storage must be associated to a security group that "
            r"allows inbound and outbound TCP traffic through ports \[988\].",
        ),
        (  # not working case, wrong security group. Lustre
            # Security group with other security groups as src/dst has to reachable from all nodes security groups.
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-23456789"}]}],
            {frozenset({"sg-12345678"}), frozenset({"sg-12345678", "sg-23456789"})},
            ["eni-09b9460295ddd4e5f"],
            "The current security group settings on file storage .* does not satisfy mounting requirement. "
            "The file storage must be associated to a security group that "
            r"allows inbound and outbound TCP traffic through ports \[988\].",
        ),
        (  # not working case, wrong security group. OpenZFS
            # Security group without CIDR cannot work with clusters containing pcluster created security group.
            "OPENZFS",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            {frozenset({None}), frozenset({None})},
            ["eni-09b9460295ddd4e5f"],
            "The current security group settings on file storage .* does not satisfy mounting requirement. "
            "The file storage must be associated to a security group that "
            r"allows inbound and outbound TCP traffic through ports \[111, 2049, 20001, 20002, 20003\].",
        ),
        (  # not working case, wrong security group. Ontap
            # Security group without CIDR cannot work with clusters containing pcluster created security group.
            "ONTAP",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            {frozenset({None}), frozenset({None})},
            ["eni-09b9460295ddd4e5f"],
            "The current security group settings on file storage .* does not satisfy mounting requirement. "
            "The file storage must be associated to a security group that "
            r"allows inbound and outbound TCP traffic through ports \[111, 635, 2049, 4046\].",
        ),
        (  # not working case --> no network interfaces
            "LUSTRE",
            "vpc-06e4ab6c6cEXAMPLE",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            {frozenset({"sg-12345678"}), frozenset({"sg-12345678", "sg-23456789"})},
            [],
            "doesn't have Elastic Network Interfaces attached",
        ),
        (  # not working case --> wrong vpc
            "LUSTRE",
            "vpc-06e4ab6c6ccWRONG",
            [{"IpProtocol": "-1", "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}]}],
            {frozenset({"sg-12345678"}), frozenset({"sg-12345678", "sg-23456789"})},
            ["eni-09b9460295ddd4e5f"],
            "only support using FSx file storage that is in the same VPC as the cluster",
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
            {frozenset({"sg-12345678"}), frozenset({"sg-12345678", "sg-23456789"})},
            ["eni-09b9460295ddd4e5f"],
            [
                "only support using FSx file storage that is in the same VPC as the cluster",
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
    nodes_security_groups,
    network_interfaces,
    expected_message,
):
    fsx_mocked_requests = []
    if fsx_file_system_type == "LUSTRE":
        # Creating describe Fsx Filecache mocker
        describe_file_caches_response = {
            "FileCaches": [
                {
                    "VpcId": fsx_vpc,
                    "NetworkInterfaceIds": network_interfaces,
                    "SubnetIds": ["subnet-12345678"],
                    "FileCacheType": "LUSTRE",
                    "CreationTime": 1567636453.038,
                    "ResourceARN": "arn:aws:fsx:us-west-2:111122223333:file-system/fc-0ff8da96d57f3b4e3",
                    "StorageCapacity": 1200,
                    "FileCacheId": "fc-0ff8da96d57f3b4e3",
                    "FileCacheTypeVersion": "2.12",
                    "DNSName": "fc-0ff8da96d57f3b4e3.fsx.us-west-2.amazonaws.com",
                    "OwnerId": "111122223333",
                    "Lifecycle": "AVAILABLE",
                    "LustreConfiguration": {
                        "PerUnitStorageThroughput": 1000,
                        "DeploymentType": "CACHE_1",
                        "MountName": "23wixbev",
                        "WeeklyMaintenanceStartTime": "1:05:00",
                        "MetadataConfiguration": {"StorageCapacity": 2400},
                    },
                    "DataRepositoryAssociationIds": ["dra-05f16b2a4ea7d032e"],
                }
            ]
        }
        fsx_mocked_requests.append(
            MockedBoto3Request(
                method="describe_file_caches",
                response=describe_file_caches_response,
                expected_params={"FileCacheIds": ["fc-0ff8da96d57f3b4e3"]},
            )
        )

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
    fsx_mocked_requests.append(
        MockedBoto3Request(
            method="describe_file_systems",
            response=describe_file_systems_response,
            expected_params={"FileSystemIds": ["fs-0ff8da96d57f3b4e3"]},
        )
    )

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

    if fsx_file_system_type == "LUSTRE":
        # No need to mock describe security group and Subnet calls as they are cached
        if network_interfaces:
            ec2_mocked_requests.append(
                MockedBoto3Request(
                    method="describe_network_interfaces",
                    response=describe_network_interfaces_response,
                    expected_params={"NetworkInterfaceIds": network_interfaces},
                )
            )

    boto3_stubber("fsx", fsx_mocked_requests)
    boto3_stubber("ec2", ec2_mocked_requests)

    if fsx_file_system_type == "LUSTRE":
        # Testing for FSx File Cache
        actual_failures = ExistingFsxNetworkingValidator().execute(
            subnet_ids=["subnet-12345678"],
            security_groups_by_nodes=nodes_security_groups,
            file_storage_ids=["fs-0ff8da96d57f3b4e3", "fc-0ff8da96d57f3b4e3"],
        )
    else:
        # Testing for other FSX
        actual_failures = ExistingFsxNetworkingValidator().execute(
            file_storage_ids=["fs-0ff8da96d57f3b4e3"],
            subnet_ids=["subnet-12345678"],
            security_groups_by_nodes=nodes_security_groups,
        )

    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "architecture, os, expected_message",
    [
        # Supported combinations
        ("x86_64", "alinux2", None),
        ("x86_64", "centos7", None),
        ("x86_64", "rhel8", None),
        ("x86_64", "ubuntu1804", None),
        ("x86_64", "ubuntu2004", None),
        ("arm64", "ubuntu1804", None),
        ("arm64", "ubuntu2004", None),
        ("arm64", "rhel8", None),
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
    "shared_storage_name_mount_dir_tuple_list, local_mount_dir_instance_types_dict, expected_message",
    [
        (
            [("name1", "dir1")],
            {},
            None,
        ),
        (
            [("name1", "dir1"), ("name2", "dir2")],
            {},
            None,
        ),
        (
            [("name1", "dir1"), ("name2", "dir2"), ("name3", "dir3")],
            {},
            None,
        ),
        (
            [("name1", "dir1"), ("name3", "dir1"), ("name2", "dir2")],
            {},
            r"The mount directory `dir1` is used for multiple shared storage: \['name1', 'name3'\]",
        ),
        # The two test cases below check two different errors from the same input.
        # Because there are two duplicate mount directories.
        (
            [("name1", "dir1"), ("name2", "dir2"), ("name3", "dir3"), ("name4", "dir2"), ("name5", "dir1")],
            {},
            r"The mount directory `dir1` is used for multiple shared storage: \['name1', 'name5'\]",
        ),
        (
            [("name1", "dir1"), ("name2", "dir2"), ("name3", "dir3"), ("name4", "dir2"), ("name5", "dir1")],
            {},
            r"The mount directory `dir2` is used for multiple shared storage: \['name2', 'name4'\]",
        ),
        (
            [("name1", "dir1"), ("name2", "dir2"), ("name3", "/scratch")],
            {},
            None,
        ),
        (
            [("name1", "dir1"), ("name2", "dir2"), ("name3", "/scratch")],
            {"/scratch": ["c5d.xlarge"]},
            r"The mount directory `/scratch` used for shared storage \['name3'\] clashes with the one used for "
            r"ephemeral volumes of the instances \['c5d.xlarge'\].",
        ),
    ],
)
def test_duplicate_mount_dir_validator(
    shared_storage_name_mount_dir_tuple_list, local_mount_dir_instance_types_dict, expected_message
):
    actual_failures = DuplicateMountDirValidator().execute(
        shared_storage_name_mount_dir_tuple_list, local_mount_dir_instance_types_dict
    )
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
        ("FSx", 1, 0, None),
        ("EFS", 1, 1, None),
        ("EBS", 5, 6, "Too many EBS shared storage specified in the configuration. ParallelCluster supports 5 EBS."),
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
        (True, "rhel8", "t2.medium", None, None, None),
        (True, "ubuntu1804", "t2.medium", None, "1.2.3.4/32", None),
        (True, "ubuntu2004", "t2.medium", None, None, None),
        (True, "centos7", "t2.medium", "0.0.0.0/0", 8443, "port 8443 to the world"),
        (True, "alinux2", "t2.medium", None, None, None),
        (True, "alinux2", "t2.nano", None, None, "is recommended to use an instance type with at least"),
        (True, "alinux2", "t2.micro", None, None, "is recommended to use an instance type with at least"),
        (False, "alinux2", "t2.micro", None, None, None),  # doesn't fail because DCV is disabled
        (True, "ubuntu1804", "m6g.xlarge", None, None, None),
        (True, "alinux2", "m6g.xlarge", None, None, None),
        (True, "rhel8", "m6g.xlarge", None, None, None),
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
        ("rhel8", "the operating system is required to be set"),
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
    "network_interfaces_count, use_efa, security_group_ids, subnet, use_public_ips, expected_result",
    [
        [
            1,
            False,
            "sg-1",
            "subnet-1",
            False,
            [
                {
                    "DeviceIndex": 0,
                    "NetworkCardIndex": 0,
                    "InterfaceType": "interface",
                    "Groups": "sg-1",
                    "SubnetId": "subnet-1",
                }
            ],
        ],
        [
            4,
            True,
            "sg-2",
            "subnet-2",
            True,
            [
                {
                    "DeviceIndex": 0,
                    "NetworkCardIndex": 0,
                    "InterfaceType": "efa",
                    "Groups": "sg-2",
                    "SubnetId": "subnet-2",
                    "AssociatePublicIpAddress": True,
                },
                {
                    "DeviceIndex": 0,
                    "NetworkCardIndex": 1,
                    "InterfaceType": "efa",
                    "Groups": "sg-2",
                    "SubnetId": "subnet-2",
                },
                {
                    "DeviceIndex": 0,
                    "NetworkCardIndex": 2,
                    "InterfaceType": "efa",
                    "Groups": "sg-2",
                    "SubnetId": "subnet-2",
                },
                {
                    "DeviceIndex": 0,
                    "NetworkCardIndex": 3,
                    "InterfaceType": "efa",
                    "Groups": "sg-2",
                    "SubnetId": "subnet-2",
                },
            ],
        ],
    ],
)
def test_build_launch_network_interfaces(
    network_interfaces_count, use_efa, security_group_ids, subnet, use_public_ips, expected_result
):
    """Verify function to build network interfaces for dry runs of RunInstances works as expected."""
    lt_network_interfaces = _LaunchTemplateValidator._build_launch_network_interfaces(
        network_interfaces_count, use_efa, security_group_ids, subnet, use_public_ips
    )
    assert_that(lt_network_interfaces).is_equal_to(expected_result)


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


@pytest.mark.parametrize(
    "deletion_policy, name, expected_message, failure_level",
    [
        (
            "Delete",
            "ebs_name",
            "The DeletionPolicy is set to Delete. The storage 'ebs_name' will be deleted when you remove it from the "
            "configuration when performing a cluster update or deleting the cluster.",
            FailureLevel.INFO,
        ),
        (
            "Retain",
            "efs_name",
            "The DeletionPolicy is set to Retain. The storage 'efs_name' will be retained when you remove it from the "
            "configuration when performing a cluster update or deleting the cluster.",
            FailureLevel.INFO,
        ),
        ("Snapshot", "storage", None, None),
    ],
)
def test_deletion_policy_validator(deletion_policy, name, expected_message, failure_level):
    actual_failures = DeletionPolicyValidator().execute(deletion_policy, name)
    assert_failure_messages(actual_failures, expected_message)
    assert_failure_level(actual_failures, failure_level)


@pytest.mark.parametrize(
    "avail_zones_mapping, cluster_subnet_cidr, nodes_security_groups, security_groups, file_system_info, "
    "failure_level, expected_message",
    [
        (
            {"dummy-az-3": {"subnet-3"}},
            "",
            {frozenset({None}), frozenset({"sg-12345678"})},
            {},
            {
                "FileSystems": [
                    {
                        "FileSystemId": "fs-084a3b173fb101f9b",
                    }
                ]
            },
            FailureLevel.ERROR,
            "There is no existing Mount Target for EFS 'dummy-efs-1' in these Availability Zones: '\\['dummy-az-3'\\]'."
            " Please create an EFS Mount Target for those availability zones.",
        ),
        (  # We expect this validator does not provide error message when there is no mount targets,
            # because another validator checks the existence of the mount targets.
            {"dummy-az-3": {"subnet-3"}},
            "",
            {frozenset({None}), frozenset({"sg-12345678"})},
            {},
            {
                "FileSystems": [
                    {
                        "FileSystemId": "fs-084a3b173fb101f9b",
                        "AvailabilityZoneName": "eu-west-1c",
                        "AvailabilityZoneId": "euw1-az3",
                    }
                ]
            },
            None,
            "",
        ),
        (  # Working case. Ip ranges of SG cover subnet.
            {"dummy-az-1": {"subnet-1", "subnet-2"}},
            "0.0.0.0/16",
            {frozenset({None}), frozenset({"sg-12345678"})},
            [
                {
                    "IpPermissions": [
                        {
                            "FromPort": 2049,
                            "IpProtocol": "tcp",
                            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "ToPort": 2049,
                            "UserIdGroupPairs": [],
                        }
                    ],
                    "GroupId": "sg-041b924ce46b2dc0b",
                    "IpPermissionsEgress": [
                        {
                            "IpProtocol": "-1",
                            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "UserIdGroupPairs": [],
                        }
                    ],
                    "VpcId": "vpc-12345678",
                },
            ],
            {},
            None,
            None,
        ),
        (  # NOT working case. Ip ranges of SG do not cover subnet.
            {"dummy-az-1": {"subnet-1", "subnet-2"}},
            "0.0.0.0/16",
            {frozenset({None}), frozenset({"sg-12345678"})},
            [
                {
                    "IpPermissions": [
                        {
                            "FromPort": 2049,
                            "IpProtocol": "tcp",
                            "IpRanges": [{"CidrIp": "172.31.0.0/16"}],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "ToPort": 2049,
                            "UserIdGroupPairs": [],
                        }
                    ],
                    "GroupId": "sg-041b924ce46b2dc0b",
                    "IpPermissionsEgress": [
                        {
                            "IpProtocol": "-1",
                            "IpRanges": [{"CidrIp": "172.31.0.0/16"}],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "UserIdGroupPairs": [],
                        }
                    ],
                    "VpcId": "vpc-12345678",
                },
            ],
            {},
            FailureLevel.ERROR,
            "There is an existing Mount Target dummy-efs-mt-1 in the Availability Zone dummy-az-1 for EFS dummy-efs-1, "
            "but it does not have a security group that allows inbound and outbound rules to support NFS. "
            "Please modify the Mount Target's security group, to allow traffic on port 2049.",
        ),
        (  # Working case. Union of Ip ranges of SG covers subnet. But individual Ip ranges do not cover subnet.
            {"dummy-az-1": {"subnet-1", "subnet-2"}},
            "172.31.0.0/16",
            {frozenset({None}), frozenset({"sg-12345678"})},
            [
                {
                    "IpPermissions": [
                        {
                            "FromPort": 2049,
                            "IpProtocol": "tcp",
                            "IpRanges": [{"CidrIp": "172.31.128.0/17"}],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "ToPort": 2049,
                            "UserIdGroupPairs": [],
                        },
                        {
                            "FromPort": 2040,
                            "IpProtocol": "tcp",
                            "IpRanges": [{"CidrIp": "172.31.0.0/17"}],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "ToPort": 2049,
                            "UserIdGroupPairs": [],
                        },
                    ],
                    "GroupId": "sg-041b924ce46b2dc0b",
                    "IpPermissionsEgress": [
                        {
                            "IpProtocol": "-1",
                            "IpRanges": [{"CidrIp": "172.31.128.0/17"}],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "UserIdGroupPairs": [],
                        },
                        {
                            "FromPort": 2049,
                            "ToPort": 2049,
                            "IpProtocol": "tcp",
                            "IpRanges": [{"CidrIp": "172.31.0.0/17"}],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "UserIdGroupPairs": [],
                        },
                    ],
                    "VpcId": "vpc-12345678",
                },
            ],
            {},
            None,
            None,
        ),
        (  # Working case. Connections allowed by security group ids.
            {"dummy-az-1": {"subnet-1", "subnet-2"}},
            "172.31.0.0/16",
            {frozenset({"sg-12345678"}), frozenset({"sg-23456789"})},
            [
                {
                    "IpPermissions": [
                        {
                            "FromPort": 2040,
                            "IpProtocol": "tcp",
                            "IpRanges": [],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "ToPort": 2049,
                            "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-12345678"}],
                        },
                        {
                            "FromPort": 2049,
                            "IpProtocol": "tcp",
                            "IpRanges": [],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "ToPort": 2049,
                            "UserIdGroupPairs": [{"UserId": "123456789012", "GroupId": "sg-23456789"}],
                        },
                    ],
                    "GroupId": "sg-041b924ce46b2dc0b",
                    "IpPermissionsEgress": [
                        {
                            "IpProtocol": "-1",
                            "IpRanges": [],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "UserIdGroupPairs": [
                                {"UserId": "123456789012", "GroupId": "sg-12345678"},
                                {"UserId": "123456789012", "GroupId": "sg-23456789"},
                            ],
                        },
                    ],
                    "VpcId": "vpc-12345678",
                },
            ],
            {},
            None,
            None,
        ),
        (
            {"dummy-az-1": {"subnet-1", "subnet-2"}},
            "172.31.64.0/20",
            {frozenset({None}), frozenset({"sg-12345678"})},
            [
                {
                    "IpPermissions": [
                        {
                            "FromPort": 1049,
                            "IpProtocol": "tcp",
                            "IpRanges": [{"CidrIp": "172.31.0.0/16"}],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "ToPort": 1049,
                            "UserIdGroupPairs": [],
                        }
                    ],
                    "GroupId": "sg-041b924ce46b2dc0b",
                    "IpPermissionsEgress": [
                        {
                            "IpProtocol": "-1",
                            "IpRanges": [{"CidrIp": "172.31.0.0/16"}],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "UserIdGroupPairs": [],
                        }
                    ],
                    "VpcId": "vpc-12345678",
                },
            ],
            {},
            FailureLevel.ERROR,
            "There is an existing Mount Target dummy-efs-mt-1 in the Availability Zone dummy-az-1 for EFS dummy-efs-1, "
            "but it does not have a security group that allows inbound and outbound rules to support NFS. Please "
            "modify the Mount Target's security group, to allow traffic on port 2049.",
        ),
        (
            {"dummy-az-1": {"subnet-1", "subnet-2"}},
            "172.31.0.0/16",
            {frozenset({None}), frozenset({"sg-12345678"})},
            [
                {
                    "IpPermissions": [
                        {
                            "FromPort": 2049,
                            "IpProtocol": "tcp",
                            "IpRanges": [{"CidrIp": "172.31.64.0/20"}],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "ToPort": 2049,
                            "UserIdGroupPairs": [],
                        }
                    ],
                    "GroupId": "sg-041b924ce46b2dc0b",
                    "IpPermissionsEgress": [
                        {
                            "IpProtocol": "-1",
                            "IpRanges": [{"CidrIp": "172.31.64.0/20"}],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "UserIdGroupPairs": [],
                        }
                    ],
                    "VpcId": "vpc-12345678",
                },
            ],
            {},
            FailureLevel.ERROR,
            "There is an existing Mount Target dummy-efs-mt-1 in the Availability Zone dummy-az-1 for EFS dummy-efs-1, "
            "but it does not have a security group that allows inbound and outbound rules to support NFS. "
            "Please modify the Mount Target's security group, to allow traffic on port 2049.",
        ),
        (
            {"dummy-az-1": {"subnet-1"}, "dummy-az-2": {"subnet-2"}},
            "0.0.0.0/16",
            {frozenset({None}), frozenset({None})},
            [
                {
                    "IpPermissions": [
                        {
                            "FromPort": 2049,
                            "IpProtocol": "tcp",
                            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "ToPort": 2049,
                            "UserIdGroupPairs": [],
                        }
                    ],
                    "GroupId": "sg-041b924ce46b2dc0b",
                    "IpPermissionsEgress": [
                        {
                            "IpProtocol": "-1",
                            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                            "Ipv6Ranges": [],
                            "PrefixListIds": [],
                            "UserIdGroupPairs": [],
                        }
                    ],
                    "VpcId": "vpc-12345678",
                },
            ],
            {
                "FileSystems": [
                    {
                        "FileSystemId": "fs-084a3b173fb101f9b",
                        "AvailabilityZoneName": "us-east-1",
                    }
                ]
            },
            FailureLevel.ERROR,
            "Cluster has subnets located in different availability zones but EFS (dummy-efs-1) uses OneZone EFS "
            "storage class which works within a single Availability Zone. Please use subnets located in one "
            "Availability Zone or use a standard storage class EFS.",
        ),
    ],
)
def test_efs_id_validator(
    mocker,
    boto3_stubber,
    avail_zones_mapping,
    nodes_security_groups,
    security_groups,
    cluster_subnet_cidr,
    file_system_info,
    failure_level,
    expected_message,
):
    mock_aws_api(mocker)
    efs_id = "dummy-efs-1"

    mocker.patch("pcluster.aws.efs.EfsClient.describe_file_system", return_value=file_system_info)
    mocker.patch("pcluster.aws.ec2.Ec2Client.get_subnet_cidr", return_value=cluster_subnet_cidr)
    mocker.patch("pcluster.aws.ec2.Ec2Client.describe_security_groups", return_value=security_groups)

    actual_failures = EfsIdValidator().execute(efs_id, avail_zones_mapping, nodes_security_groups)
    assert_failure_messages(actual_failures, expected_message)
    assert_failure_level(actual_failures, failure_level)


@pytest.mark.parametrize(
    "queue_parameters_array, new_storage_count, failure_level, expected_message",
    [
        (
            [
                dict(
                    name="queue1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
            ],
            {"efs": 0, "fsx": 0, "raid": 0},
            None,
            "",
        ),
        (
            [
                dict(
                    name="queue1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="queue2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
            ],
            {"efs": 0, "fsx": 0, "raid": 0},
            None,
            "",
        ),
        (
            [
                dict(
                    name="queue1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="queue2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1", "subnet-2"],
                    ),
                ),
            ],
            {"efs": 0, "fsx": 0, "raid": 0},
            None,
            "",
        ),
        (
            [
                dict(
                    name="queue1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="queue2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-2"],
                    ),
                ),
            ],
            {"efs": 1, "fsx": 1, "raid": 1},
            FailureLevel.ERROR,
            "Managed FSx storage created by ParallelCluster is not supported when specifying multiple subnet Ids under "
            "the SubnetIds configuration of a queue. Please make sure to provide an existing FSx shared storage, "
            "properly configured to work across the target subnets or remove the managed FSx storage to use multiple "
            "subnets for a queue.",
        ),
        (
            [
                dict(
                    name="queue1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="queue2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1", "subnet-2"],
                    ),
                ),
            ],
            {"efs": 0, "fsx": 0, "raid": 1},
            None,
            "",
        ),
        (
            [
                dict(
                    name="queue1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="queue2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-2"],
                    ),
                ),
            ],
            {"efs": 1, "fsx": 0, "raid": 1},
            None,
            "",
        ),
        (
            [
                dict(
                    name="queue1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="queue2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1", "subnet-2"],
                    ),
                ),
            ],
            {"efs": 1, "fsx": 0, "raid": 0},
            None,
            "",
        ),
        (
            [
                dict(
                    name="queue1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="queue2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1", "subnet-2"],
                    ),
                ),
            ],
            {"efs": 0, "fsx": 1, "raid": 0},
            FailureLevel.ERROR,
            "Managed FSx storage created by ParallelCluster is not supported when specifying multiple subnet Ids under "
            "the SubnetIds configuration of a queue. Please make sure to provide an existing FSx shared storage, "
            "properly configured to work across the target subnets or remove the managed FSx storage to use multiple "
            "subnets for a queue.",
        ),
        (
            [
                dict(
                    name="queue1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="queue2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1", "subnet-2"],
                    ),
                ),
            ],
            {"efs": 1, "fsx": 3, "raid": 0},
            FailureLevel.ERROR,
            "Managed FSx storage created by ParallelCluster is not supported when specifying multiple subnet Ids under "
            "the SubnetIds configuration of a queue. Please make sure to provide an existing FSx shared storage, "
            "properly configured to work across the target subnets or remove the managed FSx storage to use multiple "
            "subnets for a queue.",
        ),
    ],
)
@pytest.mark.usefixtures("get_region")
def test_new_storage_multiple_subnets_validator(
    queue_parameters_array, new_storage_count, failure_level, expected_message
):
    queues = [SlurmQueue(**queue_parameters) for queue_parameters in queue_parameters_array]
    actual_failures = ManagedFsxMultiAzValidator().execute(queues, new_storage_count)
    assert_failure_messages(actual_failures, expected_message)
    assert_failure_level(actual_failures, failure_level)


@pytest.mark.parametrize(
    "queue_parameters_array, subnet_az_mappings, fsx_az_list, failure_level, expected_messages",
    [
        (
            [
                dict(
                    name="different-az-queue",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-2"],
                    ),
                ),
                dict(
                    name="single-az-same-subnet-queue",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
            ],
            [{"subnet-2": "us-east-1b"}, {"subnet-1": "us-east-1a"}],
            ["us-east-1a"],
            FailureLevel.INFO,
            [
                "Your configuration for Queue 'different-az-queue' includes multiple subnets and external shared "
                "storage configuration. Accessing a shared storage from different AZs can lead to increased storage "
                "networking latency and added inter-AZ data transfer costs."
            ],
        ),
        (
            [
                dict(
                    name="same-az-same-subnet-queue",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="same-az-other-subnet-queue",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-3"],
                    ),
                ),
            ],
            [{"subnet-1": "us-east-1a"}, {"subnet-3": "us-east-1a"}],
            ["us-east-1a"],
            None,
            [],
        ),
        (
            [
                dict(
                    name="one-az-match-queue",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="full-az-match-queue",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1", "subnet-2"],
                    ),
                ),
            ],
            [{"subnet-1": "us-east-1a"}, {"subnet-1": "us-east-1a", "subnet-2": "us-east-1b"}],
            ["us-east-1a", "us-east-1b"],
            None,
            [],
        ),
        (
            [
                dict(
                    name="multi-az-queue-match",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1", "subnet-2"],
                    ),
                ),
                dict(
                    name="multi-az-queue-match",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-4", "subnet-5"],
                    ),
                ),
            ],
            [
                {"subnet-1": "us-east-1a", "subnet-2": "us-east-1b"},
                {"subnet-4": "us-east-1a", "subnet-5": "us-east-1b"},
            ],
            ["us-east-1a", "us-east-1b"],
            None,
            [],
        ),
        (
            [
                dict(
                    name="multi-az-queue-mismatch",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-2", "subnet-3"],
                    ),
                ),
            ],
            [{"subnet-2": "us-east-1b", "subnet-3": "us-east-1c"}],
            ["us-east-1a", "us-east-1b"],
            FailureLevel.INFO,
            [
                "Your configuration for Queue 'multi-az-queue-mismatch' includes multiple subnets and external shared "
                "storage configuration. Accessing a shared storage from different AZs can lead to increased storage "
                "networking latency and added inter-AZ data transfer costs."
            ],
        ),
        (
            [
                dict(
                    name="different-az-queue-1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="different-az-queue-2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
            ],
            [{"subnet-1": "us-east-1a"}, {"subnet-1": "us-east-1a"}],
            ["us-east-1b"],
            FailureLevel.INFO,
            [
                "Your configuration for Queue 'different-az-queue-1' includes multiple subnets and external shared "
                + "storage configuration. Accessing a shared storage from different AZs can lead to increased storage "
                + "networking latency and added inter-AZ data transfer costs.",
                "Your configuration for Queue 'different-az-queue-2' includes multiple subnets and external shared "
                + "storage configuration. Accessing a shared storage from different AZs can lead to increased storage "
                + "networking latency and added inter-AZ data transfer costs.",
            ],
        ),
    ],
)
def test_unmanaged_fsx_multiple_az_validator(
    mocker, queue_parameters_array, subnet_az_mappings, fsx_az_list, failure_level, expected_messages
):
    mock_aws_api(mocker)

    mocker.patch("pcluster.aws.ec2.Ec2Client.get_subnets_az_mapping", side_effect=subnet_az_mappings)

    queues = [SlurmQueue(**queue_parameters) for queue_parameters in queue_parameters_array]
    actual_failures = UnmanagedFsxMultiAzValidator().execute(queues, fsx_az_list)
    assert_failure_messages(actual_failures, expected_messages)
    assert_failure_level(actual_failures, failure_level)


@pytest.mark.parametrize(
    "storage_parameters, is_managed, availability_zone, volume_description",
    [
        (
            dict(
                mount_dir="mount-dir",
                name="volume-name",
                kms_key_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                snapshot_id="snapshot-abdcef76",
                volume_type="gp2",
                throughput=300,
                volume_id=None,
                raid=None,
            ),
            True,
            "",
            {"AvailabilityZone": "us-east-1a"},
        ),
        (
            dict(
                mount_dir="mount-dir",
                name="volume-name",
                volume_id="volume-id",
            ),
            False,
            "us-east-1a",
            {"AvailabilityZone": "us-east-1a"},
        ),
    ],
)
def test_shared_ebs_properties(
    mocker,
    storage_parameters,
    is_managed,
    availability_zone,
    volume_description,
):
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    mocker.patch("pcluster.aws.ec2.Ec2Client.describe_volume", return_value=volume_description)
    storage = SharedEbs(**storage_parameters)
    assert_that(storage.is_managed == is_managed).is_true()
    assert_that(storage.availability_zone == availability_zone).is_true()


class DummySharedEbs:
    def __init__(self, name: str, availability_zone: str):
        self.name = name
        self.availability_zone = availability_zone
        self.is_managed = False


@pytest.mark.parametrize(
    "head_node_az, ebs_volumes, queue_parameters_array, subnet_az_mappings, failure_level, expected_messages",
    [
        (
            "us-east-1a",
            [DummySharedEbs("vol-1", "us-east-1a")],
            [
                dict(
                    name="different-az-queue-1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-2"],
                    ),
                ),
                dict(
                    name="different-az-queue-2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-2"],
                    ),
                ),
            ],
            [{"subnet-2": "us-east-1b"}, {"subnet-2": "us-east-1b"}],
            FailureLevel.INFO,
            [
                "Your configuration for Queues 'different-az-queue-1, different-az-queue-2' includes multiple subnets "
                "and external shared storage configuration. Accessing a shared storage from different AZs can lead to "
                "increased storage network latency and inter-AZ data transfer costs.",
            ],
        ),
        (
            "us-east-1b",
            [DummySharedEbs("vol-1", "us-east-1a")],
            [
                dict(
                    name="same-az-queue-1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="same-az-queue-2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
            ],
            [{"subnet-1": "us-east-1a"}, {"subnet-1": "us-east-1a"}],
            FailureLevel.ERROR,
            [
                "Your configuration includes an EBS volume 'vol-1' created in a different availability zone than "
                + "the Head Node. The volume and instance must be in the same availability zone",
            ],
        ),
        (
            "us-east-1b",
            [
                DummySharedEbs("vol-1", "us-east-1a"),
                DummySharedEbs("vol-2", "us-east-1b"),
                DummySharedEbs("vol-3", "us-east-1c"),
            ],
            [
                dict(
                    name="queue-1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="queue-2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
            ],
            [{"subnet-1": "us-east-1a"}, {"subnet-1": "us-east-1a"}],
            FailureLevel.ERROR,
            [
                "Your configuration includes an EBS volume 'vol-1' created in a different availability zone than "
                + "the Head Node. The volume and instance must be in the same availability zone",
                "Your configuration includes an EBS volume 'vol-3' created in a different availability zone than "
                + "the Head Node. The volume and instance must be in the same availability zone",
                "Your configuration for Queues 'queue-1, queue-2' includes multiple subnets and external shared "
                + "storage configuration. Accessing a shared storage from different AZs can lead to increased storage "
                + "network latency and inter-AZ data transfer costs.",
            ],
        ),
        (
            "us-east-1a",
            [DummySharedEbs("vol-1", "us-east-1a")],
            [
                dict(
                    name="queue-1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1", "subnet-2"],
                    ),
                ),
                dict(
                    name="queue-2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="queue-3",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-2", "subnet-3"],
                    ),
                ),
            ],
            [
                {"subnet-1": "us-east-1a", "subnet-2": "us-east-1b"},
                {"subnet-1": "us-east-1a"},
                {"subnet-2": "us-east-1b", "subnet-3": "us-east-1c"},
            ],
            FailureLevel.INFO,
            [
                "Your configuration for Queues 'queue-1, queue-3' includes multiple subnets and external shared "
                + "storage configuration. Accessing a shared storage from different AZs can lead to increased storage "
                + "network latency and inter-AZ data transfer costs."
            ],
        ),
    ],
)
def test_multi_az_shared_ebs_validator(
    mocker,
    head_node_az,
    ebs_volumes,
    queue_parameters_array,
    subnet_az_mappings,
    failure_level,
    expected_messages,
):
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.get_subnets_az_mapping", side_effect=subnet_az_mappings)

    queues = [SlurmQueue(**queue_parameters) for queue_parameters in queue_parameters_array]
    actual_failures = MultiAzEbsVolumeValidator().execute(head_node_az, ebs_volumes, queues)
    assert_failure_messages(actual_failures, expected_messages)
    assert_failure_level(actual_failures, failure_level)


def test_ec2_volume_validator(mocker):
    # Test both SharedEbsVolumeIdValidator and MultiAzEbsVolumeValidator can produce good error
    # when a volume does not exist.
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    volume_id = "vol-12345678"
    aws_error_message = f"Value ({volume_id}) for parameter volumes is invalid. Expected: 'vol-...'."
    pcluster_error_message = f"Volume '{volume_id}' does not exist."

    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_volume",
        side_effect=AWSClientError("dummy_function_name", aws_error_message),
    )
    actual_failures = SharedEbsVolumeIdValidator().execute(volume_id=volume_id, head_node_instance_id="i-123")
    assert_failure_messages(actual_failures, pcluster_error_message)

    actual_failures = MultiAzEbsVolumeValidator().execute(
        "us-east-1a", [SharedEbs(mount_dir="test", name="test", volume_id=volume_id)], []
    )
    assert_failure_messages(actual_failures, pcluster_error_message)


@pytest.mark.parametrize(
    "head_node_az, queue_parameters_array, subnet_az_mappings, failure_level, expected_messages",
    [
        (
            "us-east-1a",
            [
                dict(
                    name="same-az-queue-1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1"],
                    ),
                ),
                dict(
                    name="different-az-queue-2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-2"],
                    ),
                ),
            ],
            [{"subnet-1": "us-east-1a"}, {"subnet-2": "us-east-1b"}],
            FailureLevel.INFO,
            [
                "Your configuration for Queues 'different-az-queue-2' includes multiple subnets "
                "different from where HeadNode is located. Accessing a shared storage from different AZs can lead to "
                "increased storage network latency and inter-AZ data transfer costs.",
            ],
        ),
        (
            "us-east-1a",
            [
                dict(
                    name="multi-az-queue-1",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-1", "subnet-2"],
                    ),
                ),
                dict(
                    name="different-az-queue-2",
                    compute_resources=[],
                    networking=SlurmQueueNetworking(
                        subnet_ids=["subnet-2"],
                    ),
                ),
            ],
            [{"subnet-1": "us-east-1a", "subnet-2": "us-east-1b"}, {"subnet-2": "us-east-1b"}],
            FailureLevel.INFO,
            [
                "Your configuration for Queues 'different-az-queue-2, multi-az-queue-1' includes multiple subnets "
                "different from where HeadNode is located. Accessing a shared storage from different AZs can lead to "
                "increased storage network latency and inter-AZ data transfer costs.",
            ],
        ),
    ],
)
@pytest.mark.usefixtures("get_region")
def test_multi_az_root_volume_validator(
    mocker,
    head_node_az,
    queue_parameters_array,
    subnet_az_mappings,
    failure_level,
    expected_messages,
):
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.get_subnets_az_mapping", side_effect=subnet_az_mappings)

    queues = [SlurmQueue(**queue_parameters) for queue_parameters in queue_parameters_array]
    actual_failures = MultiAzRootVolumeValidator().execute(head_node_az, queues)
    assert_failure_messages(actual_failures, expected_messages)
    assert_failure_level(actual_failures, failure_level)


@pytest.mark.parametrize(
    "ip_ranges, subnet_cidrs, covered",
    [
        (["0.0.0.0/0"], ["10.1.2.0/24"], True),  # Simple coverage
        (["0.0.0.0/0"], ["10.1.0.0/16", "192.1.2.0/24"], True),  # Cover two subnets
        (["10.1.0.0/16", "192.1.2.0/24"], ["10.1.0.0/16", "192.1.2.0/24"], True),  # Exact coverage
        (["10.1.0.0/17", "10.1.128.0/17"], ["10.1.0.0/16"], True),  # Combination coverage
        (["10.1.0.0/17"], ["10.1.0.0/16"], False),  # Uncovered
    ],
)
def test_are_subnets_covered_by_cidrs(mocker, ip_ranges, subnet_cidrs, covered):
    mock_aws_api(mocker)
    assert_that(
        _are_subnets_covered_by_cidrs([{"CidrIp": ip_range} for ip_range in ip_ranges], subnet_cidrs)
    ).is_equal_to(covered)


@pytest.mark.usefixtures("get_region")
class TestDictLaunchTemplateBuilder:
    @pytest.mark.parametrize(
        "root_volume_parameters, root_volume_device_name, region, expected_response",
        [
            pytest.param(
                dict(
                    size=10,
                    encrypted=False,
                    volume_type="mockVolumeType",
                    iops=13,
                    throughput=30,
                    delete_on_termination=False,
                ),
                "/dev/sda1",
                "WHATEVER-NON-US-ISO-REGION",
                [
                    {"DeviceName": "/dev/xvdba", "VirtualName": "ephemeral0"},
                    {"DeviceName": "/dev/xvdbb", "VirtualName": "ephemeral1"},
                    {"DeviceName": "/dev/xvdbc", "VirtualName": "ephemeral2"},
                    {"DeviceName": "/dev/xvdbd", "VirtualName": "ephemeral3"},
                    {"DeviceName": "/dev/xvdbe", "VirtualName": "ephemeral4"},
                    {"DeviceName": "/dev/xvdbf", "VirtualName": "ephemeral5"},
                    {"DeviceName": "/dev/xvdbg", "VirtualName": "ephemeral6"},
                    {"DeviceName": "/dev/xvdbh", "VirtualName": "ephemeral7"},
                    {"DeviceName": "/dev/xvdbi", "VirtualName": "ephemeral8"},
                    {"DeviceName": "/dev/xvdbj", "VirtualName": "ephemeral9"},
                    {"DeviceName": "/dev/xvdbk", "VirtualName": "ephemeral10"},
                    {"DeviceName": "/dev/xvdbl", "VirtualName": "ephemeral11"},
                    {"DeviceName": "/dev/xvdbm", "VirtualName": "ephemeral12"},
                    {"DeviceName": "/dev/xvdbn", "VirtualName": "ephemeral13"},
                    {"DeviceName": "/dev/xvdbo", "VirtualName": "ephemeral14"},
                    {"DeviceName": "/dev/xvdbp", "VirtualName": "ephemeral15"},
                    {"DeviceName": "/dev/xvdbq", "VirtualName": "ephemeral16"},
                    {"DeviceName": "/dev/xvdbr", "VirtualName": "ephemeral17"},
                    {"DeviceName": "/dev/xvdbs", "VirtualName": "ephemeral18"},
                    {"DeviceName": "/dev/xvdbt", "VirtualName": "ephemeral19"},
                    {"DeviceName": "/dev/xvdbu", "VirtualName": "ephemeral20"},
                    {"DeviceName": "/dev/xvdbv", "VirtualName": "ephemeral21"},
                    {"DeviceName": "/dev/xvdbw", "VirtualName": "ephemeral22"},
                    {"DeviceName": "/dev/xvdbx", "VirtualName": "ephemeral23"},
                    {
                        "DeviceName": "/dev/sda1",
                        "Ebs": {
                            "VolumeSize": 10,
                            "Encrypted": False,
                            "VolumeType": "mockVolumeType",
                            "Iops": 13,
                            "Throughput": 30,
                            "DeleteOnTermination": False,
                        },
                    },
                ],
                id="test with all root volume fields populated",
            ),
            pytest.param(
                dict(
                    encrypted=True,
                    volume_type="mockVolumeType",
                    iops=15,
                    throughput=20,
                    delete_on_termination=True,
                ),
                "/dev/xvda",
                "WHATEVER-NON-US-ISO-REGION",
                [
                    {"DeviceName": "/dev/xvdba", "VirtualName": "ephemeral0"},
                    {"DeviceName": "/dev/xvdbb", "VirtualName": "ephemeral1"},
                    {"DeviceName": "/dev/xvdbc", "VirtualName": "ephemeral2"},
                    {"DeviceName": "/dev/xvdbd", "VirtualName": "ephemeral3"},
                    {"DeviceName": "/dev/xvdbe", "VirtualName": "ephemeral4"},
                    {"DeviceName": "/dev/xvdbf", "VirtualName": "ephemeral5"},
                    {"DeviceName": "/dev/xvdbg", "VirtualName": "ephemeral6"},
                    {"DeviceName": "/dev/xvdbh", "VirtualName": "ephemeral7"},
                    {"DeviceName": "/dev/xvdbi", "VirtualName": "ephemeral8"},
                    {"DeviceName": "/dev/xvdbj", "VirtualName": "ephemeral9"},
                    {"DeviceName": "/dev/xvdbk", "VirtualName": "ephemeral10"},
                    {"DeviceName": "/dev/xvdbl", "VirtualName": "ephemeral11"},
                    {"DeviceName": "/dev/xvdbm", "VirtualName": "ephemeral12"},
                    {"DeviceName": "/dev/xvdbn", "VirtualName": "ephemeral13"},
                    {"DeviceName": "/dev/xvdbo", "VirtualName": "ephemeral14"},
                    {"DeviceName": "/dev/xvdbp", "VirtualName": "ephemeral15"},
                    {"DeviceName": "/dev/xvdbq", "VirtualName": "ephemeral16"},
                    {"DeviceName": "/dev/xvdbr", "VirtualName": "ephemeral17"},
                    {"DeviceName": "/dev/xvdbs", "VirtualName": "ephemeral18"},
                    {"DeviceName": "/dev/xvdbt", "VirtualName": "ephemeral19"},
                    {"DeviceName": "/dev/xvdbu", "VirtualName": "ephemeral20"},
                    {"DeviceName": "/dev/xvdbv", "VirtualName": "ephemeral21"},
                    {"DeviceName": "/dev/xvdbw", "VirtualName": "ephemeral22"},
                    {"DeviceName": "/dev/xvdbx", "VirtualName": "ephemeral23"},
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "Encrypted": True,
                            "VolumeType": "mockVolumeType",
                            "Iops": 15,
                            "Throughput": 20,
                            "DeleteOnTermination": True,
                        },
                    },
                ],
                id="test with missing volume size",
            ),
            pytest.param(
                dict(
                    encrypted=True,
                    volume_type="mockVolumeType",
                    iops=15,
                    throughput=20,
                    delete_on_termination=True,
                ),
                "/dev/xvda",
                "us-isoWHATEVER",
                [
                    {"DeviceName": "/dev/xvdba", "VirtualName": "ephemeral0"},
                    {"DeviceName": "/dev/xvdbb", "VirtualName": "ephemeral1"},
                    {"DeviceName": "/dev/xvdbc", "VirtualName": "ephemeral2"},
                    {"DeviceName": "/dev/xvdbd", "VirtualName": "ephemeral3"},
                    {"DeviceName": "/dev/xvdbe", "VirtualName": "ephemeral4"},
                    {"DeviceName": "/dev/xvdbf", "VirtualName": "ephemeral5"},
                    {"DeviceName": "/dev/xvdbg", "VirtualName": "ephemeral6"},
                    {"DeviceName": "/dev/xvdbh", "VirtualName": "ephemeral7"},
                    {"DeviceName": "/dev/xvdbi", "VirtualName": "ephemeral8"},
                    {"DeviceName": "/dev/xvdbj", "VirtualName": "ephemeral9"},
                    {"DeviceName": "/dev/xvdbk", "VirtualName": "ephemeral10"},
                    {"DeviceName": "/dev/xvdbl", "VirtualName": "ephemeral11"},
                    {"DeviceName": "/dev/xvdbm", "VirtualName": "ephemeral12"},
                    {"DeviceName": "/dev/xvdbn", "VirtualName": "ephemeral13"},
                    {"DeviceName": "/dev/xvdbo", "VirtualName": "ephemeral14"},
                    {"DeviceName": "/dev/xvdbp", "VirtualName": "ephemeral15"},
                    {"DeviceName": "/dev/xvdbq", "VirtualName": "ephemeral16"},
                    {"DeviceName": "/dev/xvdbr", "VirtualName": "ephemeral17"},
                    {"DeviceName": "/dev/xvdbs", "VirtualName": "ephemeral18"},
                    {"DeviceName": "/dev/xvdbt", "VirtualName": "ephemeral19"},
                    {"DeviceName": "/dev/xvdbu", "VirtualName": "ephemeral20"},
                    {"DeviceName": "/dev/xvdbv", "VirtualName": "ephemeral21"},
                    {"DeviceName": "/dev/xvdbw", "VirtualName": "ephemeral22"},
                    {"DeviceName": "/dev/xvdbx", "VirtualName": "ephemeral23"},
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "Encrypted": True,
                            "VolumeType": "mockVolumeType",
                            "VolumeSize": 35,
                            "Iops": 15,
                            "Throughput": 20,
                            "DeleteOnTermination": True,
                        },
                    },
                ],
                id="test with missing volume size in US isolated regions",
            ),
        ],
    )
    def test_get_block_device_mappings(
        self, mocker, root_volume_parameters, root_volume_device_name, region, expected_response
    ):
        mocker.patch("pcluster.config.cluster_config.get_region", return_value=region)
        root_volume = RootVolume(**root_volume_parameters)
        assert_that(
            DictLaunchTemplateBuilder().get_block_device_mappings(root_volume, root_volume_device_name)
        ).is_equal_to(expected_response)

    @pytest.mark.parametrize(
        "queue, compute_resource, expected_response",
        [
            pytest.param(
                BaseQueue(name="queue1", capacity_type="spot"),
                SlurmComputeResource(name="compute1", instance_type="t2.medium", spot_price=10.0),
                {
                    "MarketType": "spot",
                    "SpotOptions": {
                        "SpotInstanceType": "one-time",
                        "InstanceInterruptionBehavior": "terminate",
                        "MaxPrice": "10.0",
                    },
                },
                id="test with spot capacity",
            ),
            pytest.param(
                BaseQueue(name="queue2", capacity_type="spot"),
                SlurmComputeResource(name="compute2", instance_type="t2.medium"),
                {
                    "MarketType": "spot",
                    "SpotOptions": {
                        "SpotInstanceType": "one-time",
                        "InstanceInterruptionBehavior": "terminate",
                    },
                },
                id="test with spot capacity but no spot price",
            ),
            pytest.param(
                BaseQueue(name="queue2", capacity_type="ondemand"),
                SlurmComputeResource(name="compute2", instance_type="t2.medium", spot_price=10.0),
                None,
                id="test without spot capacity",
            ),
        ],
    )
    def test_get_instance_market_options(self, queue, compute_resource, expected_response):
        assert_that(DictLaunchTemplateBuilder().get_instance_market_options(queue, compute_resource)).is_equal_to(
            expected_response
        )

    @pytest.mark.parametrize(
        "queue_parameters, compute_resource, expected_response",
        [
            pytest.param(
                dict(
                    name="queue1",
                    capacity_reservation_target=CapacityReservationTarget(
                        capacity_reservation_resource_group_arn="queue_cr_rg_arn",
                    ),
                    compute_resources=[],
                    networking=None,
                ),
                SlurmComputeResource(
                    name="compute1",
                    instance_type="t2.medium",
                    capacity_reservation_target=CapacityReservationTarget(
                        capacity_reservation_resource_group_arn="comp_res_cr_rg_arn",
                    ),
                ),
                {
                    "CapacityReservationTarget": {
                        "CapacityReservationResourceGroupArn": "comp_res_cr_rg_arn",
                    }
                },
                id="test with queue and compute resource capacity reservation",
            ),
            pytest.param(
                dict(
                    name="queue1",
                    capacity_reservation_target=CapacityReservationTarget(
                        capacity_reservation_id="queue_cr_id",
                    ),
                    compute_resources=[],
                    networking=None,
                ),
                SlurmComputeResource(
                    name="compute1",
                    instance_type="t2.medium",
                ),
                {
                    "CapacityReservationTarget": {
                        "CapacityReservationId": "queue_cr_id",
                    }
                },
                id="test with only queue capacity reservation",
            ),
            pytest.param(
                dict(
                    name="queue1",
                    compute_resources=[],
                    networking=None,
                ),
                SlurmComputeResource(
                    name="compute1",
                    instance_type="t2.medium",
                ),
                None,
                id="test with no capacity reservation",
            ),
        ],
    )
    def test_get_capacity_reservation(self, queue_parameters, compute_resource, expected_response):
        queue = SlurmQueue(**queue_parameters)
        assert_that(DictLaunchTemplateBuilder().get_capacity_reservation(queue, compute_resource)).is_equal_to(
            expected_response
        )


@pytest.mark.parametrize(
    "encryption_settings, expected_error_message",
    [
        (
            [
                ("queue1", True),
                ("queue2", False),
            ],
            "The Encryption parameter of the root volume of the queue queue2 is not consistent with the "
            "value set for the queue queue1, and may cause a problem in case of Service Control Policies "
            "(SCPs) enforcing encryption.",
        ),
        (
            [
                ("queue1", False),
                ("queue2", True),
            ],
            "The Encryption parameter of the root volume of the queue queue2 is not consistent with the "
            "value set for the queue queue1, and may cause a problem in case of Service Control Policies "
            "(SCPs) enforcing encryption.",
        ),
        ([("queue1", True), ("queue2", True)], None),
        ([("queue1", False), ("queue2", False)], None),
    ],
)
def test_root_volume_encryption_consistency_validator(
    encryption_settings,
    expected_error_message,
):
    actual_failures = RootVolumeEncryptionConsistencyValidator().execute(encryption_settings)

    if expected_error_message:
        assert_failure_messages(actual_failures, [expected_error_message])
        assert_failure_level(actual_failures, FailureLevel.WARNING)
    else:
        assert_that(actual_failures).is_empty()


@pytest.mark.parametrize(
    "num_cards, assign_public_ip, public_ip_subnets, expected_error_messages",
    [
        pytest.param(
            1,
            True,
            [
                {"SubnetId": "subnet_1", "MapPublicIpOnLaunch": True},
                {"SubnetId": "subnet_2", "MapPublicIpOnLaunch": False},
            ],
            None,
            id="Test with single nic queue with assigned public ip and subnet with public ip",
        ),
        pytest.param(
            2,
            False,
            [
                {"SubnetId": "subnet_1", "MapPublicIpOnLaunch": False},
                {"SubnetId": "subnet_2", "MapPublicIpOnLaunch": False},
            ],
            None,
            id="Test with multi nic queue with neither assigned public ip nor subnet with public ip",
        ),
        pytest.param(
            2,
            True,
            [
                {"SubnetId": "subnet_1", "MapPublicIpOnLaunch": False},
                {"SubnetId": "subnet_2", "MapPublicIpOnLaunch": False},
            ],
            [
                "The queue queue_1 contains an instance type with multiple network interfaces however the "
                "AssignPublicIp value is set to true. AWS public IPs can only be assigned to instances "
                "launched with a single network interface."
            ],
            id="Test with multi nic queue with assigned public ip and no subnet with public ip",
        ),
        pytest.param(
            2,
            False,
            [
                {"SubnetId": "subnet_1", "MapPublicIpOnLaunch": True},
                {"SubnetId": "subnet_2", "MapPublicIpOnLaunch": False},
            ],
            [
                "The queue queue_1 contains an instance type with multiple network interfaces however the subnets "
                "['subnet_1'] is configured to automatically assign public IPs. AWS public IPs can only be assigned "
                "to instances launched with a single network interface."
            ],
            id="Test with multi nic queue with no assigned public ip and subnet with public ip",
        ),
        pytest.param(
            2,
            True,
            [
                {"SubnetId": "subnet_1", "MapPublicIpOnLaunch": True},
                {"SubnetId": "subnet_2", "MapPublicIpOnLaunch": False},
            ],
            [
                "The queue queue_1 contains an instance type with multiple network interfaces however the "
                "AssignPublicIp value is set to true. AWS public IPs can only be assigned to instances "
                "launched with a single network interface.",
                "The queue queue_1 contains an instance type with multiple network interfaces however the subnets "
                "['subnet_1'] is configured to automatically assign public IPs. AWS public IPs can only be assigned "
                "to instances launched with a single network interface.",
            ],
            id="Test with multi nic queue with assigned public ip and subnet with public ip",
        ),
    ],
)
@pytest.mark.usefixtures("get_region")
def test_multi_network_interfaces_instances_validator(
    aws_api_mock, num_cards, assign_public_ip, public_ip_subnets, expected_error_messages
):
    aws_api_mock.ec2.get_instance_type_info.return_value = InstanceTypeInfo(
        {"NetworkInfo": {"MaximumNetworkCards": num_cards}}
    )
    aws_api_mock.ec2.describe_subnets.return_value = public_ip_subnets

    queues = [
        SlurmQueue(
            name="queue_1",
            compute_resources=[SlurmComputeResource(name="compute_resource_1", instance_type="instance_type")],
            networking=SlurmQueueNetworking(subnet_ids=["subnet_1", "subnet_2"], assign_public_ip=assign_public_ip),
        ),
    ]

    actual_failures = MultiNetworkInterfacesInstancesValidator().execute(queues)

    if expected_error_messages:
        assert_failure_messages(actual_failures, expected_error_messages)
        assert_failure_level(actual_failures, FailureLevel.ERROR)
    else:
        assert_that(actual_failures).is_empty()
