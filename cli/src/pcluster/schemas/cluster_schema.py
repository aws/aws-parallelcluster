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
import re

from marshmallow import ValidationError, fields, post_load, pre_dump, validate, validates, validates_schema

from pcluster.config.cluster_config import (
    AdditionalPackages,
    AmiSearchFilters,
    AwsBatchClusterConfig,
    AwsBatchComputeResource,
    AwsBatchQueue,
    AwsBatchScheduling,
    AwsBatchSettings,
    BaseClusterConfig,
    CapacityType,
    CloudWatchDashboards,
    CloudWatchLogs,
    ClusterDevSettings,
    ClusterIam,
    ComputeSettings,
    CustomAction,
    CustomActions,
    Dashboards,
    Dcv,
    Dns,
    Ebs,
    Efa,
    EphemeralVolume,
    HeadNode,
    HeadNodeNetworking,
    Iam,
    Image,
    Imds,
    IntelSelectSolutions,
    LocalStorage,
    Logs,
    Monitoring,
    PlacementGroup,
    Proxy,
    QueueNetworking,
    Raid,
    Roles,
    S3Access,
    SharedEbs,
    SharedEfs,
    SharedFsx,
    SlurmClusterConfig,
    SlurmComputeResource,
    SlurmQueue,
    SlurmScheduling,
    SlurmSettings,
    Ssh,
)
from pcluster.config.update_policy import UpdatePolicy
from pcluster.constants import EBS_VOLUME_SIZE_DEFAULT, FSX_HDD_THROUGHPUT, FSX_SSD_THROUGHPUT, SUPPORTED_OSES
from pcluster.schemas.common_schema import (
    AdditionalIamPolicySchema,
    BaseDevSettingsSchema,
    BaseSchema,
    TagSchema,
    get_field_validator,
    validate_no_reserved_tag,
)
from pcluster.validators.cluster_validators import FSX_MESSAGES

# pylint: disable=C0302

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

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Ebs(**data)

    @validates("size")
    def validate_size(self, value):
        """Validate the size of root volume."""
        if value < EBS_VOLUME_SIZE_DEFAULT:
            raise ValidationError(
                f"Root volume size {value} is invalid. It must be at least {EBS_VOLUME_SIZE_DEFAULT}."
            )


