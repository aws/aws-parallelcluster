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
from enum import Enum
from typing import List

from pcluster.constants import CIDR_ALL_IPS, EBS_VOLUME_TYPE_IOPS_DEFAULT
from pcluster.models.common import BaseDevSettings, BaseTag, Resource
from pcluster.utils import (
    error,
    get_availability_zone_of_subnet,
    get_region,
    get_supported_architectures_for_instance_type,
)
from pcluster.validators.cluster_validators import (
    ArchitectureOsValidator,
    DcvValidator,
    DuplicateMountDirValidator,
    EfaOsArchitectureValidator,
    EfsIdValidator,
    FsxArchitectureOsValidator,
    FsxNetworkingValidator,
    IntelHpcArchitectureValidator,
    IntelHpcOsValidator,
    NameValidator,
    NumberOfStorageValidator,
    SimultaneousMultithreadingArchitectureValidator,
    TagKeyValidator,
)
from pcluster.validators.ebs_validators import (
    EbsVolumeIopsValidator,
    EbsVolumeThroughputIopsValidator,
    EbsVolumeThroughputValidator,
    EbsVolumeTypeSizeValidator,
    SharedEBSVolumeIdValidator,
)
from pcluster.validators.ec2_validators import (
    AdditionalIamPolicyValidator,
    InstanceTypeValidator,
    KeyPairValidator,
    PlacementGroupIdValidator,
)
from pcluster.validators.fsx_validators import (
    FsxBackupIdValidator,
    FsxBackupOptionsValidator,
    FsxPersistentOptionsValidator,
    FsxS3Validator,
    FsxStorageCapacityValidator,
    FsxStorageTypeOptionsValidator,
)
from pcluster.validators.networking_validators import SecurityGroupsValidator
from pcluster.validators.s3_validators import S3BucketUriValidator, S3BucketValidator, UrlValidator

# ---------------------- Storage ---------------------- #

MAX_STORAGE_COUNT = {"ebs": 5, "efs": 1, "fsx": 1}


class Ebs(Resource):
    """Represent the configuration shared by EBS root volume and Shared EBS."""

    def __init__(
        self,
        volume_type: str = None,
        iops: int = None,
        size: int = None,
        encrypted: bool = None,
        kms_key_id: str = None,
        throughput: int = None,
    ):
        super().__init__()
        self.volume_type = Resource.init_param(volume_type, default="gp2")
        self.iops = Resource.init_param(iops, default=EBS_VOLUME_TYPE_IOPS_DEFAULT.get(self.volume_type))
        self.size = Resource.init_param(size, default=20)
        self.encrypted = Resource.init_param(encrypted, default=False)
        self.kms_key_id = Resource.init_param(kms_key_id)
        self.throughput = Resource.init_param(throughput, default=125 if self.volume_type == "gp3" else None)

    def _register_validators(self):
        self._add_validator(
            EbsVolumeTypeSizeValidator, priority=10, volume_type=self.volume_type, volume_size=self.size
        )
        self._add_validator(
            EbsVolumeIopsValidator,
            volume_type=self.volume_type,
            volume_size=self.size,
            volume_iops=self.iops,
        )
        self._add_validator(
            EbsVolumeThroughputValidator,
            volume_type=self.volume_type,
            volume_throughput=self.throughput,
        )
        self._add_validator(
            EbsVolumeThroughputIopsValidator,
            volume_type=self.volume_type,
            volume_iops=self.iops,
            volume_throughput=self.throughput,
        )


class Raid(Resource):
    """Represent the Raid configuration."""

    def __init__(self, raid_type: int = None, number_of_volumes=None):
        super().__init__()
        self.raid_type = Resource.init_param(raid_type)
        self.number_of_volumes = Resource.init_param(number_of_volumes, default=2)


class EphemeralVolume(Resource):
    """Represent the Ephemeral Volume resource."""

    def __init__(self, encrypted: bool = None, mount_dir: str = None):
        super().__init__()
        self.encrypted = Resource.init_param(encrypted, default=False)
        self.mount_dir = Resource.init_param(mount_dir, default="/scratch")


