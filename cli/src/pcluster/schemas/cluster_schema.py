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
# This module contains all the classes representing the Schema of the configuration file.
# These classes are created by following marshmallow syntax.
#

import copy
import hashlib
import logging
import re
from typing import List
from urllib.request import urlopen

from marshmallow import ValidationError, fields, post_load, pre_dump, pre_load, validate, validates, validates_schema
from yaml import YAMLError

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.config.cluster_config import (
    AdditionalPackages,
    AllocationStrategy,
    AmiSearchFilters,
    AwsBatchClusterConfig,
    AwsBatchComputeResource,
    AwsBatchQueue,
    AwsBatchQueueNetworking,
    AwsBatchScheduling,
    AwsBatchSettings,
    CapacityReservationTarget,
    CapacityType,
    CloudWatchDashboards,
    CloudWatchLogs,
    ClusterDevSettings,
    ClusterIam,
    ComputeSettings,
    CustomAction,
    CustomActions,
    Dashboards,
    Database,
    Dcv,
    DirectoryService,
    Dns,
    Efa,
    EphemeralVolume,
    ExistingFsxOntap,
    ExistingFsxOpenZfs,
    FlexibleInstanceType,
    HeadNode,
    HeadNodeImage,
    HeadNodeNetworking,
    Iam,
    Image,
    Imds,
    IntelSoftware,
    LocalStorage,
    Logs,
    Monitoring,
    PlacementGroup,
    Proxy,
    QueueImage,
    QueueUpdateStrategy,
    Raid,
    Roles,
    RootVolume,
    S3Access,
    SchedulerPluginCloudFormationInfrastructure,
    SchedulerPluginClusterConfig,
    SchedulerPluginClusterInfrastructure,
    SchedulerPluginClusterSharedArtifact,
    SchedulerPluginComputeResource,
    SchedulerPluginComputeResourceConstraints,
    SchedulerPluginDefinition,
    SchedulerPluginEvent,
    SchedulerPluginEvents,
    SchedulerPluginExecuteCommand,
    SchedulerPluginFile,
    SchedulerPluginLogs,
    SchedulerPluginMonitoring,
    SchedulerPluginPluginResources,
    SchedulerPluginQueue,
    SchedulerPluginQueueConstraints,
    SchedulerPluginQueueNetworking,
    SchedulerPluginRequirements,
    SchedulerPluginScheduling,
    SchedulerPluginSettings,
    SchedulerPluginSupportedDistros,
    SchedulerPluginUser,
    SharedEbs,
    SharedEfs,
    SharedFsxLustre,
    SlurmClusterConfig,
    SlurmComputeResource,
    SlurmComputeResourceNetworking,
    SlurmFlexibleComputeResource,
    SlurmQueue,
    SlurmQueueNetworking,
    SlurmScheduling,
    SlurmSettings,
    Ssh,
    SudoerConfiguration,
    Timeouts,
)
from pcluster.config.update_policy import UpdatePolicy
from pcluster.constants import (
    DELETION_POLICIES,
    DELETION_POLICIES_WITH_SNAPSHOT,
    FSX_LUSTRE,
    FSX_ONTAP,
    FSX_OPENZFS,
    FSX_VOLUME_ID_REGEX,
    LUSTRE,
    ONTAP,
    OPENZFS,
    SCHEDULER_PLUGIN_MAX_NUMBER_OF_USERS,
    SUPPORTED_OSES,
)
from pcluster.models.s3_bucket import parse_bucket_url
from pcluster.schemas.common_schema import AdditionalIamPolicySchema, BaseDevSettingsSchema, BaseSchema
from pcluster.schemas.common_schema import ImdsSchema as TopLevelImdsSchema
from pcluster.schemas.common_schema import TagSchema, get_field_validator, validate_no_reserved_tag
from pcluster.utils import yaml_load
from pcluster.validators.cluster_validators import EFS_MESSAGES, FSX_MESSAGES

# pylint: disable=C0302


LOGGER = logging.getLogger(__name__)


# ---------------------- Storage ---------------------- #


