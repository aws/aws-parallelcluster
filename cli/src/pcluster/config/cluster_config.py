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
# This module contains all the classes representing the Configuration objects.
# These objects are obtained from the configuration file through a conversion based on the Schema classes.
#

import operator
from abc import ABC
from typing import List

from pcluster.config.extended_builtin_class import MarkedBool, MarkedInt, MarkedStr
from pcluster.constants import CIDR_ALL_IPS, EBS_VOLUME_TYPE_IOPS_DEFAULT
from pcluster.validators.common import ValidationResult, Validator
from pcluster.validators.ebs import EbsVolumeIopsValidator, EbsVolumeThroughputValidator, EbsVolumeTypeSizeValidator
from pcluster.validators.ec2 import InstanceTypeValidator
from pcluster.validators.fsx import FsxValidator


class _ConfigValidator:
    """Represent a generic validator for a configuration attribute or object. It's a module private class."""

    def __init__(self, validator_class: Validator, priority: int = 1, **kwargs):
        """Initialize validator. Note: Validators with higher priorities will be executed first."""
        self.validator_class = validator_class
        self.priority = priority
        self.validator_args = kwargs


class Config(ABC):
    """Represent an abstract Configuration entity."""

    def __init__(self):
        self.__validators: List[_ConfigValidator] = []
        self._validation_failures: List[ValidationResult] = []

    def validate(self, raise_on_error=False):
        """Execute registered validators, ordered by priority (high prio --> executed first)."""
        # order validators by priority
        self.__validators = sorted(self.__validators, key=operator.attrgetter("priority"), reverse=True)

        # execute validators and add results in validation_failures array
        for attr_validator in self.__validators:
            # execute it by passing all the arguments
            self._validation_failures.extend(
                attr_validator.validator_class(raise_on_error=raise_on_error)(**attr_validator.validator_args)
            )

        return self._validation_failures

    def _add_validator(self, validator_class: Validator, priority: int = 1, **kwargs):
        """Store validator to be executed at validation execution."""
        self.__validators.append(_ConfigValidator(validator_class, priority=priority, **kwargs))

    def __repr__(self):
        """Return a human readable representation of the Configuration object."""
        return "<{name}({attributes})>".format(
            name=self.__class__.__name__,
            attributes=",".join(f"{attr}={value}" for attr, value in self.__dict__.items()),
        )


# ---------------------- Storage ---------------------- #
class BaseEbsConfig(Config):
    """Represent the configuration shared by EBS and RootVolume."""

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
        if volume_type is None:
            volume_type = MarkedStr("gp2")
        if iops is None and volume_type in EBS_VOLUME_TYPE_IOPS_DEFAULT:
            iops = EBS_VOLUME_TYPE_IOPS_DEFAULT.get(volume_type)
        if size is None:
            size = MarkedInt(20)
        if encrypted is None:
            encrypted = MarkedBool(False)
        if throughput is None and volume_type == "gp3":
            throughput = MarkedInt(125)
        self.volume_type = volume_type
        self.iops = iops
        self.size = size
        self.encrypted = encrypted
        self.kms_key_id = kms_key_id
        self.throughput = throughput

        self._add_validator(
            EbsVolumeTypeSizeValidator, priority=10, volume_type=self.volume_type, volume_size=self.size
        )
        self._add_validator(
            EbsVolumeThroughputValidator,
            priority=1,
            volume_type=self.volume_type,
            volume_iops=self.iops,
            volume_throughput=self.throughput,
        )
        self._add_validator(
            EbsVolumeIopsValidator,
            priority=1,
            volume_type=self.volume_type,
            volume_size=self.size,
            volume_iops=self.iops,
        )


class RaidConfig(Config):
    """Represent the Raid configuration."""

    def __init__(self, type: str = None, number_of_volumes=None):
        super().__init__()
        if number_of_volumes is None:
            number_of_volumes = MarkedInt(2)
        self.type = type
        self.number_of_volumes = number_of_volumes


class EbsConfig(BaseEbsConfig):
    """Represent the EBS configuration."""

    def __init__(self, snapshot_id: str = None, volume_id: str = None, raid: RaidConfig = None, **kwargs):
        super().__init__(**kwargs)

        self.snapshot_id = snapshot_id
        self.volume_id = volume_id
        self.raid = raid


