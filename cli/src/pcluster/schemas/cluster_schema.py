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
import logging
import re
from typing import List

from marshmallow import ValidationError, fields, post_load, pre_dump, validate, validates, validates_schema

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
    ExistingFsxFileCache,
    ExistingFsxOntap,
    ExistingFsxOpenZfs,
    FlexibleInstanceType,
    GpuHealthCheck,
    HeadNode,
    HeadNodeImage,
    HeadNodeNetworking,
    HeadNodeSsh,
    HealthChecks,
    Iam,
    Image,
    Imds,
    IntelSoftware,
    LocalStorage,
    LoginNodes,
    LoginNodesIam,
    LoginNodesImage,
    LoginNodesNetworking,
    LoginNodesPool,
    LoginNodesSsh,
    LogRotation,
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
    Timeouts,
)
from pcluster.config.common import BaseTag
from pcluster.config.update_policy import UpdatePolicy
from pcluster.constants import (
    DELETION_POLICIES,
    DELETION_POLICIES_WITH_SNAPSHOT,
    FILECACHE,
    FSX_FILE_CACHE,
    FSX_FILE_CACHE_ID_REGEX,
    FSX_LUSTRE,
    FSX_ONTAP,
    FSX_OPENZFS,
    FSX_VOLUME_ID_REGEX,
    IAM_INSTANCE_PROFILE_REGEX,
    IAM_POLICY_REGEX,
    IAM_ROLE_REGEX,
    LUSTRE,
    MAX_SLURM_NODE_PRIORITY,
    MIN_SLURM_NODE_PRIORITY,
    ONTAP,
    OPENZFS,
    PCLUSTER_AMI_ID_REGEX,
    SUPPORTED_OSES,
)
from pcluster.schemas.common_schema import (
    AdditionalIamPolicySchema,
    BaseDevSettingsSchema,
    BaseSchema,
    DeploymentSettingsSchema,
)
from pcluster.schemas.common_schema import ImdsSchema as TopLevelImdsSchema
from pcluster.schemas.common_schema import (
    TagSchema,
    get_field_validator,
    validate_no_duplicate_tag,
    validate_no_reserved_tag,
)
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
    encryption_in_transit = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    iam_authorization = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @validates_schema
    def validate_file_system_id_ignored_parameters(self, data, **kwargs):
        """Return errors for parameters in the Efs config section that would be ignored."""
        # If file_system_id is specified, all parameters are ignored.
        messages = []
        if data.get("file_system_id") is not None:
            for key in data:
                if key is not None and key not in ["encryption_in_transit", "iam_authorization", "file_system_id"]:
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


