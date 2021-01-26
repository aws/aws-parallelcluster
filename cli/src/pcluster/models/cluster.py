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

import operator
from abc import ABC
from enum import Enum
from typing import List

from pcluster.constants import CIDR_ALL_IPS, EBS_VOLUME_TYPE_IOPS_DEFAULT
from pcluster.models.param import Param
from pcluster.validators.cluster_validators import FsxNetworkingValidator
from pcluster.validators.common import ValidationResult, Validator
from pcluster.validators.ebs_validators import (
    EbsVolumeIopsValidator,
    EbsVolumeThroughputIopsValidator,
    EbsVolumeThroughputValidator,
    EbsVolumeTypeSizeValidator,
)
from pcluster.validators.ec2_validators import InstanceTypeValidator
from pcluster.validators.fsx_validators import FsxValidator
from pcluster.validators.s3_validators import UrlValidator


class _ResourceValidator(ABC):
    """Represent a generic validator for a resource attribute or object. It's a module private class."""

    def __init__(self, validator_class: Validator, priority: int = 1, **kwargs):
        """Initialize validator. Note: Validators with higher priorities will be executed first."""
        self.validator_class = validator_class
        self.priority = priority
        self.validator_args = kwargs


class Resource(ABC):
    """Represent an abstract Resource entity."""

    def __init__(self):
        self.__validators: List[_ResourceValidator] = []
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
        self.__validators.append(_ResourceValidator(validator_class, priority=priority, **kwargs))

    def __repr__(self):
        """Return a human readable representation of the Resource object."""
        return "<{name}({attributes})>".format(
            name=self.__class__.__name__,
            attributes=",".join(f"{attr}={value}" for attr, value in self.__dict__.items()),
        )


# ---------------------- Storage ---------------------- #


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
        self.volume_type = Param(volume_type, default="gp2")
        self.iops = Param(iops, default=EBS_VOLUME_TYPE_IOPS_DEFAULT.get(self.volume_type.value))
        self.size = Param(size, default=20)
        self.encrypted = Param(encrypted, default=False)
        self.kms_key_id = Param(kms_key_id)
        self.throughput = Param(throughput, default=125 if self.volume_type.value == "gp3" else None)

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
        self.raid_type = Param(raid_type)
        self.number_of_volumes = Param(number_of_volumes, default=2)


class EphemeralVolume(Resource):
    """Represent the Ephemeral Volume resource."""

    def __init__(self, encrypted: bool = None, mount_dir: str = None):
        super().__init__()
        self.encrypted = Param(encrypted, default=False)
        self.mount_dir = Param(mount_dir, default="/scratch")


class Storage(Resource):
    """Represent the entire node storage configuration."""

    def __init__(self, root_volume: Ebs = None, ephemeral_volume: EphemeralVolume = None):
        super().__init__()
        self.root_volume = Param(root_volume)
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
        self.mount_dir = Param(mount_dir)
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
        self.snapshot_id = Param(snapshot_id)
        self.volume_id = Param(volume_id)
        self.raid = raid


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
        self.encrypted = Param(encrypted, default=False)
        self.kms_key_id = Param(kms_key_id)
        self.performance_mode = Param(performance_mode, default="generalPurpose")
        self.throughput_mode = Param(throughput_mode, default="bursting")
        self.provisioned_throughput = Param(provisioned_throughput)
        self.file_system_id = Param(file_system_id)


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
        self.storage_capacity = Param(storage_capacity)
        self.storage_type = Param(storage_type)
        self.deployment_type = Param(deployment_type)
        self.export_path = Param(export_path)
        self.import_path = Param(import_path)
        self.imported_file_chunk_size = Param(imported_file_chunk_size)
        self.weekly_maintenance_start_time = Param(weekly_maintenance_start_time)
        self.automatic_backup_retention_days = Param(automatic_backup_retention_days)
        self.copy_tags_to_backups = Param(copy_tags_to_backups)
        self.daily_automatic_backup_start_time = Param(daily_automatic_backup_start_time)
        self.per_unit_storage_throughput = Param(per_unit_storage_throughput)
        self.backup_id = Param(backup_id)
        self.kms_key_id = Param(kms_key_id)
        self.file_system_id = Param(file_system_id)
        self.auto_import_policy = Param(auto_import_policy)
        self.drive_cache_type = Param(drive_cache_type)
        self.storage_type = Param(storage_type)
        self._add_validator(FsxValidator, fsx_config=self)
        # TODO decide whether we should split FsxValidator into smaller ones


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
        self.assign_public_ip = Param(assign_public_ip)
        self.security_groups = security_groups
        self.additional_security_groups = additional_security_groups
        self.proxy = proxy


class HeadNodeNetworking(_BaseNetworking):
    """Represent the networking configuration for the head node."""

    def __init__(self, subnet_id: str, elastic_ip: str = None, **kwargs):
        super().__init__(**kwargs)
        self.subnet_id = Param(subnet_id)
        self.elastic_ip = Param(elastic_ip)


class PlacementGroup(Resource):
    """Represent the placement group for the Queue networking."""

    def __init__(self, enabled: bool = None, id: str = None):
        super().__init__()
        self.enabled = Param(enabled, default=False)
        self.id = Param(id)


class QueueNetworking(_BaseNetworking):
    """Represent the networking configuration for the Queue."""

    def __init__(self, subnet_ids: List[str], placement_group: PlacementGroup = None, **kwargs):
        super().__init__(**kwargs)
        self.subnet_ids = subnet_ids
        self.placement_group = placement_group


class Ssh(Resource):
    """Represent the SSH configuration for a node (or the entire cluster)."""

    def __init__(self, key_name: str, allowed_ips: str = None):
        super().__init__()
        self.key_name = Param(key_name)
        self.allowed_ips = Param(allowed_ips, default=CIDR_ALL_IPS)


