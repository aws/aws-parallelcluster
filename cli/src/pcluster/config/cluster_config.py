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
from enum import Enum
from typing import List

from pcluster.validators.common import ValidationResult, Validator
from pcluster.validators.ec2 import InstanceTypeValidator
from pcluster.validators.fsx import FsxS3OptionsValidator


class _ConfigValidator:
    """Represent a generic validator for a configuration attribute or object. It's a module private class."""

    def __init__(self, validator_class: Validator, priority: int = 1, **kwargs):
        """Validators with higher priorities will be executed first."""
        self.validator_class = validator_class
        self.priority = priority
        self.validator_args = kwargs


class Config(ABC):
    """Represent an abstract Configuration entity."""

    def __init__(self):
        self.__validators: List[_ConfigValidator] = []
        self._validation_failures: List[ValidationResult] = []

    def validate(self):
        """Execute registered validators, ordered by priority (high prio --> executed first)."""

        # order validators by priority
        self.__validators = sorted(self.__validators, key=operator.attrgetter("priority"), reverse=True)

        # execute validators and add results in validation_failures array
        for attr_validator in self.__validators:
            # execute it by passing all the arguments
            self._validation_failures.extend(attr_validator.validator_class()(**attr_validator.validator_args))

        return self._validation_failures

    def _register_validator(self, validator_class: Validator, priority: int = 1, **kwargs):
        """Store validator to be executed at validation execution."""
        self.__validators.append(_ConfigValidator(validator_class, priority=priority, **kwargs))

    def __repr__(self):
        """Return a human readable representation of the Configuration object."""
        return "<{name}({attributes})>".format(
            name=self.__class__.__name__,
            attributes=",".join(f"{attr}={value}" for attr, value in self.__dict__.items()),
        )


class ImageConfig(Config):
    """Represent the configuration of an Image."""

    def __init__(self, os: str, id: str = None):
        super().__init__()
        self.os = os
        self.id = id
        self._validators = []

    # TODO define update policies at Image level for all the attributes
    def check_update(self):
        pass


class HeadNodeNetworkingConfig(Config):
    """Represent the networking configuration for the Head Node."""

    def __init__(
        self,
        subnet_id: str,
        elastic_ip: str = None,
        assign_public_ip: str = None,
        security_groups: List[str] = None,
        additional_security_groups: List[str] = None,
    ):
        super().__init__()
        self.subnet_id = subnet_id
        self.elastic_ip = elastic_ip
        self.assign_public_ip = assign_public_ip
        self.security_groups = security_groups
        self.additional_security_groups = additional_security_groups


class QueueNetworkingConfig(Config):
    """Represent the networking configuration for the Queue."""

    def __init__(self, subnet_ids: List[str]):
        super().__init__()
        self.subnet_ids = subnet_ids


class SshConfig(Config):
    """Represent the SSH configuration for a node (or the entire cluster)."""

    def __init__(self, key_name: str):
        super().__init__()
        self.key_name = key_name


class HeadNodeConfig(Config):
    """Represent the Head Node configuration."""

    def __init__(
        self,
        instance_type: str,
        networking_config: HeadNodeNetworkingConfig,
        ssh_config: SshConfig,
        image_config: ImageConfig,
    ):
        super().__init__()
        self.instance_type = instance_type
        self.image_config = image_config
        self.networking_config = networking_config
        self.ssh_config = ssh_config
        self._register_validator(InstanceTypeValidator, priority=100, instance_type=self.instance_type)


class ComputeResourceConfig(Config):
    """Represent the Compute Resource configuration."""

    def __init__(self, instance_type: str, max_count: int = None):
        super().__init__()
        self.instance_type = instance_type
        self.max_count = max_count
        # TODO add missing attributes


class QueueConfig(Config):
    """Represent the Queue configuration."""

    def __init__(
        self, name: str, networking_config: QueueNetworkingConfig, compute_resources_config: List[ComputeResourceConfig]
    ):
        super().__init__()
        self.name = name
        self.networking_config = networking_config
        self.compute_resources_config = compute_resources_config


class SchedulingConfig(Config):
    """Represent the Scheduling configuration."""

    def __init__(self, queues_config: List[QueueConfig], scheduler: str = "slurm"):
        super().__init__()
        self.scheduler = scheduler
        self.queues_config = queues_config