class Storage(Resource):
    """Represent the entire node storage configuration."""

    def __init__(self, root_volume: Ebs = None, ephemeral_volume: EphemeralVolume = None):
        super().__init__()
        self.root_volume = root_volume
        self.ephemeral_volume = ephemeral_volume


class SharedStorage(Resource):
    """Represent a generic shared Storage resource."""

    class Type(Enum):
        """Define storage types to be used as shared storage."""

        EBS = "ebs"
        EFS = "efs"
        FSX = "fsx"

    def __init__(self, mount_dir: str, shared_storage_type: Type):
        super().__init__()
        self.mount_dir = Resource.init_param(mount_dir)
        self.shared_storage_type = shared_storage_type


class SharedEbs(SharedStorage, Ebs):
    """Represent a shared EBS, inherits from both _SharedStorage and Ebs classes."""

    def __init__(
        self,
        mount_dir: str,
        volume_type: str = None,
        iops: int = None,
        size: int = None,
        encrypted: bool = None,
        kms_key_id: str = None,
        throughput: int = None,
        snapshot_id: str = None,
        volume_id: str = None,
        raid: Raid = None,
    ):
        SharedStorage.__init__(self, mount_dir=mount_dir, shared_storage_type=SharedStorage.Type.EBS)
        Ebs.__init__(self, volume_type, iops, size, encrypted, kms_key_id, throughput)
        self.snapshot_id = Resource.init_param(snapshot_id)
        self.volume_id = Resource.init_param(volume_id)
        self.raid = raid

    def _register_validators(self):
        self._add_validator(SharedEBSVolumeIdValidator, volume_id=self.volume_id)


class SharedEfs(SharedStorage):
    """Represent the shared EFS resource."""

    def __init__(
        self,
        mount_dir: str,
        encrypted: bool = None,
        kms_key_id: str = None,
        performance_mode: str = None,
        throughput_mode: str = None,
        provisioned_throughput: int = None,
        file_system_id: str = None,
    ):
        super().__init__(mount_dir=mount_dir, shared_storage_type=SharedStorage.Type.EFS)
        self.encrypted = Resource.init_param(encrypted, default=False)
        self.kms_key_id = Resource.init_param(kms_key_id)
        self.performance_mode = Resource.init_param(performance_mode, default="generalPurpose")
        self.throughput_mode = Resource.init_param(throughput_mode, default="bursting")
        self.provisioned_throughput = Resource.init_param(provisioned_throughput)
        self.file_system_id = Resource.init_param(file_system_id)


