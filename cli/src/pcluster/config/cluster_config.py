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
from enum import Enum
from typing import List, Union

import pkg_resources

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.aws_resources import InstanceTypeInfo
from pcluster.aws.common import get_region
from pcluster.config.common import AdditionalIamPolicy, BaseDevSettings, BaseTag, Resource
from pcluster.constants import (
    CIDR_ALL_IPS,
    CW_DASHBOARD_ENABLED_DEFAULT,
    CW_LOGS_ENABLED_DEFAULT,
    CW_LOGS_RETENTION_DAYS_DEFAULT,
    DEFAULT_MAX_COUNT,
    DEFAULT_MIN_COUNT,
    EBS_VOLUME_SIZE_DEFAULT,
    EBS_VOLUME_TYPE_DEFAULT,
    EBS_VOLUME_TYPE_IOPS_DEFAULT,
    MAX_STORAGE_COUNT,
)
from pcluster.utils import get_partition, get_resource_name_from_resource_arn
from pcluster.validators.awsbatch_validators import (
    AwsBatchComputeInstanceTypeValidator,
    AwsBatchComputeResourceSizeValidator,
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
    DisableSimultaneousMultithreadingArchitectureValidator,
    DuplicateInstanceTypeValidator,
    DuplicateMountDirValidator,
    DuplicateNameValidator,
    EfaOsArchitectureValidator,
    EfaPlacementGroupValidator,
    EfaSecurityGroupValidator,
    EfaValidator,
    EfsIdValidator,
    FsxArchitectureOsValidator,
    FsxNetworkingValidator,
    HeadNodeImdsValidator,
    HeadNodeLaunchTemplateValidator,
    HostedZoneValidator,
    InstanceArchitectureCompatibilityValidator,
    IntelHpcArchitectureValidator,
    IntelHpcOsValidator,
    NameValidator,
    NumberOfStorageValidator,
    OverlappingMountDirValidator,
    RegionValidator,
    SchedulerOsValidator,
    SharedStorageNameValidator,
)
from pcluster.validators.ebs_validators import (
    EbsVolumeIopsValidator,
    EbsVolumeSizeSnapshotValidator,
    EbsVolumeThroughputIopsValidator,
    EbsVolumeThroughputValidator,
    EbsVolumeTypeSizeValidator,
    SharedEbsVolumeIdValidator,
)
from pcluster.validators.ec2_validators import (
    AmiOsCompatibleValidator,
    CapacityTypeValidator,
    InstanceTypeBaseAMICompatibleValidator,
    InstanceTypeValidator,
    KeyPairValidator,
    PlacementGroupIdValidator,
)
from pcluster.validators.fsx_validators import (
    FsxAutoImportValidator,
    FsxBackupIdValidator,
    FsxBackupOptionsValidator,
    FsxPersistentOptionsValidator,
    FsxS3Validator,
    FsxStorageCapacityValidator,
    FsxStorageTypeOptionsValidator,
)
from pcluster.validators.iam_validators import IamPolicyValidator, InstanceProfileValidator, RoleValidator
from pcluster.validators.kms_validators import KmsKeyIdEncryptedValidator, KmsKeyValidator
from pcluster.validators.networking_validators import ElasticIpValidator, SecurityGroupsValidator, SubnetsValidator
from pcluster.validators.s3_validators import (
    S3BucketRegionValidator,
    S3BucketUriValidator,
    S3BucketValidator,
    UrlValidator,
)

LOGGER = logging.getLogger(__name__)

# pylint: disable=C0302

# ---------------------- Storage ---------------------- #