class QueueRootVolumeSchema(BaseSchema):
    """Represent the RootVolume schema for the queue."""

    size = fields.Int(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    encrypted = fields.Bool(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    volume_type = fields.Str(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    iops = fields.Int(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    throughput = fields.Int(metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Ebs(**data)

    @validates("size")
    def validate_size(self, value):
        """Validate the size of root volume."""
        if value < EBS_VOLUME_SIZE_DEFAULT:
            raise ValidationError(
                f"Root volume size {value} is invalid. It must be at least {EBS_VOLUME_SIZE_DEFAULT}."
            )


class RaidSchema(BaseSchema):
    """Represent the schema of the parameters specific to Raid. It is a child of EBS schema."""

    raid_type = fields.Int(
        data_key="Type", validate=validate.OneOf([0, 1]), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
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


class HeadNodeEphemeralVolumeSchema(BaseSchema):
    """Represent the schema of ephemeral volume.It is a child of storage schema."""

    encrypted = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    mount_dir = fields.Str(
        validate=get_field_validator("file_path"), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return EphemeralVolume(**data)


class QueueEphemeralVolumeSchema(BaseSchema):
    """Represent the schema of ephemeral volume.It is a child of storage schema."""

    encrypted = fields.Bool(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    mount_dir = fields.Str(
        validate=get_field_validator("file_path"), metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return EphemeralVolume(**data)


class HeadNodeStorageSchema(BaseSchema):
    """Represent the schema of storage attached to a node."""

    root_volume = fields.Nested(HeadNodeRootVolumeSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    ephemeral_volume = fields.Nested(
        HeadNodeEphemeralVolumeSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return LocalStorage(**data)


class QueueStorageSchema(BaseSchema):
    """Represent the schema of storage attached to a node."""

    root_volume = fields.Nested(QueueRootVolumeSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    ephemeral_volume = fields.Nested(
        QueueEphemeralVolumeSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP}
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
        validate=validate.OneOf(["SCRATCH_1", "SCRATCH_2", "PERSISTENT_1"]),
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
    per_unit_storage_throughput = fields.Int(
        validate=validate.OneOf(FSX_SSD_THROUGHPUT + FSX_HDD_THROUGHPUT),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    backup_id = fields.Str(
        validate=validate.Regexp("^(backup-[0-9a-f]{8,})$"), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    kms_key_id = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    file_system_id = fields.Str(
        validate=validate.Regexp(r"^fs-[0-9a-z]{17}$"), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    auto_import_policy = fields.Str(
        validate=validate.OneOf(["NEW", "NEW_CHANGED"]), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    drive_cache_type = fields.Str(
        validate=validate.OneOf(["READ"]), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    fsx_storage_type = fields.Str(
        data_key="StorageType",
        validate=validate.OneOf(["HDD", "SSD"]),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
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


class SharedStorageSchema(BaseSchema):
    """Represent the generic SharedStorage schema."""

    mount_dir = fields.Str(
        required=True, validate=get_field_validator("file_path"), metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )
    name = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    storage_type = fields.Str(
        required=True,
        validate=validate.OneOf(["Ebs", "FsxLustre", "Efs"]),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    ebs_settings = fields.Nested(EbsSettingsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    efs_settings = fields.Nested(EfsSettingsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    fsx_lustre_settings = fields.Nested(FsxLustreSettingsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @validates_schema
    def no_coexist_storage_settings(self, data, **kwargs):
        """Validate that *_settings for different storage types do not co-exist."""
        if self.fields_coexist(data, ["ebs_settings", "efs_settings", "fsx_lustre_settings"], **kwargs):
            raise ValidationError("Multiple *Settings sections cannot be specified in the SharedStorage items.")

    @validates_schema
    def right_storage_settings(self, data, **kwargs):
        """Validate that *_settings param is associated to the right storage type."""
        for storage_type, settings in [
            ("Ebs", "ebs_settings"),
            ("Efs", "efs_settings"),
            ("FsxLustre", "fsx_lustre_settings"),
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
            data.get("efs_settings", None) or data.get("fsx_lustre_settings", None) or data.get("ebs_settings", None)
        )
        if settings:
            shared_volume_attributes.update(**settings)
        if storage_type == "Efs":
            return SharedEfs(**shared_volume_attributes)
        elif storage_type == "FsxLustre":
            return SharedFsx(**shared_volume_attributes)
        elif storage_type == "Ebs":
            return SharedEbs(**shared_volume_attributes)
        return None

    @pre_dump
    def restore_child(self, data, **kwargs):
        """Restore back the child in the schema."""
        adapted_data = copy.deepcopy(data)
        # Move SharedXxx as a child to be automatically managed by marshmallow, see post_load action
        if adapted_data.shared_storage_type == "efs":
            storage_type = "efs"
        elif adapted_data.shared_storage_type == "fsx":
            storage_type = "fsx_lustre"
        else:  # "raid", "ebs"
            storage_type = "ebs"
        setattr(adapted_data, f"{storage_type}_settings", copy.copy(adapted_data))
        # Restore storage type attribute
        adapted_data.storage_type = (
            "FsxLustre" if adapted_data.shared_storage_type == "fsx" else storage_type.capitalize()
        )
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

    http_proxy_address = fields.Str(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})

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
    assign_public_ip = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    proxy = fields.Nested(HeadNodeProxySchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return HeadNodeNetworking(**data)


class PlacementGroupSchema(BaseSchema):
    """Represent the schema of placement group."""

    enabled = fields.Bool(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    id = fields.Str(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})

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
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP},
    )
    placement_group = fields.Nested(PlacementGroupSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    assign_public_ip = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    proxy = fields.Nested(QueueProxySchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return QueueNetworking(**data)


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

    enabled = fields.Bool(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    gdr_support = fields.Bool(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})

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
    retain_on_delete = fields.Bool(metadata={"update_policy": UpdatePolicy.SUPPORTED})

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

    custom_lambda_resources = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Roles(**data)


class S3AccessSchema(BaseSchema):
    """Represent the schema of S3 access."""

    bucket_name = fields.Str(
        required=True,
        metadata={"update_policy": UpdatePolicy.SUPPORTED},
        validate=validate.Regexp(r"^[a-z0-9\-\.]+$"),
    )
    key_name = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    enable_write_access = fields.Bool(metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return S3Access(**data)


class ClusterIamSchema(BaseSchema):
    """Represent the schema of IAM for Cluster."""

    roles = fields.Nested(RolesSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ClusterIam(**data)


class IamSchema(BaseSchema):
    """Represent the schema of IAM for HeadNode and Queue."""

    instance_role = fields.Str(
        metadata={"update_policy": UpdatePolicy.SUPPORTED}, validate=validate.Regexp("^arn:.*:role/")
    )
    instance_profile = fields.Str(
        metadata={"update_policy": UpdatePolicy.SUPPORTED}, validate=validate.Regexp("^arn:.*:instance-profile/")
    )
    s3_access = fields.Nested(
        S3AccessSchema, many=True, metadata={"update_policy": UpdatePolicy.SUPPORTED, "update_key": "BucketName"}
    )
    additional_iam_policies = fields.Nested(
        AdditionalIamPolicySchema,
        many=True,
        metadata={"update_policy": UpdatePolicy.SUPPORTED, "update_key": "Policy"},
    )

    @validates_schema
    def no_coexist_role_policies(self, data, **kwargs):
        """Validate that instance_role, instance_profile or additional_iam_policies do not co-exist."""
        if self.fields_coexist(data, ["instance_role", "instance_profile", "additional_iam_policies"], **kwargs):
            raise ValidationError(
                "InstanceProfile, InstanceRole or AdditionalIamPolicies can not be configured together."
            )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Iam(**data)


class ImdsSchema(BaseSchema):
    """Represent the schema of IMDS for HeadNode."""

    secured = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Imds(**data)


class IntelSelectSolutionsSchema(BaseSchema):
    """Represent the schema of additional packages."""

    install_intel_software = fields.Bool(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return IntelSelectSolutions(**data)


class AdditionalPackagesSchema(BaseSchema):
    """Represent the schema of additional packages."""

    intel_select_solutions = fields.Nested(
        IntelSelectSolutionsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )

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


class ClusterDevSettingsSchema(BaseDevSettingsSchema):
    """Represent the schema of Dev Setting."""

    cluster_template = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    ami_search_filters = fields.Nested(AmiSearchFiltersSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    instance_types_data = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})

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

    script = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    args = fields.List(fields.Str(), metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CustomAction(**data)


class QueueCustomActionsSchema(BaseSchema):
    """Represent the schema for all available custom actions."""

    on_node_start = fields.Nested(QueueCustomActionSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    on_node_configured = fields.Nested(
        QueueCustomActionSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CustomActions(**data)


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
    iam = fields.Nested(IamSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    imds = fields.Nested(ImdsSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return HeadNode(**data)


class _ComputeResourceSchema(BaseSchema):
    """Represent the schema of the ComputeResource."""

    name = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    disable_simultaneous_multithreading = fields.Bool(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})


class SlurmComputeResourceSchema(_ComputeResourceSchema):
    """Represent the schema of the Slurm ComputeResource."""

    instance_type = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    max_count = fields.Int(validate=validate.Range(min=1), metadata={"update_policy": UpdatePolicy.MAX_COUNT})
    min_count = fields.Int(validate=validate.Range(min=0), metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    spot_price = fields.Float(validate=validate.Range(min=0), metadata={"update_policy": UpdatePolicy.SUPPORTED})
    efa = fields.Nested(EfaSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SlurmComputeResource(**data)


class AwsBatchComputeResourceSchema(_ComputeResourceSchema):
    """Represent the schema of the Batch ComputeResource."""

    instance_types = fields.List(
        fields.Str(),
        required=True,
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP},
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

    local_storage = fields.Nested(QueueStorageSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ComputeSettings(**data)


class BaseQueueSchema(BaseSchema):
    """Represent the schema of the attributes in common between all the schedulers queues."""

    name = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    networking = fields.Nested(
        QueueNetworkingSchema, required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP}
    )
    capacity_type = fields.Str(
        validate=validate.OneOf([event.value for event in CapacityType]),
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP},
    )


class SlurmQueueSchema(BaseQueueSchema):
    """Represent the schema of a Slurm Queue."""

    compute_settings = fields.Nested(ComputeSettingsSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    compute_resources = fields.Nested(
        SlurmComputeResourceSchema,
        many=True,
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP, "update_key": "Name"},
    )
    custom_actions = fields.Nested(
        QueueCustomActionsSchema,
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP},
    )
    iam = fields.Nested(IamSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})

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

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AwsBatchQueue(**data)


class DnsSchema(BaseSchema):
    """Represent the schema of Dns Settings."""

    disable_managed_dns = fields.Bool(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Dns(**data)


class SlurmSettingsSchema(BaseSchema):
    """Represent the schema of the Scheduling Settings."""

    scaledown_idletime = fields.Int(metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    dns = fields.Nested(DnsSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})

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
        validate=validate.OneOf(["slurm", "awsbatch", "custom"]),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    # Slurm schema
    slurm_settings = fields.Nested(SlurmSettingsSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    slurm_queues = fields.Nested(
        SlurmQueueSchema,
        many=True,
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP, "update_key": "Name"},
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
            scheduler_prefix = "AwsBatch" if scheduler == "awsbatch" else scheduler.capitalize()
            raise ValidationError(f"{scheduler_prefix}Queues section must be specified in the Scheduling section.")

    @validates_schema
    def right_scheduler_schema(self, data, **kwargs):
        """Validate that *_settings field is associated to the right scheduler."""
        for scheduler, settings, queues in [
            ("awsbatch", "aws_batch_settings", "aws_batch_queues"),
            ("slurm", "slurm_settings", "slurm_queues"),
        ]:
            # Verify the settings section is associated to the right storage type
            configured_scheduler = data.get("scheduler")
            if data.get(settings, None) and scheduler != configured_scheduler:
                raise ValidationError(
                    f"Scheduling > *Settings section is not appropriate to the Scheduler: {configured_scheduler}."
                )
            if data.get(queues, None) and scheduler != configured_scheduler:
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
        # if data.get("custom_queues"):
        #    return CustomScheduling(**data)
        return None

    @pre_dump
    def restore_child(self, data, **kwargs):
        """Restore back the child in the schema, see post_load action."""
        adapted_data = copy.deepcopy(data)
        scheduler_prefix = "aws_batch" if adapted_data.scheduler == "awsbatch" else adapted_data.scheduler
        setattr(adapted_data, f"{scheduler_prefix}_queues", copy.copy(getattr(adapted_data, "queues", None)))
        setattr(adapted_data, f"{scheduler_prefix}_settings", copy.copy(getattr(adapted_data, "settings", None)))
        return adapted_data


class ClusterSchema(BaseSchema):
    """Represent the schema of the Cluster."""

    image = fields.Nested(ImageSchema, required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    head_node = fields.Nested(HeadNodeSchema, required=True, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    scheduling = fields.Nested(SchedulingSchema, required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    shared_storage = fields.Nested(
        SharedStorageSchema,
        many=True,
        metadata={
            "update_policy": UpdatePolicy(
                UpdatePolicy.UNSUPPORTED, fail_reason=UpdatePolicy.FAIL_REASONS["shared_storage_change"]
            ),
            "update_key": "Name",
        },
    )

    monitoring = fields.Nested(MonitoringSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    additional_packages = fields.Nested(AdditionalPackagesSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    tags = fields.Nested(TagSchema, many=True, metadata={"update_policy": UpdatePolicy.SUPPORTED, "update_key": "Key"})
    iam = fields.Nested(ClusterIamSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    custom_s3_bucket = fields.Str(metadata={"update_policy": UpdatePolicy.READ_ONLY_RESOURCE_BUCKET})
    additional_resources = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    dev_settings = fields.Nested(ClusterDevSettingsSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @validates("tags")
    def validate_tags(self, tags):
        """Validate tags."""
        validate_no_reserved_tag(tags)

    @post_load(pass_original=True)
    def make_resource(self, data, original_data, **kwargs):
        """Generate cluster according to the scheduler. Save original configuration."""
        scheduler = data.get("scheduling").scheduler
        if scheduler == "slurm":
            cluster = SlurmClusterConfig(**data)
        elif scheduler == "awsbatch":
            cluster = AwsBatchClusterConfig(**data)
        else:  # scheduler == "custom":
            cluster = BaseClusterConfig(**data)  # FIXME Must be ByosCluster

        cluster.source_config = original_data
        return cluster
