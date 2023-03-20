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
from unittest.mock import PropertyMock, call

from assertpy import assert_that
from pkg_resources import packaging

from pcluster.aws.aws_resources import ImageInfo
from pcluster.constants import Feature
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.utils import get_installed_version, load_yaml_dict
from pcluster.validators import (
    cluster_validators,
    database_validators,
    ebs_validators,
    ec2_validators,
    fsx_validators,
    iam_validators,
    instances_validators,
    kms_validators,
    networking_validators,
    s3_validators,
    scheduler_plugin_validators,
)
from pcluster.validators.common import Validator, ValidatorContext
from tests.pcluster.aws.dummy_aws_api import mock_aws_api


def _mock_all_validators(mocker, mockers, additional_modules=None):
    modules = [
        cluster_validators,
        database_validators,
        ebs_validators,
        ec2_validators,
        fsx_validators,
        kms_validators,
        iam_validators,
        instances_validators,
        networking_validators,
        s3_validators,
    ]
    if additional_modules:
        modules += additional_modules
    for module in modules:
        module_name = module.__name__
        for name, cls in module.__dict__.items():
            if (
                isinstance(cls, type)
                and issubclass(cls, Validator)
                and name != "Validator"
                and not name.startswith("_")
            ):
                mockers.append(
                    {"name": name, "mocker": mocker.patch(f"{module_name}.{name}._validate", return_value=[])}
                )


def _load_and_validate(config_path):
    input_yaml = load_yaml_dict(config_path)
    cluster = ClusterSchema(cluster_name="clustername").load(input_yaml)
    failures = cluster.validate(context=ValidatorContext())
    assert_that(failures).is_empty()


def _assert_instance_architecture(expected_instance_architecture_validator_input, validator):
    for call_index, validator_call in enumerate(validator.call_args_list):
        args, kwargs = validator_call
        instances = [instance_type_info.instance_type() for instance_type_info in kwargs.get("instance_type_info_list")]
        architecture = kwargs.get("architecture")
        expected_instances = expected_instance_architecture_validator_input[call_index].get("instance_types")
        expected_architecture = expected_instance_architecture_validator_input[call_index].get("architecture")

        assert_that(instances).is_length(len(expected_instances))
        assert_that(set(instances) - set(expected_instances)).is_length(0)
        assert_that(architecture).is_equal_to(expected_architecture)


def test_slurm_all_validators_are_called(test_datadir, mocker):
    """Verify that all validators are called during validation."""
    mockers = []
    _mock_all_validators(mocker, mockers)

    # mock properties that use boto3 calls
    mocker.patch(
        "pcluster.config.cluster_config.HeadNode.architecture", new_callable=PropertyMock(return_value="x86_64")
    )
    mocker.patch(
        "pcluster.config.cluster_config.SlurmComputeResource.architecture",
        new_callable=PropertyMock(return_value="x86_64"),
    )
    mocker.patch(
        "pcluster.config.cluster_config.HeadNodeNetworking.availability_zone",
        new_callable=PropertyMock(return_value="us-east-1a"),
    )
    mocker.patch(
        "pcluster.config.cluster_config.BaseClusterConfig.head_node_ami",
        new_callable=PropertyMock(return_value="ami-12345678"),
    )
    mocker.patch(
        "pcluster.config.cluster_config.SlurmClusterConfig.get_instance_types_data",
    )
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo({"BlockDeviceMappings": [{"Ebs": {"VolumeSize": 35}}]}),
    )

    mock_aws_api(mocker)

    # Need to load two configuration files to execute all validators because there are mutually exclusive parameters.
    _load_and_validate(test_datadir / "slurm_1.yaml")
    _load_and_validate(test_datadir / "slurm_2.yaml")

    # Assert validators are called
    for m in mockers:
        if m["name"] in ["TagKeyValidator", "ClusterNameValidator", "InstanceProfileValidator", "RoleValidator"]:
            # ToDo: Reserved tag keys to be aligned between cluster and image builder
            continue
        print("Checking " + m["name"] + " is called")
        m["mocker"].assert_called()


