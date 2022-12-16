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
#
# This module contains all the classes representing the Resources objects.
# These objects are obtained from the configuration file through a conversion based on the Schema classes.
#
import logging
from abc import abstractmethod
from collections import defaultdict
from enum import Enum
from typing import Dict, List, Union

import pkg_resources

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.aws_resources import InstanceTypeInfo
from pcluster.aws.common import AWSClientError, get_region
from pcluster.config.common import AdditionalIamPolicy, BaseDevSettings, BaseTag, DeploymentSettings
from pcluster.config.common import Imds as TopLevelImds
from pcluster.config.common import Resource
from pcluster.constants import (
    CIDR_ALL_IPS,
    CW_DASHBOARD_ENABLED_DEFAULT,
    CW_LOGS_ENABLED_DEFAULT,
    CW_LOGS_RETENTION_DAYS_DEFAULT,
    DEFAULT_EPHEMERAL_DIR,
    DEFAULT_MAX_COUNT,
    DEFAULT_MIN_COUNT,
    DELETE_POLICY,
    EBS_VOLUME_SIZE_DEFAULT,
    EBS_VOLUME_TYPE_DEFAULT,
    EBS_VOLUME_TYPE_IOPS_DEFAULT,
    LUSTRE,
    MAX_EBS_COUNT,
    MAX_EXISTING_STORAGE_COUNT,
    MAX_NEW_STORAGE_COUNT,
    MAX_NUMBER_OF_COMPUTE_RESOURCES,
    MAX_NUMBER_OF_QUEUES,
    NODE_BOOTSTRAP_TIMEOUT,
    ONTAP,
    OPENZFS,
    SCHEDULER_PLUGIN_INTERFACE_VERSION,
    SCHEDULER_PLUGIN_INTERFACE_VERSION_LOW_RANGE,
    SUPPORTED_OSES,
)
from pcluster.utils import (
    get_attr,
    get_installed_version,
    get_partition,
    get_resource_name_from_resource_arn,
    replace_url_parameters,
    to_snake_case,
)
from pcluster.validators.awsbatch_validators import (
    AwsBatchComputeInstanceTypeValidator,
    AwsBatchComputeResourceSizeValidator,
    AwsBatchFsxValidator,
    AwsBatchInstancesArchitectureCompatibilityValidator,
    AwsBatchRegionValidator,
)
from pcluster.validators.cluster_validators import (
    ArchitectureOsValidator,
    ClusterNameValidator,
    ComputeResourceLaunchTemplateValidator,
    ComputeResourceSizeValidator,
    CustomAmiTagValidator,
    DcvValidator,
    DeletionPolicyValidator,
    DuplicateMountDirValidator,
    DuplicateNameValidator,
    EfaMultiAzValidator,
    EfaOsArchitectureValidator,
    EfaPlacementGroupValidator,
    EfaSecurityGroupValidator,
    EfaValidator,
    EfsIdValidator,
    ExistingFsxNetworkingValidator,
    FsxArchitectureOsValidator,
    HeadNodeImdsValidator,
    HeadNodeLaunchTemplateValidator,
    HostedZoneValidator,
    InstanceArchitectureCompatibilityValidator,
    IntelHpcArchitectureValidator,
    IntelHpcOsValidator,
    ManagedFsxMultiAzValidator,
    MaxCountValidator,
    MixedSecurityGroupOverwriteValidator,
    NameValidator,
    NumberOfStorageValidator,
    OverlappingMountDirValidator,
    RegionValidator,
    RootVolumeSizeValidator,
    SchedulableMemoryValidator,
    SchedulerOsValidator,
    SchedulerValidator,
    SharedStorageMountDirValidator,
    SharedStorageNameValidator,
    UnmanagedFsxMultiAzValidator,
)
from pcluster.validators.common import ValidatorContext
from pcluster.validators.database_validators import DatabaseUriValidator
from pcluster.validators.directory_service_validators import (
    AdditionalSssdConfigsValidator,
    DomainAddrValidator,
    DomainNameValidator,
    LdapTlsReqCertValidator,
    PasswordSecretArnValidator,
)
from pcluster.validators.ebs_validators import (
    EbsVolumeIopsValidator,
    EbsVolumeSizeSnapshotValidator,
    EbsVolumeThroughputIopsValidator,
    EbsVolumeThroughputValidator,
    EbsVolumeTypeSizeValidator,
    MultiAzEbsVolumeValidator,
    MultiAzRootVolumeValidator,
    SharedEbsVolumeIdValidator,
)
from pcluster.validators.ec2_validators import (
    AmiOsCompatibleValidator,
    CapacityReservationResourceGroupValidator,
    CapacityReservationValidator,
    CapacityTypeValidator,
    InstanceTypeAcceleratorManufacturerValidator,
    InstanceTypeBaseAMICompatibleValidator,
    InstanceTypeMemoryInfoValidator,
    InstanceTypePlacementGroupValidator,
    InstanceTypeValidator,
    KeyPairValidator,
    PlacementGroupCapacityReservationValidator,
    PlacementGroupNamingValidator,
)
from pcluster.validators.efs_validators import EfsMountOptionsValidator
from pcluster.validators.fsx_validators import (
    FsxAutoImportValidator,
    FsxBackupIdValidator,
    FsxBackupOptionsValidator,
    FsxPersistentOptionsValidator,
    FsxS3Validator,
    FsxStorageCapacityValidator,
    FsxStorageTypeOptionsValidator,
)
from pcluster.validators.iam_validators import (
    IamPolicyValidator,
    IamResourcePrefixValidator,
    InstanceProfileValidator,
    RoleValidator,
)
from pcluster.validators.instances_validators import (
    InstancesAcceleratorsValidator,
    InstancesAllocationStrategyValidator,
    InstancesCPUValidator,
    InstancesEFAValidator,
    InstancesMemorySchedulingValidator,
    InstancesNetworkingValidator,
)
from pcluster.validators.kms_validators import KmsKeyIdEncryptedValidator, KmsKeyValidator
from pcluster.validators.networking_validators import (
    ElasticIpValidator,
    MultiAzPlacementGroupValidator,
    QueueSubnetsValidator,
    SecurityGroupsValidator,
    SingleInstanceTypeSubnetValidator,
    SubnetsValidator,
)
from pcluster.validators.s3_validators import (
    S3BucketRegionValidator,
    S3BucketUriValidator,
    S3BucketValidator,
    UrlValidator,
)
from pcluster.validators.scheduler_plugin_validators import (
    GrantSudoPrivilegesValidator,
    PluginInterfaceVersionValidator,
    SchedulerPluginOsArchitectureValidator,
    SchedulerPluginRegionValidator,
    SudoPrivilegesValidator,
    SupportedVersionsValidator,
    UserNameValidator,
)

LOGGER = logging.getLogger(__name__)

# pylint: disable=C0302

# ---------------------- Storage ---------------------- #