class Ebs(Resource):
    """Represent the configuration shared by EBS root volume and Shared EBS."""

    def __init__(
        self,
        size: int = None,
        encrypted: bool = None,
        volume_type: str = None,
        iops: int = None,
        throughput: int = None,
    ):
        super().__init__()
        self.size = Resource.init_param(size, default=EBS_VOLUME_SIZE_DEFAULT)
        self.encrypted = Resource.init_param(encrypted, default=True)
        self.volume_type = Resource.init_param(volume_type, default=EBS_VOLUME_TYPE_DEFAULT)
        self.iops = Resource.init_param(iops, default=EBS_VOLUME_TYPE_IOPS_DEFAULT.get(self.volume_type))
        self.throughput = Resource.init_param(throughput, default=125 if self.volume_type == "gp3" else None)

    def _register_validators(self):
        self._register_validator(EbsVolumeTypeSizeValidator, volume_type=self.volume_type, volume_size=self.size)
        self._register_validator(
            EbsVolumeIopsValidator, volume_type=self.volume_type, volume_size=self.size, volume_iops=self.iops
        )
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

    def __init__(self, delete_on_termination: bool = None, **kwargs):
        super().__init__(**kwargs)
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
        self.mount_dir = Resource.init_param(mount_dir, default="/scratch")


class LocalStorage(Resource):
    """Represent the entire node storage configuration."""

    def __init__(self, root_volume: Ebs = None, ephemeral_volume: EphemeralVolume = None, **kwargs):
        super().__init__(**kwargs)
        self.root_volume = root_volume
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
        kms_key_id: str = None,
        snapshot_id: str = None,
        volume_id: str = None,
        raid: Raid = None,
        deletion_policy: str = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.kms_key_id = Resource.init_param(kms_key_id)
        self.mount_dir = Resource.init_param(mount_dir)
        self.name = Resource.init_param(name)
        self.shared_storage_type = SharedStorageType.RAID if raid else SharedStorageType.EBS
        self.snapshot_id = Resource.init_param(snapshot_id)
        self.volume_id = Resource.init_param(volume_id)
        self.raid = raid
        self.deletion_policy = Resource.init_param(deletion_policy, default="Delete")

    def _register_validators(self):
        super()._register_validators()
        self._register_validator(SharedStorageNameValidator, name=self.name)
        if self.kms_key_id:
            self._register_validator(KmsKeyValidator, kms_key_id=self.kms_key_id)
            self._register_validator(KmsKeyIdEncryptedValidator, kms_key_id=self.kms_key_id, encrypted=self.encrypted)
        self._register_validator(SharedEbsVolumeIdValidator, volume_id=self.volume_id)
        self._register_validator(EbsVolumeSizeSnapshotValidator, snapshot_id=self.snapshot_id, volume_size=self.size)


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

    def _register_validators(self):
        self._register_validator(SharedStorageNameValidator, name=self.name)
        if self.kms_key_id:
            self._register_validator(KmsKeyValidator, kms_key_id=self.kms_key_id)
            self._register_validator(KmsKeyIdEncryptedValidator, kms_key_id=self.kms_key_id, encrypted=self.encrypted)


class SharedFsx(Resource):
    """Represent the shared FSX resource."""

    def __init__(
        self,
        mount_dir: str,
        name: str,
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
    ):
        super().__init__()
        self.mount_dir = Resource.init_param(mount_dir)
        self.name = Resource.init_param(name)
        self.shared_storage_type = SharedStorageType.FSX
        self.storage_capacity = Resource.init_param(storage_capacity)
        self.fsx_storage_type = Resource.init_param(fsx_storage_type)
        self.deployment_type = Resource.init_param(deployment_type)
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
        self.fsx_storage_type = Resource.init_param(fsx_storage_type)
        self.__file_system_data = None

    def _register_validators(self):
        self._register_validator(SharedStorageNameValidator, name=self.name)
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

    @property
    def file_system_data(self):
        """Return filesystem information if using existing FSx."""
        if not self.__file_system_data and self.file_system_id:
            self.__file_system_data = AWSApi.instance().fsx.get_filesystem_info(self.file_system_id)
        return self.__file_system_data

    @property
    def existing_mount_name(self):
        """Return MountName if using existing FSx filesystem."""
        return self.file_system_data.mount_name if self.file_system_id else ""

    @property
    def existing_dns_name(self):
        """Return DNSName if using existing FSx filesystem."""
        return self.file_system_data.dns_name if self.file_system_id else ""


# ---------------------- Networking ---------------------- #


class Proxy(Resource):
    """Represent the proxy."""

    def __init__(self, http_proxy_address: str = None):
        super().__init__()
        self.http_proxy_address = http_proxy_address