def test_slurm_validators_are_called_with_correct_argument(test_datadir, mocker):
    """Verify that validators are called with proper argument during validation."""
    _mock_all_validators(mocker, [])  # To avoid failure of the test as soon as a new validator is added.

    validators_path = "pcluster.validators"

    cluster_validators = validators_path + ".cluster_validators"
    scheduler_os_validator = mocker.patch(cluster_validators + ".SchedulerOsValidator._validate", return_value=[])
    compute_resource_size_validator = mocker.patch(
        cluster_validators + ".ComputeResourceSizeValidator._validate", return_value=[]
    )
    architecture_os_validator = mocker.patch(cluster_validators + ".ArchitectureOsValidator._validate", return_value=[])
    instance_architecture_compatibility_validator = mocker.patch(
        cluster_validators + ".InstanceArchitectureCompatibilityValidator._validate", return_value=[]
    )
    name_validator = mocker.patch(cluster_validators + ".NameValidator._validate", return_value=[])
    max_count_validator = mocker.patch(cluster_validators + ".MaxCountValidator._validate", return_value=[])
    fsx_architecture_os_validator = mocker.patch(
        cluster_validators + ".FsxArchitectureOsValidator._validate", return_value=[]
    )
    duplicate_mount_dir_validator = mocker.patch(
        cluster_validators + ".DuplicateMountDirValidator._validate", return_value=[]
    )
    number_of_storage_validator = mocker.patch(
        cluster_validators + ".NumberOfStorageValidator._validate", return_value=[]
    )
    deletion_policy_validator = mocker.patch(cluster_validators + ".DeletionPolicyValidator._validate", return_value=[])
    root_volume_encryption_consistency_validator = mocker.patch(
        cluster_validators + ".RootVolumeEncryptionConsistencyValidator._validate", return_value=[]
    )
    ec2_validators = validators_path + ".ec2_validators"
    key_pair_validator = mocker.patch(ec2_validators + ".KeyPairValidator._validate", return_value=[])
    instance_type_validator = mocker.patch(ec2_validators + ".InstanceTypeValidator._validate", return_value=[])
    instance_type_base_ami_compatible_validator = mocker.patch(
        ec2_validators + ".InstanceTypeBaseAMICompatibleValidator._validate", return_value=[]
    )
    instance_type_accelerator_manufacturer_validator = mocker.patch(
        ec2_validators + ".InstanceTypeAcceleratorManufacturerValidator._validate", return_value=[]
    )
    instance_type_placement_group_validator = mocker.patch(
        ec2_validators + ".InstanceTypePlacementGroupValidator._validate", return_value=[]
    )

    networking_validators = validators_path + ".networking_validators"
    security_groups_validator = mocker.patch(
        networking_validators + ".SecurityGroupsValidator._validate", return_value=[]
    )
    subnets_validator = mocker.patch(networking_validators + ".SubnetsValidator._validate", return_value=[])
    single_instance_type_subnet_validator = mocker.patch(
        networking_validators + ".SingleInstanceTypeSubnetValidator._validate", return_value=[]
    )

    fsx_validators = validators_path + ".fsx_validators"
    fsx_s3_validator = mocker.patch(fsx_validators + ".FsxS3Validator._validate", return_value=[])
    fsx_persistent_options_validator = mocker.patch(
        fsx_validators + ".FsxPersistentOptionsValidator._validate", return_value=[]
    )
    fsx_backup_options_validator = mocker.patch(
        fsx_validators + ".FsxBackupOptionsValidator._validate", return_value=[]
    )
    fsx_storage_type_options_validator = mocker.patch(
        fsx_validators + ".FsxStorageTypeOptionsValidator._validate", return_value=[]
    )
    fsx_storage_capacity_validator = mocker.patch(
        fsx_validators + ".FsxStorageCapacityValidator._validate", return_value=[]
    )
    fsx_backup_id_validator = mocker.patch(fsx_validators + ".FsxBackupIdValidator._validate", return_value=[])

    ebs_validators = validators_path + ".ebs_validators"
    ebs_volume_type_size_validator = mocker.patch(
        ebs_validators + ".EbsVolumeTypeSizeValidator._validate", return_value=[]
    )
    ebs_volume_throughput_validator = mocker.patch(
        ebs_validators + ".EbsVolumeThroughputValidator._validate", return_value=[]
    )
    ebs_volume_throughput_iops_validator = mocker.patch(
        ebs_validators + ".EbsVolumeThroughputIopsValidator._validate", return_value=[]
    )
    ebs_volume_iops_validator = mocker.patch(ebs_validators + ".EbsVolumeIopsValidator._validate", return_value=[])
    shared_ebs_volume_id_validator = mocker.patch(
        ebs_validators + ".SharedEbsVolumeIdValidator._validate", return_value=[]
    )
    ebs_volume_size_snapshot_validator = mocker.patch(
        ebs_validators + ".EbsVolumeSizeSnapshotValidator._validate", return_value=[]
    )

    kms_validators = validators_path + ".kms_validators"
    kms_key_validator = mocker.patch(kms_validators + ".KmsKeyValidator._validate", return_value=[])
    kms_key_id_encrypted_validator = mocker.patch(
        kms_validators + ".KmsKeyIdEncryptedValidator._validate", return_value=[]
    )
    monitoring_validators = validators_path + ".monitoring_validators"
    log_rotation_validator = mocker.patch(monitoring_validators + ".LogRotationValidator._validate", return_value=[])

    mocker.patch(
        "pcluster.config.cluster_config.HeadNode.architecture", new_callable=PropertyMock(return_value="x86_64")
    )
    mocker.patch(
        "pcluster.config.cluster_config.SlurmComputeResource.architecture",
        new_callable=PropertyMock(return_value="x86_64"),
    )
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo({"BlockDeviceMappings": [{"Ebs": {"VolumeSize": 35}}]}),
    )

    mock_aws_api(mocker)

    _load_and_validate(test_datadir / "slurm.yaml")

    # Assert validators are called
    scheduler_os_validator.assert_has_calls([call(os="alinux2", scheduler="slurm")])
    compute_resource_size_validator.assert_has_calls(
        [
            # Defaults of min_count=0, max_count=10
            call(min_count=0, max_count=5),
            call(min_count=0, max_count=10),
            call(min_count=0, max_count=10),
            call(min_count=0, max_count=10),
        ],
        any_order=True,
    )
    max_count_validator.assert_has_calls(
        [
            call(max_length=40, resource_name="SlurmQueues", resources_length=2),
            call(max_length=5, resource_name="ComputeResources", resources_length=2),
            call(max_length=5, resource_name="ComputeResources", resources_length=3),
        ],
        any_order=True,
    )
    key_pair_validator.assert_has_calls([call(key_name="ec2-key-name")])
    instance_type_validator.assert_has_calls([call(instance_type="c5d.xlarge")])
    instance_type_base_ami_compatible_validator.assert_has_calls(
        [
            call(instance_type="c5d.xlarge", image="ami-12345678"),
            call(instance_type="t2.large", image="ami-12345678"),
            call(instance_type="c4.2xlarge", image="ami-12345678"),
            call(instance_type="c5.4xlarge", image="ami-12345678"),
            call(instance_type="c5d.xlarge", image="ami-12345678"),
            call(instance_type="t2.large", image="ami-12345678"),
        ],
        any_order=True,
    )
    subnets_validator.assert_has_calls([call(subnet_ids=["subnet-23456789", "subnet-12345678"])])
    single_instance_type_subnet_validator.assert_has_calls(
        [
            call(
                queue_name="queue1",
                subnet_ids=["subnet-23456789"],
            ),
            call(
                queue_name="queue2",
                subnet_ids=["subnet-23456789"],
            ),
        ]
    )
    security_groups_validator.assert_has_calls(
        [call(security_group_ids=None), call(security_group_ids=None)], any_order=True
    )
    architecture_os_validator.assert_has_calls(
        [call(os="alinux2", architecture="x86_64", custom_ami="ami-12345678", ami_search_filters=None)]
    )
    _assert_instance_architecture(
        expected_instance_architecture_validator_input=[
            {"instance_types": ["t2.large"], "architecture": "x86_64"},
            {"instance_types": ["c4.2xlarge"], "architecture": "x86_64"},
            {"instance_types": ["c5.4xlarge"], "architecture": "x86_64"},
            {"instance_types": ["c5d.xlarge"], "architecture": "x86_64"},
            {"instance_types": ["t2.large"], "architecture": "x86_64"},
        ],
        validator=instance_architecture_compatibility_validator,
    )

    root_volume_encryption_consistency_validator.assert_has_calls(
        [call(encryption_settings=[("queue1", True), ("queue2", True)])]
    )
    ebs_volume_type_size_validator.assert_has_calls([call(volume_type="gp3", volume_size=35)])
    kms_key_validator.assert_has_calls([call(kms_key_id="1234abcd-12ab-34cd-56ef-1234567890ab")])
    kms_key_id_encrypted_validator.assert_has_calls(
        [call(kms_key_id="1234abcd-12ab-34cd-56ef-1234567890ab", encrypted=True)]
    )
    fsx_architecture_os_validator.assert_has_calls([call(architecture="x86_64", os="alinux2")])
    # Scratch mount directories are retrieved from a set. So the order of them is not guaranteed.
    # The first item in call_args is regular args, the second item is keyword args.
    shared_storage_name_mount_dir_tuple_list = duplicate_mount_dir_validator.call_args[1][
        "shared_storage_name_mount_dir_tuple_list"
    ]
    shared_storage_name_mount_dir_tuple_list.sort(key=lambda tup: tup[1])
    assert_that(shared_storage_name_mount_dir_tuple_list).is_equal_to(
        [("name1", "/my/mount/point1"), ("name2", "/my/mount/point2"), ("name3", "/my/mount/point3")]
    )
    local_mount_dir_instance_types_dict = duplicate_mount_dir_validator.call_args[1][
        "local_mount_dir_instance_types_dict"
    ]
    assert_that(local_mount_dir_instance_types_dict).is_equal_to(
        {"/scratch": {"c5d.xlarge"}, "/scratch_head": {"c5d.xlarge"}}
    )
    number_of_storage_validator.assert_has_calls(
        [
            call(storage_type="EBS", max_number=5, storage_count=1),
            call(storage_type="existing EFS", max_number=20, storage_count=0),
            call(storage_type="existing FSx", max_number=20, storage_count=0),
            call(storage_type="new EFS", max_number=1, storage_count=1),
            call(storage_type="new FSx", max_number=1, storage_count=1),
            call(storage_type="new RAID", max_number=1, storage_count=0),
        ],
        any_order=True,
    )
    # No assertion on the argument for minor validators
    name_validator.assert_called()
    fsx_s3_validator.assert_called()
    fsx_backup_options_validator.assert_called()
    fsx_storage_type_options_validator.assert_called()
    fsx_storage_capacity_validator.assert_called()
    fsx_backup_id_validator.assert_called()
    ebs_volume_throughput_validator.assert_called()
    ebs_volume_throughput_iops_validator.assert_called()
    ebs_volume_iops_validator.assert_called()
    ebs_volume_size_snapshot_validator.assert_called()
    shared_ebs_volume_id_validator.assert_called()
    fsx_persistent_options_validator.assert_called()
    deletion_policy_validator.assert_called()
    instance_type_accelerator_manufacturer_validator.assert_called()
    instance_type_placement_group_validator.assert_called()
    log_rotation_validator.assert_called()