class EphemeralVolumeConfig(Config):
    """Represent the Raid configuration."""

    def __init__(self, encrypted: bool = None, mount_dir: str = None):
        super().__init__()
        if encrypted is None:
            encrypted = MarkedBool(False)
        if mount_dir is None:
            mount_dir = MarkedStr("/scratch")
        self.encrypted = encrypted
        self.mount_dir = mount_dir


class StorageConfig(Config):
    """Represent the configuration of node storage."""

    def __init__(self, root_volume: BaseEbsConfig = None, ephemeral_volume: EphemeralVolumeConfig = None):
        self.root_volume = root_volume
        self.ephemeral_volume = ephemeral_volume


class EfsConfig(Config):
    """Represent the EFS configuration."""

    def __init__(
        self,
        encrypted: bool = None,
        kms_key_id: str = None,
        performance_mode: str = None,
        throughput_mode: str = None,
        provisioned_throughput: int = None,
        id: str = None,
    ):
        super().__init__()
        if encrypted is None:
            encrypted = MarkedBool(False)
        if performance_mode is None:
            performance_mode = MarkedStr("generalPurpose")
        if throughput_mode is None:
            throughput_mode = MarkedStr("bursting")
        self.encrypted = encrypted
        self.kms_key_id = kms_key_id
        self.performance_mode = performance_mode
        self.throughput_mode = throughput_mode
        self.provisioned_throughput = provisioned_throughput
        self.id = id