class Dcv(Resource):
    """Represent the DCV configuration."""

    def __init__(self, enabled: bool, port: int = None, allowed_ips: str = None):
        super().__init__()
        self.enabled = Param(enabled)
        self.port = Param(port, default=8843)
        self.allowed_ips = Param(allowed_ips, default=CIDR_ALL_IPS)


class Efa(Resource):
    """Represent the EFA configuration."""

    def __init__(self, enabled: bool = None, gdr_support: bool = None):
        super().__init__()
        self.enabled = Param(enabled, default=True)
        self.gdr_support = Param(gdr_support, default=False)


# ---------------------- Nodes ---------------------- #


class Image(Resource):
    """Represent the configuration of an Image."""

    def __init__(self, os: str, custom_ami: str = None):
        super().__init__()
        self.os = Param(os)
        self.custom_ami = Param(custom_ami)


class HeadNode(Resource):
    """Represent the Head Node resource."""

    def __init__(
        self,
        instance_type: str,
        networking: HeadNodeNetworking,
        ssh: Ssh,
        image: Image = None,
        storage: Storage = None,
        dcv: Dcv = None,
        efa: Efa = None,
    ):
        super().__init__()
        self.instance_type = Param(instance_type)
        self.image = image
        self.networking = networking
        self.ssh = ssh
        self.storage = storage
        self.dcv = dcv
        self.efa = efa
        self._add_validator(InstanceTypeValidator, priority=1, instance_type=self.instance_type)


class BaseComputeResource(Resource):
    """Represent the base Compute Resource, with the fields in common between all the schedulers."""

    def __init__(
        self,
        allocation_strategy: str = None,
        simultaneous_multithreading: bool = None,
        efa: Efa = None,
    ):
        super().__init__()
        self.allocation_strategy = Param(allocation_strategy, default="BEST_FIT")
        self.simultaneous_multithreading = Param(simultaneous_multithreading, default=True)
        self.efa = efa


class BaseQueue(Resource):
    """Represent the generic Queue resource."""

    def __init__(
        self,
        name: str,
        networking: QueueNetworking,
        storage: Storage = None,
        compute_type: str = None,
    ):
        super().__init__()
        self.name = Param(name)
        self.networking = networking
        self.storage = storage
        self.compute_type = Param(compute_type, default="ONDEMAND")


class CommonSchedulingSettings(Resource):
    """Represent the common scheduler settings."""

    def __init__(self, scaledown_idletime: int):
        super().__init__()
        self.scaledown_idletime = Param(scaledown_idletime)


class CustomAction(Resource):
    """Represent a custom action resource."""

    def __init__(self, script: str, args: List[str] = None, event: str = None, run_as: str = None):
        super().__init__()
        self.script = Param(script)
        self.args = args
        self.event = Param(event)
        self.run_as = Param(run_as)
        self._add_validator(UrlValidator, url=self.script)


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
        self.enabled = Param(enabled, default=True)
        self.retention_in_days = Param(retention_in_days, default=14)
        self.log_group_id = Param(log_group_id)
        self.kms_key_id = Param(kms_key_id)


class CloudWatchDashboards(Resource):
    """Represent the CloudWatch Dashboard."""

    def __init__(
        self,
        enabled: bool = None,
    ):
        super().__init__()
        self.enabled = Param(enabled, default=True)


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
        self.detailed_monitoring = Param(detailed_monitoring, default=False)
        self.logs = logs
        self.dashboards = dashboards


# ---------------------- Others ---------------------- #


class Roles(Resource):
    """Represent the Roles configuration."""

    def __init__(
        self,
        head_node: str = None,
        compute_node: str = None,
        custom_lambda_resources: str = None,
    ):
        super().__init__()
        self.head_node = Param(head_node, default="AUTO")
        self.compute_node = Param(compute_node, default="AUTO")
        self.custom_lambda_resources = Param(custom_lambda_resources, default="AUTO")


class S3Access(Resource):
    """Represent the S3 Access configuration."""

    def __init__(
        self,
        bucket_name: str,
        type: str = None,
    ):
        super().__init__()
        self.bucket_name = Param(bucket_name)
        self.type = Param(type, default="READ_ONLY")


class AdditionalIamPolicy(Resource):
    """Represent the Additional IAM Policy configuration."""

    def __init__(
        self,
        policy: str,
        scope: str = None,
    ):
        super().__init__()
        self.policy = Param(policy)
        self.scope = Param(scope, default="CLUSTER")


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


class Tag(Resource):
    """Represent the Tag configuration."""

    def __init__(
        self,
        key: str = None,
        value: str = None,
    ):
        super().__init__()
        self.key = Param(key)
        self.value = Param(value)


# ---------------------- Root resource ---------------------- #


class BaseCluster(Resource):
    """Represent the common Cluster resource."""

    def __init__(
        self,
        image: Image,
        head_node: HeadNode,
        shared_storage: List[SharedStorage] = None,
        monitoring: Monitoring = None,
        tags: List[Tag] = None,
        iam: Iam = None,
        custom_actions: CustomAction = None,
    ):
        super().__init__()
        self.image = image
        self.head_node = head_node
        self.shared_storage = shared_storage
        self.monitoring = monitoring
        self.tags = tags
        self.iam = iam
        self.custom_actions = custom_actions
        self.cores = None
        if self.shared_storage:
            for storage in self.shared_storage:
                if isinstance(storage, SharedFsx):
                    self._add_validator(
                        FsxNetworkingValidator,
                        fs_system_id=storage.file_system_id,
                        head_node_subnet_id=self.head_node.networking.subnet_id,
                    )

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
