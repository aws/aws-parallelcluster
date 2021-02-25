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
from typing import List

import pkg_resources

from common.aws.aws_api import AWSApi
from pcluster.constants import CIDR_ALL_IPS, EBS_VOLUME_TYPE_IOPS_DEFAULT
from pcluster.models.common import BaseDevSettings, BaseTag, Resource
from pcluster.utils import (
    delete_s3_artifacts,
    delete_s3_bucket,
    get_availability_zone_of_subnet,
    get_partition,
    get_region,
)
from pcluster.validators.awsbatch_validators import (
    AwsbatchComputeInstanceTypeValidator,
    AwsbatchInstancesArchitectureCompatibilityValidator,
    AwsbatchRegionValidator,
)
from pcluster.validators.cluster_validators import (
    ArchitectureOsValidator,
    DcvValidator,
    DisableSimultaneousMultithreadingArchitectureValidator,
    DuplicateInstanceTypeValidator,
    DuplicateMountDirValidator,
    EfaOsArchitectureValidator,
    EfaPlacementGroupValidator,
    EfaSecurityGroupValidator,
    EfaValidator,
    EfsIdValidator,
    FsxArchitectureOsValidator,
    FsxNetworkingValidator,
    InstanceArchitectureCompatibilityValidator,
    IntelHpcArchitectureValidator,
    IntelHpcOsValidator,
    NameValidator,
    NumberOfStorageValidator,
    SchedulerOsValidator,
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
    InstanceTypeBaseAMICompatibleValidator,
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
from pcluster.validators.kms_validators import KmsKeyValidator
from pcluster.validators.networking_validators import SecurityGroupsValidator, SubnetsValidator
from pcluster.validators.s3_validators import S3BucketUriValidator, S3BucketValidator, UrlValidator

LOGGER = logging.getLogger(__name__)

# pylint: disable=C0302

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

    def _validate(self):
        # FIXME This method is not executed because subclass override the method.
        self._execute_validator(EbsVolumeTypeSizeValidator, volume_type=self.volume_type, volume_size=self.size)
        self._execute_validator(
            EbsVolumeIopsValidator,
            volume_type=self.volume_type,
            volume_size=self.size,
            volume_iops=self.iops,
        )
        self._execute_validator(
            EbsVolumeThroughputValidator,
            volume_type=self.volume_type,
            volume_throughput=self.throughput,
        )
        self._execute_validator(
            EbsVolumeThroughputIopsValidator,
            volume_type=self.volume_type,
            volume_iops=self.iops,
            volume_throughput=self.throughput,
        )
        if self.kms_key_id:
            self._execute_validator(KmsKeyValidator, kms_key_id=self.kms_key_id)


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


class SharedStorageType(Enum):
    """Define storage types to be used as shared storage."""

    EBS = "ebs"
    EFS = "efs"
    FSX = "fsx"


class SharedEbs(Ebs):
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
        Ebs.__init__(self, volume_type, iops, size, encrypted, kms_key_id, throughput)
        self.mount_dir = mount_dir
        self.shared_storage_type = SharedStorageType.EBS
        self.snapshot_id = Resource.init_param(snapshot_id)
        self.volume_id = Resource.init_param(volume_id)
        self.raid = raid

    def _validate(self):
        self._execute_validator(SharedEBSVolumeIdValidator, volume_id=self.volume_id)


class SharedEfs(Resource):
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
        super().__init__()
        self.mount_dir = mount_dir
        self.shared_storage_type = SharedStorageType.EFS
        self.encrypted = Resource.init_param(encrypted, default=False)
        self.kms_key_id = Resource.init_param(kms_key_id)
        self.performance_mode = Resource.init_param(performance_mode, default="generalPurpose")
        self.throughput_mode = Resource.init_param(throughput_mode, default="bursting")
        self.provisioned_throughput = Resource.init_param(provisioned_throughput)
        self.file_system_id = Resource.init_param(file_system_id)

    def _validate(self):
        if self.kms_key_id:
            self._execute_validator(KmsKeyValidator, kms_key_id=self.kms_key_id)


class SharedFsx(Resource):
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
        super().__init__()
        self.mount_dir = mount_dir
        self.shared_storage_type = SharedStorageType.FSX
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

    def _validate(self):
        self._execute_validator(
            FsxS3Validator,
            import_path=self.import_path,
            imported_file_chunk_size=self.imported_file_chunk_size,
            export_path=self.export_path,
            auto_import_policy=self.auto_import_policy,
        )
        self._execute_validator(
            FsxPersistentOptionsValidator,
            deployment_type=self.deployment_type,
            kms_key_id=self.kms_key_id,
            per_unit_storage_throughput=self.per_unit_storage_throughput,
        )
        self._execute_validator(
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
        self._execute_validator(
            FsxStorageTypeOptionsValidator,
            storage_type=self.storage_type,
            deployment_type=self.deployment_type,
            per_unit_storage_throughput=self.per_unit_storage_throughput,
            drive_cache_type=self.drive_cache_type,
        )
        self._execute_validator(
            FsxStorageCapacityValidator,
            storage_capacity=self.storage_capacity,
            deployment_type=self.deployment_type,
            storage_type=self.storage_type,
            per_unit_storage_throughput=self.per_unit_storage_throughput,
            file_system_id=self.file_system_id,
            backup_id=self.backup_id,
        )
        self._execute_validator(FsxBackupIdValidator, backup_id=self.backup_id)

        if self.import_path:
            self._execute_validator(S3BucketUriValidator, url=self.import_path)
        if self.export_path:
            self._execute_validator(S3BucketUriValidator, url=self.export_path)
        if self.kms_key_id:
            self._execute_validator(KmsKeyValidator, kms_key_id=self.kms_key_id)


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

    def _validate(self):
        self._execute_validator(SecurityGroupsValidator, security_group_ids=self.security_groups)
        self._execute_validator(SecurityGroupsValidator, security_group_ids=self.additional_security_groups)


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

    def _validate(self):
        self._execute_validator(PlacementGroupIdValidator, placement_group_id=self.id)


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

    def _validate(self):
        self._execute_validator(KeyPairValidator, key_name=self.key_name)


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

    def _validate(self):
        if self.kms_key_id:
            self._execute_validator(KmsKeyValidator, kms_key_id=self.kms_key_id)


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

    def _validate(self):
        self._execute_validator(TagKeyValidator, key=self.key)


class Roles(Resource):
    """Represent the Roles configuration."""

    def __init__(
        self,
        instance_role: str = None,
        custom_lambda_resources: str = None,
    ):
        super().__init__()
        self.instance_role = Resource.init_param(instance_role)
        self.custom_lambda_resources = Resource.init_param(custom_lambda_resources)


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

    def _validate(self):
        self._execute_validator(AdditionalIamPolicyValidator, policy=self.policy)


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

    def _validate(self):
        super()._validate()
        self._execute_validator(UrlValidator, url=self.cluster_template)


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

    def _validate(self):
        self._execute_validator(UrlValidator, url=self.script)


class HeadNode(Resource):
    """Represent the Head Node resource."""

    def __init__(
        self,
        instance_type: str,
        networking: HeadNodeNetworking,
        ssh: Ssh,
        image: Image = None,
        disable_simultaneous_multithreading: bool = None,
        storage: Storage = None,
        dcv: Dcv = None,
        efa: Efa = None,
        custom_actions: List[CustomAction] = None,
        iam: Iam = None,
    ):
        super().__init__()
        self.instance_type = Resource.init_param(instance_type)
        self.disable_simultaneous_multithreading = Resource.init_param(
            disable_simultaneous_multithreading, default=True
        )
        self.networking = networking
        self.ssh = ssh
        self.image = image
        self.storage = storage
        self.dcv = dcv
        self.efa = efa
        self.custom_actions = custom_actions
        self.iam = iam

    def _validate(self):
        self._execute_validator(InstanceTypeValidator, instance_type=self.instance_type)
        self._execute_validator(
            DisableSimultaneousMultithreadingArchitectureValidator,
            disable_simultaneous_multithreading=self.disable_simultaneous_multithreading,
            architecture=self.architecture,
        )

    @property
    def architecture(self):
        """Compute cluster's architecture based on its head node instance type."""
        instance_type_info = AWSApi.instance().ec2.get_instance_type_info(self.instance_type)
        return instance_type_info.supported_architecture()[0]

    @property
    def vcpus(self):
        """Get the number of vcpus for the instance according to disable_hyperthreading and instance features."""
        instance_type_info = AWSApi.instance().ec2.get_instance_type_info(self.instance_type)
        default_threads_per_core = instance_type_info.default_threads_per_core()
        return (
            instance_type_info.vcpus_count()
            if not self.disable_simultaneous_multithreading
            else (instance_type_info.vcpus_count() // default_threads_per_core)
        )

    @property
    def pass_cpu_options_in_launch_template(self):
        """Check whether CPU Options must be passed in launch template for head node."""
        instance_type_info = AWSApi.instance().ec2.get_instance_type_info(self.instance_type)
        return self.disable_simultaneous_multithreading and instance_type_info.is_cpu_options_supported_in_lt()

    @property
    def instance_type_info(self):
        """Return head node instance type information as returned from aws ec2 describe-instamce-types."""
        return AWSApi.instance().ec2.get_instance_type_info(self.instance_type)


class BaseComputeResource(Resource):
    """Represent the base Compute Resource, with the fields in common between all the schedulers."""

    def __init__(
        self,
        name: str,
        instance_type: str,
        allocation_strategy: str = None,
        disable_simultaneous_multithreading: bool = None,
    ):
        super().__init__()
        self.name = Resource.init_param(name)
        self.instance_type = Resource.init_param(instance_type)
        self.allocation_strategy = Resource.init_param(allocation_strategy, default="BEST_FIT")
        self.disable_simultaneous_multithreading = Resource.init_param(
            disable_simultaneous_multithreading, default=True
        )

    def _validate(self):
        self._execute_validator(NameValidator, name=self.name)
        self._execute_validator(
            DisableSimultaneousMultithreadingArchitectureValidator,
            disable_simultaneous_multithreading=self.disable_simultaneous_multithreading,
            architecture=self.architecture,
        )

    @property
    def architecture(self):
        """Compute cluster's architecture based on its head node instance type."""
        instance_type_info = AWSApi.instance().ec2.get_instance_type_info(self.instance_type)
        return instance_type_info.supported_architecture()[0]


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

    def _validate(self):
        self._execute_validator(NameValidator, name=self.name)


class CommonSchedulingSettings(Resource):
    """Represent the common scheduler settings."""

    def __init__(self, scaledown_idletime: int):
        super().__init__()
        self.scaledown_idletime = Resource.init_param(scaledown_idletime)


class BaseClusterConfig(Resource):
    """Represent the common Cluster config."""

    def __init__(
        self,
        image: Image,
        head_node: HeadNode,
        shared_storage: List[Resource] = None,
        monitoring: Monitoring = None,
        additional_packages: AdditionalPackages = None,
        tags: List[Tag] = None,
        iam: Iam = None,
        cluster_s3_bucket: str = None,
        additional_resources: str = None,
        dev_settings: ClusterDevSettings = None,
    ):
        super().__init__()
        self.__region = None
        self.name = None
        self.image = image
        self.head_node = head_node
        self.shared_storage = shared_storage
        self.monitoring = monitoring
        self.additional_packages = additional_packages
        self.tags = tags
        self.iam = iam
        self.cluster_s3_bucket = Resource.init_param(cluster_s3_bucket)
        self._bucket = None
        self.additional_resources = Resource.init_param(additional_resources)
        self.dev_settings = dev_settings
        self.cluster_template_body = None
        self.source_config = None
        self.config_version = None

    def _validate(self):
        self._execute_validator(
            ArchitectureOsValidator,
            os=self.image.os,
            architecture=self.head_node.architecture,
        )
        self._execute_validator(
            InstanceTypeBaseAMICompatibleValidator,
            instance_type=self.head_node.instance_type,
            image=self.ami_id,
        )
        self._execute_validator(
            SubnetsValidator, subnet_ids=self.compute_subnet_ids + [self.head_node.networking.subnet_id]
        )
        for queue in self.scheduling.queues:
            for compute_resource in queue.compute_resources:
                self._execute_validator(
                    InstanceTypeBaseAMICompatibleValidator,
                    instance_type=compute_resource.instance_type,
                    image=self.ami_id,
                )
                if compute_resource.efa:
                    self._execute_validator(
                        EfaOsArchitectureValidator,
                        efa_enabled=compute_resource.efa.enabled,
                        os=self.image.os,
                        # FIXME: head_node.architecture vs compute_resource.architecture?
                        architecture=self.head_node.architecture,
                    )
        if self.head_node.efa:
            self._execute_validator(
                EfaOsArchitectureValidator,
                efa_enabled=self.head_node.efa.enabled,
                os=self.image.os,
                architecture=self.head_node.architecture,
            )
        self._register_storage_validators()

        if self.head_node.dcv:
            self._execute_validator(
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
            self._execute_validator(IntelHpcOsValidator, os=self.image.os)
            self._execute_validator(
                IntelHpcArchitectureValidator,
                architecture=self.head_node.architecture,
            )
        if self.cluster_s3_bucket:
            self._execute_validator(S3BucketValidator, bucket=self.cluster_s3_bucket)

    def _register_storage_validators(self):
        storage_count = {"ebs": 0, "efs": 0, "fsx": 0}
        if self.shared_storage:
            for storage in self.shared_storage:
                if isinstance(storage, SharedFsx):
                    storage_count["fsx"] += 1
                    self._execute_validator(
                        FsxNetworkingValidator,
                        fs_system_id=storage.file_system_id,
                        head_node_subnet_id=self.head_node.networking.subnet_id,
                    )
                    self._execute_validator(
                        FsxArchitectureOsValidator,
                        architecture=self.head_node.architecture,
                        os=self.image.os,
                    )
                if isinstance(storage, SharedEbs):
                    storage_count["ebs"] += 1
                if isinstance(storage, SharedEfs):
                    storage_count["efs"] += 1
                    self._execute_validator(
                        EfsIdValidator,
                        efs_id=storage.file_system_id,
                        head_node_avail_zone=self.head_node.networking.availability_zone,
                    )

            for storage_type in ["ebs", "efs", "fsx"]:
                self._execute_validator(
                    NumberOfStorageValidator,
                    storage_type=storage_type.upper(),
                    max_number=MAX_STORAGE_COUNT.get(storage_type),
                    storage_count=storage_count[storage_type],
                )

        self._execute_validator(DuplicateMountDirValidator, mount_dir_list=self.mount_dir_list)

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

        if self.head_node.storage and self.head_node.storage.ephemeral_volume:
            mount_dir_list.append(self.head_node.storage.ephemeral_volume.mount_dir)

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
    def head_iam_role(self):
        """Return the IAM role for head node, if set."""
        role = None
        if self.iam and self.iam.roles:
            role = self.iam.roles.head_node
        return role

    @property
    def compute_iam_role(self):
        """Return the IAM role for compute nodes, if set."""
        role = None
        if self.iam and self.iam.roles:
            role = self.iam.roles.compute_node
        return role

    @property
    def vpc_id(self):
        """Return the VPC of the cluster."""
        return AWSApi.instance().ec2.get_subnet_vpc(self.head_node.networking.subnet_id)

    @property
    def ami_id(self):
        """Get the image id of the cluster."""
        return (
            self.image.custom_ami
            if self.image.custom_ami
            else AWSApi.instance().ec2.get_official_image_id(self.image.os, self.head_node.architecture)
        )

    @property
    def scheduler_resources(self):
        """Return scheduler resources. To be overridden with scheduler specific logic, if any."""
        return None


class AwsbatchComputeResource(BaseComputeResource):
    """Represent the Awsbatch Compute Resource."""

    def __init__(
        self,
        max_vcpus: int = None,
        min_vcpus: int = None,
        desired_vcpus: int = None,
        spot_bid_percentage: float = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.max_vcpus = Resource.init_param(max_vcpus, default=10)
        self.min_vcpus = Resource.init_param(min_vcpus, default=0)
        self.desired_vcpus = Resource.init_param(desired_vcpus, default=0)
        self.spot_bid_percentage = Resource.init_param(spot_bid_percentage)

    def _validate(self):
        super()._validate()
        self._execute_validator(
            AwsbatchComputeInstanceTypeValidator, instance_types=self.instance_type, max_vcpus=self.max_vcpus
        )


class AwsbatchQueue(BaseQueue):
    """Represent the Awsbatch Queue resource."""

    def __init__(
        self,
        name: str,
        networking: QueueNetworking,
        compute_resources: List[AwsbatchComputeResource],
        storage: Storage = None,
        compute_type: str = None,
    ):
        super().__init__(name, networking, storage, compute_type)
        self.compute_resources = compute_resources


class AwsbatchScheduling(Resource):
    """Represent a Awsbatch Scheduling resource."""

    def __init__(self, queues: List[AwsbatchQueue], settings: CommonSchedulingSettings = None):
        super().__init__()
        self.scheduler = "awsbatch"
        self.queues = queues
        self.settings = settings


class AwsbatchClusterConfig(BaseClusterConfig):
    """Represent the full Awsbatch Cluster configuration."""

    def __init__(self, scheduling: AwsbatchScheduling, **kwargs):
        super().__init__(**kwargs)
        self.scheduling = scheduling

    def _validate(self):
        super()._validate()
        self._execute_validator(AwsbatchRegionValidator, region=self.region)
        self._execute_validator(SchedulerOsValidator, scheduler=self.scheduling.scheduler, os=self.image.os)

        for queue in self.scheduling.queues:
            for compute_resource in queue.compute_resources:
                self._execute_validator(
                    AwsbatchInstancesArchitectureCompatibilityValidator,
                    instance_types=compute_resource.instance_type,
                    architecture=self.head_node.architecture,
                )

    @property
    def scheduler_resources(self):
        """Return scheduler specific resources."""
        return pkg_resources.resource_filename(__name__, "resources/batch")


class SlurmComputeResource(BaseComputeResource):
    """Represent the Slurm Compute Resource."""

    def __init__(
        self, max_count: int = None, min_count: int = None, spot_price: float = None, efa: Efa = None, **kwargs
    ):
        super().__init__(**kwargs)
        self.max_count = Resource.init_param(max_count, default=10)
        self.min_count = Resource.init_param(min_count, default=0)
        self.spot_price = Resource.init_param(spot_price)
        self.efa = efa

    def _validate(self):
        super()._validate()
        self._execute_validator(InstanceTypeValidator, instance_type=self.instance_type)
        if self.efa:
            self._execute_validator(
                EfaValidator,
                instance_type=self.instance_type,
                efa_enabled=self.efa.enabled,
                gdr_support=self.efa.gdr_support,
            )


class SlurmQueue(BaseQueue):
    """Represent the Slurm Queue resource."""

    def __init__(
        self, compute_resources: List[SlurmComputeResource], custom_actions: List[CustomAction] = None, **kwargs
    ):
        super().__init__(**kwargs)
        self.compute_resources = compute_resources
        self.custom_actions = custom_actions

    def _validate(self):
        self._execute_validator(
            DuplicateInstanceTypeValidator,
            instance_type_list=self.instance_type_list,
        )
        for compute_resource in self.compute_resources:
            if compute_resource.efa:
                self._execute_validator(
                    EfaSecurityGroupValidator,
                    efa_enabled=compute_resource.efa,
                    security_groups=self.networking.security_groups,
                    additional_security_groups=self.networking.additional_security_groups,
                )
                if self.networking.placement_group:
                    self._execute_validator(
                        EfaPlacementGroupValidator,
                        efa_enabled=compute_resource.efa,
                        placement_group_id=self.networking.placement_group.id,
                        placement_group_enabled=self.networking.placement_group.enabled,
                    )

    @property
    def instance_type_list(self):
        """Return the list of instance types associated to the Queue."""
        return [compute_resource.instance_type for compute_resource in self.compute_resources]


class Dns(Resource):
    """Represent the DNS settings."""

    def __init__(self, disable_managed_dns: bool = None, domain: str = None, hosted_zone_id: str = None):
        super().__init__()
        self.disable_managed_dns = Resource.init_param(disable_managed_dns, default=False)
        self.domain = Resource.init_param(domain)
        self.hosted_zone_id = Resource.init_param(hosted_zone_id)


class SlurmSettings(CommonSchedulingSettings):
    """Represent the Slurm settings."""

    def __init__(self, scaledown_idletime: int, dns: Dns = None):
        super().__init__(scaledown_idletime)
        self.dns = dns


class SlurmScheduling(Resource):
    """Represent a slurm Scheduling resource."""

    def __init__(self, queues: List[SlurmQueue], settings: SlurmSettings = None):
        super().__init__()
        self.scheduler = "slurm"
        self.queues = queues
        self.settings = settings


class SlurmClusterConfig(BaseClusterConfig):
    """Represent the full Slurm Cluster configuration."""

    def __init__(self, scheduling: SlurmScheduling, **kwargs):
        super().__init__(**kwargs)
        self.scheduling = scheduling

    def _validate(self):
        super()._validate()
        self._execute_validator(SchedulerOsValidator, scheduler=self.scheduling.scheduler, os=self.image.os)

        for queue in self.scheduling.queues:
            for compute_resource in queue.compute_resources:
                self._execute_validator(
                    InstanceArchitectureCompatibilityValidator,
                    instance_type=compute_resource.instance_type,
                    architecture=self.head_node.architecture,
                )


class ClusterBucket:
    """Represent the cluster s3 bucket configuration."""

    def __init__(
        self,
        name: str,
        artifact_directory: str,
        remove_on_deletion: bool,
    ):
        super().__init__()
        self.name = name
        self.artifact_directory = artifact_directory
        self.remove_on_deletion = remove_on_deletion

    def delete(self):
        """Cleanup S3 bucket and/or artifact directory."""
        LOGGER.debug(
            "Cleaning up S3 resources bucket_name=%s, artifact_directory=%s, remove_bucket=%s",
            self.name,
            self.artifact_directory,
            self.remove_on_deletion,
        )
        if self.artifact_directory:
            delete_s3_artifacts(self.name, self.artifact_directory)
        if self.remove_on_deletion:
            delete_s3_bucket(self.name)