class SharedFsx(SharedStorage):
    """Represent the shared FSX resource."""

    def __init__(
        self,
        mount_dir: str,
        storage_capacity: str = None,
        deployment_type: str = None,
        export_path: str = None,
        import_path: str = None,
        imported_file_chunk_size: str = None,
        weekly_maintenance_start_time: str = None,
        automatic_backup_retention_days: str = None,
        copy_tags_to_backups: bool = None,
        daily_automatic_backup_start_time: str = None,
        per_unit_storage_throughput: int = None,
        backup_id: str = None,
        kms_key_id: str = None,
        file_system_id: str = None,
        auto_import_policy: str = None,
        drive_cache_type: str = None,
        storage_type: str = None,
    ):
        super().__init__(mount_dir=mount_dir, shared_storage_type=SharedStorage.Type.FSX)
        self.storage_capacity = Resource.init_param(storage_capacity)
        self.storage_type = Resource.init_param(storage_type)
        self.deployment_type = Resource.init_param(deployment_type)
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
        self.storage_type = Resource.init_param(storage_type)

    def _register_validators(self):
        self._add_validator(
            FsxS3Validator,
            import_path=self.import_path,
            imported_file_chunk_size=self.imported_file_chunk_size,
            export_path=self.export_path,
            auto_import_policy=self.auto_import_policy,
        )
        self._add_validator(
            FsxPersistentOptionsValidator,
            deployment_type=self.deployment_type,
            kms_key_id=self.kms_key_id,
            per_unit_storage_throughput=self.per_unit_storage_throughput,
        )
        self._add_validator(
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
        self._add_validator(
            FsxStorageTypeOptionsValidator,
            storage_type=self.storage_type,
            deployment_type=self.deployment_type,
            per_unit_storage_throughput=self.per_unit_storage_throughput,
            drive_cache_type=self.drive_cache_type,
        )
        self._add_validator(
            FsxStorageCapacityValidator,
            storage_capacity=self.storage_capacity,
            deployment_type=self.deployment_type,
            storage_type=self.storage_type,
            per_unit_storage_throughput=self.per_unit_storage_throughput,
            file_system_id=self.file_system_id,
            backup_id=self.backup_id,
        )
        self._add_validator(FsxBackupIdValidator, backup_id=self.backup_id)

        if self.import_path:
            self._add_validator(S3BucketUriValidator, url=self.import_path)
        if self.export_path:
            self._add_validator(S3BucketUriValidator, url=self.export_path)


# ---------------------- Networking ---------------------- #


class Proxy(Resource):
    """Represent the proxy."""

    def __init__(self, http_proxy_address: str = None):
        super().__init__()
        self.http_proxy_address = http_proxy_address


class _BaseNetworking(Resource):
    """Represent the networking configuration shared by head node and compute node."""

    def __init__(
        self,
        assign_public_ip: str = None,
        security_groups: List[str] = None,
        additional_security_groups: List[str] = None,
        proxy: Proxy = None,
    ):
        super().__init__()
        self.assign_public_ip = Resource.init_param(assign_public_ip)
        self.security_groups = Resource.init_param(security_groups)
        self.additional_security_groups = Resource.init_param(additional_security_groups)
        self.proxy = proxy

    def _register_validators(self):
        self._add_validator(SecurityGroupsValidator, security_group_ids=self.security_groups)
        self._add_validator(SecurityGroupsValidator, security_group_ids=self.additional_security_groups)


class HeadNodeNetworking(_BaseNetworking):
    """Represent the networking configuration for the head node."""

    def __init__(self, subnet_id: str, elastic_ip: str = None, **kwargs):
        super().__init__(**kwargs)
        self.subnet_id = Resource.init_param(subnet_id)
        self.elastic_ip = Resource.init_param(elastic_ip)

    @property
    def availability_zone(self):
        """Compute availability zone from subnet id."""
        return get_availability_zone_of_subnet(self.subnet_id)


class PlacementGroup(Resource):
    """Represent the placement group for the Queue networking."""

    def __init__(self, enabled: bool = None, id: str = None):
        super().__init__()
        self.enabled = Resource.init_param(enabled, default=False)
        self.id = Resource.init_param(id)

    def _register_validators(self):
        self._add_validator(PlacementGroupIdValidator, placement_group_id=self.id)


class QueueNetworking(_BaseNetworking):
    """Represent the networking configuration for the Queue."""

    def __init__(self, subnet_ids: List[str], placement_group: PlacementGroup = None, **kwargs):
        super().__init__(**kwargs)
        self.subnet_ids = Resource.init_param(subnet_ids)
        self.placement_group = placement_group


class Ssh(Resource):
    """Represent the SSH configuration for a node (or the entire cluster)."""

    def __init__(self, key_name: str, allowed_ips: str = None):
        super().__init__()
        self.key_name = Resource.init_param(key_name)
        self.allowed_ips = Resource.init_param(allowed_ips, default=CIDR_ALL_IPS)

    def _register_validators(self):
        self._add_validator(KeyPairValidator, key_name=self.key_name)


class Dcv(Resource):
    """Represent the DCV configuration."""

    def __init__(self, enabled: bool, port: int = None, allowed_ips: str = None):
        super().__init__()
        self.enabled = Resource.init_param(enabled)
        self.port = Resource.init_param(port, default=8843)
        self.allowed_ips = Resource.init_param(allowed_ips, default=CIDR_ALL_IPS)


class Efa(Resource):
    """Represent the EFA configuration."""

    def __init__(self, enabled: bool = None, gdr_support: bool = None):
        super().__init__()
        self.enabled = Resource.init_param(enabled, default=True)
        self.gdr_support = Resource.init_param(gdr_support, default=False)


# ---------------------- Monitoring ---------------------- #


class CloudWatchLogs(Resource):
    """Represent the CloudWatch configuration in Logs."""

    def __init__(
        self,
        enabled: bool = None,
        retention_in_days: int = None,
        log_group_id: str = None,
        kms_key_id: str = None,
    ):
        super().__init__()
        self.enabled = Resource.init_param(enabled, default=True)
        self.retention_in_days = Resource.init_param(retention_in_days, default=14)
        self.log_group_id = Resource.init_param(log_group_id)
        self.kms_key_id = Resource.init_param(kms_key_id)


class CloudWatchDashboards(Resource):
    """Represent the CloudWatch Dashboard."""

    def __init__(
        self,
        enabled: bool = None,
    ):
        super().__init__()
        self.enabled = Resource.init_param(enabled, default=True)


class Logs(Resource):
    """Represent the CloudWatch Logs configuration."""

    def __init__(
        self,
        cloud_watch: CloudWatchLogs = None,
    ):
        super().__init__()
        self.cloud_watch = cloud_watch


class Dashboards(Resource):
    """Represent the Dashboards configuration."""

    def __init__(
        self,
        cloud_watch: CloudWatchDashboards = None,
    ):
        super().__init__()
        self.cloud_watch = cloud_watch


class Monitoring(Resource):
    """Represent the Monitoring configuration."""

    def __init__(
        self,
        detailed_monitoring: bool = None,
        logs: Logs = None,
        dashboards: Dashboards = None,
    ):
        super().__init__()
        self.detailed_monitoring = Resource.init_param(detailed_monitoring, default=False)
        self.logs = logs
        self.dashboards = dashboards


# ---------------------- Others ---------------------- #


class Tag(BaseTag):
    """Represent the Tag configuration."""

    def __init__(
        self,
        key: str = None,
        value: str = None,
    ):
        super().__init__(key, value)

    def _register_validators(self):
        self._add_validator(TagKeyValidator, key=self.key)


class Roles(Resource):
    """Represent the Roles configuration."""

    def __init__(
        self,
        instance_role: str = None,
        custom_lambda_resources: str = None,
    ):
        super().__init__()
        self.instance_role = Resource.init_param(instance_role, default="AUTO")
        self.custom_lambda_resources = Resource.init_param(custom_lambda_resources, default="AUTO")


class S3Access(Resource):
    """Represent the S3 Access configuration."""

    def __init__(
        self,
        bucket_name: str,
        type: str = None,
    ):
        super().__init__()
        self.bucket_name = Resource.init_param(bucket_name)
        self.type = Resource.init_param(type, default="READ_ONLY")


class AdditionalIamPolicy(Resource):
    """Represent the Additional IAM Policy configuration."""

    def __init__(
        self,
        policy: str,
    ):
        super().__init__()
        self.policy = Resource.init_param(policy)

    def _register_validators(self):
        self._add_validator(AdditionalIamPolicyValidator, policy=self.policy)


class Iam(Resource):
    """Represent the IAM configuration."""

    def __init__(
        self,
        roles: Roles = None,
        s3_access: List[S3Access] = None,
        additional_iam_policies: List[AdditionalIamPolicy] = None,
    ):
        super().__init__()
        self.roles = roles
        self.s3_access = s3_access
        self.additional_iam_policies = additional_iam_policies


class IntelSelectSolutions(Resource):
    """Represent the Intel select solution configuration."""

    def __init__(
        self,
        install_intel_software: bool = None,
    ):
        super().__init__()
        self.install_intel_software = Resource.init_param(install_intel_software, default=False)


class AdditionalPackages(Resource):
    """Represent the additional packages configuration."""

    def __init__(
        self,
        intel_select_solutions: IntelSelectSolutions = None,
    ):
        super().__init__()
        self.intel_select_solutions = intel_select_solutions


class ClusterDevSettings(BaseDevSettings):
    """Represent the dev settings configuration."""

    def __init__(self, cluster_template: str = None, **kwargs):
        super().__init__(**kwargs)
        self.cluster_template = Resource.init_param(cluster_template)

    def _register_validators(self):
        super()._register_validators()
        self._add_validator(UrlValidator, url=self.cluster_template)


# ---------------------- Nodes and Cluster ---------------------- #


class Image(Resource):
    """Represent the configuration of an Image."""

    def __init__(self, os: str, custom_ami: str = None):
        super().__init__()
        self.os = Resource.init_param(os)
        self.custom_ami = Resource.init_param(custom_ami)


class CustomAction(Resource):
    """Represent a custom action resource."""

    def __init__(self, script: str, args: List[str] = None, event: str = None, run_as: str = None):
        super().__init__()
        self.script = Resource.init_param(script)
        self.args = Resource.init_param(args)
        self.event = Resource.init_param(event)
        self.run_as = Resource.init_param(run_as)

    def _register_validators(self):
        self._add_validator(UrlValidator, url=self.script)


class HeadNode(Resource):
    """Represent the Head Node resource."""

    def __init__(
        self,
        instance_type: str,
        networking: HeadNodeNetworking,
        ssh: Ssh,
        image: Image = None,
        simultaneous_multithreading: bool = None,
        storage: Storage = None,
        dcv: Dcv = None,
        efa: Efa = None,
        custom_actions: List[CustomAction] = None,
        iam: Iam = None,
    ):
        super().__init__()
        self.instance_type = Resource.init_param(instance_type)
        self.simultaneous_multithreading = Resource.init_param(simultaneous_multithreading, default=True)
        self.networking = networking
        self.ssh = ssh
        self.image = image
        self.storage = storage
        self.dcv = dcv
        self.efa = efa
        self.custom_actions = custom_actions
        self.iam = iam

    def _register_validators(self):
        self._add_validator(InstanceTypeValidator, instance_type=self.instance_type)

    @property
    def architecture(self):
        """Compute cluster's architecture based on its head node instance type."""
        supported_architectures = get_supported_architectures_for_instance_type(self.instance_type)
        if not supported_architectures:
            error(f"Unable to get architectures supported by instance type {self.instance_type}")
        # If the instance type supports multiple architectures, choose the first one.
        # TODO: this is currently not an issue because none of the instance types we support more than one of the
        #       architectures we support. If this were ever to change (e.g., we start supporting i386) then we would
        #       probably need to choose based on the subset of the architectures supported by both the head node and
        #       compute instance types.
        return supported_architectures[0]


class BaseComputeResource(Resource):
    """Represent the base Compute Resource, with the fields in common between all the schedulers."""

    def __init__(
        self,
        name: str,
        allocation_strategy: str = None,
        simultaneous_multithreading: bool = None,
    ):
        super().__init__()
        self.name = Resource.init_param(name)
        self.allocation_strategy = Resource.init_param(allocation_strategy, default="BEST_FIT")
        self.simultaneous_multithreading = Resource.init_param(simultaneous_multithreading, default=True)

    def _register_validators(self):
        self._add_validator(NameValidator, name=self.name)


class BaseQueue(Resource):
    """Represent the generic Queue resource."""

    def __init__(
        self,
        name: str,
        networking: QueueNetworking,
        storage: Storage = None,
        compute_type: str = None,
        image: Image = None,
        iam: Iam = None,
    ):
        super().__init__()
        self.name = Resource.init_param(name)
        self.networking = networking
        self.storage = storage
        self.compute_type = Resource.init_param(compute_type, default="ONDEMAND")
        self.image = image
        self.iam = iam

    def _register_validators(self):
        self._add_validator(NameValidator, name=self.name)


class CommonSchedulingSettings(Resource):
    """Represent the common scheduler settings."""

    def __init__(self, scaledown_idletime: int):
        super().__init__()
        self.scaledown_idletime = Resource.init_param(scaledown_idletime)


class BaseCluster(Resource):
    """Represent the common Cluster resource."""

    def __init__(
        self,
        image: Image,
        head_node: HeadNode,
        shared_storage: List[SharedStorage] = None,
        monitoring: Monitoring = None,
        additional_packages: AdditionalPackages = None,
        tags: List[Tag] = None,
        iam: Iam = None,
        cluster_s3_bucket: str = None,
        additional_resources: str = None,
        dev_settings: ClusterDevSettings = None,
    ):
        super().__init__()
        self.image = image
        self.head_node = head_node
        self.shared_storage = shared_storage
        self.monitoring = monitoring
        self.additional_packages = additional_packages
        self.tags = tags
        self.iam = iam
        self.cluster_s3_bucket = Resource.init_param(cluster_s3_bucket)
        self.additional_resources = Resource.init_param(additional_resources)
        self.dev_settings = dev_settings

    def _register_validators(self):
        self._add_validator(
            ArchitectureOsValidator,
            priority=10,
            os=self.image.os,
            architecture=self.head_node.architecture,
        )
        if self.head_node.efa:
            self._add_validator(
                EfaOsArchitectureValidator,
                priority=9,
                efa_enabled=self.head_node.efa.enabled,
                os=self.image.os,
                architecture=self.head_node.architecture,
            )
        self._add_validator(
            SimultaneousMultithreadingArchitectureValidator,
            priority=8,
            simultaneous_multithreading=self.head_node.simultaneous_multithreading,
            architecture=self.head_node.architecture,
        )
        self._register_storage_validators()

        if self.head_node.dcv:
            self._add_validator(
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
            and self.additional_packages.intel_select_solutions
            and self.additional_packages.intel_select_solutions.install_intel_software
        ):
            self._add_validator(IntelHpcOsValidator, os=self.image.os)
            self._add_validator(
                IntelHpcArchitectureValidator,
                architecture=self.head_node.architecture,
            )
        if self.cluster_s3_bucket:
            self._add_validator(S3BucketValidator, bucket=self.cluster_s3_bucket)

    def _register_storage_validators(self):
        storage_count = {"ebs": 0, "efs": 0, "fsx": 0}
        if self.shared_storage:
            for storage in self.shared_storage:
                if isinstance(storage, SharedFsx):
                    storage_count["fsx"] += 1
                    self._add_validator(
                        FsxNetworkingValidator,
                        fs_system_id=storage.file_system_id,
                        head_node_subnet_id=self.head_node.networking.subnet_id,
                    )
                    self._add_validator(
                        FsxArchitectureOsValidator,
                        architecture=self.head_node.architecture,
                        os=self.image.os,
                    )
                if isinstance(storage, SharedEbs):
                    storage_count["ebs"] += 1
                if isinstance(storage, SharedEfs):
                    storage_count["efs"] += 1
                    self._add_validator(
                        EfsIdValidator,
                        efs_id=storage.file_system_id,
                        head_node_avail_zone=self.head_node.networking.availability_zone,
                    )

            for storage_type in ["ebs", "efs", "fsx"]:
                self._add_validator(
                    NumberOfStorageValidator,
                    storage_type=storage_type.upper(),
                    max_number=MAX_STORAGE_COUNT.get(storage_type),
                    storage_count=storage_count[storage_type],
                )

        self._add_validator(DuplicateMountDirValidator, mount_dir_list=self.mount_dir_list)

    @property
    def region(self):
        """Retrieve region from environment."""
        return get_region()

    @property
    def mount_dir_list(self):
        """Retrieve the list of mount dirs for the shared storage and head node ephemeral volume."""
        mount_dir_list = []
        if self.shared_storage:
            for storage in self.shared_storage:
                mount_dir_list.append(storage.mount_dir)

        if self.head_node.storage and self.head_node.storage.ephemeral_volume:
            mount_dir_list.append(self.head_node.storage.ephemeral_volume.mount_dir)

        return mount_dir_list