def test_scheduler_plugin_all_validators_are_called(test_datadir, mocker):
    """Verify that all validators are called during validation."""
    mockers = []
    _mock_all_validators(mocker, mockers, additional_modules=[scheduler_plugin_validators])

    # mock properties that use boto3 calls
    mocker.patch(
        "pcluster.config.cluster_config.HeadNode.architecture", new_callable=PropertyMock(return_value="x86_64")
    )
    mocker.patch(
        "pcluster.config.cluster_config.SchedulerPluginComputeResource.architecture",
        new_callable=PropertyMock(return_value="x86_64"),
    )
    mocker.patch(
        "pcluster.config.cluster_config.HeadNodeNetworking.availability_zone",
        new_callable=PropertyMock(return_value="us-east-1a"),
    )
    mocker.patch(
        "pcluster.config.cluster_config.BaseClusterConfig.head_node_ami",
        new_callable=PropertyMock(return_value="ami-12345678"),
    )
    mocker.patch(
        "pcluster.config.cluster_config.SchedulerPluginClusterConfig.get_instance_types_data",
    )
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo({"BlockDeviceMappings": [{"Ebs": {"VolumeSize": 35}}]}),
    )

    mock_aws_api(mocker)

    # Need to load two configuration files to execute all validators because there are mutually exclusive parameters.
    _load_and_validate(test_datadir / "scheduler_plugin_1.yaml")
    _load_and_validate(test_datadir / "scheduler_plugin_2.yaml")

    # FlexibleInstanceTypes Only supported in Slurm
    flexible_instance_types_validators = [
        "InstancesCPUValidator",
        "InstancesAcceleratorsValidator",
        "InstancesEFAValidator",
        "InstancesNetworkingValidator",
        "InstancesAllocationStrategyValidator",
        "InstancesMemorySchedulingValidator",
    ]

    # Assert validators are called
    for m in mockers:
        if (
            m["name"]
            in [
                "TagKeyValidator",
                "ClusterNameValidator",
                "InstanceProfileValidator",
                "RoleValidator",
                "MixedSecurityGroupOverwriteValidator",
                "HostedZoneValidator",
                "InstanceTypeMemoryInfoValidator",
                "InstanceTypeAcceleratorManufacturerValidator",
                "CapacityReservationValidator",
                "CapacityReservationResourceGroupValidator",
                "DatabaseUriValidator",
                "InstanceTypePlacementGroupValidator",
                "RootVolumeEncryptionConsistencyValidator",
                "MultiNetworkInterfacesInstancesValidator",
            ]
            + flexible_instance_types_validators
        ):
            # ToDo: Reserved tag keys to be aligned between cluster and image builder
            continue
        print("Checking " + m["name"] + " is called")
        m["mocker"].assert_called()