class Ebs(Resource):
    """Represent the configuration shared by EBS root volume and Shared EBS."""

    def __init__(
        self,
        encrypted: bool = None,
        volume_type: str = None,
        iops: int = None,
        throughput: int = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.encrypted = Resource.init_param(encrypted, default=True)
        self.volume_type = Resource.init_param(volume_type, default=EBS_VOLUME_TYPE_DEFAULT)
        self.iops = Resource.init_param(iops, default=EBS_VOLUME_TYPE_IOPS_DEFAULT.get(self.volume_type))
        self.throughput = Resource.init_param(throughput, default=125 if self.volume_type == "gp3" else None)

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(
            EbsVolumeThroughputValidator, volume_type=self.volume_type, volume_throughput=self.throughput
        )
        self._register_validator(
            EbsVolumeThroughputIopsValidator,
            volume_type=self.volume_type,
            volume_iops=self.iops,
            volume_throughput=self.throughput,
        )


class RootVolume(Ebs):
    """Represent the root volume configuration."""

    def __init__(self, size: int = None, delete_on_termination: bool = None, **kwargs):
        super().__init__(**kwargs)
        self.size = Resource.init_param(size)
        # The default delete_on_termination takes effect both on head and compute nodes.
        # If the default of the head node is to be changed, please separate this class for different defaults.
        self.delete_on_termination = Resource.init_param(delete_on_termination, default=True)


class Raid(Resource):
    """Represent the Raid configuration."""

    def __init__(self, raid_type: int, number_of_volumes=None):
        super().__init__()
        self.raid_type = Resource.init_param(raid_type)
        self.number_of_volumes = Resource.init_param(number_of_volumes, default=2)


class EphemeralVolume(Resource):
    """Represent the Ephemeral Volume resource."""

    def __init__(self, mount_dir: str = None):
        super().__init__()
        self.mount_dir = Resource.init_param(mount_dir, default=DEFAULT_EPHEMERAL_DIR)


class LocalStorage(Resource):
    """Represent the entire node storage configuration."""

    def __init__(self, root_volume: RootVolume = None, ephemeral_volume: EphemeralVolume = None, **kwargs):
        super().__init__(**kwargs)
        self.root_volume = root_volume or RootVolume(implied=True)
        self.ephemeral_volume = ephemeral_volume


class SharedStorageType(Enum):
    """Define storage types to be used as shared storage."""

    EBS = "ebs"
    RAID = "raid"
    EFS = "efs"
    FSX = "fsx"


class SharedEbs(Ebs):
    """Represent a shared EBS, inherits from both _SharedStorage and Ebs classes."""

    def __init__(
        self,
        mount_dir: str,
        name: str,
        size: int = None,
        kms_key_id: str = None,
        snapshot_id: str = None,
        volume_id: str = None,
        raid: Raid = None,
        deletion_policy: str = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.size = Resource.init_param(size, default=EBS_VOLUME_SIZE_DEFAULT)
        self.kms_key_id = Resource.init_param(kms_key_id)
        self.mount_dir = Resource.init_param(mount_dir)
        self.name = Resource.init_param(name)
        self.shared_storage_type = SharedStorageType.RAID if raid else SharedStorageType.EBS
        self.snapshot_id = Resource.init_param(snapshot_id)
        self.volume_id = Resource.init_param(volume_id)
        self.raid = raid
        self.deletion_policy = Resource.init_param(deletion_policy, default=DELETE_POLICY if not volume_id else None)

    def _register_validators(self, context: ValidatorContext = None):
        super()._register_validators(context)
        self._register_validator(EbsVolumeTypeSizeValidator, volume_type=self.volume_type, volume_size=self.size)
        self._register_validator(
            EbsVolumeIopsValidator, volume_type=self.volume_type, volume_size=self.size, volume_iops=self.iops
        )
        self._register_validator(SharedStorageNameValidator, name=self.name)
        if self.kms_key_id:
            self._register_validator(KmsKeyValidator, kms_key_id=self.kms_key_id)
            self._register_validator(KmsKeyIdEncryptedValidator, kms_key_id=self.kms_key_id, encrypted=self.encrypted)
        self._register_validator(
            SharedEbsVolumeIdValidator,
            volume_id=self.volume_id,
            head_node_instance_id=context.head_node_instance_id,
        )
        self._register_validator(EbsVolumeSizeSnapshotValidator, snapshot_id=self.snapshot_id, volume_size=self.size)
        self._register_validator(DeletionPolicyValidator, deletion_policy=self.deletion_policy, name=self.name)

    @property
    def is_managed(self):
        """Return True if the volume is managed."""
        return self.volume_id is None

    @property
    def availability_zone(self):
        """Return the availability zone of an existing EBS volume."""
        if not self.is_managed:
            return AWSApi.instance().ec2.describe_volume(self.volume_id)["AvailabilityZone"]
        else:
            return ""


class SharedEfs(Resource):
    """Represent the shared EFS resource."""

    def __init__(
        self,
        mount_dir: str,
        name: str,
        encrypted: bool = None,
        kms_key_id: str = None,
        performance_mode: str = None,
        throughput_mode: str = None,
        provisioned_throughput: int = None,
        file_system_id: str = None,
        deletion_policy: str = None,
        encryption_in_transit: bool = None,
        iam_authorization: bool = None,
    ):
        super().__init__()
        self.mount_dir = Resource.init_param(mount_dir)
        self.name = Resource.init_param(name)
        self.shared_storage_type = SharedStorageType.EFS
        self.encrypted = Resource.init_param(encrypted, default=False)
        self.kms_key_id = Resource.init_param(kms_key_id)
        self.performance_mode = Resource.init_param(performance_mode, default="generalPurpose")
        self.throughput_mode = Resource.init_param(throughput_mode, default="bursting")
        self.provisioned_throughput = Resource.init_param(provisioned_throughput)
        self.file_system_id = Resource.init_param(file_system_id)
        self.deletion_policy = Resource.init_param(
            deletion_policy, default=DELETE_POLICY if not file_system_id else None
        )
        self.encryption_in_transit = Resource.init_param(encryption_in_transit, default=False)
        self.iam_authorization = Resource.init_param(iam_authorization, default=False)

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(SharedStorageNameValidator, name=self.name)
        if self.kms_key_id:
            self._register_validator(KmsKeyValidator, kms_key_id=self.kms_key_id)
            self._register_validator(KmsKeyIdEncryptedValidator, kms_key_id=self.kms_key_id, encrypted=self.encrypted)
        self._register_validator(DeletionPolicyValidator, deletion_policy=self.deletion_policy, name=self.name)
        self._register_validator(
            EfsMountOptionsValidator,
            encryption_in_transit=self.encryption_in_transit,
            iam_authorization=self.iam_authorization,
            name=self.name,
        )


class BaseSharedFsx(Resource):
    """Represent the shared FSX resource."""

    def __init__(self, mount_dir: str, name: str):
        super().__init__()
        self.mount_dir = Resource.init_param(mount_dir)
        self.name = Resource.init_param(name)
        self.shared_storage_type = SharedStorageType.FSX
        self.__file_system_data = None

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(SharedStorageNameValidator, name=self.name)

    @property
    def is_unmanaged(self):
        """Return true if using existing FSx."""
        return self.file_system_id is not None

    @property
    def file_system_data(self):
        """Return filesystem information if using existing FSx."""
        if not self.__file_system_data and self.is_unmanaged:
            self.__file_system_data = AWSApi.instance().fsx.get_file_systems_info([self.file_system_id])[0]
        return self.__file_system_data

    @property
    def file_system_subnets(self):
        """Return list of subnets associated to existing FSx."""
        return self.file_system_data.subnet_ids if self.is_unmanaged else []

    @property
    def file_system_availability_zones(self):
        """Return list of AZ associated to existing FSx."""
        availability_zones = []
        if self.is_unmanaged:
            mapping = AWSApi.instance().ec2.get_subnets_az_mapping(self.file_system_subnets)
            for availability_zone in mapping.values():
                availability_zones.append(availability_zone)

        return availability_zones

    @property
    def existing_dns_name(self):
        """Return DNSName if using existing FSx filesystem."""
        return self.file_system_data.dns_name if self.is_unmanaged else ""


class SharedFsxLustre(BaseSharedFsx):
    """Represent the shared FSX resource."""

    def __init__(
        self,
        storage_capacity: int = None,
        deployment_type: str = None,
        data_compression_type: str = None,
        export_path: str = None,
        import_path: str = None,
        imported_file_chunk_size: int = None,
        weekly_maintenance_start_time: str = None,
        automatic_backup_retention_days: int = None,
        copy_tags_to_backups: bool = None,
        daily_automatic_backup_start_time: str = None,
        per_unit_storage_throughput: int = None,
        backup_id: str = None,
        kms_key_id: str = None,
        file_system_id: str = None,
        auto_import_policy: str = None,
        drive_cache_type: str = None,
        fsx_storage_type: str = None,
        deletion_policy: str = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.storage_capacity = Resource.init_param(storage_capacity)
        self.fsx_storage_type = Resource.init_param(fsx_storage_type)
        self.deployment_type = Resource.init_param(
            deployment_type, default="SCRATCH_2" if backup_id is None and file_system_id is None else None
        )
        self.data_compression_type = Resource.init_param(data_compression_type)
        self.export_path = Resource.init_param(export_path)
        self.import_path = Resource.init_param(import_path)
        self.imported_file_chunk_size = Resource.init_param(imported_file_chunk_size)
        self.weekly_maintenance_start_time = Resource.init_param(weekly_maintenance_start_time)
        self.automatic_backup_retention_days = Resource.init_param(automatic_backup_retention_days)
        self.copy_tags_to_backups = Resource.init_param(copy_tags_to_backups)
        self.daily_automatic_backup_start_time = Resource.init_param(daily_automatic_backup_start_time)
        self.per_unit_storage_throughput = Resource.init_param(per_unit_storage_throughput)
        self.backup_id = Resource.init_param(backup_id)
        self.kms_key_id = Resource.init_param(kms_key_id)
        self.file_system_id = Resource.init_param(file_system_id)
        self.auto_import_policy = Resource.init_param(auto_import_policy)
        self.drive_cache_type = Resource.init_param(drive_cache_type)
        self.file_system_type = LUSTRE
        self.file_system_type_version = "2.12" if backup_id is None and file_system_id is None else None
        self.deletion_policy = Resource.init_param(
            deletion_policy, default=DELETE_POLICY if not file_system_id else None
        )

    def _register_validators(self, context: ValidatorContext = None):
        super()._register_validators(context)
        self._register_validator(
            FsxS3Validator,
            import_path=self.import_path,
            imported_file_chunk_size=self.imported_file_chunk_size,
            export_path=self.export_path,
            auto_import_policy=self.auto_import_policy,
        )
        self._register_validator(
            FsxPersistentOptionsValidator,
            deployment_type=self.deployment_type,
            kms_key_id=self.kms_key_id,
            per_unit_storage_throughput=self.per_unit_storage_throughput,
        )
        self._register_validator(
            FsxBackupOptionsValidator,
            automatic_backup_retention_days=self.automatic_backup_retention_days,
            daily_automatic_backup_start_time=self.daily_automatic_backup_start_time,
            copy_tags_to_backups=self.copy_tags_to_backups,
            deployment_type=self.deployment_type,
            imported_file_chunk_size=self.imported_file_chunk_size,
            import_path=self.import_path,
            export_path=self.export_path,
            auto_import_policy=self.auto_import_policy,
        )
        self._register_validator(
            FsxStorageTypeOptionsValidator,
            fsx_storage_type=self.fsx_storage_type,
            deployment_type=self.deployment_type,
            per_unit_storage_throughput=self.per_unit_storage_throughput,
            drive_cache_type=self.drive_cache_type,
        )
        self._register_validator(
            FsxStorageCapacityValidator,
            storage_capacity=self.storage_capacity,
            deployment_type=self.deployment_type,
            fsx_storage_type=self.fsx_storage_type,
            per_unit_storage_throughput=self.per_unit_storage_throughput,
            file_system_id=self.file_system_id,
            backup_id=self.backup_id,
        )
        self._register_validator(FsxBackupIdValidator, backup_id=self.backup_id)

        if self.import_path:
            self._register_validator(S3BucketUriValidator, url=self.import_path)
        if self.export_path:
            self._register_validator(S3BucketUriValidator, url=self.export_path)
        if self.kms_key_id:
            self._register_validator(KmsKeyValidator, kms_key_id=self.kms_key_id)
        if self.auto_import_policy:
            self._register_validator(
                FsxAutoImportValidator, auto_import_policy=self.auto_import_policy, import_path=self.import_path
            )
        self._register_validator(DeletionPolicyValidator, deletion_policy=self.deletion_policy, name=self.name)

    @property
    def existing_mount_name(self):
        """Return MountName if using existing FSx filesystem."""
        return self.file_system_data.mount_name if self.file_system_id else ""


class ExistingFsxOpenZfs(BaseSharedFsx):
    """Represent the shared FSX for OpenZFS resource."""

    def __init__(self, volume_id: str, **kwargs):
        super().__init__(**kwargs)
        self.volume_id = volume_id
        self.file_system_type = OPENZFS

    @property
    def file_system_id(self):
        """Return the file system id behind the volume."""
        return AWSApi.instance().fsx.describe_volumes([self.volume_id])[0]["FileSystemId"]

    @property
    def volume_path(self):
        """Return the volume path."""
        return AWSApi.instance().fsx.describe_volumes([self.volume_id])[0]["OpenZFSConfiguration"]["VolumePath"]


class ExistingFsxOntap(BaseSharedFsx):
    """Represent the shared FSX for Ontap resource."""

    def __init__(self, volume_id: str, **kwargs):
        super().__init__(**kwargs)
        self.volume_id = volume_id
        self.file_system_type = ONTAP

    @property
    def file_system_id(self):
        """Return the file system id behind the volume."""
        return AWSApi.instance().fsx.describe_volumes([self.volume_id])[0]["FileSystemId"]

    @property
    def storage_virtual_machine_id(self):
        """Return the storage virtual machine behind the volume."""
        return AWSApi.instance().fsx.describe_volumes([self.volume_id])[0]["OntapConfiguration"][
            "StorageVirtualMachineId"
        ]

    @property
    def junction_path(self):
        """Return the junction path."""
        return AWSApi.instance().fsx.describe_volumes([self.volume_id])[0]["OntapConfiguration"]["JunctionPath"]

    @property
    def existing_dns_name(self):
        """Return DNSName of the SVM of existing FSx filesystem."""
        return AWSApi.instance().fsx.describe_storage_virtual_machines([self.storage_virtual_machine_id])[0][
            "Endpoints"
        ]["Nfs"]["DNSName"]


# ---------------------- Networking ---------------------- #


class Proxy(Resource):
    """Represent the proxy."""

    def __init__(self, http_proxy_address: str = None):
        super().__init__()
        self.http_proxy_address = http_proxy_address


class _BaseNetworking(Resource):
    """Represent the networking configuration shared by head node and compute node."""

    def __init__(self, security_groups: List[str] = None, additional_security_groups: List[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.security_groups = Resource.init_param(security_groups)
        self.additional_security_groups = Resource.init_param(additional_security_groups)

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(SecurityGroupsValidator, security_group_ids=self.security_groups)
        self._register_validator(SecurityGroupsValidator, security_group_ids=self.additional_security_groups)


class HeadNodeNetworking(_BaseNetworking):
    """Represent the networking configuration for the head node."""

    def __init__(self, subnet_id: str, elastic_ip: Union[str, bool] = None, proxy: Proxy = None, **kwargs):
        super().__init__(**kwargs)
        self.subnet_id = Resource.init_param(subnet_id)
        self.elastic_ip = Resource.init_param(elastic_ip)
        self.proxy = proxy

    def _register_validators(self, context: ValidatorContext = None):
        super()._register_validators(context)
        self._register_validator(ElasticIpValidator, elastic_ip=self.elastic_ip)

    @property
    def availability_zone(self):
        """Compute availability zone from subnet id."""
        return AWSApi.instance().ec2.get_subnet_avail_zone(self.subnet_id)


class PlacementGroup(Resource):
    """Represent the placement group for networking."""

    def __init__(self, enabled: bool = None, name: str = None, id: str = None, **kwargs):
        super().__init__(**kwargs)
        self.enabled = Resource.init_param(enabled)
        self.name = Resource.init_param(name)
        self.id = Resource.init_param(id)  # Duplicate of name

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(PlacementGroupNamingValidator, placement_group=self)

    @property
    def assignment(self) -> str:
        """Check if the placement group has a name or id and get it, preferring the name if it exists."""
        return self.name or self.id

    @property
    def enabled_or_assigned(self):
        """Check if a placement group was enabled or passed as parameter."""
        return self.enabled or self.assignment is not None


class SlurmComputeResourceNetworking(Resource):
    """Represent the networking configuration for the compute resource."""

    def __init__(self, placement_group: PlacementGroup = None, **kwargs):
        super().__init__(**kwargs)
        self.placement_group = placement_group or PlacementGroup(implied=True)


class _QueueNetworking(_BaseNetworking):
    """Represent the networking configuration for the Queue."""

    def __init__(self, subnet_ids: List[str], assign_public_ip: str = None, **kwargs):
        super().__init__(**kwargs)
        self.assign_public_ip = Resource.init_param(assign_public_ip)
        self.subnet_ids = Resource.init_param(subnet_ids)
        self._az_subnet_ids_mapping = None

    @property
    def subnet_id_az_mapping(self):
        """Map queue subnet ids to availability zones."""
        return AWSApi.instance().ec2.get_subnets_az_mapping(self.subnet_ids)

    @property
    def az_subnet_ids_mapping(self):
        """Map queue subnet ids to availability zones."""
        if not self._az_subnet_ids_mapping:
            self._az_subnet_ids_mapping = defaultdict(set)
            for subnet_id, _az in self.subnet_id_az_mapping.items():
                self._az_subnet_ids_mapping[_az].add(subnet_id)
        return self._az_subnet_ids_mapping

    @property
    def az_list(self):
        return list(self.az_subnet_ids_mapping.keys())


class SlurmQueueNetworking(_QueueNetworking):
    """Represent the networking configuration for the slurm Queue."""

    def __init__(self, placement_group: PlacementGroup = None, proxy: Proxy = None, **kwargs):
        super().__init__(**kwargs)
        self.placement_group = placement_group or PlacementGroup(implied=True)
        self.proxy = proxy


class AwsBatchQueueNetworking(_QueueNetworking):
    """Represent the networking configuration for the aws batch Queue."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class SchedulerPluginQueueNetworking(SlurmQueueNetworking):
    """Represent the networking configuration for the Scheduler Plugin Queue."""

    pass


class Ssh(Resource):
    """Represent the SSH configuration for a node."""

    def __init__(self, key_name: str = None, allowed_ips: str = None, **kwargs):
        super().__init__(**kwargs)
        self.key_name = Resource.init_param(key_name)
        self.allowed_ips = Resource.init_param(allowed_ips, default=CIDR_ALL_IPS)

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(KeyPairValidator, key_name=self.key_name)


class Dcv(Resource):
    """Represent the DCV configuration."""

    def __init__(self, enabled: bool, port: int = None, allowed_ips: str = None):
        super().__init__()
        self.enabled = Resource.init_param(enabled)
        self.port = Resource.init_param(port, default=8443)
        self.allowed_ips = Resource.init_param(allowed_ips, default=CIDR_ALL_IPS)


class Efa(Resource):
    """Represent the EFA configuration."""

    def __init__(self, enabled: bool = None, gdr_support: bool = None, **kwargs):
        super().__init__(**kwargs)
        self.enabled = enabled
        self.gdr_support = Resource.init_param(gdr_support, default=False)


# ---------------------- Monitoring ---------------------- #


class CloudWatchLogs(Resource):
    """Represent the CloudWatch configuration in Logs."""

    def __init__(self, enabled: bool = None, retention_in_days: int = None, deletion_policy: str = None, **kwargs):
        super().__init__(**kwargs)
        self.enabled = Resource.init_param(enabled, default=CW_LOGS_ENABLED_DEFAULT)
        self.retention_in_days = Resource.init_param(retention_in_days, default=CW_LOGS_RETENTION_DAYS_DEFAULT)
        self.deletion_policy = Resource.init_param(deletion_policy, default="Retain")


class CloudWatchDashboards(Resource):
    """Represent the CloudWatch Dashboard."""

    def __init__(self, enabled: bool = None, **kwargs):
        super().__init__(**kwargs)
        self.enabled = Resource.init_param(enabled, default=CW_DASHBOARD_ENABLED_DEFAULT)


class Logs(Resource):
    """Represent the CloudWatch Logs configuration."""

    def __init__(self, cloud_watch: CloudWatchLogs = None, **kwargs):
        super().__init__(**kwargs)
        self.cloud_watch = cloud_watch or CloudWatchLogs(implied=True)


class Dashboards(Resource):
    """Represent the Dashboards configuration."""

    def __init__(self, cloud_watch: CloudWatchDashboards = None, **kwargs):
        super().__init__(**kwargs)
        self.cloud_watch = cloud_watch or CloudWatchDashboards(implied=True)


class Monitoring(Resource):
    """Represent the Monitoring configuration."""

    def __init__(self, detailed_monitoring: bool = None, logs: Logs = None, dashboards: Dashboards = None, **kwargs):
        super().__init__(**kwargs)
        self.detailed_monitoring = Resource.init_param(detailed_monitoring, default=False)
        self.logs = logs or Logs(implied=True)
        self.dashboards = dashboards or Dashboards(implied=True)


# ---------------------- Others ---------------------- #


class Tag(BaseTag):
    """Represent the Tag configuration."""

    def __init__(self, key: str = None, value: str = None):
        super().__init__(key, value)


class Roles(Resource):
    """Represent the Roles configuration."""

    def __init__(self, lambda_functions_role: str = None):
        super().__init__()
        self.lambda_functions_role = Resource.init_param(lambda_functions_role)

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        if self.lambda_functions_role:
            self._register_validator(RoleValidator, role_arn=self.lambda_functions_role)


class S3Access(Resource):
    """Represent the S3 Access configuration."""

    def __init__(self, bucket_name: str, key_name: str = None, enable_write_access: bool = None):
        super().__init__()
        self.bucket_name = Resource.init_param(bucket_name)
        self.key_name = Resource.init_param(key_name)
        self.enable_write_access = Resource.init_param(enable_write_access, default=False)

    @property
    def resource_regex(self):
        """Resource regex to be added in IAM policies."""
        if self.key_name:  # If bucket name and key name are specified, we combine them directly
            return [f"{self.bucket_name}/{self.key_name}"]
        else:  # If only bucket name is specified, we add two resources (the bucket and the contents in the bucket).
            return [self.bucket_name, f"{self.bucket_name}/*"]


class Iam(Resource):
    """Represent the IAM configuration for HeadNode and Queue."""

    def __init__(
        self,
        s3_access: List[S3Access] = None,
        additional_iam_policies: List[AdditionalIamPolicy] = (),
        instance_role: str = None,
        instance_profile: str = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.s3_access = s3_access
        self.additional_iam_policies = additional_iam_policies
        self.instance_role = Resource.init_param(instance_role)
        self.instance_profile = Resource.init_param(instance_profile)

    @property
    def additional_iam_policy_arns(self) -> List[str]:
        """Get list of arn strings from the list of policy objects."""
        arns = []
        for policy in self.additional_iam_policies:
            arns.append(policy.policy)
        return arns

    def _extract_roles_from_instance_profile(self, instance_profile_name) -> List[str]:
        """Return the ARNs of the IAM roles attached to the given instance profile."""
        return [
            role.get("Arn")
            for role in (
                AWSApi.instance().iam.get_instance_profile(instance_profile_name).get("InstanceProfile").get("Roles")
            )
        ]

    @property
    def instance_role_arns(self) -> List[str]:
        """
        Get unique collection of ARNs of IAM roles underlying instance profile.

        self.instance_role is used if it's specified. Otherwise the roles contained within self.instance_profile are
        used. It's assumed that self.instance_profile and self.instance_role cannot both be specified.
        """
        if self.instance_role:
            instance_role_arns = {self.instance_role}
        elif self.instance_profile:
            instance_role_arns = set(
                self._extract_roles_from_instance_profile(get_resource_name_from_resource_arn(self.instance_profile))
            )
        else:
            instance_role_arns = {}
        return list(instance_role_arns)

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        if self.instance_role:
            self._register_validator(RoleValidator, role_arn=self.instance_role)
        elif self.instance_profile:
            self._register_validator(InstanceProfileValidator, instance_profile_arn=self.instance_profile)


class Imds(Resource):
    """Represent the IMDS configuration."""

    def __init__(self, secured: bool = None, **kwargs):
        super().__init__(**kwargs)
        self.secured = Resource.init_param(secured, default=True)


class DirectoryService(Resource):
    """Represent DirectoryService configuration."""

    def __init__(
        self,
        domain_name: str = None,
        domain_addr: str = None,
        password_secret_arn: str = None,
        domain_read_only_user: str = None,
        ldap_tls_ca_cert: str = None,
        ldap_tls_req_cert: str = None,
        ldap_access_filter: str = None,
        generate_ssh_keys_for_users: bool = None,
        additional_sssd_configs: Dict = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.domain_name = Resource.init_param(domain_name)
        self.domain_addr = Resource.init_param(domain_addr)
        self.password_secret_arn = Resource.init_param(password_secret_arn)
        self.domain_read_only_user = Resource.init_param(domain_read_only_user)
        self.ldap_tls_ca_cert = Resource.init_param(ldap_tls_ca_cert)
        self.ldap_tls_req_cert = Resource.init_param(ldap_tls_req_cert, default="hard")
        self.ldap_access_filter = Resource.init_param(ldap_access_filter)
        self.generate_ssh_keys_for_users = Resource.init_param(generate_ssh_keys_for_users, default=True)
        self.additional_sssd_configs = Resource.init_param(additional_sssd_configs, default={})

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        if self.domain_name:
            self._register_validator(DomainNameValidator, domain_name=self.domain_name)
        if self.domain_addr:
            self._register_validator(
                DomainAddrValidator, domain_addr=self.domain_addr, additional_sssd_configs=self.additional_sssd_configs
            )
        if self.password_secret_arn:
            self._register_validator(PasswordSecretArnValidator, password_secret_arn=self.password_secret_arn)
        if self.ldap_tls_req_cert:
            self._register_validator(LdapTlsReqCertValidator, ldap_tls_reqcert=self.ldap_tls_req_cert)
        if self.additional_sssd_configs:
            self._register_validator(
                AdditionalSssdConfigsValidator,
                additional_sssd_configs=self.additional_sssd_configs,
                ldap_access_filter=self.ldap_access_filter,
            )


class ClusterIam(Resource):
    """Represent the IAM configuration for Cluster."""

    def __init__(self, roles: Roles = None, permissions_boundary: str = None, resource_prefix: str = None):
        super().__init__()
        self.roles = roles
        self.permissions_boundary = Resource.init_param(permissions_boundary)
        self.resource_prefix = Resource.init_param(resource_prefix)

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        if self.permissions_boundary:
            self._register_validator(IamPolicyValidator, policy=self.permissions_boundary)
        if self.resource_prefix:
            self._register_validator(IamResourcePrefixValidator, resource_prefix=self.resource_prefix)


class IntelSoftware(Resource):
    """Represent the Intel select solution configuration."""

    def __init__(self, intel_hpc_platform: bool = None):
        super().__init__()
        self.intel_hpc_platform = Resource.init_param(intel_hpc_platform, default=False)


class AdditionalPackages(Resource):
    """Represent the additional packages configuration."""

    def __init__(self, intel_software: IntelSoftware = None):
        super().__init__()
        self.intel_software = intel_software


class AmiSearchFilters(Resource):
    """Represent the configuration for AMI search filters."""

    def __init__(self, tags: List[Tag] = None, owner: str = None):
        super().__init__()
        self.tags = tags
        self.owner = owner


class Timeouts(Resource):
    """Represent the configuration for node boostrap timeout."""

    def __init__(self, head_node_bootstrap_timeout: int = None, compute_node_bootstrap_timeout: int = None):
        super().__init__()
        self.head_node_bootstrap_timeout = Resource.init_param(
            head_node_bootstrap_timeout, default=NODE_BOOTSTRAP_TIMEOUT
        )
        self.compute_node_bootstrap_timeout = Resource.init_param(
            compute_node_bootstrap_timeout, default=NODE_BOOTSTRAP_TIMEOUT
        )


class CapacityReservationTarget(Resource):
    """Represent the CapacityReservationTarget configuration."""

    def __init__(self, capacity_reservation_id: str = None, capacity_reservation_resource_group_arn: str = None):
        super().__init__()
        self.capacity_reservation_id = Resource.init_param(capacity_reservation_id)
        self.capacity_reservation_resource_group_arn = Resource.init_param(capacity_reservation_resource_group_arn)


class ClusterDevSettings(BaseDevSettings):
    """Represent the dev settings configuration."""

    def __init__(
        self,
        cluster_template: str = None,
        ami_search_filters: AmiSearchFilters = None,
        instance_types_data: str = None,
        timeouts: Timeouts = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.cluster_template = Resource.init_param(cluster_template)
        self.ami_search_filters = Resource.init_param(ami_search_filters)
        self.instance_types_data = Resource.init_param(instance_types_data)
        self.timeouts = Resource.init_param(timeouts)

    def _register_validators(self, context: ValidatorContext = None):
        super()._register_validators(context)
        if self.cluster_template:
            self._register_validator(UrlValidator, url=self.cluster_template)


# ---------------------- Nodes and Cluster ---------------------- #


class Image(Resource):
    """Represent the configuration of an Image."""

    def __init__(self, os: str, custom_ami: str = None):
        super().__init__()
        self.os = Resource.init_param(os)
        self.custom_ami = Resource.init_param(custom_ami)

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        if self.custom_ami:
            self._register_validator(CustomAmiTagValidator, custom_ami=self.custom_ami)
            self._register_validator(AmiOsCompatibleValidator, os=self.os, image_id=self.custom_ami)


class HeadNodeImage(Resource):
    """Represent the configuration of HeadNode Image."""

    def __init__(self, custom_ami: str, **kwargs):
        super().__init__()
        self.custom_ami = Resource.init_param(custom_ami)

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        if self.custom_ami:
            self._register_validator(CustomAmiTagValidator, custom_ami=self.custom_ami)


class QueueImage(Resource):
    """Represent the configuration of Queue Image."""

    def __init__(self, custom_ami: str, **kwargs):
        super().__init__()
        self.custom_ami = Resource.init_param(custom_ami)

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        if self.custom_ami:
            self._register_validator(CustomAmiTagValidator, custom_ami=self.custom_ami)


class CustomAction(Resource):
    """Represent a custom action resource."""

    def __init__(self, script: str, args: List[str] = None):
        super().__init__()
        self.script = Resource.init_param(script)
        self.args = Resource.init_param(args)

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(UrlValidator, url=self.script)


class CustomActions(Resource):
    """Represent a custom action resource."""

    def __init__(
        self,
        on_node_start: CustomAction = None,
        on_node_configured: CustomAction = None,
        on_node_updated: CustomAction = None,
    ):
        super().__init__()
        self.on_node_start = Resource.init_param(on_node_start)
        self.on_node_configured = Resource.init_param(on_node_configured)
        self.on_node_updated = Resource.init_param(on_node_updated)


class HeadNode(Resource):
    """Represent the Head Node resource."""

    def __init__(
        self,
        instance_type: str,
        networking: HeadNodeNetworking,
        ssh: Ssh = None,
        disable_simultaneous_multithreading: bool = None,
        local_storage: LocalStorage = None,
        dcv: Dcv = None,
        custom_actions: CustomActions = None,
        iam: Iam = None,
        imds: Imds = None,
        image: HeadNodeImage = None,
    ):
        super().__init__()
        self.instance_type = Resource.init_param(instance_type)
        self.disable_simultaneous_multithreading = Resource.init_param(
            disable_simultaneous_multithreading, default=False
        )
        self.networking = networking
        self.ssh = ssh or Ssh(implied=True)
        self.local_storage = local_storage or LocalStorage(implied=True)
        self.dcv = dcv
        self.custom_actions = custom_actions
        self.iam = iam or Iam(implied=True)
        self.imds = imds or Imds(implied=True)
        self.image = image
        self.__instance_type_info = None

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(InstanceTypeValidator, instance_type=self.instance_type)

    @property
    def architecture(self) -> str:
        """Compute cluster's architecture based on its head node instance type."""
        return self.instance_type_info.supported_architecture()[0]

    @property
    def is_ebs_optimized(self) -> bool:
        """Return True if the instance has optimized EBS support."""
        return self.instance_type_info.is_ebs_optimized()

    @property
    def max_network_interface_count(self) -> int:
        """Return max number of NICs for the instance."""
        return self.instance_type_info.max_network_interface_count()

    @property
    def instance_type_info(self) -> InstanceTypeInfo:
        """Return head node instance type information as returned from aws ec2 describe-instance-types."""
        if not self.__instance_type_info:
            self.__instance_type_info = AWSApi.instance().ec2.get_instance_type_info(self.instance_type)
        return self.__instance_type_info

    @property
    def disable_simultaneous_multithreading_manually(self) -> bool:
        """Return true if simultaneous multithreading must be disabled with a cookbook script."""
        return self.disable_simultaneous_multithreading and self.instance_type_info.default_threads_per_core() > 1

    @property
    def instance_role(self):
        """Return the IAM role for head node, if set."""
        return self.iam.instance_role if self.iam else None

    @property
    def instance_profile(self):
        """Return the IAM instance profile for head node, if set."""
        return self.iam.instance_profile if self.iam else None


class BaseComputeResource(Resource):
    """Represent the base Compute Resource, with the fields in common between all the schedulers."""

    def __init__(self, name: str):
        super().__init__()
        self.name = Resource.init_param(name)

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(NameValidator, name=self.name)


class CapacityType(Enum):
    """Enum to identify the type compute supported by the queues."""

    ONDEMAND = "ONDEMAND"
    SPOT = "SPOT"


class ComputeSettings(Resource):
    """Represent the ComputeSettings resource."""

    def __init__(self, local_storage: LocalStorage = None, **kwargs):
        super().__init__(**kwargs)
        self.local_storage = local_storage or LocalStorage(implied=True)


class BaseQueue(Resource):
    """Represent the generic Queue resource."""

    def __init__(self, name: str, capacity_type: str = None):
        super().__init__()
        self.name = Resource.init_param(name)
        _capacity_type = CapacityType[capacity_type.upper()] if capacity_type else None
        self.capacity_type = Resource.init_param(_capacity_type, default=CapacityType.ONDEMAND)

    def is_spot(self):
        """Return True if the queue has SPOT capacity."""
        return self.capacity_type == CapacityType.SPOT

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(NameValidator, name=self.name)


class BaseClusterConfig(Resource):
    """Represent the common Cluster config."""

    def __init__(
        self,
        cluster_name: str,
        image: Image,
        head_node: HeadNode,
        scheduling=None,
        shared_storage: List[Resource] = None,
        monitoring: Monitoring = None,
        additional_packages: AdditionalPackages = None,
        tags: List[Tag] = None,
        iam: ClusterIam = None,
        directory_service: DirectoryService = None,
        config_region: str = None,
        custom_s3_bucket: str = None,
        imds: TopLevelImds = None,
        additional_resources: str = None,
        dev_settings: ClusterDevSettings = None,
        deployment_settings: DeploymentSettings = None,
    ):
        super().__init__()
        self.__region = None
        # config_region represents the region parameter in the configuration file
        # and is only used by configure_aws_region_from_config in controllers.
        # Since the region is already set by configure_aws_region_from_config to the environment variable,
        # the self.config_region is never used. It has to be here to make sure cluster_config stores all information
        # from a configuration file, so it is able to recreate the same file.
        self.config_region = config_region
        self.cluster_name = cluster_name
        self.image = image
        self.head_node = head_node
        self.scheduling = scheduling
        self.shared_storage = shared_storage
        self.monitoring = monitoring or Monitoring(implied=True)
        self.additional_packages = additional_packages
        self.tags = tags
        self.iam = iam
        self.directory_service = directory_service
        self.custom_s3_bucket = Resource.init_param(custom_s3_bucket)
        self._bucket = None
        self.additional_resources = Resource.init_param(additional_resources)
        self.dev_settings = dev_settings
        self.cluster_template_body = None
        self.source_config = None
        self.config_version = ""
        self.original_config_version = ""
        self._official_ami = None
        self.imds = imds or TopLevelImds(implied="v1.0")
        self.deployment_settings = deployment_settings

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(RegionValidator, region=self.region)
        self._register_validator(ClusterNameValidator, name=self.cluster_name)
        self._register_validator(
            ArchitectureOsValidator,
            os=self.image.os,
            architecture=self.head_node.architecture,
            custom_ami=self.image.custom_ami,
            ami_search_filters=self.dev_settings.ami_search_filters if self.dev_settings else None,
        )
        if self.head_node_ami:
            self._register_validator(
                InstanceTypeBaseAMICompatibleValidator,
                instance_type=self.head_node.instance_type,
                image=self.head_node_ami,
            )
        if self.head_node.image and self.head_node.image.custom_ami:
            self._register_validator(
                AmiOsCompatibleValidator, os=self.image.os, image_id=self.head_node.image.custom_ami
            )
        # Check that all subnets in the cluster (head node subnet included) are in the same VPC and support DNS.
        self._register_validator(
            SubnetsValidator, subnet_ids=self.compute_subnet_ids + [self.head_node.networking.subnet_id]
        )
        self._register_storage_validators()
        self._register_validator(
            HeadNodeLaunchTemplateValidator,
            head_node=self.head_node,
            os=self.image.os,
            ami_id=self.head_node_ami,
            tags=self.get_cluster_tags(),
        )
        if self.head_node.dcv:
            self._register_validator(
                DcvValidator,
                instance_type=self.head_node.instance_type,
                dcv_enabled=self.head_node.dcv.enabled,
                allowed_ips=self.head_node.dcv.allowed_ips,
                port=self.head_node.dcv.port,
                os=self.image.os,
                architecture=self.head_node.architecture,
            )
        if (
            self.additional_packages
            and self.additional_packages.intel_software
            and self.additional_packages.intel_software.intel_hpc_platform
        ):
            self._register_validator(IntelHpcOsValidator, os=self.image.os)
            self._register_validator(IntelHpcArchitectureValidator, architecture=self.head_node.architecture)
        if self.custom_s3_bucket:
            self._register_validator(S3BucketValidator, bucket=self.custom_s3_bucket)
            self._register_validator(S3BucketRegionValidator, bucket=self.custom_s3_bucket, region=self.region)
        self._register_validator(SchedulerValidator, scheduler=self.scheduling.scheduler)
        self._register_validator(SchedulerOsValidator, scheduler=self.scheduling.scheduler, os=self.image.os)
        self._register_validator(
            HeadNodeImdsValidator, imds_secured=self.head_node.imds.secured, scheduler=self.scheduling.scheduler
        )
        ami_volume_size = AWSApi.instance().ec2.describe_image(self.head_node_ami).volume_size
        root_volume = self.head_node.local_storage.root_volume
        root_volume_size = root_volume.size
        if root_volume_size is None:  # If root volume size is not specified, it will be the size of the AMI.
            root_volume_size = ami_volume_size
        self._register_validator(
            RootVolumeSizeValidator,
            root_volume_size=root_volume_size,
            ami_volume_size=ami_volume_size,
        )
        self._register_validator(
            EbsVolumeTypeSizeValidator, volume_type=root_volume.volume_type, volume_size=root_volume_size
        )
        self._register_validator(
            EbsVolumeIopsValidator,
            volume_type=root_volume.volume_type,
            volume_size=root_volume_size,
            volume_iops=root_volume.iops,
        )

    def _register_storage_validators(self):
        if self.shared_storage:
            ebs_count = 0
            new_storage_count = defaultdict(int)
            existing_storage_count = defaultdict(int)

            self._cache_describe_volume()

            self._register_validator(
                DuplicateNameValidator,
                name_list=[storage.name for storage in self.shared_storage],
                resource_name="Shared Storage",
            )
            self._register_validator(
                DuplicateNameValidator,
                name_list=self.existing_storage_id_list,
                resource_name="Shared Storage IDs",
            )

            existing_fsx = set()
            for storage in self.shared_storage:
                self._register_validator(SharedStorageNameValidator, name=storage.name)
                self._register_validator(SharedStorageMountDirValidator, mount_dir=storage.mount_dir)
                if isinstance(storage, SharedFsxLustre):
                    if storage.file_system_id:
                        existing_storage_count["fsx"] += 1
                        existing_fsx.add(storage.file_system_id)
                    else:
                        new_storage_count["fsx"] += 1
                    self._register_validator(
                        FsxArchitectureOsValidator, architecture=self.head_node.architecture, os=self.image.os
                    )
                elif isinstance(storage, (ExistingFsxOpenZfs, ExistingFsxOntap)):
                    existing_storage_count["fsx"] += 1
                    existing_fsx.add(storage.file_system_id)
                elif isinstance(storage, SharedEbs):
                    if storage.raid:
                        new_storage_count["raid"] += 1
                    else:
                        ebs_count += 1
                elif isinstance(storage, SharedEfs):
                    if storage.file_system_id:
                        existing_storage_count["efs"] += 1
                        self._register_validator(
                            EfsIdValidator,
                            efs_id=storage.file_system_id,
                            avail_zones_mapping=self.availability_zones_subnets_mapping,
                            are_all_security_groups_customized=self.are_all_security_groups_customized,
                        )
                    else:
                        new_storage_count["efs"] += 1
            self._register_validator(
                ExistingFsxNetworkingValidator,
                file_system_ids=list(existing_fsx),
                head_node_subnet_id=self.head_node.networking.subnet_id,
                are_all_security_groups_customized=self.are_all_security_groups_customized,
            )

            self._validate_max_storage_count(ebs_count, existing_storage_count, new_storage_count)
            self._validate_new_storage_multiple_subnets(
                self.scheduling.queues, self.compute_subnet_ids, new_storage_count
            )

        self._validate_mount_dirs()

    def _validate_mount_dirs(self):
        self._register_validator(
            DuplicateMountDirValidator,
            shared_storage_name_mount_dir_tuple_list=self.shared_storage_name_mount_dir_tuple_list,
            local_mount_dir_instance_types_dict=self.local_mount_dir_instance_types_dict,
        )
        self._register_validator(
            OverlappingMountDirValidator,
            shared_mount_dir_list=[mount_dir for mount_dir, _ in self.shared_storage_name_mount_dir_tuple_list],
            local_mount_dir_list=list(self.local_mount_dir_instance_types_dict.keys()),
        )

    def _validate_new_storage_multiple_subnets(self, queues, compute_subnet_ids, new_storage_count):
        self._register_validator(
            ManagedFsxMultiAzValidator,
            compute_subnet_ids=compute_subnet_ids,
            new_storage_count=new_storage_count,
        )
        ebs_volumes = []
        head_node_az = self.head_node.networking.availability_zone
        for storage in self.shared_storage:
            if isinstance(storage, (SharedFsxLustre, ExistingFsxOpenZfs, ExistingFsxOntap)) and storage.is_unmanaged:
                self._register_validator(
                    UnmanagedFsxMultiAzValidator,
                    queues=queues,
                    fsx_az_list=storage.file_system_availability_zones,
                )
            if isinstance(storage, SharedEbs):
                ebs_volumes.append(storage)

        self._register_validator(
            MultiAzEbsVolumeValidator,
            head_node_az=head_node_az,
            ebs_volumes=ebs_volumes,
            queues=queues,
        )
        self._register_validator(
            MultiAzRootVolumeValidator,
            head_node_az=head_node_az,
            queues=queues,
        )

    def _validate_max_storage_count(self, ebs_count, existing_storage_count, new_storage_count):
        for storage_type in ["EFS", "FSx", "RAID"]:
            storage_type_lower_case = storage_type.lower()
            self._register_validator(
                NumberOfStorageValidator,
                storage_type=f"new {storage_type}",
                max_number=MAX_NEW_STORAGE_COUNT.get(storage_type_lower_case),
                storage_count=new_storage_count[storage_type_lower_case],
            )
            self._register_validator(
                NumberOfStorageValidator,
                storage_type=f"existing {storage_type}",
                max_number=MAX_EXISTING_STORAGE_COUNT.get(storage_type_lower_case),
                storage_count=existing_storage_count[storage_type_lower_case],
            )
        self._register_validator(
            NumberOfStorageValidator,
            storage_type="EBS",
            max_number=MAX_EBS_COUNT,
            storage_count=ebs_count,
        )

    def _cache_describe_volume(self):
        volume_ids = []
        for storage in self.shared_storage:
            if isinstance(storage, (ExistingFsxOpenZfs, ExistingFsxOntap)):
                volume_ids.append(storage.volume_id)
        if volume_ids:
            AWSApi.instance().fsx.describe_volumes(volume_ids)

    @property
    def region(self):
        """Retrieve region from environment if not set."""
        if not self.__region:
            self.__region = get_region()
        return self.__region

    @region.setter
    def region(self, region):
        self.__region = region

    @property
    def partition(self):
        """Retrieve partition from environment."""
        return get_partition()

    @property
    def shared_storage_name_mount_dir_tuple_list(self):
        """Retrieve the list of shared storage names and mount dirs."""
        mount_dir_list = []
        if self.shared_storage:
            for storage in self.shared_storage:
                mount_dir_list.append((storage.name, storage.mount_dir))
        return mount_dir_list

    @property
    def local_mount_dir_instance_types_dict(self):
        """Retrieve a dictionary of local mount dirs and corresponding instance types."""
        mount_dir_instance_types_dict = defaultdict(set)
        if self.head_node.instance_type_info.instance_storage_supported():
            mount_dir_instance_types_dict[
                self.head_node.local_storage.ephemeral_volume.mount_dir
                if self.head_node.local_storage.ephemeral_volume
                else DEFAULT_EPHEMERAL_DIR
            ].add(self.head_node.instance_type)

        scheduling = self.scheduling
        if isinstance(scheduling, (SchedulerPluginScheduling, SlurmScheduling)):
            for queue in scheduling.queues:
                instance_types_with_instance_storage = queue.instance_types_with_instance_storage
                if instance_types_with_instance_storage:
                    mount_dir_instance_types_dict[
                        queue.compute_settings.local_storage.ephemeral_volume.mount_dir
                        if queue.compute_settings.local_storage.ephemeral_volume
                        else DEFAULT_EPHEMERAL_DIR
                    ].update(instance_types_with_instance_storage)

        return mount_dir_instance_types_dict

    @property
    def existing_storage_id_list(self):
        """Retrieve the list of IDs of EBS, FSx, EFS provided."""
        storage_id_list = []
        if self.shared_storage:
            for storage in self.shared_storage:
                storage_id = None
                if isinstance(storage, (SharedEfs, SharedFsxLustre)):
                    storage_id = storage.file_system_id
                elif isinstance(storage, (SharedEbs, ExistingFsxOpenZfs, ExistingFsxOntap)):
                    storage_id = storage.volume_id
                if storage_id:
                    storage_id_list.append(storage_id)
        return storage_id_list

    @property
    def compute_subnet_ids(self):
        """Return the list of all compute subnet ids in the cluster."""
        subnet_ids_list = []
        for queue in self.scheduling.queues:
            for subnet_id in queue.networking.subnet_ids:
                if subnet_id not in subnet_ids_list:
                    subnet_ids_list.append(subnet_id)
        return subnet_ids_list

    @property
    def availability_zones_subnets_mapping(self):
        """Retrieve the mapping of availability zone and cluster subnets."""
        mapping = {self.head_node.networking.availability_zone: {self.head_node.networking.subnet_id}}
        for subnet_id in self.compute_subnet_ids:
            mapping.setdefault(AWSApi.instance().ec2.get_subnet_avail_zone(subnet_id), set()).add(subnet_id)
        return mapping

    @property
    def compute_security_groups(self):
        """Return the list of all compute security groups in the cluster."""
        return list(
            {
                security_group
                for queue in self.scheduling.queues
                if queue.networking.security_groups
                for security_group in queue.networking.security_groups
            }
        )

    @property
    def vpc_id(self):
        """Return the VPC of the cluster."""
        return AWSApi.instance().ec2.get_subnet_vpc(self.head_node.networking.subnet_id)

    @property
    def head_node_ami(self):
        """Get the image id of the HeadNode."""
        if self.head_node.image and self.head_node.image.custom_ami:
            return self.head_node.image.custom_ami
        elif self.image.custom_ami:
            return self.image.custom_ami
        else:
            return self.official_ami

    @property
    def scheduler_resources(self):
        """Return scheduler resources. To be overridden with scheduler specific logic, if any."""
        return None

    @property
    def is_intel_hpc_platform_enabled(self):
        """Return True if intel hpc platform is enabled."""
        return (
            self.additional_packages.intel_software.intel_hpc_platform
            if self.additional_packages and self.additional_packages.intel_software
            else False
        )

    @property
    def is_cw_logging_enabled(self):
        """Return True if CloudWatch logging is enabled."""
        return (
            self.monitoring.logs.cloud_watch.enabled
            if self.monitoring and self.monitoring.logs and self.monitoring.logs.cloud_watch
            else False
        )

    @property
    def is_cw_dashboard_enabled(self):
        """Return True if CloudWatch Dashboard is enabled."""
        return (
            self.monitoring.dashboards.cloud_watch.enabled
            if self.monitoring and self.monitoring.dashboards and self.monitoring.dashboards.cloud_watch
            else False
        )

    @property
    def is_dcv_enabled(self):
        """Return True if DCV is enabled."""
        return self.head_node.dcv and self.head_node.dcv.enabled

    @property
    def are_all_security_groups_customized(self):
        """Return True if all head node and queues have (additional) security groups specified."""
        head_node_networking = self.head_node.networking
        if not (head_node_networking.security_groups or head_node_networking.additional_security_groups):
            return False
        for queue in self.scheduling.queues:
            queue_networking = queue.networking
            if isinstance(queue_networking, _QueueNetworking):
                if not (queue_networking.security_groups or queue_networking.additional_security_groups):
                    return False
        return True

    @property
    def extra_chef_attributes(self):
        """Return extra chef attributes."""
        return (
            self.dev_settings.cookbook.extra_chef_attributes
            if self.dev_settings and self.dev_settings.cookbook and self.dev_settings.cookbook.extra_chef_attributes
            else "{}"
        )

    @property
    def custom_chef_cookbook(self):
        """Return custom chef cookbook value or None."""
        return (
            self.dev_settings.cookbook.chef_cookbook
            if self.dev_settings and self.dev_settings.cookbook and self.dev_settings.cookbook.chef_cookbook
            else None
        )

    @property
    def custom_node_package(self):
        """Return custom node package value or None."""
        return self.dev_settings.node_package if self.dev_settings else None

    @property
    def custom_aws_batch_cli_package(self):
        """Return custom custom aws batch cli package value or None."""
        return self.dev_settings.aws_batch_cli_package if self.dev_settings else None

    @property
    def official_ami(self):
        """Return official ParallelCluster AMI by filter."""
        if not self._official_ami:
            ami_filters = self.dev_settings.ami_search_filters if self.dev_settings else None
            self._official_ami = AWSApi.instance().ec2.get_official_image_id(
                self.image.os, self.head_node.architecture, ami_filters
            )
        return self._official_ami

    @official_ami.setter
    def official_ami(self, value):
        self._official_ami = value

    @property
    def lambda_functions_vpc_config(self):
        """Return the vpc config of the PCluster Lambda Functions or None."""
        return self.deployment_settings.lambda_functions_vpc_config if self.deployment_settings else None

    def get_cluster_tags(self):
        """Return tags configured in the cluster configuration."""
        return self.tags


class AwsBatchComputeResource(BaseComputeResource):
    """Represent the AwsBatch Compute Resource."""

    def __init__(
        self,
        instance_types: List[str] = None,
        max_vcpus: int = None,
        min_vcpus: int = None,
        desired_vcpus: int = None,
        spot_bid_percentage: float = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.instance_types = Resource.init_param(instance_types)
        self.max_vcpus = Resource.init_param(max_vcpus, default=DEFAULT_MAX_COUNT)
        self.min_vcpus = Resource.init_param(min_vcpus, default=DEFAULT_MIN_COUNT)
        self.desired_vcpus = Resource.init_param(desired_vcpus, default=self.min_vcpus)
        self.spot_bid_percentage = Resource.init_param(spot_bid_percentage)

    def _register_validators(self, context: ValidatorContext = None):
        super()._register_validators(context)
        self._register_validator(
            AwsBatchComputeInstanceTypeValidator, instance_types=self.instance_types, max_vcpus=self.max_vcpus
        )
        self._register_validator(
            AwsBatchComputeResourceSizeValidator,
            min_vcpus=self.min_vcpus,
            max_vcpus=self.max_vcpus,
            desired_vcpus=self.desired_vcpus,
        )


class AwsBatchQueue(BaseQueue):
    """Represent the AwsBatch Queue resource."""

    def __init__(self, compute_resources: List[AwsBatchComputeResource], networking: AwsBatchQueueNetworking, **kwargs):
        super().__init__(**kwargs)
        self.compute_resources = compute_resources
        self.networking = networking

    def _register_validators(self, context: ValidatorContext = None):
        super()._register_validators(context)
        self._register_validator(
            DuplicateNameValidator,
            name_list=[compute_resource.name for compute_resource in self.compute_resources],
            resource_name="Compute resource",
        )


class AwsBatchSettings(Resource):
    """Represent the AwsBatchSettings resource."""

    pass


class AwsBatchScheduling(Resource):
    """Represent a AwsBatch Scheduling resource."""

    def __init__(self, queues: List[AwsBatchQueue], settings: AwsBatchSettings = None):
        super().__init__()
        self.scheduler = "awsbatch"
        self.queues = queues
        self.settings = settings

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(
            DuplicateNameValidator, name_list=[queue.name for queue in self.queues], resource_name="Queue"
        )


class AwsBatchClusterConfig(BaseClusterConfig):
    """Represent the full AwsBatch Cluster configuration."""

    def __init__(self, cluster_name: str, scheduling: AwsBatchScheduling, **kwargs):
        super().__init__(cluster_name, **kwargs)
        self.scheduling = scheduling

    def _register_validators(self, context: ValidatorContext = None):
        super()._register_validators(context)
        self._register_validator(AwsBatchRegionValidator, region=self.region)
        # TODO add InstanceTypesBaseAMICompatibleValidator

        if self.shared_storage:
            for storage in self.shared_storage:
                if isinstance(storage, BaseSharedFsx):
                    self._register_validator(AwsBatchFsxValidator)

        for queue in self.scheduling.queues:
            for compute_resource in queue.compute_resources:
                self._register_validator(
                    AwsBatchInstancesArchitectureCompatibilityValidator,
                    instance_types=compute_resource.instance_types,
                    architecture=self.head_node.architecture,
                )

    @property
    def scheduler_resources(self):
        """Return scheduler specific resources."""
        return pkg_resources.resource_filename(__name__, "../resources/batch")


class _BaseSlurmComputeResource(BaseComputeResource):
    """Represent the Slurm Compute Resource."""

    def __init__(
        self,
        max_count: int = None,
        min_count: int = None,
        spot_price: float = None,
        efa: Efa = None,
        disable_simultaneous_multithreading: bool = None,
        schedulable_memory: int = None,
        capacity_reservation_target: CapacityReservationTarget = None,
        networking: SlurmComputeResourceNetworking = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.max_count = Resource.init_param(max_count, default=DEFAULT_MAX_COUNT)
        self.min_count = Resource.init_param(min_count, default=DEFAULT_MIN_COUNT)
        self.spot_price = Resource.init_param(spot_price)
        self.disable_simultaneous_multithreading = Resource.init_param(
            disable_simultaneous_multithreading, default=False
        )
        self.efa = efa or Efa(enabled=False, implied=True)
        self.schedulable_memory = Resource.init_param(schedulable_memory)
        self.capacity_reservation_target = capacity_reservation_target
        self._instance_types_with_instance_storage = []
        self._instance_type_info_map = {}
        self.networking = networking or SlurmComputeResourceNetworking(implied=True)

    @staticmethod
    def fetch_instance_type_info(instance_type) -> InstanceTypeInfo:
        """Return instance type information."""
        return AWSApi.instance().ec2.get_instance_type_info(instance_type)

    @property
    def instance_types_with_instance_storage(self):
        """Return a set of instance types in the Compute Resource that have local instance storage."""
        if not self._instance_types_with_instance_storage:
            self._instance_types_with_instance_storage = [
                instance_type
                for instance_type in self.instance_types
                if self.instance_type_info_map[instance_type].instance_storage_supported()
            ]
        return self._instance_types_with_instance_storage

    @property
    def instance_type_info_map(self) -> Dict[str, InstanceTypeInfo]:
        """List of Instance Type information for each instance type in the compute resource.

        :returns: [ "InstanceType1": {... InstanceTypeInfo ...}, "InstanceType1": {... InstanceTypeInfo ...} ]
        """
        if not self._instance_type_info_map:
            self._instance_type_info_map = {
                instance_type: self.fetch_instance_type_info(instance_type) for instance_type in self.instance_types
            }
        return self._instance_type_info_map

    @property
    @abstractmethod
    def disable_simultaneous_multithreading_manually(self) -> bool:
        pass

    @property
    @abstractmethod
    def max_network_interface_count(self) -> int:
        pass

    @property
    def is_ebs_optimized(self) -> bool:
        return all(
            self.instance_type_info_map[instance_type].is_ebs_optimized() for instance_type in self.instance_types
        )

    @property
    @abstractmethod
    def instance_types(self) -> List[str]:
        pass


class FlexibleInstanceType(Resource):
    """Represent an instance type listed in the Instances of a ComputeResources."""

    def __init__(self, instance_type: str, **kwargs):
        super().__init__(**kwargs)
        self.instance_type = Resource.init_param(instance_type)


class SlurmFlexibleComputeResource(_BaseSlurmComputeResource):
    """Represents a Slurm Compute Resource with Multiple Instance Types."""

    def __init__(self, instances: List[FlexibleInstanceType], **kwargs):
        super().__init__(**kwargs)
        self.instances = Resource.init_param(instances)

    @property
    def instance_types(self) -> List[str]:
        """Return list of instance type names in this compute resource."""
        return [flexible_instance_type.instance_type for flexible_instance_type in self.instances]

    @property
    def disable_simultaneous_multithreading_manually(self) -> bool:
        """Return true if simultaneous multithreading must be disabled with a cookbook script."""
        return self.disable_simultaneous_multithreading

    @property
    def max_network_interface_count(self) -> int:
        """Return max number of NICs for the compute resource.

        In this case the Compute Resource may have multiple instance types, hence the instance-type with
        the least MaxNetworkInterfaceCards value will be considered.
        """
        least_max_nics = self.instance_type_info_map[self.instance_types[0]].max_network_interface_count()
        if len(self.instance_types) > 1:
            for instance_type in self.instance_types[1:]:
                instance_type_info = self.instance_type_info_map[instance_type]
                max_nics = instance_type_info.max_network_interface_count()
                if max_nics < least_max_nics:
                    least_max_nics = max_nics
        return least_max_nics


class SlurmComputeResource(_BaseSlurmComputeResource):
    """Represents a Slurm Compute Resource with a Single Instance Type."""

    def __init__(self, instance_type, **kwargs):
        super().__init__(**kwargs)
        self.instance_type = Resource.init_param(instance_type)
        self.__instance_type_info = None

    @property
    def instance_types(self) -> List[str]:
        """List of instance types under this compute resource."""
        return [self.instance_type]

    @property
    def instance_type_info(self) -> InstanceTypeInfo:
        """Return instance type information."""
        return AWSApi.instance().ec2.get_instance_type_info(self.instance_type)

    def _register_validators(self, context: ValidatorContext = None):
        super()._register_validators(context)
        self._register_validator(ComputeResourceSizeValidator, min_count=self.min_count, max_count=self.max_count)
        self._register_validator(
            SchedulableMemoryValidator,
            schedulable_memory=self.schedulable_memory,
            ec2memory=self._instance_type_info.ec2memory_size_in_mib(),
            instance_type=self.instance_type,
        )

    @property
    def architecture(self) -> str:
        """Compute cluster's architecture based on its head node instance type."""
        return self._instance_type_info.supported_architecture()[0]

    @property
    def is_ebs_optimized(self) -> bool:
        """Return True if the instance has optimized EBS support."""
        return self._instance_type_info.is_ebs_optimized()

    @property
    def max_network_interface_count(self) -> int:
        """Return max number of NICs for the instance."""
        return self._instance_type_info.max_network_interface_count()

    @property
    def _instance_type_info(self) -> InstanceTypeInfo:
        """Return instance type information as returned from aws ec2 describe-instance-types."""
        if not self.__instance_type_info:
            self.__instance_type_info = AWSApi.instance().ec2.get_instance_type_info(self.instance_type)
        return self.__instance_type_info

    @property
    def disable_simultaneous_multithreading_manually(self) -> bool:
        """Return true if simultaneous multithreading must be disabled with a cookbook script."""
        return self.disable_simultaneous_multithreading and self.instance_type_info.default_threads_per_core() > 1


class SchedulerPluginComputeResource(SlurmComputeResource):
    """Represent the Scheduler Plugin Compute Resource."""

    def __init__(
        self,
        custom_settings: Dict = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.custom_settings = custom_settings


class _CommonQueue(BaseQueue):
    """Represent the Common Queue resource between Slurm and Scheduler Plugin."""

    def __init__(
        self,
        compute_resources: List[Union[_BaseSlurmComputeResource, SchedulerPluginComputeResource]],
        networking: Union[SlurmQueueNetworking, SchedulerPluginQueueNetworking],
        compute_settings: ComputeSettings = None,
        custom_actions: CustomActions = None,
        iam: Iam = None,
        image: QueueImage = None,
        capacity_reservation_target: CapacityReservationTarget = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.compute_settings = compute_settings or ComputeSettings(implied=True)
        self.custom_actions = custom_actions
        self.iam = iam or Iam(implied=True)
        self.image = image
        self.capacity_reservation_target = capacity_reservation_target
        self.compute_resources = compute_resources
        self.networking = networking

    @property
    def instance_role(self):
        """Return the IAM role for compute nodes, if set."""
        return self.iam.instance_role if self.iam else None

    @property
    def instance_profile(self):
        """Return the IAM instance profile for compute nodes, if set."""
        return self.iam.instance_profile if self.iam else None

    @property
    def queue_ami(self):
        """Return queue image id."""
        if self.image and self.image.custom_ami:
            return self.image.custom_ami
        else:
            return None

    @property
    def multi_az_enabled(self):
        """Return true if more than one AZ are defined in the queue Networking section."""
        return len(self.networking.az_list) > 1

    def get_managed_placement_group_keys(self) -> List[str]:
        managed_placement_group_keys = []
        for compute_resource in self.compute_resources:
            placement_group_setting = self.get_placement_group_settings_for_compute_resource(compute_resource)
            if placement_group_setting.get("is_managed"):
                managed_placement_group_keys.append(placement_group_setting.get("key"))
        return managed_placement_group_keys

    def get_placement_group_settings_for_compute_resource(
        self, compute_resource: Union[_BaseSlurmComputeResource, SchedulerPluginComputeResource]
    ) -> Dict[str, bool]:
        # Placement Group key is None and not managed by default
        placement_group_key, managed = None, False
        # prefer compute level groups over queue level groups
        chosen_pg = self.get_chosen_placement_group_setting_for_compute_resource(compute_resource)
        if chosen_pg.assignment:
            placement_group_key, managed = chosen_pg.assignment, False
        elif chosen_pg.enabled:
            placement_group_key, managed = f"{self.name}-{compute_resource.name}", True
        return {"key": placement_group_key, "is_managed": managed}

    def is_placement_group_enabled_for_compute_resource(
        self, compute_resource: Union[_BaseSlurmComputeResource, SchedulerPluginComputeResource]
    ) -> bool:
        return self.get_placement_group_settings_for_compute_resource(compute_resource).get("key") is not None

    def get_chosen_placement_group_setting_for_compute_resource(
        self, compute_resource: Union[_BaseSlurmComputeResource, SchedulerPluginComputeResource]
    ) -> PlacementGroup:
        """Handle logic that the Placement Group on compute resource level overrides queue level."""
        return (
            compute_resource.networking.placement_group
            if not compute_resource.networking.placement_group.implied
            else self.networking.placement_group
        )

    def _register_validators(self, context: ValidatorContext = None):
        super()._register_validators(context)
        for compute_resource in self.compute_resources:
            self._register_validator(
                EfaMultiAzValidator,
                queue_name=self.name,
                multi_az_enabled=self.multi_az_enabled,
                compute_resource_name=compute_resource.name,
                compute_resource_efa_enabled=compute_resource.efa.enabled,
            )
            # SlurmFlexibleComputeResource are managed in SlurmClusterConfig since they have a different validator
            if isinstance(compute_resource, SlurmComputeResource):
                self._register_validator(
                    EfaValidator,
                    instance_type=compute_resource.instance_type,
                    efa_enabled=compute_resource.efa.enabled,
                    gdr_support=compute_resource.efa.gdr_support,
                    multiaz_enabled=self.multi_az_enabled,
                )
            placement_group = self.get_chosen_placement_group_setting_for_compute_resource(compute_resource)
            self._register_validator(
                MultiAzPlacementGroupValidator,
                multi_az_enabled=self.multi_az_enabled,
                placement_group_enabled=placement_group.enabled_or_assigned,
                compute_resource_name=compute_resource.name,
                queue_name=self.name,
            )


class AllocationStrategy(Enum):
    """Define supported allocation strategies."""

    LOWEST_PRICE = "lowest-price"
    CAPACITY_OPTIMIZED = "capacity-optimized"


class SlurmQueue(_CommonQueue):
    """Represents a Slurm Queue that has Compute Resources with both Single and Multiple Instance Types."""

    def __init__(
        self,
        allocation_strategy: str = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        if any(
            isinstance(compute_resource, SlurmFlexibleComputeResource) for compute_resource in self.compute_resources
        ):
            self.allocation_strategy = (
                AllocationStrategy[to_snake_case(allocation_strategy).upper()]
                if allocation_strategy
                else AllocationStrategy.LOWEST_PRICE
            )

    @property
    def instance_type_list(self):
        """Return the list of instance types associated to the Queue."""
        instance_types = set()
        for compute_resource in self.compute_resources:
            instance_types.update(compute_resource.instance_types)
        return list(instance_types)

    @property
    def instance_types_with_instance_storage(self):
        """Return a set of instance types in the queue that have instance store."""
        result = set()
        for compute_resource in self.compute_resources:
            result.update(compute_resource.instance_types_with_instance_storage)
        return result

    def _register_validators(self, context: ValidatorContext = None):
        super()._register_validators(context)
        self._register_validator(
            DuplicateNameValidator,
            name_list=[compute_resource.name for compute_resource in self.compute_resources],
            resource_name="Compute resource",
        )
        self._register_validator(
            MaxCountValidator,
            resources_length=len(self.compute_resources),
            max_length=MAX_NUMBER_OF_COMPUTE_RESOURCES,
            resource_name="ComputeResources",
        )
        self._register_validator(
            QueueSubnetsValidator,
            queue_name=self.name,
            subnet_ids=self.networking.subnet_ids,
            az_subnet_ids_mapping=self.networking.az_subnet_ids_mapping,
        )
        if any(isinstance(compute_resource, SlurmComputeResource) for compute_resource in self.compute_resources):
            self._register_validator(
                SingleInstanceTypeSubnetValidator,
                queue_name=self.name,
                subnet_ids=self.networking.subnet_ids,
            )
        for compute_resource in self.compute_resources:
            self._register_validator(
                EfaSecurityGroupValidator,
                efa_enabled=compute_resource.efa.enabled,
                security_groups=self.networking.security_groups,
                additional_security_groups=self.networking.additional_security_groups,
            )
            self._register_validator(
                EfaPlacementGroupValidator,
                efa_enabled=compute_resource.efa.enabled,
                placement_group_key=self.get_placement_group_settings_for_compute_resource(compute_resource).get("key"),
                placement_group_disabled=self.get_chosen_placement_group_setting_for_compute_resource(
                    compute_resource
                ).enabled
                is False,
                multi_az_enabled=self.multi_az_enabled,
            )
            for instance_type in compute_resource.instance_types:
                self._register_validator(
                    CapacityTypeValidator,
                    capacity_type=self.capacity_type,
                    instance_type=instance_type,
                )


class Dns(Resource):
    """Represent the DNS settings."""

    def __init__(
        self, disable_managed_dns: bool = None, hosted_zone_id: str = None, use_ec2_hostnames: bool = None, **kwargs
    ):
        super().__init__(**kwargs)
        self.disable_managed_dns = Resource.init_param(disable_managed_dns, default=False)
        self.hosted_zone_id = Resource.init_param(hosted_zone_id)
        self.use_ec2_hostnames = Resource.init_param(use_ec2_hostnames, default=False)


class Database(Resource):
    """Represent the Slurm Database settings."""

    def __init__(
        self,
        uri: str = None,
        user_name: str = None,
        password_secret_arn: str = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.uri = Resource.init_param(uri)
        self.user_name = Resource.init_param(user_name)
        self.password_secret_arn = Resource.init_param(password_secret_arn)

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        if self.uri:
            self._register_validator(DatabaseUriValidator, uri=self.uri)
        if self.password_secret_arn:
            self._register_validator(PasswordSecretArnValidator, password_secret_arn=self.password_secret_arn)


class SlurmSettings(Resource):
    """Represent the Slurm settings."""

    def __init__(
        self,
        scaledown_idletime: int = None,
        dns: Dns = None,
        queue_update_strategy: str = None,
        enable_memory_based_scheduling: bool = None,
        database: Database = None,
        **kwargs,
    ):
        super().__init__()
        self.scaledown_idletime = Resource.init_param(scaledown_idletime, default=10)
        self.dns = dns or Dns(implied=True)
        self.queue_update_strategy = Resource.init_param(
            queue_update_strategy, default=QueueUpdateStrategy.COMPUTE_FLEET_STOP.value
        )
        self.enable_memory_based_scheduling = Resource.init_param(enable_memory_based_scheduling, default=False)
        self.database = database


class QueueUpdateStrategy(Enum):
    """Enum to identify the update strategy supported by the queue."""

    DRAIN = "DRAIN"
    COMPUTE_FLEET_STOP = "COMPUTE_FLEET_STOP"
    TERMINATE = "TERMINATE"


class SlurmScheduling(Resource):
    """Represent a slurm Scheduling resource."""

    def __init__(self, queues: List[SlurmQueue], settings: SlurmSettings = None):
        super().__init__()
        self.scheduler = "slurm"
        self.queues = queues
        self.settings = settings or SlurmSettings(implied=True)

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(
            DuplicateNameValidator, name_list=[queue.name for queue in self.queues], resource_name="Queue"
        )
        self._register_validator(
            MaxCountValidator,
            resources_length=len(self.queues),
            max_length=MAX_NUMBER_OF_QUEUES,
            resource_name="SlurmQueues",
        )


class SchedulerPluginQueue(_CommonQueue):
    """Represent the Scheduler Plugin queue."""

    def __init__(
        self,
        custom_settings: Dict = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.custom_settings = custom_settings

    def _register_validators(self, context: ValidatorContext = None):
        super()._register_validators(context)
        self._register_validator(
            DuplicateNameValidator,
            name_list=[compute_resource.name for compute_resource in self.compute_resources],
            resource_name="Compute resource",
        )
        self._register_validator(
            QueueSubnetsValidator,
            queue_name=self.name,
            subnet_ids=self.networking.subnet_ids,
            az_subnet_ids_mapping=self.networking.az_subnet_ids_mapping,
        )
        if any(isinstance(compute_resource, SlurmComputeResource) for compute_resource in self.compute_resources):
            self._register_validator(
                SingleInstanceTypeSubnetValidator,
                queue_name=self.name,
                subnet_ids=self.networking.subnet_ids,
            )
        for compute_resource in self.compute_resources:
            self._register_validator(
                CapacityTypeValidator, capacity_type=self.capacity_type, instance_type=compute_resource.instance_type
            )
            self._register_validator(
                EfaSecurityGroupValidator,
                efa_enabled=compute_resource.efa.enabled,
                security_groups=self.networking.security_groups,
                additional_security_groups=self.networking.additional_security_groups,
            )
            self._register_validator(
                EfaPlacementGroupValidator,
                efa_enabled=compute_resource.efa.enabled,
                placement_group_key=self.get_placement_group_settings_for_compute_resource(compute_resource).get("key"),
                placement_group_disabled=self.get_chosen_placement_group_setting_for_compute_resource(
                    compute_resource
                ).enabled
                is False,
                multi_az_enabled=self.multi_az_enabled,
            )

    @property
    def instance_type_list(self):
        """Return the list of instance types associated to the Queue."""
        return [compute_resource.instance_type for compute_resource in self.compute_resources]

    @property
    def instance_types_with_instance_storage(self):
        """Return a set of instance types in the queue that have instance store."""
        result = set()
        for compute_resource in self.compute_resources:
            if compute_resource.instance_type_info.instance_storage_supported():
                result.add(compute_resource.instance_type)
        return result


class SchedulerPluginSupportedDistros(Resource):
    """Represent the Supported Distros for a Scheduler Plugin."""

    def __init__(self, x86: List[str] = None, arm64: List[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.x86 = Resource.init_param(x86, default=SUPPORTED_OSES)
        self.arm64 = Resource.init_param(arm64, default=SUPPORTED_OSES)


class SchedulerPluginQueueConstraints(Resource):
    """Represent the Queue Constraints for a Scheduler Plugin."""

    def __init__(self, max_count: int = None, **kwargs):
        super().__init__(**kwargs)
        self.max_count = Resource.init_param(max_count, default=MAX_NUMBER_OF_QUEUES)


class SchedulerPluginComputeResourceConstraints(Resource):
    """Represent the Compute Resource Constraints for a Scheduler Plugin."""

    def __init__(self, max_count: int = None, **kwargs):
        super().__init__(**kwargs)
        self.max_count = Resource.init_param(max_count, default=MAX_NUMBER_OF_COMPUTE_RESOURCES)


class SchedulerPluginRequirements(Resource):
    """Represent the Requirements for a Scheduler Plugin."""

    def __init__(
        self,
        supported_distros: SchedulerPluginSupportedDistros = None,
        supported_regions: List[str] = None,
        queue_constraints: SchedulerPluginQueueConstraints = None,
        compute_resource_constraints: SchedulerPluginComputeResourceConstraints = None,
        requires_sudo_privileges: bool = None,
        supports_cluster_update: bool = None,
        supported_parallel_cluster_versions: str = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.supported_distros = supported_distros
        self.supported_regions = supported_regions
        self.queue_constraints = queue_constraints
        self.compute_resource_constraints = compute_resource_constraints
        self.requires_sudo_privileges = Resource.init_param(requires_sudo_privileges, default=False)
        self.supports_cluster_update = Resource.init_param(supports_cluster_update, default=True)
        self.supported_parallel_cluster_versions = supported_parallel_cluster_versions

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        if self.supported_parallel_cluster_versions:
            self._register_validator(
                SupportedVersionsValidator,
                installed_version=get_installed_version(),
                supported_versions_string=self.supported_parallel_cluster_versions,
            )


class SchedulerPluginCloudFormationInfrastructure(Resource):
    """Represent the CloudFormation infrastructure for a Scheduler Plugin."""

    def __init__(self, template: str, s3_bucket_owner: str = None, checksum: str = None, **kwargs):
        super().__init__(**kwargs)
        self.template = replace_url_parameters(template)
        self.s3_bucket_owner = s3_bucket_owner
        self.checksum = checksum

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(
            UrlValidator,
            url=self.template,
            fail_on_https_error=True,
            fail_on_s3_error=True,
            expected_bucket_owner=self.s3_bucket_owner,
        )


class SchedulerPluginClusterInfrastructure(Resource):
    """Represent the ClusterInfastructure config for a Scheduler Plugin."""

    def __init__(self, cloud_formation: SchedulerPluginCloudFormationInfrastructure = None, **kwargs):
        super().__init__(**kwargs)
        self.cloud_formation = cloud_formation


class SchedulerPluginClusterSharedArtifact(Resource):
    """Represent the ClusterSharedArtifact config for a Scheduler Plugin."""

    def __init__(self, source: str, s3_bucket_owner: str = None, checksum: str = None, **kwargs):
        super().__init__(**kwargs)
        self.source = replace_url_parameters(source)
        self.s3_bucket_owner = s3_bucket_owner
        self.checksum = checksum

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(UrlValidator, url=self.source, expected_bucket_owner=self.s3_bucket_owner)


class SchedulerPluginPluginResources(Resource):
    """Represent the PluginResources config for a Scheduler Plugin."""

    def __init__(self, cluster_shared_artifacts: [SchedulerPluginClusterSharedArtifact], **kwargs):
        super().__init__(**kwargs)
        self.cluster_shared_artifacts = cluster_shared_artifacts


class SchedulerPluginExecuteCommand(Resource):
    """Represent the ExecuteCommand for a Scheduler Plugin."""

    def __init__(self, command: str, **kwargs):
        super().__init__(**kwargs)
        self.command = command


class SchedulerPluginEvent(Resource):
    """Represent the Event config for a Scheduler Plugin."""

    def __init__(self, execute_command: SchedulerPluginExecuteCommand, **kwargs):
        super().__init__(**kwargs)
        self.execute_command = execute_command


class SchedulerPluginEvents(Resource):
    """Represent the Events config for a Scheduler Plugin."""

    def __init__(
        self,
        head_init: SchedulerPluginEvent = None,
        head_configure: SchedulerPluginEvent = None,
        head_finalize: SchedulerPluginEvent = None,
        compute_init: SchedulerPluginEvent = None,
        compute_configure: SchedulerPluginEvent = None,
        compute_finalize: SchedulerPluginEvent = None,
        head_cluster_update: SchedulerPluginEvent = None,
        head_compute_fleet_update: SchedulerPluginEvent = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.head_init = head_init
        self.head_configure = head_configure
        self.head_finalize = head_finalize
        self.compute_init = compute_init
        self.compute_configure = compute_configure
        self.compute_finalize = compute_finalize
        self.head_cluster_update = head_cluster_update
        self.head_compute_fleet_update = head_compute_fleet_update


class SchedulerPluginFile(Resource):
    """Represent the Scheduler Plugin file resource."""

    def __init__(
        self, file_path: str, log_stream_name: str, node_type: str = None, timestamp_format: str = None, **kwargs
    ):
        super().__init__(**kwargs)
        self.file_path = file_path
        self.timestamp_format = Resource.init_param(timestamp_format, default="%Y-%m-%dT%H:%M:%S%z")
        self.node_type = Resource.init_param(node_type, default="ALL")
        self.log_stream_name = log_stream_name


class SchedulerPluginLogs(Resource):
    """Represent the Scheduler Plugin logs resource."""

    def __init__(self, files: [SchedulerPluginFile], **kwargs):
        super().__init__(**kwargs)
        self.files = files


class SchedulerPluginMonitoring(Resource):
    """Represent the Scheduler Plugin monitoring resource."""

    def __init__(self, logs: SchedulerPluginLogs, **kwargs):
        super().__init__(**kwargs)
        self.logs = logs


class SudoerConfiguration(Resource):
    """Represent the SudoerConfiguration resource."""

    def __init__(self, commands: str, run_as: str, **kwargs):
        super().__init__(**kwargs)
        self.commands = commands
        self.run_as = run_as


class SchedulerPluginUser(Resource):
    """Represent the Scheduler Plugin user resource."""

    def __init__(
        self, name: str, enable_imds: bool = None, sudoer_configuration: List[SudoerConfiguration] = (), **kwargs
    ):
        super().__init__(**kwargs)
        self.name = name
        self.enable_imds = Resource.init_param(enable_imds, default=False)
        self.sudoer_configuration = sudoer_configuration

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(
            UserNameValidator,
            user_name=self.name,
        )


class SchedulerPluginDefinition(Resource):
    """Represent the Scheduler Plugin scheduler definition."""

    def __init__(
        self,
        plugin_interface_version: str,
        events: SchedulerPluginEvents,
        metadata: Dict = None,
        requirements: SchedulerPluginRequirements = None,
        cluster_infrastructure: SchedulerPluginClusterInfrastructure = None,
        plugin_resources: SchedulerPluginPluginResources = None,
        monitoring: SchedulerPluginMonitoring = None,
        system_users: [SchedulerPluginUser] = None,
        tags: List[Tag] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.plugin_interface_version = plugin_interface_version
        self.metadata = metadata
        self.requirements = requirements
        self.cluster_infrastructure = cluster_infrastructure
        self.plugin_resources = plugin_resources
        self.events = events
        self.monitoring = monitoring
        self.system_users = system_users
        self.tags = tags

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(
            PluginInterfaceVersionValidator,
            plugin_version=self.plugin_interface_version,
            support_version_low_range=SCHEDULER_PLUGIN_INTERFACE_VERSION_LOW_RANGE,
            support_version_high_range=SCHEDULER_PLUGIN_INTERFACE_VERSION,
        )


class SchedulerPluginSettings(Resource):
    """Represent the Scheduler Plugin settings."""

    def __init__(
        self,
        scheduler_definition: SchedulerPluginDefinition,
        grant_sudo_privileges: bool = None,
        custom_settings: Dict = None,
        scheduler_definition_s3_bucket_owner: str = None,
        scheduler_definition_checksum: str = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.scheduler_definition = scheduler_definition
        self.grant_sudo_privileges = Resource.init_param(grant_sudo_privileges, default=False)
        self.custom_settings = custom_settings
        self.scheduler_definition_s3_bucket_owner = scheduler_definition_s3_bucket_owner
        self.scheduler_definition_checksum = scheduler_definition_checksum

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(
            SudoPrivilegesValidator,
            grant_sudo_privileges=self.grant_sudo_privileges,
            requires_sudo_privileges=self.scheduler_definition.requirements.requires_sudo_privileges
            if self.scheduler_definition.requirements
            else None,
        )

        self._register_validator(
            GrantSudoPrivilegesValidator,
            grant_sudo_privileges=self.grant_sudo_privileges,
            system_users=get_attr(self.scheduler_definition, "system_users"),
        )


class SchedulerPluginScheduling(Resource):
    """Represent a Scheduler Plugin Scheduling resource."""

    def __init__(self, queues: List[SchedulerPluginQueue], settings: SchedulerPluginSettings, **kwargs):
        super().__init__(**kwargs)
        self.scheduler = "plugin"
        self.queues = queues
        self.settings = settings

    def _register_validators(self, context: ValidatorContext = None):  # noqa: D102 #pylint: disable=unused-argument
        self._register_validator(
            DuplicateNameValidator, name_list=[queue.name for queue in self.queues], resource_name="Queue"
        )
        self._register_validator(
            MaxCountValidator,
            resources_length=len(self.queues),
            max_length=get_attr(
                self.settings.scheduler_definition,
                "requirements.queue_constraints.max_count",
                default=MAX_NUMBER_OF_QUEUES,
            ),
            resource_name="SchedulerQueues",
        )
        for queue in self.queues:
            self._register_validator(
                MaxCountValidator,
                resources_length=len(queue.compute_resources),
                max_length=get_attr(
                    self.settings.scheduler_definition,
                    "requirements.compute_resource_constraints.max_count",
                    default=MAX_NUMBER_OF_COMPUTE_RESOURCES,
                ),
                resource_name="ComputeResources",
            )


class CommonSchedulerClusterConfig(BaseClusterConfig):
    """Represent the common Cluster configuration between Slurm Config and Scheduler Plugin Config."""

    def _register_validators(self, context: ValidatorContext = None):
        super()._register_validators(context)
        checked_images = []
        for queue in self.scheduling.queues:
            queue_image = self.image_dict[queue.name]
            self._register_validator(
                ComputeResourceLaunchTemplateValidator,
                queue=queue,
                ami_id=queue_image,
                os=self.image.os,
                tags=self.get_cluster_tags(),
            )
            ami_volume_size = AWSApi.instance().ec2.describe_image(queue_image).volume_size
            root_volume = queue.compute_settings.local_storage.root_volume
            root_volume_size = root_volume.size
            if root_volume_size is None:  # If root volume size is not specified, it will be the size of the AMI.
                root_volume_size = ami_volume_size
            self._register_validator(
                RootVolumeSizeValidator,
                root_volume_size=root_volume_size,
                ami_volume_size=ami_volume_size,
            )
            self._register_validator(
                EbsVolumeTypeSizeValidator, volume_type=root_volume.volume_type, volume_size=root_volume_size
            )
            self._register_validator(
                EbsVolumeIopsValidator,
                volume_type=root_volume.volume_type,
                volume_size=root_volume_size,
                volume_iops=root_volume.iops,
            )
            if queue_image not in checked_images and queue.queue_ami:
                checked_images.append(queue_image)
                self._register_validator(AmiOsCompatibleValidator, os=self.image.os, image_id=queue_image)
            for compute_resource in queue.compute_resources:
                for instance_type in compute_resource.instance_types:
                    self._register_validator(
                        InstanceTypeBaseAMICompatibleValidator,
                        instance_type=instance_type,
                        image=queue_image,
                    )
                self._register_validator(
                    InstanceArchitectureCompatibilityValidator,
                    instance_type_info_list=list(compute_resource.instance_type_info_map.values()),
                    architecture=self.head_node.architecture,
                )
                self._register_validator(
                    EfaOsArchitectureValidator,
                    efa_enabled=compute_resource.efa.enabled,
                    os=self.image.os,
                    architecture=self.head_node.architecture,
                )
                # The validation below has to be in cluster config class instead of queue class
                # to make sure the subnet APIs are cached by previous validations.
                cr_target = compute_resource.capacity_reservation_target or queue.capacity_reservation_target
                if cr_target:
                    self._register_validator(
                        CapacityReservationValidator,
                        capacity_reservation_id=cr_target.capacity_reservation_id,
                        instance_type=getattr(compute_resource, "instance_type", None),
                        subnet=queue.networking.subnet_ids[0],
                    )
                    self._register_validator(
                        CapacityReservationResourceGroupValidator,
                        capacity_reservation_resource_group_arn=cr_target.capacity_reservation_resource_group_arn,
                        instance_types=compute_resource.instance_types,
                        subnet_ids=queue.networking.subnet_ids,
                        queue_name=queue.name,
                        subnet_id_az_mapping=queue.networking.subnet_id_az_mapping,
                    )
                    self._register_validator(
                        PlacementGroupCapacityReservationValidator,
                        placement_group=queue.get_placement_group_settings_for_compute_resource(compute_resource).get(
                            "key"
                        ),
                        odcr=cr_target,
                        subnet=queue.networking.subnet_ids[0],
                        instance_types=compute_resource.instance_types,
                        multi_az_enabled=queue.multi_az_enabled,
                        subnet_id_az_mapping=queue.networking.subnet_id_az_mapping,
                    )

    @property
    def _capacity_reservation_targets(self):
        """Return a list of capacity reservation targets from all queues and compute resources with the section."""
        capacity_reservation_targets_list = []
        for queue in self.scheduling.queues:
            if queue.capacity_reservation_target:
                capacity_reservation_targets_list.append(queue.capacity_reservation_target)
            for compute_resource in queue.compute_resources:
                if compute_resource.capacity_reservation_target:
                    capacity_reservation_targets_list.append(compute_resource.capacity_reservation_target)
        return capacity_reservation_targets_list

    @property
    def capacity_reservation_ids(self):
        """Return a list of capacity reservation ids specified in the config."""
        result = set()
        for capacity_reservation_target in self._capacity_reservation_targets:
            if capacity_reservation_target.capacity_reservation_id:
                result.add(capacity_reservation_target.capacity_reservation_id)
        return list(result)

    @property
    def capacity_reservation_resource_group_arns(self):
        """Return a list of capacity reservation resource group in the config."""
        result = set()
        for capacity_reservation_target in self._capacity_reservation_targets:
            if capacity_reservation_target.capacity_reservation_resource_group_arn:
                result.add(capacity_reservation_target.capacity_reservation_resource_group_arn)
        return list(result)

    @property
    def all_relevant_capacity_reservation_ids(self):
        """Return a list of capacity reservation ids specified in the config or used by resource groups."""
        capacity_reservation_ids = set(self.capacity_reservation_ids)
        for capacity_reservation_resource_group_arn in self.capacity_reservation_resource_group_arns:
            capacity_reservation_ids.update(
                AWSApi.instance().resource_groups.get_capacity_reservation_ids_from_group_resources(
                    capacity_reservation_resource_group_arn
                )
            )
        return list(capacity_reservation_ids)


class SchedulerPluginClusterConfig(CommonSchedulerClusterConfig):
    """Represent the full Scheduler Plugin Cluster configuration."""

    def __init__(self, cluster_name: str, scheduling: SchedulerPluginScheduling, **kwargs):
        super().__init__(cluster_name, **kwargs)
        self.scheduling = scheduling
        self.__image_dict = None
        # Cache capacity reservations information together to reduce number of boto3 calls.
        # Since this cache is only used for validation, if AWSClientError happens
        # (e.g insufficient IAM permissions to describe the capacity reservations), we catch the exception to avoid
        # blocking CLI execution if the user want to suppress the validation.
        try:
            AWSApi.instance().ec2.describe_capacity_reservations(self.all_relevant_capacity_reservation_ids)
        except AWSClientError:
            logging.warning("Unable to cache describe_capacity_reservations results for all capacity reservation ids.")

    def get_instance_types_data(self):
        """Get instance type infos for all instance types used in the configuration file."""
        result = {}
        instance_type_info = self.head_node.instance_type_info
        result[instance_type_info.instance_type()] = instance_type_info.instance_type_data
        for queue in self.scheduling.queues:
            for compute_resource in queue.compute_resources:
                instance_type_info = compute_resource.instance_type_info
                result[instance_type_info.instance_type()] = instance_type_info.instance_type_data
        return result

    def get_cluster_tags(self):
        """Return tags configured in the root of the cluster config and under scheduler definition."""
        return (self.tags if self.tags else []) + get_attr(
            self.scheduling, "settings.scheduler_definition.tags", default=[]
        )

    def _register_validators(self, context: ValidatorContext = None):
        super()._register_validators(context)
        scheduler_definition = self.scheduling.settings.scheduler_definition
        self._register_validator(
            SchedulerPluginOsArchitectureValidator,
            os=self.image.os,
            architecture=self.head_node.architecture,
            supported_x86=get_attr(scheduler_definition, "requirements.supported_distros.x86", default=SUPPORTED_OSES),
            supported_arm64=get_attr(
                scheduler_definition, "requirements.supported_distros.arm64", default=SUPPORTED_OSES
            ),
        )
        self._register_validator(
            SchedulerPluginRegionValidator,
            region=self.region,
            supported_regions=get_attr(scheduler_definition, "requirements.supported_regions"),
        )

    @property
    def image_dict(self):
        """Return image dict of queues, key is queue name, value is image id."""
        if self.__image_dict:
            return self.__image_dict
        self.__image_dict = {}

        for queue in self.scheduling.queues:
            self.__image_dict[queue.name] = queue.queue_ami or self.image.custom_ami or self.official_ami

        return self.__image_dict


class SlurmClusterConfig(CommonSchedulerClusterConfig):
    """Represent the full Slurm Cluster configuration."""

    def __init__(self, cluster_name: str, scheduling: SlurmScheduling, **kwargs):
        super().__init__(cluster_name, **kwargs)
        self.scheduling = scheduling
        self.__image_dict = None
        # Cache capacity reservations information together to reduce number of boto3 calls.
        # Since this cache is only used for validation, if AWSClientError happens
        # (e.g insufficient IAM permissions to describe the capacity reservations), we catch the exception to avoid
        # blocking CLI execution if the user want to suppress the validation.
        try:
            AWSApi.instance().ec2.describe_capacity_reservations(self.all_relevant_capacity_reservation_ids)
        except AWSClientError:
            logging.warning("Unable to cache describe_capacity_reservations results for all capacity reservation ids.")

    def get_instance_types_data(self):
        """Get instance type infos for all instance types used in the configuration file."""
        result = {}
        instance_type_info = self.head_node.instance_type_info
        result[instance_type_info.instance_type()] = instance_type_info.instance_type_data
        for queue in self.scheduling.queues:
            for compute_resource in queue.compute_resources:
                for instance_type in compute_resource.instance_types:
                    instance_type_info = compute_resource.instance_type_info_map[instance_type]
                    result[instance_type] = instance_type_info.instance_type_data
        return result

    def _register_validators(self, context: ValidatorContext = None):
        super()._register_validators(context)
        self._register_validator(
            MixedSecurityGroupOverwriteValidator,
            head_node_security_groups=self.head_node.networking.security_groups,
            queues=self.scheduling.queues,
        )
        if self.scheduling.settings and self.scheduling.settings.dns and self.scheduling.settings.dns.hosted_zone_id:
            self._register_validator(
                HostedZoneValidator,
                hosted_zone_id=self.scheduling.settings.dns.hosted_zone_id,
                cluster_vpc=self.vpc_id,
                cluster_name=self.cluster_name,
            )

        instance_types_data = self.get_instance_types_data()
        for queue in self.scheduling.queues:
            for compute_resource in queue.compute_resources:
                if self.scheduling.settings.enable_memory_based_scheduling:
                    for instance_type in compute_resource.instance_types:
                        self._register_validator(
                            InstanceTypeMemoryInfoValidator,
                            instance_type=instance_type,
                            instance_type_data=instance_types_data[instance_type],
                        )
                for instance_type in compute_resource.instance_types:
                    self._register_validator(
                        InstanceTypeAcceleratorManufacturerValidator,
                        instance_type=instance_type,
                        instance_type_data=instance_types_data[instance_type],
                    )
                    self._register_validator(
                        InstanceTypePlacementGroupValidator,
                        instance_type=instance_type,
                        instance_type_data=instance_types_data[instance_type],
                        placement_group_enabled=queue.is_placement_group_enabled_for_compute_resource(compute_resource),
                    )
                if isinstance(compute_resource, SlurmFlexibleComputeResource):
                    validator_args = dict(
                        queue_name=queue.name,
                        multiaz_queue=queue.multi_az_enabled,
                        capacity_type=queue.capacity_type,
                        allocation_strategy=queue.allocation_strategy,
                        compute_resource_name=compute_resource.name,
                        instance_types_info=compute_resource.instance_type_info_map,
                        disable_simultaneous_multithreading=compute_resource.disable_simultaneous_multithreading,
                        efa_enabled=compute_resource.efa and compute_resource.efa.enabled,
                        placement_group_enabled=queue.is_placement_group_enabled_for_compute_resource(compute_resource),
                        memory_scheduling_enabled=self.scheduling.settings.enable_memory_based_scheduling,
                    )
                    flexible_instance_types_validators = [
                        InstancesCPUValidator,
                        InstancesAcceleratorsValidator,
                        InstancesEFAValidator,
                        InstancesNetworkingValidator,
                        InstancesAllocationStrategyValidator,
                        InstancesMemorySchedulingValidator,
                    ]
                    for validator in flexible_instance_types_validators:
                        self._register_validator(validator, **validator_args)

    @property
    def image_dict(self):
        """Return image dict of queues, key is queue name, value is image id."""
        if self.__image_dict:
            return self.__image_dict
        self.__image_dict = {}

        for queue in self.scheduling.queues:
            self.__image_dict[queue.name] = queue.queue_ami or self.image.custom_ami or self.official_ami

        return self.__image_dict