class HeadNodeRootVolumeSchema(BaseSchema):
    """Represent the RootVolume schema for the Head node."""

    volume_type = fields.Str(
        validate=get_field_validator("volume_type"),
        metadata={
            "update_policy": UpdatePolicy(
                UpdatePolicy.UNSUPPORTED, action_needed=UpdatePolicy.ACTIONS_NEEDED["ebs_volume_update"]
            )
        },
    )
    iops = fields.Int(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    size = fields.Int(
        metadata={
            "update_policy": UpdatePolicy(
                UpdatePolicy.UNSUPPORTED,
                fail_reason=UpdatePolicy.FAIL_REASONS["ebs_volume_resize"],
                action_needed=UpdatePolicy.ACTIONS_NEEDED["ebs_volume_update"],
            )
        }
    )
    throughput = fields.Int(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    encrypted = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    delete_on_termination = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return RootVolume(**data)


class QueueRootVolumeSchema(BaseSchema):
    """Represent the RootVolume schema for the queue."""

    size = fields.Int(metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})
    encrypted = fields.Bool(metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})
    volume_type = fields.Str(metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})
    iops = fields.Int(metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})
    throughput = fields.Int(metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return RootVolume(**data)


class RaidSchema(BaseSchema):
    """Represent the schema of the parameters specific to Raid. It is a child of EBS schema."""

    raid_type = fields.Int(
        required=True,
        data_key="Type",
        validate=validate.OneOf([0, 1]),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    number_of_volumes = fields.Int(
        validate=validate.Range(min=2, max=5), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Raid(**data)


class EbsSettingsSchema(BaseSchema):
    """Represent the schema of EBS."""

    volume_type = fields.Str(
        validate=get_field_validator("volume_type"),
        metadata={
            "update_policy": UpdatePolicy(
                UpdatePolicy.UNSUPPORTED, action_needed=UpdatePolicy.ACTIONS_NEEDED["ebs_volume_update"]
            )
        },
    )
    iops = fields.Int(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    size = fields.Int(
        metadata={
            "update_policy": UpdatePolicy(
                UpdatePolicy.UNSUPPORTED,
                fail_reason=UpdatePolicy.FAIL_REASONS["ebs_volume_resize"],
                action_needed=UpdatePolicy.ACTIONS_NEEDED["ebs_volume_update"],
            )
        }
    )
    kms_key_id = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    throughput = fields.Int(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    encrypted = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    snapshot_id = fields.Str(
        validate=validate.Regexp(r"^snap-[0-9a-z]{8}$|^snap-[0-9a-z]{17}$"),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    volume_id = fields.Str(
        validate=validate.Regexp(r"^vol-[0-9a-z]{8}$|^vol-[0-9a-z]{17}$"),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    raid = fields.Nested(RaidSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    deletion_policy = fields.Str(
        validate=validate.OneOf(DELETION_POLICIES_WITH_SNAPSHOT), metadata={"update_policy": UpdatePolicy.SUPPORTED}
    )


class HeadNodeEphemeralVolumeSchema(BaseSchema):
    """Represent the schema of ephemeral volume.It is a child of storage schema."""

    mount_dir = fields.Str(
        validate=get_field_validator("file_path"), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return EphemeralVolume(**data)


class QueueEphemeralVolumeSchema(BaseSchema):
    """Represent the schema of ephemeral volume.It is a child of storage schema."""

    mount_dir = fields.Str(
        validate=get_field_validator("file_path"), metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return EphemeralVolume(**data)


class HeadNodeStorageSchema(BaseSchema):
    """Represent the schema of storage attached to a node."""

    root_volume = fields.Nested(HeadNodeRootVolumeSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    ephemeral_volume = fields.Nested(
        HeadNodeEphemeralVolumeSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return LocalStorage(**data)


class QueueStorageSchema(BaseSchema):
    """Represent the schema of storage attached to a node."""

    root_volume = fields.Nested(QueueRootVolumeSchema, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})
    ephemeral_volume = fields.Nested(
        QueueEphemeralVolumeSchema, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return LocalStorage(**data)


class EfsSettingsSchema(BaseSchema):
    """Represent the EFS schema."""

    encrypted = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    kms_key_id = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    performance_mode = fields.Str(
        validate=validate.OneOf(["generalPurpose", "maxIO"]), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    throughput_mode = fields.Str(
        validate=validate.OneOf(["provisioned", "bursting"]), metadata={"update_policy": UpdatePolicy.SUPPORTED}
    )
    provisioned_throughput = fields.Int(
        validate=validate.Range(min=1, max=1024), metadata={"update_policy": UpdatePolicy.SUPPORTED}
    )
    file_system_id = fields.Str(
        validate=validate.Regexp(r"^fs-[0-9a-z]{8}$|^fs-[0-9a-z]{17}$"),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    deletion_policy = fields.Str(
        validate=validate.OneOf(DELETION_POLICIES), metadata={"update_policy": UpdatePolicy.SUPPORTED}
    )

    @validates_schema
    def validate_file_system_id_ignored_parameters(self, data, **kwargs):
        """Return errors for parameters in the Efs config section that would be ignored."""
        # If file_system_id is specified, all parameters are ignored.
        messages = []
        if data.get("file_system_id") is not None:
            for key in data:
                if key is not None and key != "file_system_id":
                    messages.append(EFS_MESSAGES["errors"]["ignored_param_with_efs_fs_id"].format(efs_param=key))
            if messages:
                raise ValidationError(message=messages)

    @validates_schema
    def validate_existence_of_mode_throughput(self, data, **kwargs):
        """Validate the conditional existence requirement between throughput_mode and provisioned_throughput."""
        if kwargs.get("partial"):
            # If the schema is to be loaded partially, do not check existence constrain.
            return
        throughput_mode = data.get("throughput_mode")
        provisioned_throughput = data.get("provisioned_throughput")
        if throughput_mode != "provisioned" and provisioned_throughput:
            raise ValidationError(
                message="When specifying provisioned throughput, the throughput mode must be set to provisioned",
                field_name="ThroughputMode",
            )

        if throughput_mode == "provisioned" and not provisioned_throughput:
            raise ValidationError(
                message="When specifying throughput mode to provisioned,"
                " the provisioned throughput option must be specified",
                field_name="ProvisionedThroughput",
            )


class FsxLustreSettingsSchema(BaseSchema):
    """Represent the FSX schema."""

    storage_capacity = fields.Int(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    deployment_type = fields.Str(
        validate=validate.OneOf(["SCRATCH_1", "SCRATCH_2", "PERSISTENT_1", "PERSISTENT_2"]),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    imported_file_chunk_size = fields.Int(
        validate=validate.Range(min=1, max=512000, error="has a minimum size of 1 MiB, and max size of 512,000 MiB"),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    export_path = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    import_path = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    weekly_maintenance_start_time = fields.Str(
        validate=validate.Regexp(r"^[1-7]:([01]\d|2[0-3]):([0-5]\d)$"),
        metadata={"update_policy": UpdatePolicy.SUPPORTED},
    )
    automatic_backup_retention_days = fields.Int(
        validate=validate.Range(min=0, max=35), metadata={"update_policy": UpdatePolicy.SUPPORTED}
    )
    copy_tags_to_backups = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    daily_automatic_backup_start_time = fields.Str(
        validate=validate.Regexp(r"^([01]\d|2[0-3]):([0-5]\d)$"), metadata={"update_policy": UpdatePolicy.SUPPORTED}
    )
    per_unit_storage_throughput = fields.Int(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    backup_id = fields.Str(
        validate=validate.Regexp("^(backup-[0-9a-f]{8,})$"),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    kms_key_id = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    file_system_id = fields.Str(
        validate=validate.Regexp(r"^fs-[0-9a-z]{17}$"),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    auto_import_policy = fields.Str(
        validate=validate.OneOf(["NEW", "NEW_CHANGED", "NEW_CHANGED_DELETED"]),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    drive_cache_type = fields.Str(
        validate=validate.OneOf(["READ"]), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    data_compression_type = fields.Str(
        validate=validate.OneOf(["LZ4"]), metadata={"update_policy": UpdatePolicy.SUPPORTED}
    )
    fsx_storage_type = fields.Str(
        data_key="StorageType",
        validate=validate.OneOf(["HDD", "SSD"]),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    deletion_policy = fields.Str(
        validate=validate.OneOf(DELETION_POLICIES), metadata={"update_policy": UpdatePolicy.SUPPORTED}
    )

    @validates_schema
    def validate_file_system_id_ignored_parameters(self, data, **kwargs):
        """Return errors for parameters in the FSx config section that would be ignored."""
        # If file_system_id is specified, all parameters are ignored.
        messages = []
        if data.get("file_system_id") is not None:
            for key in data:
                if key is not None and key != "file_system_id":
                    messages.append(FSX_MESSAGES["errors"]["ignored_param_with_fsx_fs_id"].format(fsx_param=key))
            if messages:
                raise ValidationError(message=messages)

    @validates_schema
    def validate_backup_id_unsupported_parameters(self, data, **kwargs):
        """Return errors for parameters in the FSx config section that would be ignored."""
        # If file_system_id is specified, all parameters are ignored.
        messages = []
        if data.get("backup_id") is not None:
            unsupported_config_param_names = [
                "deployment_type",
                "per_unit_storage_throughput",
                "storage_capacity",
                "import_path",
                "export_path",
                "imported_file_chunk_size",
                "kms_key_id",
            ]

            for key in data:
                if key in unsupported_config_param_names:
                    messages.append(FSX_MESSAGES["errors"]["unsupported_backup_param"].format(name=key))

            if messages:
                raise ValidationError(message=messages)


class FsxOpenZfsSettingsSchema(BaseSchema):
    """Represent the FSX OpenZFS schema."""

    volume_id = fields.Str(
        required=True,
        validate=validate.Regexp(FSX_VOLUME_ID_REGEX),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )


class FsxOntapSettingsSchema(BaseSchema):
    """Represent the FSX Ontap schema."""

    volume_id = fields.Str(
        required=True,
        validate=validate.Regexp(FSX_VOLUME_ID_REGEX),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )


class SharedStorageSchema(BaseSchema):
    """Represent the generic SharedStorage schema."""

    mount_dir = fields.Str(
        required=True,
        validate=get_field_validator("file_path"),
        metadata={"update_policy": UpdatePolicy.SHARED_STORAGE_UPDATE_POLICY},
    )
    name = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    storage_type = fields.Str(
        required=True,
        validate=validate.OneOf(["Ebs", FSX_LUSTRE, FSX_OPENZFS, FSX_ONTAP, "Efs"]),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    ebs_settings = fields.Nested(EbsSettingsSchema, metadata={"update_policy": UpdatePolicy.IGNORED})
    efs_settings = fields.Nested(EfsSettingsSchema, metadata={"update_policy": UpdatePolicy.IGNORED})
    fsx_lustre_settings = fields.Nested(FsxLustreSettingsSchema, metadata={"update_policy": UpdatePolicy.IGNORED})
    fsx_open_zfs_settings = fields.Nested(
        FsxOpenZfsSettingsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    fsx_ontap_settings = fields.Nested(FsxOntapSettingsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @validates_schema
    def no_coexist_storage_settings(self, data, **kwargs):
        """Validate that *_settings for different storage types do not co-exist."""
        if self.fields_coexist(
            data,
            ["ebs_settings", "efs_settings", "fsx_lustre_settings", "fsx_open_zfs_settings", "fsx_ontap_settings"],
            **kwargs,
        ):
            raise ValidationError("Multiple *Settings sections cannot be specified in the SharedStorage items.")

    @validates_schema
    def right_storage_settings(self, data, **kwargs):
        """Validate that *_settings param is associated to the right storage type."""
        for storage_type, settings in [
            ("Ebs", "ebs_settings"),
            ("Efs", "efs_settings"),
            (FSX_LUSTRE, "fsx_lustre_settings"),
            (FSX_OPENZFS, "fsx_open_zfs_settings"),
            (FSX_ONTAP, "fsx_ontap_settings"),
        ]:
            # Verify the settings section is associated to the right storage type
            if data.get(settings, None) and storage_type != data.get("storage_type"):
                raise ValidationError(
                    "SharedStorage > *Settings section is not appropriate to the "
                    f"StorageType {data.get('storage_type')}."
                )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate the right type of shared storage according to the child type (EBS vs EFS vs FsxLustre)."""
        storage_type = data.get("storage_type")
        shared_volume_attributes = {"mount_dir": data.get("mount_dir"), "name": data.get("name")}
        settings = (
            data.get("efs_settings", None)
            or data.get("ebs_settings", None)
            or data.get("fsx_lustre_settings", None)
            or data.get("fsx_open_zfs_settings", None)
            or data.get("fsx_ontap_settings", None)
        )
        if settings:
            shared_volume_attributes.update(**settings)
        if storage_type == "Efs":
            return SharedEfs(**shared_volume_attributes)
        elif storage_type == "Ebs":
            return SharedEbs(**shared_volume_attributes)
        elif storage_type == FSX_LUSTRE:
            return SharedFsxLustre(**shared_volume_attributes)
        elif storage_type == FSX_OPENZFS:
            return ExistingFsxOpenZfs(**shared_volume_attributes)
        elif storage_type == FSX_ONTAP:
            return ExistingFsxOntap(**shared_volume_attributes)
        return None

    @pre_dump
    def restore_child(self, data, **kwargs):
        """Restore back the child in the schema."""
        adapted_data = copy.deepcopy(data)
        # Move SharedXxx as a child to be automatically managed by marshmallow, see post_load action
        if adapted_data.shared_storage_type == "efs":
            storage_type = "efs"
        elif adapted_data.shared_storage_type == "fsx":
            mapping = {LUSTRE: "fsx_lustre", OPENZFS: "fsx_open_zfs", ONTAP: "fsx_ontap"}
            storage_type = mapping.get(adapted_data.file_system_type)
        else:  # "raid", "ebs"
            storage_type = "ebs"
        setattr(adapted_data, f"{storage_type}_settings", copy.copy(adapted_data))
        # Restore storage type attribute
        if adapted_data.shared_storage_type == "fsx":
            mapping = {LUSTRE: FSX_LUSTRE, OPENZFS: FSX_OPENZFS, ONTAP: FSX_ONTAP}
            adapted_data.storage_type = mapping.get(adapted_data.file_system_type)
        else:
            adapted_data.storage_type = storage_type.capitalize()
        return adapted_data

    @validates("mount_dir")
    def shared_dir_validator(self, value):
        """Validate that user is not specifying /NONE or NONE as shared_dir for any filesystem."""
        # FIXME: pcluster2 doesn't allow "^/?NONE$" mount dir to avoid an ambiguity in cookbook.
        #  We should change cookbook to solve the ambiguity and allow "^/?NONE$" for mount dir
        #  Cookbook location to be modified:
        #  https://github.com/aws/aws-parallelcluster-cookbook/blob/develop/recipes/head_node_base_config.rb#L51
        if re.match("^/?NONE$", value):
            raise ValidationError(f"{value} cannot be used as a shared directory")


# ---------------------- Networking ---------------------- #


class HeadNodeProxySchema(BaseSchema):
    """Represent the schema of proxy for the Head node."""

    http_proxy_address = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Proxy(**data)


class QueueProxySchema(BaseSchema):
    """Represent the schema of proxy for a queue."""

    http_proxy_address = fields.Str(metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Proxy(**data)


class BaseNetworkingSchema(BaseSchema):
    """Represent the schema of common networking parameters used by head and compute nodes."""

    additional_security_groups = fields.List(
        fields.Str(validate=get_field_validator("security_group_id")),
        metadata={"update_policy": UpdatePolicy.SUPPORTED},
    )
    security_groups = fields.List(
        fields.Str(validate=get_field_validator("security_group_id")),
        metadata={"update_policy": UpdatePolicy.SUPPORTED},
    )

    @validates_schema
    def no_coexist_security_groups(self, data, **kwargs):
        """Validate that security_groups and additional_security_groups do not co-exist."""
        if self.fields_coexist(data, ["security_groups", "additional_security_groups"], **kwargs):
            raise ValidationError("SecurityGroups and AdditionalSecurityGroups can not be configured together.")


class HeadNodeNetworkingSchema(BaseNetworkingSchema):
    """Represent the schema of the Networking, child of the HeadNode."""

    subnet_id = fields.Str(
        required=True, validate=get_field_validator("subnet_id"), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    elastic_ip = fields.Raw(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    proxy = fields.Nested(HeadNodeProxySchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return HeadNodeNetworking(**data)


class PlacementGroupSchema(BaseSchema):
    """Represent the schema of placement group."""

    enabled = fields.Bool(metadata={"update_policy": UpdatePolicy.MANAGED_PLACEMENT_GROUP})
    id = fields.Str(metadata={"update_policy": UpdatePolicy.MANAGED_PLACEMENT_GROUP})
    name = fields.Str(metadata={"update_policy": UpdatePolicy.MANAGED_PLACEMENT_GROUP})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return PlacementGroup(**data)


class QueueNetworkingSchema(BaseNetworkingSchema):
    """Represent the schema of the Networking, child of Queue."""

    subnet_ids = fields.List(
        fields.Str(validate=get_field_validator("subnet_id")),
        required=True,
        validate=validate.Length(equal=1),
        metadata={"update_policy": UpdatePolicy.MANAGED_FSX},
    )
    assign_public_ip = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})


class SlurmQueueNetworkingSchema(QueueNetworkingSchema):
    """Represent the schema of the Networking, child of slurm Queue."""

    placement_group = fields.Nested(
        PlacementGroupSchema, metadata={"update_policy": UpdatePolicy.MANAGED_PLACEMENT_GROUP}
    )
    proxy = fields.Nested(QueueProxySchema, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SlurmQueueNetworking(**data)


class AwsBatchQueueNetworkingSchema(QueueNetworkingSchema):
    """Represent the schema of the Networking, child of aws batch Queue."""

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AwsBatchQueueNetworking(**data)


class SchedulerPluginQueueNetworkingSchema(SlurmQueueNetworkingSchema):
    """Represent the schema of the Networking, child of Scheduler Plugin Queue."""

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginQueueNetworking(**data)


class SshSchema(BaseSchema):
    """Represent the schema of the SSH."""

    key_name = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    allowed_ips = fields.Str(validate=get_field_validator("cidr"), metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Ssh(**data)


class DcvSchema(BaseSchema):
    """Represent the schema of DCV."""

    enabled = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    port = fields.Int(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    allowed_ips = fields.Str(validate=get_field_validator("cidr"), metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Dcv(**data)


class EfaSchema(BaseSchema):
    """Represent the schema of EFA for a Compute Resource."""

    enabled = fields.Bool(metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})
    gdr_support = fields.Bool(metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Efa(**data)


# ---------------------- Monitoring ---------------------- #


class CloudWatchLogsSchema(BaseSchema):
    """Represent the schema of the CloudWatchLogs section."""

    enabled = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    retention_in_days = fields.Int(
        validate=validate.OneOf([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653]),
        metadata={"update_policy": UpdatePolicy.SUPPORTED},
    )
    deletion_policy = fields.Str(
        validate=validate.OneOf(DELETION_POLICIES), metadata={"update_policy": UpdatePolicy.SUPPORTED}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CloudWatchLogs(**data)


class CloudWatchDashboardsSchema(BaseSchema):
    """Represent the schema of the CloudWatchDashboards section."""

    enabled = fields.Bool(metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CloudWatchDashboards(**data)


class LogsSchema(BaseSchema):
    """Represent the schema of the Logs section."""

    cloud_watch = fields.Nested(CloudWatchLogsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Logs(**data)


class DashboardsSchema(BaseSchema):
    """Represent the schema of the Dashboards section."""

    cloud_watch = fields.Nested(CloudWatchDashboardsSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Dashboards(**data)


class MonitoringSchema(BaseSchema):
    """Represent the schema of the Monitoring section."""

    detailed_monitoring = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    logs = fields.Nested(LogsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    dashboards = fields.Nested(DashboardsSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Monitoring(**data)


# ---------------------- Others ---------------------- #


class RolesSchema(BaseSchema):
    """Represent the schema of roles."""

    lambda_functions_role = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Roles(**data)


class S3AccessSchema(BaseSchema):
    """Represent the schema of S3 access."""

    bucket_name = fields.Str(
        required=True,
        metadata={"update_policy": UpdatePolicy.SUPPORTED},
        validate=validate.Regexp(r"^[\*a-z0-9\-\.]+$"),
    )
    key_name = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    enable_write_access = fields.Bool(metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return S3Access(**data)


class ClusterIamSchema(BaseSchema):
    """Represent the schema of IAM for Cluster."""

    roles = fields.Nested(RolesSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    permissions_boundary = fields.Str(
        metadata={"update_policy": UpdatePolicy.SUPPORTED}, validate=validate.Regexp("^arn:.*:policy/")
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ClusterIam(**data)


class IamSchema(BaseSchema):
    """Common schema of IAM for HeadNode and Queue."""

    instance_role = fields.Str(
        metadata={"update_policy": UpdatePolicy.SUPPORTED}, validate=validate.Regexp("^arn:.*:role/")
    )
    s3_access = fields.Nested(
        S3AccessSchema, many=True, metadata={"update_policy": UpdatePolicy.SUPPORTED, "update_key": "BucketName"}
    )
    additional_iam_policies = fields.Nested(
        AdditionalIamPolicySchema, many=True, metadata={"update_policy": UpdatePolicy.SUPPORTED, "update_key": "Policy"}
    )

    @validates_schema
    def no_coexist_role_policies(self, data, **kwargs):
        """Validate that instance_role, instance_profile or additional_iam_policies do not co-exist."""
        if self.fields_coexist(data, ["instance_role", "instance_profile", "additional_iam_policies"], **kwargs):
            raise ValidationError(
                "InstanceProfile, InstanceRole or AdditionalIamPolicies can not be configured together."
            )

    @validates_schema
    def no_coexist_s3_access(self, data, **kwargs):
        """Validate that instance_role, instance_profile or additional_iam_policies do not co-exist."""
        if self.fields_coexist(data, ["instance_role", "s3_access"], **kwargs):
            raise ValidationError("S3Access can not be configured when InstanceRole is set.")
        if self.fields_coexist(data, ["instance_profile", "s3_access"], **kwargs):
            raise ValidationError("S3Access can not be configured when InstanceProfile is set.")

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Iam(**data)


class HeadNodeIamSchema(IamSchema):
    """Represent the schema of IAM for HeadNode."""

    instance_profile = fields.Str(
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED}, validate=validate.Regexp("^arn:.*:instance-profile/")
    )


class QueueIamSchema(IamSchema):
    """Represent the schema of IAM for Queue."""

    instance_profile = fields.Str(
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP},
        validate=validate.Regexp("^arn:.*:instance-profile/"),
    )


class ImdsSchema(BaseSchema):
    """Represent the schema of IMDS for HeadNode."""

    secured = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Imds(**data)


class IntelSoftwareSchema(BaseSchema):
    """Represent the schema of additional packages."""

    intel_hpc_platform = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return IntelSoftware(**data)


class AdditionalPackagesSchema(BaseSchema):
    """Represent the schema of additional packages."""

    intel_software = fields.Nested(IntelSoftwareSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AdditionalPackages(**data)


class AmiSearchFiltersSchema(BaseSchema):
    """Represent the schema of the AmiSearchFilters section."""

    tags = fields.Nested(
        TagSchema, many=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED, "update_key": "Key"}
    )
    owner = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AmiSearchFilters(**data)


class TimeoutsSchema(BaseSchema):
    """Represent the schema of the Timeouts section."""

    head_node_bootstrap_timeout = fields.Int(
        validate=validate.Range(min=1), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    compute_node_bootstrap_timeout = fields.Int(
        validate=validate.Range(min=1), metadata={"update_policy": UpdatePolicy.SUPPORTED}
    )

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Timeouts(**data)


class CapacityReservationTargetSchema(BaseSchema):
    """Represent the schema of the CapacityReservationTarget section."""

    capacity_reservation_id = fields.Str(metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})
    capacity_reservation_resource_group_arn = fields.Str(metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CapacityReservationTarget(**data)

    @validates_schema
    def no_coexist_id_and_group_arn(self, data, **kwargs):
        """Validate that 'capacity_reservation_id' and 'capacity_reservation_resource_group_arn' do not co-exist."""
        if self.fields_coexist(
            data,
            ["capacity_reservation_id", "capacity_reservation_resource_group_arn"],
            one_required=True,
            **kwargs,
        ):
            raise ValidationError(
                "A Capacity Reservation Target needs to specify either Capacity Reservation ID or "
                "Capacity Reservation Resource Group ARN."
            )


class ClusterDevSettingsSchema(BaseDevSettingsSchema):
    """Represent the schema of Dev Setting."""

    cluster_template = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    ami_search_filters = fields.Nested(AmiSearchFiltersSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    instance_types_data = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    timeouts = fields.Nested(TimeoutsSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ClusterDevSettings(**data)


# ---------------------- Node and Cluster Schema ---------------------- #


class ImageSchema(BaseSchema):
    """Represent the schema of the Image."""

    os = fields.Str(
        required=True, validate=validate.OneOf(SUPPORTED_OSES), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    custom_ami = fields.Str(
        validate=validate.Regexp(r"^ami-[0-9a-z]{8}$|^ami-[0-9a-z]{17}$"),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Image(**data)


class HeadNodeImageSchema(BaseSchema):
    """Represent the schema of the HeadNode Image."""

    custom_ami = fields.Str(
        validate=validate.Regexp(r"^ami-[0-9a-z]{8}$|^ami-[0-9a-z]{17}$"),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return HeadNodeImage(**data)


class QueueImageSchema(BaseSchema):
    """Represent the schema of the Queue Image."""

    custom_ami = fields.Str(
        validate=validate.Regexp(r"^ami-[0-9a-z]{8}$|^ami-[0-9a-z]{17}$"),
        metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return QueueImage(**data)


class HeadNodeCustomActionSchema(BaseSchema):
    """Represent the schema of the custom action."""

    script = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    args = fields.List(fields.Str(), metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CustomAction(**data)


class HeadNodeCustomActionsSchema(BaseSchema):
    """Represent the schema for all available custom actions."""

    on_node_start = fields.Nested(HeadNodeCustomActionSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    on_node_configured = fields.Nested(HeadNodeCustomActionSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CustomActions(**data)


class QueueCustomActionSchema(BaseSchema):
    """Represent the schema of the custom action."""

    script = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})
    args = fields.List(fields.Str(), metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CustomAction(**data)


class QueueCustomActionsSchema(BaseSchema):
    """Represent the schema for all available custom actions."""

    on_node_start = fields.Nested(
        QueueCustomActionSchema, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY}
    )
    on_node_configured = fields.Nested(
        QueueCustomActionSchema, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CustomActions(**data)


class InstanceTypeSchema(BaseSchema):
    """Schema of a compute resource that supports a pool of instance types."""

    instance_type = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return FlexibleInstanceType(**data)


class HeadNodeSchema(BaseSchema):
    """Represent the schema of the HeadNode."""

    instance_type = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    disable_simultaneous_multithreading = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    networking = fields.Nested(
        HeadNodeNetworkingSchema, required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    ssh = fields.Nested(SshSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    local_storage = fields.Nested(HeadNodeStorageSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    dcv = fields.Nested(DcvSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    custom_actions = fields.Nested(HeadNodeCustomActionsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    iam = fields.Nested(HeadNodeIamSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    imds = fields.Nested(ImdsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    image = fields.Nested(HeadNodeImageSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return HeadNode(**data)


class _ComputeResourceSchema(BaseSchema):
    """Represent the schema of the ComputeResource."""

    name = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})


class SlurmComputeResourceNetworkingSchema(BaseSchema):
    """Represent the Networking schema of the Slurm ComputeResource."""

    placement_group = fields.Nested(
        PlacementGroupSchema, metadata={"update_policy": UpdatePolicy.MANAGED_PLACEMENT_GROUP}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SlurmComputeResourceNetworking(**data)


class SlurmComputeResourceSchema(_ComputeResourceSchema):
    """Represent the schema of the Slurm ComputeResource."""

    instance_type = fields.Str(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    instances = fields.Nested(
        InstanceTypeSchema,
        many=True,
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP_ON_REMOVE, "update_key": "InstanceType"},
    )
    max_count = fields.Int(validate=validate.Range(min=1), metadata={"update_policy": UpdatePolicy.MAX_COUNT})
    min_count = fields.Int(validate=validate.Range(min=0), metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    spot_price = fields.Float(
        validate=validate.Range(min=0), metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY}
    )
    efa = fields.Nested(EfaSchema, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})
    disable_simultaneous_multithreading = fields.Bool(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    schedulable_memory = fields.Int(metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})
    capacity_reservation_target = fields.Nested(
        CapacityReservationTargetSchema, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY}
    )
    networking = fields.Nested(
        SlurmComputeResourceNetworkingSchema, metadata={"update_policy": UpdatePolicy.MANAGED_PLACEMENT_GROUP}
    )

    @validates_schema
    def no_coexist_instance_type_flexibility(self, data, **kwargs):
        """Validate that 'instance_type' and 'instances' do not co-exist."""
        if self.fields_coexist(
            data,
            ["instance_type", "instances"],
            one_required=True,
            **kwargs,
        ):
            raise ValidationError("A Compute Resource needs to specify either InstanceType or Instances.")

    @validates("instances")
    def no_duplicate_instance_types(self, flexible_instance_types: List[FlexibleInstanceType]):
        """Verify that there are no duplicates in Instances."""
        instance_types = set()
        for flexible_instance_type in flexible_instance_types:
            instance_type_name = flexible_instance_type.instance_type
            if instance_type_name in instance_types:
                raise ValidationError(
                    f"Duplicate instance type ({instance_type_name}) detected. Instances should not have "
                    f"duplicate instance types. "
                )
            instance_types.add(instance_type_name)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        if data.get("instances"):
            return SlurmFlexibleComputeResource(**data)
        return SlurmComputeResource(**data)


class AwsBatchComputeResourceSchema(_ComputeResourceSchema):
    """Represent the schema of the Batch ComputeResource."""

    instance_types = fields.List(
        fields.Str(), required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP}
    )
    max_vcpus = fields.Int(
        data_key="MaxvCpus",
        validate=validate.Range(min=1),
        metadata={"update_policy": UpdatePolicy.AWSBATCH_CE_MAX_RESIZE},
    )
    min_vcpus = fields.Int(
        data_key="MinvCpus", validate=validate.Range(min=0), metadata={"update_policy": UpdatePolicy.SUPPORTED}
    )
    desired_vcpus = fields.Int(
        data_key="DesiredvCpus", validate=validate.Range(min=0), metadata={"update_policy": UpdatePolicy.IGNORED}
    )
    spot_bid_percentage = fields.Int(
        validate=validate.Range(min=0, max=100, min_inclusive=False), metadata={"update_policy": UpdatePolicy.SUPPORTED}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AwsBatchComputeResource(**data)


class SchedulerPluginComputeResourceSchema(SlurmComputeResourceSchema):
    """Represent the schema of the Scheduler Plugin ComputeResource."""

    custom_settings = fields.Dict(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginComputeResource(**data)


class ComputeSettingsSchema(BaseSchema):
    """Represent the schema of the compute_settings schedulers queues."""

    local_storage = fields.Nested(QueueStorageSchema, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ComputeSettings(**data)


class BaseQueueSchema(BaseSchema):
    """Represent the schema of the attributes in common between all the schedulers queues."""

    name = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    capacity_type = fields.Str(
        validate=validate.OneOf([event.value for event in CapacityType]),
        metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY},
    )


class _CommonQueueSchema(BaseQueueSchema):
    """Represent the schema of common part between Slurm and Scheduler Plugin Queue."""

    compute_settings = fields.Nested(
        ComputeSettingsSchema, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY}
    )
    custom_actions = fields.Nested(
        QueueCustomActionsSchema, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY}
    )
    iam = fields.Nested(QueueIamSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    image = fields.Nested(QueueImageSchema, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})
    capacity_reservation_target = fields.Nested(
        CapacityReservationTargetSchema, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY}
    )


class SlurmQueueSchema(_CommonQueueSchema):
    """Represent the schema of a Slurm Queue."""

    allocation_strategy = fields.Str(
        validate=validate.OneOf([strategy.value for strategy in AllocationStrategy]),
        metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY},
    )
    compute_resources = fields.Nested(
        SlurmComputeResourceSchema,
        many=True,
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP_ON_REMOVE, "update_key": "Name"},
    )
    networking = fields.Nested(
        SlurmQueueNetworkingSchema, required=True, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SlurmQueue(**data)


class AwsBatchQueueSchema(BaseQueueSchema):
    """Represent the schema of a Batch Queue."""

    compute_resources = fields.Nested(
        AwsBatchComputeResourceSchema,
        many=True,
        validate=validate.Length(equal=1),
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP, "update_key": "Name"},
    )
    networking = fields.Nested(
        AwsBatchQueueNetworkingSchema, required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AwsBatchQueue(**data)


class SchedulerPluginQueueSchema(_CommonQueueSchema):
    """Represent the schema of a Scheduler Plugin Queue."""

    compute_resources = fields.Nested(
        SchedulerPluginComputeResourceSchema,
        many=True,
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP, "update_key": "Name"},
    )
    networking = fields.Nested(
        SchedulerPluginQueueNetworkingSchema, required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP}
    )
    custom_settings = fields.Dict(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginQueue(**data)


class DnsSchema(BaseSchema):
    """Represent the schema of Dns Settings."""

    disable_managed_dns = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    hosted_zone_id = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    use_ec2_hostnames = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Dns(**data)


class DatabaseSchema(BaseSchema):
    """Represent the schema of the DirectoryService."""

    uri = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    user_name = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    password_secret_arn = fields.Str(
        required=True,
        validate=validate.Regexp(r"^arn:.*:secret"),
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Database(**data)


class SlurmSettingsSchema(BaseSchema):
    """Represent the schema of the Scheduling Settings."""

    scaledown_idletime = fields.Int(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    dns = fields.Nested(DnsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    queue_update_strategy = fields.Str(
        validate=validate.OneOf([strategy.value for strategy in QueueUpdateStrategy]),
        metadata={"update_policy": UpdatePolicy.IGNORED},
    )
    enable_memory_based_scheduling = fields.Bool(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    database = fields.Nested(DatabaseSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SlurmSettings(**data)


class AwsBatchSettingsSchema(BaseSchema):
    """Represent the schema of the AwsBatch Scheduling Settings."""

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AwsBatchSettings(**data)


class SchedulerPluginSupportedDistrosSchema(BaseSchema):
    """Represent the schema for SupportedDistros in a Scheduler Plugin."""

    x86 = fields.List(fields.Str(), metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    arm64 = fields.List(fields.Str(), metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginSupportedDistros(**data)


class SchedulerPluginQueueConstraintsSchema(BaseSchema):
    """Represent the schema for QueueConstraints in a Scheduler Plugin."""

    max_count = fields.Int(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginQueueConstraints(**data)


class SchedulerPluginComputeResourceConstraintsSchema(BaseSchema):
    """Represent the schema for ComputeResourceConstraints in a Scheduler Plugin."""

    max_count = fields.Int(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginComputeResourceConstraints(**data)


class SchedulerPluginRequirementsSchema(BaseSchema):
    """Represent the schema for Requirements in a Scheduler Plugin."""

    supported_distros = fields.Nested(
        SchedulerPluginSupportedDistrosSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    supported_regions = fields.List(fields.Str(), metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    queue_constraints = fields.Nested(
        SchedulerPluginQueueConstraintsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    compute_resource_constraints = fields.Nested(
        SchedulerPluginComputeResourceConstraintsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    requires_sudo_privileges = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    supports_cluster_update = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    supported_parallel_cluster_versions = fields.Str(
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
        validate=validate.Regexp(
            r"^((>|<|>=|<=)?[0-9]+\.[0-9]+\.[0-9]+([a-z][0-9]+)?,\s*)*(>|<|>=|<=)?[0-9]+\.[0-9]+\.[0-9]+([a-z][0-9]+)?$"
        ),
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginRequirements(**data)


class SchedulerPluginCloudFormationClusterInfrastructureSchema(BaseSchema):
    """Represent the CloudFormation section of the Scheduler Plugin ClusterInfrastructure schema."""

    template = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    s3_bucket_owner = fields.Str(
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED}, validate=validate.Regexp(r"^\d{12}$")
    )
    checksum = fields.Str(
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED}, validate=validate.Regexp(r"^[A-Fa-f0-9]{64}$")
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginCloudFormationInfrastructure(**data)


class SchedulerPluginClusterInfrastructureSchema(BaseSchema):
    """Represent the schema for ClusterInfrastructure schema in a Scheduler Plugin."""

    cloud_formation = fields.Nested(
        SchedulerPluginCloudFormationClusterInfrastructureSchema,
        required=True,
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginClusterInfrastructure(**data)


class SchedulerPluginClusterSharedArtifactSchema(BaseSchema):
    """Represent the schema for Cluster Shared Artifact in a Scheduler Plugin."""

    source = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    s3_bucket_owner = fields.Str(
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED}, validate=validate.Regexp(r"^\d{12}$")
    )
    checksum = fields.Str(
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED}, validate=validate.Regexp(r"^[A-Fa-f0-9]{64}$")
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginClusterSharedArtifact(**data)


class SchedulerPluginResourcesSchema(BaseSchema):
    """Represent the schema for Plugin Resouces in a Scheduler Plugin."""

    cluster_shared_artifacts = fields.Nested(
        SchedulerPluginClusterSharedArtifactSchema,
        many=True,
        required=True,
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED, "update_key": "Source"},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginPluginResources(**data)


class SchedulerPluginExecuteCommandSchema(BaseSchema):
    """Represent the schema for ExecuteCommand in a Scheduler Plugin."""

    command = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginExecuteCommand(**data)


class SchedulerPluginEventSchema(BaseSchema):
    """Represent the schema for Event in a Scheduler Plugin."""

    execute_command = fields.Nested(
        SchedulerPluginExecuteCommandSchema, required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginEvent(**data)


class SchedulerPluginEventsSchema(BaseSchema):
    """Represent the schema for Events in a Scheduler Plugin."""

    head_init = fields.Nested(SchedulerPluginEventSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    head_configure = fields.Nested(SchedulerPluginEventSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    head_finalize = fields.Nested(SchedulerPluginEventSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    compute_init = fields.Nested(SchedulerPluginEventSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    compute_configure = fields.Nested(SchedulerPluginEventSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    compute_finalize = fields.Nested(SchedulerPluginEventSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    head_cluster_update = fields.Nested(
        SchedulerPluginEventSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    head_compute_fleet_update = fields.Nested(
        SchedulerPluginEventSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginEvents(**data)


class SchedulerPluginFileSchema(BaseSchema):
    """Represent the schema of the Scheduler Plugin."""

    file_path = fields.Str(
        required=True, validate=get_field_validator("file_path"), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    timestamp_format = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    node_type = fields.Str(
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED}, validate=validate.OneOf(["HEAD", "COMPUTE", "ALL"])
    )
    log_stream_name = fields.Str(
        required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}, validate=validate.Regexp(r"^[^:*]*$")
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginFile(**data)


class SchedulerPluginLogsSchema(BaseSchema):
    """Represent the schema of the Scheduler Plugin Logs."""

    files = fields.Nested(
        SchedulerPluginFileSchema,
        required=True,
        many=True,
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED, "update_key": "FilePath"},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginLogs(**data)


class SchedulerPluginMonitoringSchema(BaseSchema):
    """Represent the schema of the Scheduler plugin Monitoring."""

    logs = fields.Nested(SchedulerPluginLogsSchema, required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginMonitoring(**data)


class SudoerConfigurationSchema(BaseSchema):
    """Represent the SudoerConfiguration for scheduler plugin SystemUsers declared in the SchedulerDefinition."""

    commands = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    run_as = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SudoerConfiguration(**data)


class SchedulerPluginUserSchema(BaseSchema):
    """Represent the schema of the Scheduler Plugin."""

    name = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    enable_imds = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    sudoer_configuration = fields.Nested(
        SudoerConfigurationSchema, many=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED, "update_key": "Name"}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginUser(**data)


class SchedulerPluginDefinitionSchema(BaseSchema):
    """Represent the schema of the Scheduler Plugin SchedulerDefinition."""

    plugin_interface_version = fields.Str(
        required=True,
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
        validate=validate.Regexp(r"^[0-9]+\.[0-9]+$"),
    )
    metadata = fields.Dict(metadata={"update_policy": UpdatePolicy.UNSUPPORTED}, required=True)
    requirements = fields.Nested(
        SchedulerPluginRequirementsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    cluster_infrastructure = fields.Nested(
        SchedulerPluginClusterInfrastructureSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    plugin_resources = fields.Nested(
        SchedulerPluginResourcesSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    events = fields.Nested(
        SchedulerPluginEventsSchema, required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    monitoring = fields.Nested(SchedulerPluginMonitoringSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    system_users = fields.Nested(
        SchedulerPluginUserSchema,
        many=True,
        validate=validate.Length(max=SCHEDULER_PLUGIN_MAX_NUMBER_OF_USERS),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED, "update_key": "Name"},
    )
    tags = fields.Nested(
        TagSchema, many=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED, "update_key": "Key"}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginDefinition(**data)

    @validates("metadata")
    def validate_metadata(self, value):
        """Validate metadata contains fieds 'name' and 'version'."""
        for key in ["Name", "Version"]:
            if key not in value.keys():
                raise ValidationError(f"{key} is required for scheduler plugin Metadata.")


class SchedulerPluginSettingsSchema(BaseSchema):
    """Represent the schema of the Scheduling Settings."""

    scheduler_definition = fields.Nested(
        SchedulerPluginDefinitionSchema, required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    grant_sudo_privileges = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    custom_settings = fields.Dict(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    scheduler_definition_s3_bucket_owner = fields.Str(
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED}, validate=validate.Regexp(r"^\d{12}$")
    )
    scheduler_definition_checksum = fields.Str(
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED}, validate=validate.Regexp(r"^[A-Fa-f0-9]{64}$")
    )

    def _verify_checksum(self, file_content, original_definition, expected_checksum):
        if expected_checksum:
            actual_checksum = hashlib.sha256(file_content.encode()).hexdigest()
            if actual_checksum != expected_checksum:
                raise ValidationError(
                    f"Error when validating SchedulerDefinition '{original_definition}': "
                    f"checksum ({actual_checksum}) does not match expected one ({expected_checksum})"
                )

    def _fetch_scheduler_definition_from_s3(self, original_scheduler_definition, s3_bucket_owner):
        try:
            bucket_parsing_result = parse_bucket_url(original_scheduler_definition)
            result = AWSApi.instance().s3.get_object(
                bucket_name=bucket_parsing_result["bucket_name"],
                key=bucket_parsing_result["object_key"],
                expected_bucket_owner=s3_bucket_owner,
            )
            scheduler_definition = result["Body"].read().decode("utf-8")
            return scheduler_definition
        except AWSClientError as e:
            error_message = (
                f"Error while downloading scheduler definition from {original_scheduler_definition}: {str(e)}"
            )
            if s3_bucket_owner and e.error_code == "AccessDenied":
                error_message = (
                    f"{error_message}. This can be due to bucket owner not matching the expected "
                    f"one '{s3_bucket_owner}'"
                )
            raise ValidationError(error_message) from e
        except Exception as e:
            raise ValidationError(
                f"Error while downloading scheduler definition from {original_scheduler_definition}: {str(e)}"
            ) from e

    def _fetch_scheduler_definition_from_https(self, original_scheduler_definition):
        try:
            with urlopen(original_scheduler_definition) as f:  # nosec nosemgrep
                scheduler_definition = f.read().decode("utf-8")
                return scheduler_definition
        except Exception:
            error_message = (
                f"Error while downloading scheduler definition from {original_scheduler_definition}: "
                "The provided URL is invalid or unavailable."
            )
            raise ValidationError(error_message)

    def _validate_scheduler_definition_url(self, original_scheduler_definition, s3_bucket_owner):
        """Validate SchedulerDefinition url is valid."""
        if not original_scheduler_definition.startswith("s3") and not original_scheduler_definition.startswith("https"):
            raise ValidationError(
                f"Error while downloading scheduler definition from {original_scheduler_definition}: The provided value"
                " for SchedulerDefinition is invalid. You can specify this as an S3 URL, HTTPS URL or as an inline "
                "YAML object."
            )
        if original_scheduler_definition.startswith("https") and s3_bucket_owner:
            raise ValidationError(
                f"Error while downloading scheduler definition from {original_scheduler_definition}: "
                "SchedulerDefinitionS3BucketOwner can only be specified when SchedulerDefinition is S3 URL."
            )

    def _fetch_scheduler_definition_from_url(
        self, original_scheduler_definition, s3_bucket_owner, scheduler_definition_checksum, data
    ):
        LOGGER.info("Downloading scheduler plugin definition from %s", original_scheduler_definition)
        if original_scheduler_definition.startswith("s3"):
            scheduler_definition = self._fetch_scheduler_definition_from_s3(
                original_scheduler_definition, s3_bucket_owner
            )
        elif original_scheduler_definition.startswith("https"):
            scheduler_definition = self._fetch_scheduler_definition_from_https(original_scheduler_definition)

        self._verify_checksum(scheduler_definition, original_scheduler_definition, scheduler_definition_checksum)

        LOGGER.info("Using the following scheduler plugin definition:\n%s", scheduler_definition)
        try:
            data["SchedulerDefinition"] = yaml_load(scheduler_definition)
        except YAMLError as e:
            raise ValidationError(
                f"The retrieved SchedulerDefinition ({original_scheduler_definition}) is not a valid YAML."
            ) from e

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SchedulerPluginSettings(**data)

    @pre_load
    def fetch_scheduler_definition(self, data, **kwargs):
        """Fetch scheduler definition if it is s3 or https url."""
        original_scheduler_definition = data["SchedulerDefinition"]
        s3_bucket_owner = data.get("SchedulerDefinitionS3BucketOwner", None)
        scheduler_definition_checksum = data.get("SchedulerDefinitionChecksum", None)
        if isinstance(original_scheduler_definition, str):
            self._validate_scheduler_definition_url(original_scheduler_definition, s3_bucket_owner)
            self._fetch_scheduler_definition_from_url(
                original_scheduler_definition, s3_bucket_owner, scheduler_definition_checksum, data
            )
        elif s3_bucket_owner or scheduler_definition_checksum:
            raise ValidationError(
                "SchedulerDefinitionS3BucketOwner or SchedulerDefinitionChecksum can only specified when "
                "SchedulerDefinition is a URL."
            )
        return data


class SchedulingSchema(BaseSchema):
    """Represent the schema of the Scheduling."""

    scheduler = fields.Str(
        required=True,
        validate=validate.OneOf(["slurm", "awsbatch", "plugin"]),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    # Slurm schema
    slurm_settings = fields.Nested(SlurmSettingsSchema, metadata={"update_policy": UpdatePolicy.IGNORED})
    slurm_queues = fields.Nested(
        SlurmQueueSchema,
        many=True,
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP_ON_REMOVE, "update_key": "Name"},
    )
    # Awsbatch schema:
    aws_batch_queues = fields.Nested(
        AwsBatchQueueSchema,
        many=True,
        validate=validate.Length(equal=1),
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP, "update_key": "Name"},
    )
    aws_batch_settings = fields.Nested(
        AwsBatchSettingsSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP}
    )
    # Scheduler Plugin
    scheduler_settings = fields.Nested(
        SchedulerPluginSettingsSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP}
    )
    scheduler_queues = fields.Nested(
        SchedulerPluginQueueSchema,
        many=True,
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP, "update_key": "Name"},
    )

    @validates_schema
    def no_coexist_schedulers(self, data, **kwargs):
        """Validate that *_settings and *_queues for different schedulers do not co-exist."""
        scheduler = data.get("scheduler")
        if self.fields_coexist(data, ["aws_batch_settings", "slurm_settings", "scheduler_settings"], **kwargs):
            raise ValidationError("Multiple *Settings sections cannot be specified in the Scheduling section.")
        if self.fields_coexist(
            data, ["aws_batch_queues", "slurm_queues", "scheduler_queues"], one_required=True, **kwargs
        ):
            if scheduler == "awsbatch":
                scheduler_prefix = "AwsBatch"
            elif scheduler == "plugin":
                scheduler_prefix = "Scheduler"
            else:
                scheduler_prefix = scheduler.capitalize()
            raise ValidationError(f"{scheduler_prefix}Queues section must be specified in the Scheduling section.")

    @validates_schema
    def right_scheduler_schema(self, data, **kwargs):
        """Validate that *_settings field is associated to the right scheduler."""
        for scheduler, settings, queues in [
            ("awsbatch", "aws_batch_settings", "aws_batch_queues"),
            ("slurm", "slurm_settings", "slurm_queues"),
            ("plugin", "scheduler_settings", "scheduler_queues"),
        ]:
            # Verify the settings section is associated to the right scheduler type
            configured_scheduler = data.get("scheduler")
            if settings in data and scheduler != configured_scheduler:
                raise ValidationError(
                    f"Scheduling > *Settings section is not appropriate to the Scheduler: {configured_scheduler}."
                )
            if queues in data and scheduler != configured_scheduler:
                raise ValidationError(
                    f"Scheduling > *Queues section is not appropriate to the Scheduler: {configured_scheduler}."
                )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate the right type of scheduling according to the child type (Slurm vs AwsBatch vs Custom)."""
        scheduler = data.get("scheduler")
        if scheduler == "slurm":
            return SlurmScheduling(queues=data.get("slurm_queues"), settings=data.get("slurm_settings", None))
        if scheduler == "plugin":
            return SchedulerPluginScheduling(
                queues=data.get("scheduler_queues"), settings=data.get("scheduler_settings", None)
            )
        if scheduler == "awsbatch":
            return AwsBatchScheduling(
                queues=data.get("aws_batch_queues"), settings=data.get("aws_batch_settings", None)
            )
        return None

    @pre_dump
    def restore_child(self, data, **kwargs):
        """Restore back the child in the schema, see post_load action."""
        adapted_data = copy.deepcopy(data)
        if adapted_data.scheduler == "awsbatch":
            scheduler_prefix = "aws_batch"
        elif adapted_data.scheduler == "plugin":
            scheduler_prefix = "scheduler"
        else:
            scheduler_prefix = adapted_data.scheduler
        setattr(adapted_data, f"{scheduler_prefix}_queues", copy.copy(getattr(adapted_data, "queues", None)))
        setattr(adapted_data, f"{scheduler_prefix}_settings", copy.copy(getattr(adapted_data, "settings", None)))
        return adapted_data


class DirectoryServiceSchema(BaseSchema):
    """Represent the schema of the DirectoryService."""

    domain_name = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    domain_addr = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    password_secret_arn = fields.Str(
        required=True,
        validate=validate.Regexp(r"^arn:.*:secret"),
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP},
    )
    domain_read_only_user = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    ldap_tls_ca_cert = fields.Str(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    ldap_tls_req_cert = fields.Str(
        validate=validate.OneOf(["never", "allow", "try", "demand", "hard"]),
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP},
    )
    ldap_access_filter = fields.Str(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    generate_ssh_keys_for_users = fields.Bool(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    additional_sssd_configs = fields.Dict(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return DirectoryService(**data)


class ClusterSchema(BaseSchema):
    """Represent the schema of the Cluster."""

    image = fields.Nested(ImageSchema, required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    head_node = fields.Nested(HeadNodeSchema, required=True, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    scheduling = fields.Nested(SchedulingSchema, required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    shared_storage = fields.Nested(
        SharedStorageSchema,
        many=True,
        metadata={
            "update_policy": UpdatePolicy(UpdatePolicy.SHARED_STORAGE_UPDATE_POLICY),
            "update_key": "Name",
        },
    )

    monitoring = fields.Nested(MonitoringSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    additional_packages = fields.Nested(AdditionalPackagesSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    tags = fields.Nested(
        TagSchema, many=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED, "update_key": "Key"}
    )
    iam = fields.Nested(ClusterIamSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    directory_service = fields.Nested(
        DirectoryServiceSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP}
    )
    config_region = fields.Str(data_key="Region", metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    imds = fields.Nested(TopLevelImdsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    custom_s3_bucket = fields.Str(metadata={"update_policy": UpdatePolicy.READ_ONLY_RESOURCE_BUCKET})
    additional_resources = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    dev_settings = fields.Nested(ClusterDevSettingsSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})

    def __init__(self, cluster_name: str):
        super().__init__()
        self.cluster_name = cluster_name

    @validates("tags")
    def validate_tags(self, tags):
        """Validate tags."""
        validate_no_reserved_tag(tags)

    @validates_schema
    def no_settings_for_batch(self, data, **kwargs):
        """Ensure IntelSoftware and DirectoryService section is not included when AWS Batch is the scheduler."""
        scheduling = data.get("scheduling")
        if scheduling and scheduling.scheduler == "awsbatch":
            error_message = "The use of the {} configuration is not supported when using awsbatch as the scheduler."
            additional_packages = data.get("additional_packages")
            if additional_packages and additional_packages.intel_software.intel_hpc_platform:
                raise ValidationError(error_message.format("IntelSoftware"))
            if data.get("directory_service"):
                raise ValidationError(error_message.format("DirectoryService"))

    @post_load(pass_original=True)
    def make_resource(self, data, original_data, **kwargs):
        """Generate cluster according to the scheduler. Save original configuration."""
        scheduler = data.get("scheduling").scheduler
        if scheduler == "slurm":
            cluster = SlurmClusterConfig(cluster_name=self.cluster_name, **data)
        elif scheduler == "awsbatch":
            cluster = AwsBatchClusterConfig(cluster_name=self.cluster_name, **data)
        elif scheduler == "plugin":
            cluster = SchedulerPluginClusterConfig(cluster_name=self.cluster_name, **data)
        else:
            raise ValidationError(f"Unsupported scheduler {scheduler}.")

        cluster.source_config = original_data
        return cluster