def test_scheduler_plugin_validators_are_called_with_correct_argument(test_datadir, mocker):
    """Verify that validators are called with proper argument during validation."""
    _mock_all_validators(
        mocker, [], additional_modules=[scheduler_plugin_validators]
    )  # To avoid failure of the test as soon as a new validator is added.

    validators_path = "pcluster.validators"

    cluster_validators = validators_path + ".cluster_validators"
    head_node_lt_validator = mocker.patch(
        cluster_validators + ".HeadNodeLaunchTemplateValidator._validate", return_value=[]
    )
    compute_resources_lt_validator = mocker.patch(
        cluster_validators + ".ComputeResourceLaunchTemplateValidator._validate", return_value=[]
    )
    scheduler_os_validator = mocker.patch(cluster_validators + ".SchedulerOsValidator._validate", return_value=[])
    feature_validators = validators_path + ".feature_validators"
    feature_region_validator = mocker.patch(feature_validators + ".FeatureRegionValidator._validate", return_value=[])
    compute_resource_size_validator = mocker.patch(
        cluster_validators + ".ComputeResourceSizeValidator._validate", return_value=[]
    )
    architecture_os_validator = mocker.patch(cluster_validators + ".ArchitectureOsValidator._validate", return_value=[])
    instance_architecture_compatibility_validator = mocker.patch(
        cluster_validators + ".InstanceArchitectureCompatibilityValidator._validate", return_value=[]
    )
    name_validator = mocker.patch(cluster_validators + ".NameValidator._validate", return_value=[])
    max_count_validator = mocker.patch(cluster_validators + ".MaxCountValidator._validate", return_value=[])
    fsx_architecture_os_validator = mocker.patch(
        cluster_validators + ".FsxArchitectureOsValidator._validate", return_value=[]
    )
    duplicate_mount_dir_validator = mocker.patch(
        cluster_validators + ".DuplicateMountDirValidator._validate", return_value=[]
    )
    number_of_storage_validator = mocker.patch(
        cluster_validators + ".NumberOfStorageValidator._validate", return_value=[]
    )

    ec2_validators = validators_path + ".ec2_validators"
    key_pair_validator = mocker.patch(ec2_validators + ".KeyPairValidator._validate", return_value=[])
    instance_type_validator = mocker.patch(ec2_validators + ".InstanceTypeValidator._validate", return_value=[])
    instance_type_base_ami_compatible_validator = mocker.patch(
        ec2_validators + ".InstanceTypeBaseAMICompatibleValidator._validate", return_value=[]
    )

    networking_validators = validators_path + ".networking_validators"
    security_groups_validator = mocker.patch(
        networking_validators + ".SecurityGroupsValidator._validate", return_value=[]
    )
    subnets_validator = mocker.patch(networking_validators + ".SubnetsValidator._validate", return_value=[])
    single_instance_type_subnet_validator = mocker.patch(
        networking_validators + ".SingleInstanceTypeSubnetValidator._validate", return_value=[]
    )

    fsx_validators = validators_path + ".fsx_validators"
    fsx_s3_validator = mocker.patch(fsx_validators + ".FsxS3Validator._validate", return_value=[])
    fsx_persistent_options_validator = mocker.patch(
        fsx_validators + ".FsxPersistentOptionsValidator._validate", return_value=[]
    )
    fsx_backup_options_validator = mocker.patch(
        fsx_validators + ".FsxBackupOptionsValidator._validate", return_value=[]
    )
    fsx_storage_type_options_validator = mocker.patch(
        fsx_validators + ".FsxStorageTypeOptionsValidator._validate", return_value=[]
    )
    fsx_storage_capacity_validator = mocker.patch(
        fsx_validators + ".FsxStorageCapacityValidator._validate", return_value=[]
    )
    fsx_backup_id_validator = mocker.patch(fsx_validators + ".FsxBackupIdValidator._validate", return_value=[])

    ebs_validators = validators_path + ".ebs_validators"
    ebs_volume_type_size_validator = mocker.patch(
        ebs_validators + ".EbsVolumeTypeSizeValidator._validate", return_value=[]
    )
    ebs_volume_throughput_validator = mocker.patch(
        ebs_validators + ".EbsVolumeThroughputValidator._validate", return_value=[]
    )
    ebs_volume_throughput_iops_validator = mocker.patch(
        ebs_validators + ".EbsVolumeThroughputIopsValidator._validate", return_value=[]
    )
    ebs_volume_iops_validator = mocker.patch(ebs_validators + ".EbsVolumeIopsValidator._validate", return_value=[])
    shared_ebs_volume_id_validator = mocker.patch(
        ebs_validators + ".SharedEbsVolumeIdValidator._validate", return_value=[]
    )
    ebs_volume_size_snapshot_validator = mocker.patch(
        ebs_validators + ".EbsVolumeSizeSnapshotValidator._validate", return_value=[]
    )

    kms_validators = validators_path + ".kms_validators"
    kms_key_validator = mocker.patch(kms_validators + ".KmsKeyValidator._validate", return_value=[])
    kms_key_id_encrypted_validator = mocker.patch(
        kms_validators + ".KmsKeyIdEncryptedValidator._validate", return_value=[]
    )

    # Scheduler plugin related validators
    scheduler_plugin = validators_path + ".scheduler_plugin_validators"
    grant_sudo_privileges_validator = mocker.patch(
        scheduler_plugin + ".GrantSudoPrivilegesValidator._validate", return_value=[]
    )
    plugin_interface_version_validator = mocker.patch(
        scheduler_plugin + ".PluginInterfaceVersionValidator._validate", return_value=[]
    )
    scheduler_plugin_os_architecture_validator = mocker.patch(
        scheduler_plugin + ".SchedulerPluginOsArchitectureValidator._validate", return_value=[]
    )
    scheduler_plugin_region_validator = mocker.patch(
        scheduler_plugin + ".SchedulerPluginRegionValidator._validate", return_value=[]
    )
    sudo_privileges_validator = mocker.patch(scheduler_plugin + ".SudoPrivilegesValidator._validate", return_value=[])
    supported_versions_validator = mocker.patch(
        scheduler_plugin + ".SupportedVersionsValidator._validate", return_value=[]
    )
    user_name_validator = mocker.patch(scheduler_plugin + ".UserNameValidator._validate", return_value=[])

    mocker.patch(
        "pcluster.config.cluster_config.HeadNode.architecture", new_callable=PropertyMock(return_value="x86_64")
    )
    mocker.patch(
        "pcluster.config.cluster_config.SlurmComputeResource.architecture",
        new_callable=PropertyMock(return_value="x86_64"),
    )
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo({"BlockDeviceMappings": [{"Ebs": {"VolumeSize": 35}}]}),
    )

    mock_aws_api(mocker)

    _load_and_validate(test_datadir / "scheduler_plugin.yaml")

    # Assert validators are called
    scheduler_os_validator.assert_has_calls([call(os="centos7", scheduler="plugin")])
    feature_region_validator.assert_has_calls(
        [call(feature=feature, region="us-east-1") for feature in Feature if feature is not Feature.BATCH],
        any_order=True,
    )
    compute_resource_size_validator.assert_has_calls(
        [
            # Defaults of min_count=0, max_count=10
            call(min_count=0, max_count=10),
            call(min_count=0, max_count=10),
            call(min_count=0, max_count=10),
            call(min_count=1, max_count=15),
        ],
        any_order=True,
    )
    max_count_validator.assert_has_calls(
        [
            call(max_length=5, resource_name="SchedulerQueues", resources_length=2),
            call(max_length=3, resource_name="ComputeResources", resources_length=2),
            call(max_length=3, resource_name="ComputeResources", resources_length=2),
        ],
        any_order=True,
    )
    key_pair_validator.assert_has_calls([call(key_name="ec2-key-name")])
    instance_type_validator.assert_has_calls([call(instance_type="c5d.xlarge")])
    instance_type_base_ami_compatible_validator.assert_has_calls(
        [
            call(instance_type="c5d.xlarge", image="ami-12345678"),
            call(instance_type="c5.xlarge", image="ami-12345678"),
            call(instance_type="c4.xlarge", image="ami-12345678"),
            call(instance_type="c4.2xlarge", image="ami-23456789"),
            call(instance_type="c5.2xlarge", image="ami-23456789"),
        ],
        any_order=True,
    )
    subnets_validator.assert_has_calls([call(subnet_ids=["subnet-12345678", "subnet-23456789"])])
    single_instance_type_subnet_validator.assert_has_calls(
        [
            call(
                queue_name="queue1",
                subnet_ids=["subnet-12345678"],
            ),
            call(
                queue_name="queue2",
                subnet_ids=["subnet-12345678"],
            ),
        ]
    )
    security_groups_validator.assert_has_calls(
        [call(security_group_ids=None), call(security_group_ids=None)], any_order=True
    )
    architecture_os_validator.assert_has_calls(
        [call(os="centos7", architecture="x86_64", custom_ami="ami-12345678", ami_search_filters=None)]
    )
    _assert_instance_architecture(
        expected_instance_architecture_validator_input=[
            {"instance_types": ["c5.xlarge"], "architecture": "x86_64"},
            {"instance_types": ["c4.xlarge"], "architecture": "x86_64"},
            {"instance_types": ["c4.2xlarge"], "architecture": "x86_64"},
            {"instance_types": ["c5.2xlarge"], "architecture": "x86_64"},
        ],
        validator=instance_architecture_compatibility_validator,
    )

    ebs_volume_type_size_validator.assert_has_calls([call(volume_type="gp3", volume_size=35)])
    kms_key_validator.assert_has_calls([call(kms_key_id="1234abcd-12ab-34cd-56ef-1234567890ab")])
    kms_key_id_encrypted_validator.assert_has_calls(
        [call(kms_key_id="1234abcd-12ab-34cd-56ef-1234567890ab", encrypted=True)]
    )
    fsx_architecture_os_validator.assert_has_calls([call(architecture="x86_64", os="centos7")])
    # Scratch mount directories are retrieved from a set. So the order of them is not guaranteed.
    # The first item in call_args is regular args, the second item is keyword args.
    shared_storage_name_mount_dir_tuple_list = duplicate_mount_dir_validator.call_args[1][
        "shared_storage_name_mount_dir_tuple_list"
    ]
    shared_storage_name_mount_dir_tuple_list.sort(key=lambda tup: tup[1])
    assert_that(shared_storage_name_mount_dir_tuple_list).is_equal_to(
        [
            ("name1", "/my/mount/point1"),
            ("name2", "/my/mount/point2"),
            ("name3", "/my/mount/point3"),
            ("name4", "/my/mount/point4"),
            ("name5", "/my/mount/point5"),
        ]
    )
    local_mount_dir_instance_types_dict = duplicate_mount_dir_validator.call_args[1][
        "local_mount_dir_instance_types_dict"
    ]
    assert_that(local_mount_dir_instance_types_dict).is_equal_to({"/scratch_head": {"c5d.xlarge"}})
    number_of_storage_validator.assert_has_calls(
        [
            call(storage_type="EBS", max_number=5, storage_count=1),
            call(storage_type="existing EFS", max_number=20, storage_count=0),
            call(storage_type="existing FSx", max_number=20, storage_count=2),
            call(storage_type="new EFS", max_number=1, storage_count=1),
            call(storage_type="new FSx", max_number=1, storage_count=1),
            call(storage_type="new RAID", max_number=1, storage_count=0),
        ],
        any_order=True,
    )
    # Scheduler plugin related validators
    plugin_interface_version_validator.assert_has_calls(
        [
            call(
                plugin_version="1.0",
                support_version_high_range=packaging.version.Version("1.0"),
                support_version_low_range=packaging.version.Version("1.0"),
            )
        ]
    )
    scheduler_plugin_os_architecture_validator.assert_has_calls(
        [
            call(
                architecture="x86_64",
                os="centos7",
                supported_arm64=["ubuntu1804"],
                supported_x86=["ubuntu18", "centos7"],
            )
        ]
    )
    scheduler_plugin_region_validator.assert_has_calls(
        [call(region="us-east-1", supported_regions=["cn-north-1", "us-east-1"])]
    )
    sudo_privileges_validator.assert_has_calls([call(grant_sudo_privileges=True, requires_sudo_privileges=False)])
    supported_versions_validator.assert_has_calls(
        [call(installed_version=get_installed_version(), supported_versions_string=">=3.1.0, <=3.4.2")]
    )
    user_name_validator.assert_has_calls([call(user_name="user1"), call(user_name="user2")])

    # No assertion on the argument for minor validators
    head_node_lt_validator.assert_called_once()
    compute_resources_lt_validator.assert_called_once()
    name_validator.assert_called()
    fsx_s3_validator.assert_called()
    fsx_backup_options_validator.assert_called()
    fsx_storage_type_options_validator.assert_called()
    fsx_storage_capacity_validator.assert_called()
    fsx_backup_id_validator.assert_called()
    ebs_volume_throughput_validator.assert_called()
    ebs_volume_throughput_iops_validator.assert_called()
    ebs_volume_iops_validator.assert_called()
    ebs_volume_size_snapshot_validator.assert_called()
    shared_ebs_volume_id_validator.assert_called()
    fsx_persistent_options_validator.assert_called()
    grant_sudo_privileges_validator.assert_called()
