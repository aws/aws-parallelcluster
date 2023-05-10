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

from pcluster.aws.aws_resources import ImageInfo
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.utils import load_yaml_dict
from pcluster.validators import (
    cluster_validators,
    database_validators,
    ebs_validators,
    ec2_validators,
    fsx_validators,
    iam_validators,
    instances_validators,
    kms_validators,
    monitoring_validators,
    networking_validators,
    s3_validators,
    slurm_settings_validator,
    tags_validators,
)
from pcluster.validators.common import AsyncValidator, Validator, ValidatorContext
from tests.pcluster.aws.dummy_aws_api import mock_aws_api


def _is_validator_of_type(cls, name, validator_type):
    return (
        isinstance(cls, type)
        and issubclass(cls, validator_type)
        and name != "Validator"
        and name != "AsyncValidator"
        and not name.startswith("_")
    )


def _mock_all_validators(mocker, additional_modules=None):
    mockers = []
    async_mockers = []

    # when python 3.7 support is dropped, this can be substituted with AsyncMockc
    def create_validate_async_mock():
        _awaited = False

        async def _validate_async(*args, **kwargs):
            nonlocal _awaited
            _awaited = True
            return []

        _validate_async.assert_awaited = lambda: assert_that(_awaited).is_true()

        return _validate_async

    modules = [
        cluster_validators,
        database_validators,
        ebs_validators,
        ec2_validators,
        fsx_validators,
        kms_validators,
        iam_validators,
        instances_validators,
        monitoring_validators,
        networking_validators,
        s3_validators,
        slurm_settings_validator,
        tags_validators,
    ]
    if additional_modules:
        modules += additional_modules
    for module in modules:
        module_name = module.__name__
        for name, cls in module.__dict__.items():
            if _is_validator_of_type(cls, name, AsyncValidator):
                mock = create_validate_async_mock()
                mocker.patch(f"{module_name}.{name}._validate_async", side_effect=mock)
                async_mockers.append(
                    {
                        "name": name,
                        "mocker": mock,
                    }
                )
            elif _is_validator_of_type(cls, name, Validator):
                mockers.append(
                    {"name": name, "mocker": mocker.patch(f"{module_name}.{name}._validate", return_value=[])}
                )
    return mockers, async_mockers


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
    mockers, async_mockers = _mock_all_validators(mocker)

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
        print(f"Checking validator of class \"{m['name']}\" is called")
        m["mocker"].assert_called()

    for m in async_mockers:
        print(f"Checking validator of class \"{m['name']}\" is awaited")
        m["mocker"].assert_awaited()


def test_slurm_validators_are_called_with_correct_argument(test_datadir, mocker):
    """Verify that validators are called with proper argument during validation."""
    # To avoid failure of the test as soon as a new validator is added.
    _mock_all_validators(mocker)

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
    detailed_monitoring_validator = mocker.patch(
        monitoring_validators + ".DetailedMonitoringValidator._validate", return_value=[]
    )
    tags_validators = validators_path + ".tags_validators"
    compute_resource_tags_validator = mocker.patch(
        tags_validators + ".ComputeResourceTagsValidator._validate", return_value=[]
    )
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
            call(resources_length=2, max_length=50, resource_name="SlurmQueues"),
            call(resources_length=5, max_length=50, resource_name="ComputeResources per Cluster"),
            call(resources_length=3, max_length=50, resource_name="ComputeResources per Queue"),
            call(resources_length=2, max_length=50, resource_name="ComputeResources per Queue"),
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
    detailed_monitoring_validator.assert_called()
    compute_resource_tags_validator.assert_called()