class _BaseNetworking(Resource):
    """Represent the networking configuration shared by head node and compute node."""

    def __init__(
        self, security_groups: List[str] = None, additional_security_groups: List[str] = None, proxy: Proxy = None
    ):
        super().__init__()
        self.security_groups = Resource.init_param(security_groups)
        self.additional_security_groups = Resource.init_param(additional_security_groups)
        self.proxy = proxy

    def _register_validators(self):
        self._register_validator(SecurityGroupsValidator, security_group_ids=self.security_groups)
        self._register_validator(SecurityGroupsValidator, security_group_ids=self.additional_security_groups)


class HeadNodeNetworking(_BaseNetworking):
    """Represent the networking configuration for the head node."""

    def __init__(self, subnet_id: str, elastic_ip: Union[str, bool] = None, **kwargs):
        super().__init__(**kwargs)
        self.subnet_id = Resource.init_param(subnet_id)
        self.elastic_ip = Resource.init_param(elastic_ip)

    def _register_validators(self):
        super()._register_validators()
        self._register_validator(ElasticIpValidator, elastic_ip=self.elastic_ip)

    @property
    def availability_zone(self):
        """Compute availability zone from subnet id."""
        return AWSApi.instance().ec2.get_subnet_avail_zone(self.subnet_id)


class PlacementGroup(Resource):
    """Represent the placement group for the Queue networking."""

    def __init__(self, enabled: bool = None, id: str = None):
        super().__init__()
        self.enabled = Resource.init_param(enabled, default=False)
        self.id = Resource.init_param(id)

    def _register_validators(self):
        self._register_validator(PlacementGroupIdValidator, placement_group_id=self.id)


class QueueNetworking(_BaseNetworking):
    """Represent the networking configuration for the Queue."""

    def __init__(
        self, subnet_ids: List[str], placement_group: PlacementGroup = None, assign_public_ip: str = None, **kwargs
    ):
        super().__init__(**kwargs)
        self.assign_public_ip = Resource.init_param(assign_public_ip)
        self.subnet_ids = Resource.init_param(subnet_ids)
        self.placement_group = placement_group


class Ssh(Resource):
    """Represent the SSH configuration for a node."""

    def __init__(self, key_name: str = None, allowed_ips: str = None, **kwargs):
        super().__init__(**kwargs)
        self.key_name = Resource.init_param(key_name)
        self.allowed_ips = Resource.init_param(allowed_ips, default=CIDR_ALL_IPS)

    def _register_validators(self):
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

    def _register_validators(self):
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

    def _register_validators(self):
        if self.instance_role:
            self._register_validator(RoleValidator, role_arn=self.instance_role)
        elif self.instance_profile:
            self._register_validator(InstanceProfileValidator, instance_profile_arn=self.instance_profile)


class Imds(Resource):
    """Represent the IMDS configuration."""

    def __init__(self, secured: bool = None, **kwargs):
        super().__init__(**kwargs)
        self.secured = Resource.init_param(secured, default=True)


class ClusterIam(Resource):
    """Represent the IAM configuration for Cluster."""

    def __init__(self, roles: Roles = None, permissions_boundary: str = None):
        super().__init__()
        self.roles = roles
        self.permissions_boundary = Resource.init_param(permissions_boundary)

    def _register_validators(self):
        if self.permissions_boundary:
            self._register_validator(IamPolicyValidator, policy=self.permissions_boundary)


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