class SharedStorageType(Enum):
    """Describe the Type of a shared storage."""

    EBS = "EBS"
    EFS = "EFS"
    FSX = "FSX"

    @classmethod
    def is_valid(cls, value):
        """Verifies if the given value is a valid SharedStorageType"""
        return value in cls._member_names_


class SharedStorageConfig(Config):
    """Represent a generic shared storage configuration."""

    def __init__(self, mount_dir: str, storage_type: SharedStorageType):
        super().__init__()
        self.type = storage_type
        self.mount_dir = mount_dir


class EbsConfig(SharedStorageConfig):
    """Represent the EBS configuration."""

    def __init__(
        self,
        mount_dir: str,
        volume_type: str = None,
        iops: int = None,
        size: int = None,
        encrypted: bool = None,
        kms_key_id: str = None,
        snapshot_id: str = None,
        id: str = None,
    ):
        super().__init__(mount_dir, SharedStorageType.EBS)
        self.volume_type = volume_type
        self.iops = iops
        self.size = size
        self.encrypted = encrypted
        self.kms_key_id = kms_key_id
        self.snapshot_id = snapshot_id
        self.id = id


class EfsConfig(SharedStorageConfig):
    """Represent the EFS configuration."""

    def __init__(
        self,
        mount_dir: str,
        encrypted: bool = None,
        kms_key_id: str = None,
        performance_mode: str = None,
        throughput_mode: str = None,
        provisioned_throughput: int = None,
        id: str = None,
    ):
        super().__init__(mount_dir, SharedStorageType.EFS)
        self.encrypted = encrypted
        self.kms_key_id = kms_key_id
        self.performance_mode = performance_mode
        self.throughput_mode = throughput_mode
        self.provisioned_throughput = provisioned_throughput
        self.id = id


class FsxConfig(SharedStorageConfig):
    """Represent the FSX configuration."""

    def __init__(
        self,
        mount_dir: str,
        deployment_type: str = None,
        export_path: str = None,
        import_path: str = None,
        imported_file_chunk_size: str = None,
        weekly_maintenance_start_time: str = None,
        automatic_backup_retention_days: str = None,
        copy_tags_to_backup: bool = None,
        daily_automatic_backup_start_time: str = None,
        per_unit_storage_throughput: int = None,
        backup_id: str = None,
        kms_key_id: str = None,
        id: str = None,
        auto_import_policy: str = None,
        drive_cache_type: str = None,
        storage_type: str = None,
    ):
        super().__init__(mount_dir, SharedStorageType.FSX)
        self.storage_type = storage_type
        self.deployment_type = deployment_type
        self.export_path = export_path
        self.import_path = import_path
        self.imported_file_chunk_size = imported_file_chunk_size
        self.weekly_maintenance_start_time = weekly_maintenance_start_time
        self.automatic_backup_retention_days = automatic_backup_retention_days
        self.copy_tags_to_backup = copy_tags_to_backup
        self.daily_automatic_backup_start_time = daily_automatic_backup_start_time
        self.per_unit_storage_throughput = per_unit_storage_throughput
        self.backup_id = backup_id
        self.kms_key_id = kms_key_id
        self.id = id
        self.auto_import_policy = auto_import_policy
        self.drive_cache_type = drive_cache_type
        self.storage_type = storage_type
        self._register_validator(
            FsxS3OptionsValidator,
            priority=10,
            import_path=self.import_path,
            export_path=self.export_path,
            imported_file_chunk_size=self.imported_file_chunk_size,
            auto_import_policy=self.auto_import_policy,
        )
        # TODO register validators


class ClusterConfig(Config):
    """Represent the full Cluster configuration."""

    def __init__(
        self,
        image_config: ImageConfig,
        head_node_config: HeadNodeConfig,
        scheduling_config: SchedulingConfig,
        shared_storage_list_config: List[SharedStorageConfig] = None,
    ):
        super().__init__()
        self.image_config = image_config
        self.head_node_config = head_node_config
        self.scheduling_config = scheduling_config
        self.shared_storage_list_config = shared_storage_list_config
        self.cores = None

    @property
    def cores(self):
        """Example of property to be used for derived values, not present in the configuration file."""
        if self._cores is None:
            # FIXME boto3 call to retrieve the value
            self._cores = "1"
        return self._cores

    @cores.setter
    def cores(self, value):
        self._cores = value