class FsxFileCacheSettingsSchema(BaseSchema):
    """Represent the FSX File Cache schema."""

    file_cache_id = fields.Str(
        required=True,
        validate=validate.Regexp(FSX_FILE_CACHE_ID_REGEX),
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
        validate=validate.OneOf(["Ebs", FSX_LUSTRE, FSX_OPENZFS, FSX_ONTAP, "Efs", FSX_FILE_CACHE]),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    ebs_settings = fields.Nested(EbsSettingsSchema, metadata={"update_policy": UpdatePolicy.IGNORED})
    efs_settings = fields.Nested(EfsSettingsSchema, metadata={"update_policy": UpdatePolicy.IGNORED})
    fsx_lustre_settings = fields.Nested(FsxLustreSettingsSchema, metadata={"update_policy": UpdatePolicy.IGNORED})
    fsx_open_zfs_settings = fields.Nested(
        FsxOpenZfsSettingsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    fsx_ontap_settings = fields.Nested(FsxOntapSettingsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    fsx_file_cache_settings = fields.Nested(
        FsxFileCacheSettingsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )

    @validates_schema
    def no_coexist_storage_settings(self, data, **kwargs):
        """Validate that *_settings for different storage types do not co-exist."""
        if self.fields_coexist(
            data,
            [
                "ebs_settings",
                "efs_settings",
                "fsx_lustre_settings",
                "fsx_open_zfs_settings",
                "fsx_ontap_settings",
                "fsx_file_cache_settings",
            ],
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
            (FSX_FILE_CACHE, "fsx_file_cache_settings"),
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
            or data.get("fsx_file_cache_settings", None)
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
        elif storage_type == FSX_FILE_CACHE:
            return ExistingFsxFileCache(**shared_volume_attributes)
        return None

    @pre_dump
    def restore_child(self, data, **kwargs):
        """Restore back the child in the schema."""
        adapted_data = copy.deepcopy(data)
        # Move SharedXxx as a child to be automatically managed by marshmallow, see post_load action
        if adapted_data.shared_storage_type == "efs":
            storage_type = "efs"
        elif adapted_data.shared_storage_type == "fsx":
            mapping = {
                LUSTRE: "fsx_lustre",
                OPENZFS: "fsx_open_zfs",
                ONTAP: "fsx_ontap",
                FILECACHE: "fsx_file_cache_settings",
            }
            storage_type = mapping.get(adapted_data.file_system_type)
        else:  # "raid", "ebs"
            storage_type = "ebs"
        setattr(adapted_data, f"{storage_type}_settings", copy.copy(adapted_data))
        # Restore storage type attribute
        if adapted_data.shared_storage_type == "fsx":
            mapping = {LUSTRE: FSX_LUSTRE, OPENZFS: FSX_OPENZFS, ONTAP: FSX_ONTAP, FILECACHE: FSX_FILE_CACHE}
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


class LoginNodeProxySchema(BaseSchema):
    """Represent the schema of proxy for a Login Node."""

    http_proxy_address = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Proxy(**data)


class BaseNetworkingSchema(BaseSchema):
    """Represent the schema of common networking parameters used by head, compute and login nodes."""

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

    assign_public_ip = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})


class SlurmQueueNetworkingSchema(QueueNetworkingSchema):
    """Represent the schema of the Networking, child of slurm Queue."""

    subnet_ids = fields.List(
        fields.Str(validate=get_field_validator("subnet_id")),
        required=True,
        validate=validate.Length(min=1),
        metadata={"update_policy": UpdatePolicy.MANAGED_FSX},
    )
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

    subnet_ids = fields.List(
        fields.Str(validate=get_field_validator("subnet_id")),
        required=True,
        validate=validate.Length(equal=1),
        metadata={"update_policy": UpdatePolicy.MANAGED_FSX},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AwsBatchQueueNetworking(**data)


class BaseSshSchema(BaseSchema):
    """Represent the schema of common Ssh parameters used by head and login nodes."""

    key_name = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})


class HeadNodeSshSchema(BaseSshSchema):
    """Represent the schema of the HeadNodeSsh."""

    allowed_ips = fields.Str(validate=get_field_validator("cidr"), metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return HeadNodeSsh(**data)


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


class RotationSchema(BaseSchema):
    """Represent the schema of the Log Rotation section."""

    enabled = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return LogRotation(**data)


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
    rotation = fields.Nested(RotationSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

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

    detailed_monitoring = fields.Bool(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
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
        metadata={"update_policy": UpdatePolicy.SUPPORTED}, validate=validate.Regexp(IAM_POLICY_REGEX)
    )

    resource_prefix = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ClusterIam(**data)


class BaseIamSchema(BaseSchema):
    """Represent the schema of common Iam parameters used by head, queue and login nodes."""

    instance_role = fields.Str(
        metadata={"update_policy": UpdatePolicy.SUPPORTED}, validate=validate.Regexp(IAM_ROLE_REGEX)
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


class IamSchema(BaseIamSchema):
    """Common schema of IAM for HeadNode and Queue."""

    s3_access = fields.Nested(
        S3AccessSchema, many=True, metadata={"update_policy": UpdatePolicy.SUPPORTED, "update_key": "BucketName"}
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
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED}, validate=validate.Regexp(IAM_INSTANCE_PROFILE_REGEX)
    )


class QueueIamSchema(IamSchema):
    """Represent the schema of IAM for Queue."""

    instance_profile = fields.Str(
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP},
        validate=validate.Regexp(IAM_INSTANCE_PROFILE_REGEX),
    )


class LoginNodesIamSchema(BaseIamSchema):
    """Represent the IAM schema of LoginNodes."""

    instance_role = fields.Str(
        metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP}, validate=validate.Regexp(IAM_ROLE_REGEX)
    )

    additional_iam_policies = fields.Nested(
        AdditionalIamPolicySchema,
        many=True,
        metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP, "update_key": "Policy"},
    )

    instance_profile = fields.Str(
        metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP}, validate=validate.Regexp(IAM_INSTANCE_PROFILE_REGEX)
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return LoginNodesIam(**data)


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
    compute_startup_time_metric_enabled = fields.Bool(metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ClusterDevSettings(**data)


# ---------------------- Health Checks ---------------------- #


class GpuHealthCheckSchema(BaseSchema):
    """Represent the schema of gpu health check."""

    enabled = fields.Bool(metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return GpuHealthCheck(**data)


class HealthChecksSchema(BaseSchema):
    """Represent the HealthChecks schema."""

    gpu = fields.Nested(GpuHealthCheckSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return HealthChecks(**data)


# ---------------------- Node and Cluster Schema ---------------------- #


class ImageSchema(BaseSchema):
    """Represent the schema of the Image."""

    os = fields.Str(
        required=True, validate=validate.OneOf(SUPPORTED_OSES), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    custom_ami = fields.Str(
        validate=validate.Regexp(PCLUSTER_AMI_ID_REGEX),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Image(**data)


class HeadNodeImageSchema(BaseSchema):
    """Represent the schema of the HeadNode Image."""

    custom_ami = fields.Str(
        validate=validate.Regexp(PCLUSTER_AMI_ID_REGEX),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return HeadNodeImage(**data)


class QueueImageSchema(BaseSchema):
    """Represent the schema of the Queue Image."""

    custom_ami = fields.Str(
        validate=validate.Regexp(PCLUSTER_AMI_ID_REGEX),
        metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return QueueImage(**data)


class OneOrManyCustomActionField(fields.Nested):
    """Custom Marshmallow filed to handle backward compatible single script custom actions."""

    def __init__(self, **kwargs):
        schema = self._build_dynamic_schema_class(
            kwargs.get("metadata", {}).get("update_policy", UpdatePolicy.UNSUPPORTED)
        )
        super().__init__(schema, **kwargs)

    @staticmethod
    def _build_dynamic_schema_class(update_policy):
        class_name = f"CustomActionScriptSchema{update_policy.name}"
        if class_name not in globals():
            schema_class_type = type(
                class_name,
                (CustomActionScriptSchemaBase,),
                {
                    "script": fields.Str(required=True, metadata={"update_policy": update_policy}),
                    "args": fields.List(fields.Str(), metadata={"update_policy": update_policy}),
                },
            )
            globals()[class_name] = schema_class_type
        else:
            schema_class_type = globals()[class_name]
        return schema_class_type

    def _deserialize(self, value, attr, data, **kwargs):
        if "Script" in value and "Sequence" in value:
            raise ValidationError("Both Script and Sequence fields are provided. Only one is allowed.")

        if "Script" in value:
            return super()._deserialize(value, attr, data, **kwargs)

        if "Sequence" in value:
            sequence = value["Sequence"]
            if not isinstance(sequence, list):
                raise ValidationError("Invalid input type for Sequence, expected list.")
            res = []
            for item in sequence:
                res.append(super()._deserialize(item, attr, data, **kwargs))
            return res

        raise ValidationError("Either Script or Sequence field must be provided.")

    def _serialize(self, nested_obj, attr, obj, **kwargs):
        if isinstance(nested_obj, list):
            nested_serialized = []
            for item in nested_obj:
                nested_serialized.append(super()._serialize(item, attr, obj, **kwargs))
            res = {"Sequence": nested_serialized}
        else:
            res = super()._serialize(nested_obj, attr, obj, **kwargs)
        return res


class CustomActionScriptSchemaBase(BaseSchema):
    """Represent the schema of the custom action script that cannot be updated."""

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CustomAction(**data)


class QueueCustomActionsSchema(BaseSchema):
    """Represent the schema for all available custom actions in the queues."""

    on_node_start = OneOrManyCustomActionField(metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})
    on_node_configured = OneOrManyCustomActionField(metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CustomActions(**data)


class HeadNodeCustomActionsSchema(BaseSchema):
    """Represent the schema for all available custom actions in the head node."""

    on_node_start = OneOrManyCustomActionField(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    on_node_configured = OneOrManyCustomActionField(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    on_node_updated = OneOrManyCustomActionField(metadata={"update_policy": UpdatePolicy.SUPPORTED})

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
    ssh = fields.Nested(HeadNodeSshSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    local_storage = fields.Nested(HeadNodeStorageSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    dcv = fields.Nested(DcvSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    custom_actions = fields.Nested(HeadNodeCustomActionsSchema, metadata={"update_policy": UpdatePolicy.IGNORED})
    iam = fields.Nested(HeadNodeIamSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    imds = fields.Nested(ImdsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    image = fields.Nested(HeadNodeImageSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return HeadNode(**data)


class LoginNodesImageSchema(BaseSchema):
    """Represent the Image schema of LoginNodes."""

    custom_ami = fields.Str(
        validate=validate.Regexp(PCLUSTER_AMI_ID_REGEX),
        metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return LoginNodesImage(**data)


class LoginNodesSshSchema(BaseSshSchema):
    """Represent the Ssh schema of LoginNodes."""

    key_name = fields.Str(metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return LoginNodesSsh(**data)


class LoginNodesNetworkingSchema(BaseNetworkingSchema):
    """Represent the networking schema of LoginNodes."""

    subnet_ids = fields.List(
        fields.Str(validate=get_field_validator("subnet_id")),
        required=True,
        validate=validate.Length(equal=1, error="Only one subnet can be associated with a login node pool."),
        metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP},
    )
    additional_security_groups = fields.List(
        fields.Str(validate=get_field_validator("security_group_id")),
        metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP},
    )
    security_groups = fields.List(
        fields.Str(validate=get_field_validator("security_group_id")),
        metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP},
    )

    proxy = fields.Nested(LoginNodeProxySchema, metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return LoginNodesNetworking(**data)


class LoginNodesPoolSchema(BaseSchema):
    """Represent the schema of the LoginNodesPool."""

    name = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP})
    instance_type = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP})
    image = fields.Nested(LoginNodesImageSchema, metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP})
    networking = fields.Nested(
        LoginNodesNetworkingSchema, required=True, metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP}
    )
    count = fields.Int(
        required=True,
        validate=validate.Range(
            min=0,
            error="The count for LoginNodes Pool must be greater than or equal to 0.",
        ),
        metadata={"update_policy": UpdatePolicy.SUPPORTED},
    )
    ssh = fields.Nested(LoginNodesSshSchema, metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP})
    iam = fields.Nested(LoginNodesIamSchema, metadata={"update_policy": UpdatePolicy.LOGIN_NODES_STOP})
    gracetime_period = fields.Int(
        validate=validate.Range(
            min=1, max=120, error="The gracetime period for LoginNodes Pool must be an interger from 1 to 120."
        ),
        metadata={"update_policy": UpdatePolicy.SUPPORTED},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return LoginNodesPool(**data)


class LoginNodesSchema(BaseSchema):
    """Represent the schema of LoginNodes."""

    pools = fields.Nested(
        LoginNodesPoolSchema,
        many=True,
        required=True,
        validate=validate.Length(equal=1, error="Only one pool can be specified when using login nodes."),
        metadata={"update_policy": UpdatePolicy(UpdatePolicy.LOGIN_NODES_POOLS), "update_key": "Name"},
    )

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return LoginNodes(**data)


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


class QueueTagSchema(BaseSchema):
    """Represent the schema of Tag section."""

    key = fields.Str(
        required=True,
        validate=validate.Length(max=128),
        metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY},
    )
    value = fields.Str(
        required=True,
        validate=validate.Length(max=256),
        metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return BaseTag(**data)


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
    health_checks = fields.Nested(HealthChecksSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    custom_slurm_settings = fields.Dict(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    tags = fields.Nested(
        QueueTagSchema, many=True, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY, "update_key": "Key"}
    )
    static_node_priority = fields.Int(
        validate=validate.Range(min=MIN_SLURM_NODE_PRIORITY, max=MAX_SLURM_NODE_PRIORITY),
        metadata={"update_policy": UpdatePolicy.SUPPORTED},
    )
    dynamic_node_priority = fields.Int(
        validate=validate.Range(min=MIN_SLURM_NODE_PRIORITY, max=MAX_SLURM_NODE_PRIORITY),
        metadata={"update_policy": UpdatePolicy.SUPPORTED},
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

    @validates("tags")
    def validate_tags(self, tags):
        """Validate tags."""
        validate_no_reserved_tag(tags)
        validate_no_duplicate_tag(tags)

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
    """Represent the schema of common part between Slurm and future scheduler Queue."""

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
    health_checks = fields.Nested(HealthChecksSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    custom_slurm_settings = fields.Dict(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    tags = fields.Nested(
        QueueTagSchema, many=True, metadata={"update_policy": UpdatePolicy.QUEUE_UPDATE_STRATEGY, "update_key": "Key"}
    )
    job_exclusive_allocation = fields.Bool(metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SlurmQueue(**data)

    @validates("tags")
    def validate_tags(self, tags):
        """Validate tags."""
        validate_no_reserved_tag(tags)
        validate_no_duplicate_tag(tags)


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

    scaledown_idletime = fields.Int(
        validate=validate.Range(min=-1),
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP},
    )
    dns = fields.Nested(DnsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    queue_update_strategy = fields.Str(
        validate=validate.OneOf([strategy.value for strategy in QueueUpdateStrategy]),
        metadata={"update_policy": UpdatePolicy.IGNORED},
    )
    enable_memory_based_scheduling = fields.Bool(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    database = fields.Nested(DatabaseSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    custom_slurm_settings = fields.List(fields.Dict, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    custom_slurm_settings_include_file = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})

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


class SchedulingSchema(BaseSchema):
    """Represent the schema of the Scheduling."""

    scheduler = fields.Str(
        required=True,
        validate=validate.OneOf(["slurm", "awsbatch"]),
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

    @validates_schema
    def no_coexist_schedulers(self, data, **kwargs):
        """Validate that *_settings and *_queues for different schedulers do not co-exist."""
        scheduler = data.get("scheduler")
        if self.fields_coexist(data, ["aws_batch_settings", "slurm_settings"], **kwargs):
            raise ValidationError("Multiple *Settings sections cannot be specified in the Scheduling section.")
        if self.fields_coexist(data, ["aws_batch_queues", "slurm_queues"], one_required=True, **kwargs):
            if scheduler == "awsbatch":
                scheduler_prefix = "AwsBatch"
            else:
                scheduler_prefix = scheduler.capitalize()
            raise ValidationError(f"{scheduler_prefix}Queues section must be specified in the Scheduling section.")

    @validates_schema
    def right_scheduler_schema(self, data, **kwargs):
        """Validate that *_settings field is associated to the right scheduler."""
        for scheduler, settings, queues in [
            ("awsbatch", "aws_batch_settings", "aws_batch_queues"),
            ("slurm", "slurm_settings", "slurm_queues"),
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
        else:
            scheduler_prefix = adapted_data.scheduler
        setattr(adapted_data, f"{scheduler_prefix}_queues", copy.copy(getattr(adapted_data, "queues", None)))
        setattr(adapted_data, f"{scheduler_prefix}_settings", copy.copy(getattr(adapted_data, "settings", None)))
        return adapted_data


class DirectoryServiceSchema(BaseSchema):
    """Represent the schema of the DirectoryService."""

    domain_name = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_AND_LOGIN_NODES_STOP})
    domain_addr = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_AND_LOGIN_NODES_STOP})
    password_secret_arn = fields.Str(
        required=True,
        validate=validate.Regexp(r"^arn:.*:(secretsmanager:.*:.*:secret:|ssm:.*:.*:parameter\/).*$"),
        metadata={"update_policy": UpdatePolicy.COMPUTE_AND_LOGIN_NODES_STOP},
    )
    domain_read_only_user = fields.Str(
        required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_AND_LOGIN_NODES_STOP}
    )
    ldap_tls_ca_cert = fields.Str(metadata={"update_policy": UpdatePolicy.COMPUTE_AND_LOGIN_NODES_STOP})
    ldap_tls_req_cert = fields.Str(
        validate=validate.OneOf(["never", "allow", "try", "demand", "hard"]),
        metadata={"update_policy": UpdatePolicy.COMPUTE_AND_LOGIN_NODES_STOP},
    )
    ldap_access_filter = fields.Str(metadata={"update_policy": UpdatePolicy.COMPUTE_AND_LOGIN_NODES_STOP})
    generate_ssh_keys_for_users = fields.Bool(metadata={"update_policy": UpdatePolicy.COMPUTE_AND_LOGIN_NODES_STOP})
    additional_sssd_configs = fields.Dict(metadata={"update_policy": UpdatePolicy.COMPUTE_AND_LOGIN_NODES_STOP})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return DirectoryService(**data)


class ClusterSchema(BaseSchema):
    """Represent the schema of the Cluster."""

    login_nodes = fields.Nested(LoginNodesSchema, many=False, metadata={"update_policy": UpdatePolicy.SUPPORTED})
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

    monitoring = fields.Nested(MonitoringSchema, metadata={"update_policy": UpdatePolicy.IGNORED})
    additional_packages = fields.Nested(AdditionalPackagesSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    tags = fields.Nested(
        TagSchema, many=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED, "update_key": "Key"}
    )
    iam = fields.Nested(ClusterIamSchema, metadata={"update_policy": UpdatePolicy.IGNORED})
    directory_service = fields.Nested(
        DirectoryServiceSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_AND_LOGIN_NODES_STOP}
    )
    config_region = fields.Str(data_key="Region", metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    imds = fields.Nested(TopLevelImdsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    custom_s3_bucket = fields.Str(metadata={"update_policy": UpdatePolicy.READ_ONLY_RESOURCE_BUCKET})
    additional_resources = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    dev_settings = fields.Nested(ClusterDevSettingsSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    deployment_settings = fields.Nested(DeploymentSettingsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    def __init__(self, cluster_name: str):
        super().__init__()
        self.cluster_name = cluster_name

    @validates("tags")
    def validate_tags(self, tags):
        """Validate tags."""
        validate_no_reserved_tag(tags)
        validate_no_duplicate_tag(tags)

    @validates_schema
    def no_settings_for_batch(self, data, **kwargs):
        """Ensure IntelSoftware and DirectoryService section is not included when AWS Batch is the scheduler."""
        scheduling = data.get("scheduling")
        head_node = data.get("head_node")
        if scheduling and scheduling.scheduler == "awsbatch":
            error_message = "The use of the {} configuration is not supported when using awsbatch as the scheduler."
            additional_packages = data.get("additional_packages")
            if (
                additional_packages
                and additional_packages.intel_software
                and additional_packages.intel_software.intel_hpc_platform
            ):
                raise ValidationError(error_message.format("IntelSoftware"))
            if head_node.custom_actions and head_node.custom_actions.on_node_updated:
                raise ValidationError(error_message.format("OnNodeUpdated"))
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
        else:
            raise ValidationError(f"Unsupported scheduler {scheduler}.")

        cluster.source_config = original_data
        return cluster