class ClusterDevSettings(BaseDevSettings):
    """Represent the dev settings configuration."""

    def __init__(
        self,
        cluster_template: str = None,
        ami_search_filters: AmiSearchFilters = None,
        instance_types_data: str = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.cluster_template = Resource.init_param(cluster_template)
        self.ami_search_filters = Resource.init_param(ami_search_filters)
        self.instance_types_data = Resource.init_param(instance_types_data)

    def _register_validators(self):
        super()._register_validators()
        if self.cluster_template:
            self._register_validator(UrlValidator, url=self.cluster_template)


# ---------------------- Nodes and Cluster ---------------------- #


class Image(Resource):
    """Represent the configuration of an Image."""

    def __init__(self, os: str, custom_ami: str = None):
        super().__init__()
        self.os = Resource.init_param(os)
        self.custom_ami = Resource.init_param(custom_ami)

    def _register_validators(self):
        if self.custom_ami:
            self._register_validator(CustomAmiTagValidator, custom_ami=self.custom_ami)
            self._register_validator(AmiOsCompatibleValidator, os=self.os, image_id=self.custom_ami)


class HeadNodeImage(Resource):
    """Represent the configuration of HeadNode Image."""

    def __init__(self, custom_ami: str, **kwargs):
        super().__init__()
        self.custom_ami = Resource.init_param(custom_ami)

    def _register_validators(self):
        if self.custom_ami:
            self._register_validator(CustomAmiTagValidator, custom_ami=self.custom_ami)


class QueueImage(Resource):
    """Represent the configuration of Queue Image."""

    def __init__(self, custom_ami: str, **kwargs):
        super().__init__()
        self.custom_ami = Resource.init_param(custom_ami)

    def _register_validators(self):
        if self.custom_ami:
            self._register_validator(CustomAmiTagValidator, custom_ami=self.custom_ami)


class CustomAction(Resource):
    """Represent a custom action resource."""

    def __init__(self, script: str, args: List[str] = None):
        super().__init__()
        self.script = Resource.init_param(script)
        self.args = Resource.init_param(args)

    def _register_validators(self):
        self._register_validator(UrlValidator, url=self.script)


class CustomActions(Resource):
    """Represent a custom action resource."""

    def __init__(self, on_node_start: CustomAction = None, on_node_configured: CustomAction = None):
        super().__init__()
        self.on_node_start = Resource.init_param(on_node_start)
        self.on_node_configured = Resource.init_param(on_node_configured)


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

    def _register_validators(self):
        self._register_validator(InstanceTypeValidator, instance_type=self.instance_type)
        self._register_validator(
            DisableSimultaneousMultithreadingArchitectureValidator,
            disable_simultaneous_multithreading=self.disable_simultaneous_multithreading,
            architecture=self.architecture,
        )

    @property
    def architecture(self) -> str:
        """Compute cluster's architecture based on its head node instance type."""
        return self.instance_type_info.supported_architecture()[0]

    @property
    def vcpus(self) -> int:
        """Get the number of vcpus for the instance according to disable_hyperthreading and instance features."""
        instance_type_info = self.instance_type_info
        default_threads_per_core = instance_type_info.default_threads_per_core()
        return (
            instance_type_info.vcpus_count()
            if not self.disable_simultaneous_multithreading
            else (instance_type_info.vcpus_count() // default_threads_per_core)
        )

    @property
    def pass_cpu_options_in_launch_template(self) -> bool:
        """Check whether CPU Options must be passed in launch template for head node."""
        return self.disable_simultaneous_multithreading and self.instance_type_info.is_cpu_options_supported_in_lt()

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
    def disable_simultaneous_multithreading_via_cpu_options(self) -> bool:
        """Return true if simultaneous multithreading must be disabled through cpu options."""
        return self.disable_simultaneous_multithreading and self.instance_type_info.is_cpu_options_supported_in_lt()

    @property
    def disable_simultaneous_multithreading_manually(self) -> bool:
        """Return true if simultaneous multithreading must be disabled with a cookbook script."""
        return self.disable_simultaneous_multithreading and not self.instance_type_info.is_cpu_options_supported_in_lt()

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

    def _register_validators(self):
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

    def __init__(self, name: str, networking: QueueNetworking, capacity_type: str = None):
        super().__init__()
        self.name = Resource.init_param(name)
        self.networking = networking
        _capacity_type = CapacityType[capacity_type.upper()] if capacity_type else None
        self.capacity_type = Resource.init_param(_capacity_type, default=CapacityType.ONDEMAND)

    def _register_validators(self):
        self._register_validator(NameValidator, name=self.name)


class BaseClusterConfig(Resource):
    """Represent the common Cluster config."""

    def __init__(
        self,
        cluster_name: str,
        image: Image,
        head_node: HeadNode,
        shared_storage: List[Resource] = None,
        monitoring: Monitoring = None,
        additional_packages: AdditionalPackages = None,
        tags: List[Tag] = None,
        iam: ClusterIam = None,
        config_region: str = None,
        custom_s3_bucket: str = None,
        additional_resources: str = None,
        dev_settings: ClusterDevSettings = None,
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
        self.shared_storage = shared_storage
        self.monitoring = monitoring or Monitoring(implied=True)
        self.additional_packages = additional_packages
        self.tags = tags
        self.iam = iam
        self.custom_s3_bucket = Resource.init_param(custom_s3_bucket)
        self._bucket = None
        self.additional_resources = Resource.init_param(additional_resources)
        self.dev_settings = dev_settings
        self.cluster_template_body = None
        self.source_config = None
        self.config_version = ""
        self.original_config_version = ""
        self._official_ami = None

    def _register_validators(self):
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
        self._register_validator(
            SubnetsValidator, subnet_ids=self.compute_subnet_ids + [self.head_node.networking.subnet_id]
        )
        self._register_storage_validators()
        self._register_validator(HeadNodeLaunchTemplateValidator, head_node=self.head_node, ami_id=self.head_node_ami)

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

    def _register_storage_validators(self):
        storage_count = {"ebs": 0, "efs": 0, "fsx": 0, "raid": 0}
        if self.shared_storage:
            self._register_validator(
                DuplicateNameValidator,
                name_list=[storage.name for storage in self.shared_storage],
                resource_name="Shared Storage",
            )
            for storage in self.shared_storage:
                self._register_validator(SharedStorageNameValidator, name=storage.name)
                if isinstance(storage, SharedFsx):
                    storage_count["fsx"] += 1
                    if storage.file_system_id:
                        self._register_validator(
                            FsxNetworkingValidator,
                            file_system_id=storage.file_system_id,
                            head_node_subnet_id=self.head_node.networking.subnet_id,
                        )
                    self._register_validator(
                        FsxArchitectureOsValidator, architecture=self.head_node.architecture, os=self.image.os
                    )
                if isinstance(storage, SharedEbs):
                    if storage.raid:
                        storage_count["raid"] += 1
                    else:
                        storage_count["ebs"] += 1
                if isinstance(storage, SharedEfs):
                    storage_count["efs"] += 1
                    if storage.file_system_id:
                        self._register_validator(
                            EfsIdValidator,
                            efs_id=storage.file_system_id,
                            head_node_avail_zone=self.head_node.networking.availability_zone,
                        )

            for storage_type in ["ebs", "efs", "fsx", "raid"]:
                self._register_validator(
                    NumberOfStorageValidator,
                    storage_type=storage_type.upper(),
                    max_number=MAX_STORAGE_COUNT.get(storage_type),
                    storage_count=storage_count[storage_type],
                )

        self._register_validator(DuplicateMountDirValidator, mount_dir_list=self.mount_dir_list)
        self._register_validator(OverlappingMountDirValidator, mount_dir_list=self.mount_dir_list)

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
    def mount_dir_list(self):
        """Retrieve the list of mount dirs for the shared storage and head node ephemeral volume."""
        mount_dir_list = []
        if self.shared_storage:
            for storage in self.shared_storage:
                mount_dir_list.append(storage.mount_dir)

        if self.head_node.local_storage.ephemeral_volume:
            mount_dir_list.append(self.head_node.local_storage.ephemeral_volume.mount_dir)

        return mount_dir_list

    @property
    def compute_subnet_ids(self):
        """Return the list of all compute subnet ids in the cluster."""
        return list(
            {
                subnet_id
                for queue in self.scheduling.queues
                if queue.networking.subnet_ids
                for subnet_id in queue.networking.subnet_ids
                if queue.networking.subnet_ids
            }
        )

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

    def _register_validators(self):
        super()._register_validators()
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

    def __init__(self, compute_resources: List[AwsBatchComputeResource], **kwargs):
        super().__init__(**kwargs)
        self.compute_resources = compute_resources

    def _register_validators(self):
        super()._register_validators()
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

    def _register_validators(self):
        self._register_validator(
            DuplicateNameValidator, name_list=[queue.name for queue in self.queues], resource_name="Queue"
        )


class AwsBatchClusterConfig(BaseClusterConfig):
    """Represent the full AwsBatch Cluster configuration."""

    def __init__(self, cluster_name: str, scheduling: AwsBatchScheduling, **kwargs):
        super().__init__(cluster_name, **kwargs)
        self.scheduling = scheduling

    def _register_validators(self):
        super()._register_validators()
        self._register_validator(AwsBatchRegionValidator, region=self.region)
        self._register_validator(SchedulerOsValidator, scheduler=self.scheduling.scheduler, os=self.image.os)
        self._register_validator(
            HeadNodeImdsValidator, imds_secured=self.head_node.imds.secured, scheduler=self.scheduling.scheduler
        )
        # TODO add InstanceTypesBaseAMICompatibleValidator

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


class SlurmComputeResource(BaseComputeResource):
    """Represent the Slurm Compute Resource."""

    def __init__(
        self,
        instance_type: str = None,
        max_count: int = None,
        min_count: int = None,
        spot_price: float = None,
        efa: Efa = None,
        disable_simultaneous_multithreading: bool = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.instance_type = Resource.init_param(instance_type)
        self.max_count = Resource.init_param(max_count, default=DEFAULT_MAX_COUNT)
        self.min_count = Resource.init_param(min_count, default=DEFAULT_MIN_COUNT)
        self.spot_price = Resource.init_param(spot_price)
        self.disable_simultaneous_multithreading = Resource.init_param(
            disable_simultaneous_multithreading, default=False
        )
        self.__instance_type_info = None
        self.efa = efa or Efa(enabled=False, implied=True)

    @property
    def instance_type_info(self) -> InstanceTypeInfo:
        """Return instance type information."""
        return AWSApi.instance().ec2.get_instance_type_info(self.instance_type)

    def _register_validators(self):
        super()._register_validators()
        self._register_validator(ComputeResourceSizeValidator, min_count=self.min_count, max_count=self.max_count)
        self._register_validator(
            DisableSimultaneousMultithreadingArchitectureValidator,
            disable_simultaneous_multithreading=self.disable_simultaneous_multithreading,
            architecture=self.architecture,
        )
        self._register_validator(
            EfaValidator,
            instance_type=self.instance_type,
            efa_enabled=self.efa.enabled,
            gdr_support=self.efa.gdr_support,
        )

    @property
    def architecture(self) -> str:
        """Compute cluster's architecture based on its head node instance type."""
        return self._instance_type_info.supported_architecture()[0]

    @property
    def vcpus(self) -> int:
        """Get the number of vcpus for the instance according to disable_hyperthreading and instance features."""
        instance_type_info = self._instance_type_info
        default_threads_per_core = instance_type_info.default_threads_per_core()
        return (
            instance_type_info.vcpus_count()
            if not self.disable_simultaneous_multithreading
            else (instance_type_info.vcpus_count() // default_threads_per_core)
        )

    @property
    def pass_cpu_options_in_launch_template(self) -> bool:
        """Check whether CPU Options must be passed in launch template for head node."""
        return self.disable_simultaneous_multithreading and self._instance_type_info.is_cpu_options_supported_in_lt()

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
    def disable_simultaneous_multithreading_via_cpu_options(self) -> bool:
        """Return true if simultaneous multithreading must be disabled through cpu options."""
        return self.disable_simultaneous_multithreading and self.instance_type_info.is_cpu_options_supported_in_lt()

    @property
    def disable_simultaneous_multithreading_manually(self) -> bool:
        """Return true if simultaneous multithreading must be disabled with a cookbook script."""
        return self.disable_simultaneous_multithreading and not self.instance_type_info.is_cpu_options_supported_in_lt()


class SlurmQueue(BaseQueue):
    """Represent the Slurm Queue resource."""

    def __init__(
        self,
        compute_resources: List[SlurmComputeResource],
        compute_settings: ComputeSettings = None,
        custom_actions: CustomActions = None,
        iam: Iam = None,
        image: QueueImage = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.compute_resources = compute_resources
        self.compute_settings = compute_settings or ComputeSettings(implied=True)
        self.custom_actions = custom_actions
        self.iam = iam or Iam(implied=True)
        self.image = image

    def _register_validators(self):
        super()._register_validators()
        self._register_validator(DuplicateInstanceTypeValidator, instance_type_list=self.instance_type_list)
        self._register_validator(
            DuplicateNameValidator,
            name_list=[compute_resource.name for compute_resource in self.compute_resources],
            resource_name="Compute resource",
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
                placement_group_enabled=self.networking.placement_group and self.networking.placement_group.enabled,
                placement_group_config_implicit=self.networking.placement_group is None
                or self.networking.placement_group.is_implied("enabled"),
            )

    @property
    def instance_type_list(self):
        """Return the list of instance types associated to the Queue."""
        return [compute_resource.instance_type for compute_resource in self.compute_resources]

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


class Dns(Resource):
    """Represent the DNS settings."""

    def __init__(self, disable_managed_dns: bool = None, hosted_zone_id: str = None):
        super().__init__()
        self.disable_managed_dns = Resource.init_param(disable_managed_dns, default=False)
        self.hosted_zone_id = Resource.init_param(hosted_zone_id)


class SlurmSettings(Resource):
    """Represent the Slurm settings."""

    def __init__(self, scaledown_idletime: int = None, dns: Dns = None, **kwargs):
        super().__init__(**kwargs)
        self.scaledown_idletime = Resource.init_param(scaledown_idletime, default=10)
        self.dns = dns


class SlurmScheduling(Resource):
    """Represent a slurm Scheduling resource."""

    def __init__(self, queues: List[SlurmQueue], settings: SlurmSettings = None):
        super().__init__()
        self.scheduler = "slurm"
        self.queues = queues
        self.settings = settings or SlurmSettings(implied=True)

    def _register_validators(self):
        self._register_validator(
            DuplicateNameValidator, name_list=[queue.name for queue in self.queues], resource_name="Queue"
        )


class SlurmClusterConfig(BaseClusterConfig):
    """Represent the full Slurm Cluster configuration."""

    def __init__(self, cluster_name: str, scheduling: SlurmScheduling, **kwargs):
        super().__init__(cluster_name, **kwargs)
        self.scheduling = scheduling
        self.__image_dict = None

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

    def _register_validators(self):
        super()._register_validators()
        self._register_validator(SchedulerOsValidator, scheduler=self.scheduling.scheduler, os=self.image.os)
        self._register_validator(
            HeadNodeImdsValidator, imds_secured=self.head_node.imds.secured, scheduler=self.scheduling.scheduler
        )
        if self.scheduling.settings and self.scheduling.settings.dns and self.scheduling.settings.dns.hosted_zone_id:
            self._register_validator(
                HostedZoneValidator,
                hosted_zone_id=self.scheduling.settings.dns.hosted_zone_id,
                cluster_vpc=self.vpc_id,
                cluster_name=self.cluster_name,
            )

        checked_images = []

        for queue in self.scheduling.queues:
            self._register_validator(
                ComputeResourceLaunchTemplateValidator, queue=queue, ami_id=self.image_dict[queue.name]
            )
            queue_image = self.image_dict[queue.name]
            if queue_image not in checked_images and queue.queue_ami:
                checked_images.append(queue_image)
                self._register_validator(AmiOsCompatibleValidator, os=self.image.os, image_id=queue_image)
            for compute_resource in queue.compute_resources:
                if self.image_dict[queue.name]:
                    self._register_validator(
                        InstanceTypeBaseAMICompatibleValidator,
                        instance_type=compute_resource.instance_type,
                        image=queue_image,
                    )
                self._register_validator(
                    InstanceArchitectureCompatibilityValidator,
                    instance_type=compute_resource.instance_type,
                    architecture=self.head_node.architecture,
                )
                self._register_validator(
                    EfaOsArchitectureValidator,
                    efa_enabled=compute_resource.efa.enabled,
                    os=self.image.os,
                    architecture=self.head_node.architecture,
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