class FsxConfig(Config):
    """Represent the FSX configuration."""

    def __init__(
        self,
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
        self.storage_capacity = storage_capacity
        self.storage_type = storage_type
        self.deployment_type = deployment_type
        self.export_path = export_path
        self.import_path = import_path
        self.imported_file_chunk_size = imported_file_chunk_size
        self.weekly_maintenance_start_time = weekly_maintenance_start_time
        self.automatic_backup_retention_days = automatic_backup_retention_days
        self.copy_tags_to_backups = copy_tags_to_backups
        self.daily_automatic_backup_start_time = daily_automatic_backup_start_time
        self.per_unit_storage_throughput = per_unit_storage_throughput
        self.backup_id = backup_id
        self.kms_key_id = kms_key_id
        self.file_system_id = file_system_id
        self.auto_import_policy = auto_import_policy
        self.drive_cache_type = drive_cache_type
        self.storage_type = storage_type
        self._add_validator(FsxValidator, fsx_config=self)
        # TODO decide whether we should split FsxValidator into smaller ones


class SharedStorageConfig(Config):
    """Represent the Shared Storage configuration."""

    def __init__(
        self,
        mount_dir: str,
        ebs_settings: EbsConfig = None,
        efs_settings: EfsConfig = None,
        fsx_settings: FsxConfig = None,
    ):
        super().__init__()
        self.mount_dir = mount_dir
        if ebs_settings:
            self.ebs_settings = ebs_settings
        elif efs_settings:
            self.efs_settings = efs_settings
        elif fsx_settings:
            self.fsx_settings = fsx_settings


# ---------------------- Networking ---------------------- #
class ProxyConfig(Config):
    """Represent the proxy."""

    def __init__(self, http_proxy_address: str = None):
        super().__init__()
        self.http_proxy_address = http_proxy_address


class BaseNetworkingConfig(Config):
    """Represent the networking configuration shared by head node and compute node."""

    def __init__(
        self,
        assign_public_ip: str = None,
        security_groups: List[str] = None,
        additional_security_groups: List[str] = None,
        proxy: ProxyConfig = None,
    ):
        super().__init__()
        self.assign_public_ip = assign_public_ip
        self.security_groups = security_groups
        self.additional_security_groups = additional_security_groups
        self.proxy = proxy


class HeadNodeNetworkingConfig(BaseNetworkingConfig):
    """Represent the networking configuration for the head node."""

    def __init__(self, subnet_id: str, elastic_ip: str = None, **kwargs):
        super().__init__(**kwargs)
        self.subnet_id = subnet_id
        self.elastic_ip = elastic_ip


class PlacementGroupConfig(Config):
    """Represent the placement group for the Queue networking."""

    def __init__(self, enabled: bool = None, id: str = None):
        super().__init__()
        if enabled is None:
            enabled = MarkedBool(False)
        self.enabled = enabled
        self.id = id


class QueueNetworkingConfig(BaseNetworkingConfig):
    """Represent the networking configuration for the Queue."""

    def __init__(self, subnet_ids: List[str], placement_group: PlacementGroupConfig = None, **kwargs):
        super().__init__(**kwargs)
        self.subnet_ids = subnet_ids
        self.placement_group = placement_group


class SshConfig(Config):
    """Represent the SSH configuration for a node (or the entire cluster)."""

    def __init__(self, key_name: str, allowed_ips: str = None):
        super().__init__()
        if allowed_ips is None:
            allowed_ips = MarkedStr(CIDR_ALL_IPS)
        self.key_name = key_name
        self.allowed_ips = allowed_ips


class DcvConfig(Config):
    """Represent the DCV configuration."""

    def __init__(self, enabled: bool, port: int = None, allowed_ips: str = None):
        super().__init__()
        if port is None:
            port = MarkedInt(8843)
        if allowed_ips is None:
            allowed_ips = MarkedStr(CIDR_ALL_IPS)
        self.enabled = enabled
        self.port = port
        self.allowed_ips = allowed_ips


# ---------------------- Nodes ---------------------- #
class ImageConfig(Config):
    """Represent the configuration of an Image."""

    def __init__(self, os: str, custom_ami: str = None):
        super().__init__()
        self.os = os
        self.custom_ami = custom_ami


class HeadNodeConfig(Config):
    """Represent the Head Node configuration."""

    def __init__(
        self,
        instance_type: str,
        networking: HeadNodeNetworkingConfig,
        ssh: SshConfig,
        image: ImageConfig = None,
        storage: StorageConfig = None,
        dcv: DcvConfig = None,
    ):
        super().__init__()
        self.instance_type = instance_type
        self.image = image
        self.networking = networking
        self.ssh = ssh
        self.storage = storage
        self.dcv = dcv
        self._add_validator(InstanceTypeValidator, priority=1, instance_type=self.instance_type)


class ComputeResourceConfig(Config):
    """Represent the Compute Resource configuration."""

    def __init__(self, instance_type: str, max_count: int = None):
        super().__init__()
        if max_count is None:
            max_count = MarkedInt(10)
        self.instance_type = instance_type
        self.max_count = max_count
        # TODO add missing attributes


class QueueConfig(Config):
    """Represent the Queue configuration."""

    def __init__(self, name: str, networking: QueueNetworkingConfig, compute_resources: List[ComputeResourceConfig]):
        super().__init__()
        self.name = name
        self.networking = networking
        self.compute_resources = compute_resources


class SchedulingSettingsConfig(Config):
    """Represent the Scheduling configuration."""

    def __init__(self, scaledown_idletime: int):
        super().__init__()
        self.scaledown_idletime = scaledown_idletime


class SchedulingConfig(Config):
    """Represent the Scheduling configuration."""

    def __init__(self, queues: List[QueueConfig], scheduler: str = None, settings: SchedulingSettingsConfig = None):
        super().__init__()
        if scheduler is None:
            scheduler = MarkedStr("slurm")
        self.scheduler = scheduler
        self.queues = queues
        self.settings = settings


class CustomActionConfig(Config):
    """Represent the custom action configuration."""

    def __init__(self, script: str, args: List[str] = None, event: str = None, run_as: str = None):
        super().__init__()
        self.script = script
        self.args = args
        self.event = event
        self.run_as = run_as


# ---------------------- Monitoring ---------------------- #
class CloudWatchLogsConfig(Config):
    """Represent the CloudWatch configuration in Logs."""

    def __init__(
        self,
        enabled: bool = None,
        retention_in_days: int = None,
        log_group_id: str = None,
        kms_key_id: str = None,
    ):
        super().__init__()
        if enabled is None:
            enabled = MarkedBool(True)
        if retention_in_days is None:
            retention_in_days = MarkedInt(14)
        self.enabled = enabled
        self.retention_in_days = retention_in_days
        self.log_group_id = log_group_id
        self.kms_key_id = kms_key_id


class CloudWatchDashboardsConfig(Config):
    """Represent the CloudWatch configuration in Dashboards."""

    def __init__(
        self,
        enabled: bool = None,
    ):
        super().__init__()
        if enabled is None:
            enabled = MarkedBool(True)
        self.enabled = enabled


class LogsConfig(Config):
    """Represent the Logs configuration."""

    def __init__(
        self,
        cloud_watch: CloudWatchLogsConfig = None,
    ):
        super().__init__()
        self.cloud_watch = cloud_watch


class DashboardsConfig(Config):
    """Represent the Dashboards configuration."""

    def __init__(
        self,
        cloud_watch: CloudWatchDashboardsConfig = None,
    ):
        super().__init__()
        self.cloud_watch = cloud_watch


class MonitoringConfig(Config):
    """Represent the Monitoring configuration."""

    def __init__(
        self,
        detailed_monitoring: bool = None,
        logs: LogsConfig = None,
        dashboards: DashboardsConfig = None,
    ):
        super().__init__()
        if detailed_monitoring is None:
            detailed_monitoring = MarkedBool(False)
        self.detailed_monitoring = detailed_monitoring
        self.logs = logs
        self.dashboards = dashboards


# ---------------------- Others ---------------------- #
class RolesConfig(Config):
    """Represent the Roles configuration."""

    def __init__(
        self,
        head_node: str = None,
        compute_node: str = None,
        custom_lambda_resources: str = None,
    ):
        super().__init__()
        if head_node is None:
            head_node = MarkedStr("AUTO")
        if compute_node is None:
            compute_node = MarkedStr("AUTO")
        if custom_lambda_resources is None:
            custom_lambda_resources = MarkedStr("AUTO")
        self.head_node = head_node
        self.compute_node = compute_node
        self.custom_lambda_resources = custom_lambda_resources


class S3AccessConfig(Config):
    """Represent the S3 Access configuration."""

    def __init__(
        self,
        bucket_name: str,
        type: str = None,
    ):
        super().__init__()
        if type is None:
            type = MarkedStr("READ_ONLY")
        self.bucket_name = bucket_name
        self.type = type


class AdditionalIamPolicyConfig(Config):
    """Represent the Additional IAM Policy configuration."""

    def __init__(
        self,
        policy: str,
        scope: str = None,
    ):
        super().__init__()
        if scope is None:
            scope = MarkedStr("CLUSTER")
        self.policy = policy
        self.scope = scope


class IamConfig(Config):
    """Represent the IAM configuration."""

    def __init__(
        self,
        roles: RolesConfig = None,
        s3_access: List[S3AccessConfig] = None,
        additional_iam_policies: List[AdditionalIamPolicyConfig] = None,
    ):
        super().__init__()
        self.roles = roles
        self.s3_access = s3_access
        self.additional_iam_policies = additional_iam_policies


class TagConfig(Config):
    """Represent the Tag configuration."""

    def __init__(
        self,
        key: str = None,
        value: str = None,
    ):
        super().__init__()
        self.key = key
        self.value = value


# ---------------------- Root Schema ---------------------- #
class ClusterConfig(Config):
    """Represent the full Cluster configuration."""

    def __init__(
        self,
        image: ImageConfig,
        head_node: HeadNodeConfig,
        scheduling: SchedulingConfig,
        shared_storage: List[SharedStorageConfig] = None,
        monitoring: MonitoringConfig = None,
        tags: List[TagConfig] = None,
        iam: IamConfig = None,
        custom_actions: CustomActionConfig = None,
    ):
        super().__init__()
        self.image = image
        self.head_node = head_node
        self.scheduling = scheduling
        self.shared_storage = shared_storage
        self.monitoring = monitoring
        self.tags = tags
        self.iam = iam
        self.custom_actions = custom_actions
        self.cores = None

    @property
    def cores(self):
        """Return the number of cores. Example derived attribute, not present in the config file."""
        if self._cores is None:
            # FIXME boto3 call to retrieve the value
            self._cores = "1"
        return self._cores

    @cores.setter
    def cores(self, value):
        self._cores = value
