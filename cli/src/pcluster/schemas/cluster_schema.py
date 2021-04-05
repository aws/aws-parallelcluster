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

from marshmallow import (
    ValidationError,
    fields,
    post_dump,
    post_load,
    pre_dump,
    pre_load,
    validate,
    validates,
    validates_schema,
)

from pcluster.config.update_policy import UpdatePolicy
from pcluster.constants import EBS_VOLUME_SIZE_DEFAULT, FSX_HDD_THROUGHPUT, FSX_SSD_THROUGHPUT, SUPPORTED_OSES
from pcluster.models.cluster_config import (
    AdditionalIamPolicy,
    AdditionalPackages,
    AmiSearchFilters,
    AwsbatchClusterConfig,
    AwsbatchComputeResource,
    AwsbatchQueue,
    AwsbatchScheduling,
    AwsbatchSettings,
    BaseClusterConfig,
    CapacityType,
    CloudWatchDashboards,
    CloudWatchLogs,
    ClusterDevSettings,
    ClusterIam,
    ComputeSettings,
    CustomAction,
    CustomActionEvent,
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
from pcluster.schemas.common_schema import BaseDevSettingsSchema, BaseSchema, TagSchema, get_field_validator
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


class EbsSchema(BaseSchema):
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


class EfsSchema(BaseSchema):
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


class FsxSchema(BaseSchema):
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
    ebs = fields.Nested(EbsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    efs = fields.Nested(EfsSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    fsx = fields.Nested(FsxSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @pre_load
    def preprocess(self, data, **kwargs):
        """Before load the data into schema, change the settings to adapt different storage types."""
        if data.get("StorageType") == "Efs":
            data["Efs"] = data.pop("EfsSettings", {})
        elif data.get("StorageType") == "Ebs":
            data["Ebs"] = data.pop("EbsSettings", {})
        elif data.get("StorageType") == "FsxLustre":
            data["Fsx"] = data.pop("FsxLustreSettings", {})
        return data

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate the right type of shared storage according to the child type (EBS vs EFS vs FsxLustre)."""
        if data.get("efs") is not None:
            return SharedEfs(data.get("mount_dir"), data.get("name"), **data.get("efs"))
        if data.get("fsx") is not None:
            return SharedFsx(data.get("mount_dir"), data.get("name"), **data.get("fsx"))
        if data.get("ebs") is not None:
            return SharedEbs(data.get("mount_dir"), data.get("name"), **data.get("ebs"))
        return None

    @pre_dump
    def restore_child(self, data, **kwargs):
        """Restore back the child in the schema. Note: Enums are converted back to string from BaseSchema."""
        child = copy.deepcopy(data)
        # Move SharedXxx as a child to be automatically managed by marshmallow
        storage_type = "ebs" if data.shared_storage_type == "raid" else data.shared_storage_type
        setattr(data, storage_type, child)
        # Restore storage type
        data.storage_type = "FsxLustre" if data.shared_storage_type == "fsx" else storage_type.capitalize()
        return data

    @post_dump
    def post_processed(self, data, **kwargs):
        """Restore the SharedStorage Schema back to its origin."""
        if data.get("Efs") is not None:
            storage_type, storage_settings = "Efs", "EfsSettings"
        elif data.get("Ebs") is not None:
            storage_type, storage_settings = "Ebs", "EbsSettings"
        elif data.get("Fsx") is not None:
            storage_type, storage_settings = "Fsx", "FsxLustreSettings"
        if data.get(storage_type):
            data[storage_settings] = data.pop(storage_type)
        else:
            data.pop(storage_type)

        return data

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
        """Validate that security_groups and additional_security_groups are not co-exist."""
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
        validate=validate.Length(equal=1),  # FIXME Add multi-subnet support for Awsbatch
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

    bucket_name = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    enable_write_access = fields.Bool(metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return S3Access(**data)


class AdditionalIamPolicySchema(BaseSchema):
    """Represent the schema of Additional IAM policy."""

    policy = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AdditionalIamPolicy(**data)


class ClusterIamSchema(BaseSchema):
    """Represent the schema of IAM for Cluster."""

    roles = fields.Nested(RolesSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ClusterIam(**data)


class IamSchema(BaseSchema):
    """Represent the schema of IAM for HeadNode and Queue."""

    instance_role = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    s3_access = fields.Nested(
        S3AccessSchema, many=True, metadata={"update_policy": UpdatePolicy.SUPPORTED, "update_key": "BucketName"}
    )
    additional_iam_policies = fields.Nested(
        AdditionalIamPolicySchema,
        many=True,
        metadata={"update_policy": UpdatePolicy.SUPPORTED, "update_key": "Policy"},
    )

    @validates_schema
    def no_coexist_security_groups(self, data, **kwargs):
        """Validate that security_groups and additional_security_groups are not co-exist."""
        if self.fields_coexist(data, ["instance_role", "additional_iam_policies"], **kwargs):
            raise ValidationError("InstanceRole and AdditionalIamPolicies can not be configured together.")

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Iam(**data)


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

    tags = fields.Nested(TagSchema, many=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    owner = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AmiSearchFilters(**data)


class ClusterDevSettingsSchema(BaseDevSettingsSchema):
    """Represent the schema of Dev Setting."""

    cluster_template = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    ami_search_filters = fields.Nested(AmiSearchFiltersSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})

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
    """Represent the schema of the custom action for the Head node."""

    script = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    args = fields.List(fields.Str(), metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    event = fields.Str(
        validate=validate.OneOf([event.value for event in CustomActionEvent]),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CustomAction(**data)


class QueueCustomActionSchema(BaseSchema):
    """Represent the schema of the custom action for the queue."""

    script = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    args = fields.List(fields.Str(), metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    event = fields.Str(
        validate=validate.OneOf([event.value for event in CustomActionEvent]),
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CustomAction(**data)


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
    custom_actions = fields.Nested(
        HeadNodeCustomActionSchema,
        many=True,
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED, "update_key": "Script"},
    )  # TODO validate to avoid more than one script for event type or add support for them.
    iam = fields.Nested(IamSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})

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


class AwsbatchComputeResourceSchema(_ComputeResourceSchema):
    """Represent the schema of the Batch ComputeResource."""

    instance_types = fields.Str(required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
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
    spot_bid_percentage = fields.Float(
        validate=validate.Range(min=0, max=1, min_inclusive=False), metadata={"update_policy": UpdatePolicy.SUPPORTED}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AwsbatchComputeResource(**data)


class ComputeSettingsSchema(BaseSchema):
    """Represent the schema of the compute_settings schedulers queues."""

    local_storage = fields.Nested(QueueStorageSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ComputeSettings(**data)


class BaseQueueSchema(BaseSchema):
    """Represent the schema of the attributes in common between all the schedulers queues."""

    name = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    compute_settings = fields.Nested(ComputeSettingsSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    networking = fields.Nested(
        QueueNetworkingSchema, required=True, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP}
    )
    capacity_type = fields.Str(
        validate=validate.OneOf([event.value for event in CapacityType]),
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP},
    )
    iam = fields.Nested(IamSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})


class SlurmQueueSchema(BaseQueueSchema):
    """Represent the schema of a Slurm Queue."""

    compute_resources = fields.Nested(
        SlurmComputeResourceSchema,
        many=True,
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP, "update_key": "Name"},
    )
    custom_actions = fields.Nested(
        QueueCustomActionSchema,
        many=True,
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP, "update_key": "Script"},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SlurmQueue(**data)


class AwsbatchQueueSchema(BaseQueueSchema):
    """Represent the schema of a Batch Queue."""

    compute_resources = fields.Nested(
        AwsbatchComputeResourceSchema,
        many=True,
        validate=validate.Length(equal=1),
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP, "update_key": "Name"},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AwsbatchQueue(**data)


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


class SlurmSchema(BaseSchema):
    """Represent the schema of the Slurm section."""

    settings = fields.Nested(SlurmSettingsSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})
    queues = fields.Nested(
        SlurmQueueSchema,
        many=True,
        required=True,
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP, "update_key": "Name"},
    )


class AwsbatchSettingsSchema(BaseSchema):
    """Represent the schema of the Awsbatch Scheduling Settings."""

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AwsbatchSettings(**data)


class AwsbatchSchema(BaseSchema):
    """Represent the schema of the Awsbatch section."""

    queues = fields.Nested(
        AwsbatchQueueSchema,
        many=True,
        required=True,
        validate=validate.Length(equal=1),
        metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP, "update_key": "Name"},
    )
    settings = fields.Nested(AwsbatchSettingsSchema, metadata={"update_policy": UpdatePolicy.COMPUTE_FLEET_STOP})


class SchedulingSchema(BaseSchema):
    """Represent the schema of the Scheduling."""

    slurm = fields.Nested(SlurmSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    awsbatch = fields.Nested(AwsbatchSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})
    scheduler = fields.Str(
        required=True,
        validate=validate.OneOf(["slurm", "awsbatch", "custom"]),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    # custom = fields.Str(CustomSchema)

    @pre_load
    def preprocess(self, data, **kwargs):
        """Before load the data into schema, change the settings to adapt different storage types."""
        if data.get("Scheduler") == "slurm":
            scheduler, scheduler_settings = "Slurm", "SlurmSettings"
        elif data.get("Scheduler") == "awsbatch":
            scheduler, scheduler_settings = "Awsbatch", "AwsbatchSettings"
        # elif data.get("Scheduler") == "custom":
        #     scheduler, scheduler_settings = "Custom", "CustomSettings"
        else:
            raise ValidationError("You must provide scheduler configuration")

        data[scheduler] = {}
        data[scheduler]["Settings"] = data.pop(scheduler_settings, {})
        if data.get("Queues"):
            data[scheduler]["Queues"] = data.pop("Queues")
        else:
            raise ValidationError("Queues must be configured in scheduler configuration")

        return data

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate the right type of scheduling according to the child type (Slurm vs Awsbatch vs Custom)."""
        if data.get("slurm"):
            return SlurmScheduling(**data.get("slurm"))
        if data.get("awsbatch"):
            return AwsbatchScheduling(**data.get("awsbatch"))
        # if data.get("custom_scheduling"):
        #    return CustomScheduling(data.get("scheduler"), **data.get("custom_scheduling"))
        return None

    @pre_dump
    def restore_child(self, data, **kwargs):
        """Restore back the child in the schema."""
        setattr(data, data.scheduler, data)
        return data

    @post_dump
    def post_processed(self, data, **kwargs):
        """Restore the SharedStorage Schema back to its origin."""
        if data.get("Slurm"):
            scheduler, schedulersettings = "Slurm", "SlurmSettings"
        elif data.get("Awsbatch"):
            scheduler, schedulersettings = "Awsbatch", "AwsbatchSettings"
        # elif data.get("Scheduler") == "custom":
        #     scheduler, scheduler_settings = "Custom", "CustomSettings"

        if data.get(scheduler).get("Settings"):
            data[schedulersettings] = data[scheduler].pop("Settings")
        else:
            data[scheduler].pop("Settings")

        data["Queues"] = data[scheduler].pop("Queues")
        data.pop(scheduler)

        return data


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
    cluster_s3_bucket = fields.Str(metadata={"update_policy": UpdatePolicy.READ_ONLY_RESOURCE_BUCKET})
    additional_resources = fields.Str(metadata={"update_policy": UpdatePolicy.SUPPORTED})
    dev_settings = fields.Nested(ClusterDevSettingsSchema, metadata={"update_policy": UpdatePolicy.SUPPORTED})

    @post_load(pass_original=True)
    def make_resource(self, data, original_data, **kwargs):
        """Generate cluster according to the scheduler. Save original configuration."""
        scheduler = data.get("scheduling").scheduler
        if scheduler == "slurm":
            cluster = SlurmClusterConfig(**data)
        elif scheduler == "awsbatch":
            cluster = AwsbatchClusterConfig(**data)
        else:  # scheduler == "custom":
            cluster = BaseClusterConfig(**data)  # FIXME Must be ByosCluster

        cluster.source_config = original_data
        return cluster
