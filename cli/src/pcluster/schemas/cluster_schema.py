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
import re

from marshmallow import (
    Schema,
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

from pcluster.config.cluster_config import (
    AdditionalIamPolicyConfig,
    BaseEbsConfig,
    CloudWatchDashboardsConfig,
    CloudWatchLogsConfig,
    ClusterConfig,
    ComputeResourceConfig,
    CustomActionConfig,
    DashboardsConfig,
    DcvConfig,
    EbsConfig,
    EfsConfig,
    EphemeralVolumeConfig,
    FsxConfig,
    HeadNodeConfig,
    HeadNodeNetworkingConfig,
    IamConfig,
    ImageConfig,
    LogsConfig,
    MonitoringConfig,
    PlacementGroupConfig,
    ProxyConfig,
    QueueConfig,
    QueueNetworkingConfig,
    RaidConfig,
    RolesConfig,
    S3AccessConfig,
    SchedulingConfig,
    SchedulingSettingsConfig,
    SharedStorageConfig,
    SshConfig,
    StorageConfig,
    TagConfig,
)
from pcluster.constants import FSX_HDD_THROUGHPUT, FSX_SSD_THROUGHPUT, SUPPORTED_ARCHITECTURES

ALLOWED_VALUES = {
    "cidr": r"^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}"
    r"([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])"
    r"(\/([0-9]|[1-2][0-9]|3[0-2]))$",
    "file_path": r"^\/?[^\/.\\][^\/\\]*(\/[^\/.\\][^\/]*)*$",
    "security_group_id": r"^sg-[0-9a-z]{8}$|^sg-[0-9a-z]{17}$",
    "subnet_id": r"^subnet-[0-9a-z]{8}$|^subnet-[0-9a-z]{17}$",
    "architectures": SUPPORTED_ARCHITECTURES,
}


def _get_field_validator(field_name):
    allowed_values = ALLOWED_VALUES[field_name]
    return validate.OneOf(allowed_values) if isinstance(allowed_values, list) else validate.Regexp(allowed_values)


def _camelcase(s):

    parts = iter(s.split("_"))
    return "".join(i.title() for i in parts)


class BaseSchema(Schema):
    """Represent a base schema, containing all the features required by all the Schema classes."""

    def on_bind_field(self, field_name, field_obj):
        """
        Bind CamelCase in the config with with snake_case in Python.

        For example, subnet_id in the code is automatically bind with SubnetId in the config file.
        The bind can be overwritten by specifying data_key.
        For example, `EBS` in the config file is not CamelCase, we have to bind it with ebs manually.
        """
        if field_obj.data_key is None:
            field_obj.data_key = _camelcase(field_name)

    @pre_load
    def evaluate_dynamic_defaults(self, raw_data, **kwargs):
        """Evaluate dynamic default, it's just an example to be removed."""
        # FIXME to be removed, it's a test
        for fieldname, field in self.fields.items():
            if fieldname not in raw_data and callable(field.metadata.get("dynamic_default")):
                raw_data[fieldname] = field.metadata.get("dynamic_default")(raw_data)
        return raw_data

    @pre_dump
    def remove_implied_values(self, data, **kwargs):
        """Remove value implied by the code. i.e., only keep parameters that were specified in the yaml file."""
        for key, value in vars(data).copy().items():
            if _is_implied(value):
                delattr(data, key)
        return data

    @post_dump
    def remove_none_values(self, data, **kwargs):
        """Remove None values before creating the Yaml format."""
        return {key: value for key, value in data.items() if value is not None}


def _is_implied(value):
    return hasattr(value, "implied") and value.implied


# ---------------------- Storage ---------------------- #
class BaseEbsSchema(BaseSchema):
    """Represent the schema of shared by EBS and RootVolume section."""

    volume_type = fields.Str(validate=validate.OneOf(["standard", "io1", "io2", "gp2", "st1", "sc1", "gp3"]))
    iops = fields.Int()
    size = fields.Int()
    kms_key_id = fields.Str()
    throughput = fields.Int()
    encrypted = fields.Bool()

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return BaseEbsConfig(**data)


class RaidSchema(BaseSchema):
    """Represent the schema of the parameters specific to Raid. It is a child of EBS schema."""

    raid_type = fields.Str(data_key="Type", validate=validate.OneOf(["0", "1"]))
    number_of_volumes = fields.Int(validate=validate.Range(min=2, max=5))

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return RaidConfig(**data)


class EbsSchema(BaseEbsSchema):
    """Represent the schema of EBS."""

    snapshot_id = fields.Str(validate=validate.Regexp(r"^snap-[0-9a-z]{8}$|^snap-[0-9a-z]{17}$"))
    volume_id = fields.Str(validate=validate.Regexp(r"^vol-[0-9a-z]{8}$|^vol-[0-9a-z]{17}$"))
    raid = fields.Nested(RaidSchema)

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return EbsConfig(**data)


class EphemeralVolumeSchema(BaseSchema):
    """Represent the schema of ephemeral volume.It is a child of storage schema."""

    encrypted = fields.Bool()
    mount_dir = fields.Str(validate=_get_field_validator("file_path"))

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return EphemeralVolumeConfig(**data)


class StorageSchema(BaseSchema):
    """Represent the schema of root volume."""

    root_volume = fields.Nested(BaseEbsSchema)
    ephemeral_volume = fields.Nested(EphemeralVolumeSchema)

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return StorageConfig(**data)


class EfsSchema(BaseSchema):
    """Represent the schema of EFS."""

    encrypted = fields.Bool()
    kms_key_id = fields.Str()
    performance_mode = fields.Str(validate=validate.OneOf(["generalPurpose", "maxIO"]))
    throughput_mode = fields.Str(validate=validate.OneOf(["provisioned", "bursting"]))
    provisioned_throughput = fields.Int(validate=validate.Range(min=0, max=1024))
    file_system_id = fields.Str(validate=validate.Regexp(r"^fs-[0-9a-z]{8}$|^fs-[0-9a-z]{17}$"))

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return EfsConfig(**data)

    @validates_schema
    def validate_existence_of_mode_throughput(self, data, **kwargs):
        """Validate the conditional existence requirement between throughput_mode and provisioned_throughput."""
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
    """Represent the schema of FSX."""

    storage_capacity = fields.Int()
    deployment_type = fields.Str(validate=validate.OneOf(["SCRATCH_1", "SCRATCH_2", "PERSISTENT_1"]))
    imported_file_chunk_size = fields.Int(
        validate=validate.Range(min=1, max=512000, error="has a minimum size of 1 MiB, and max size of 512,000 MiB")
    )
    export_path = fields.Str()
    import_path = fields.Str()
    weekly_maintenance_start_time = fields.Str(validate=validate.Regexp(r"^[1-7]:([01]\d|2[0-3]):([0-5]\d)$"))
    automatic_backup_retention_days = fields.Int(validate=validate.Range(min=0, max=35))
    copy_tags_to_backups = fields.Bool()
    daily_automatic_backup_start_time = fields.Str(validate=validate.Regexp(r"^([01]\d|2[0-3]):([0-5]\d)$"))
    per_unit_storage_throughput = fields.Int(validate=validate.OneOf(FSX_SSD_THROUGHPUT + FSX_HDD_THROUGHPUT))
    backup_id = fields.Str(validate=validate.Regexp("^(backup-[0-9a-f]{8,})$"))
    kms_key_id = fields.Str()
    file_system_id = fields.Str(validate=validate.Regexp(r"^fs-[0-9a-z]{17}$"))
    auto_import_policy = fields.Str(validate=validate.OneOf(["NEW", "NEW_CHANGED"]))
    drive_cache_type = fields.Str(validate=validate.OneOf(["READ"]))
    storage_type = fields.Str(validate=validate.OneOf(["HDD", "SSD"]))

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return FsxConfig(**data)


class SharedStorageSchema(BaseSchema):
    """Represent the generic SharedStorage schema."""

    mount_dir = fields.Str(required=True, validate=_get_field_validator("file_path"))
    ebs_settings = fields.Nested(EbsSchema, data_key="EBS")
    efs_settings = fields.Nested(EfsSchema, data_key="EFS")
    fsx_settings = fields.Nested(FsxSchema, data_key="FSxLustre")

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return SharedStorageConfig(**data)

    @validates("mount_dir")
    def validate_not_none_dir(self, value):
        """Validate that user is not specifying /NONE or NONE as MountDir for any filesystem."""
        if re.match("^/?NONE$", value):
            raise ValidationError(f"{value} cannot be used as a mount directory")

    @validates_schema
    def validate_existence_of_settings(self, data, **kwargs):
        """Validate that there is one and only one setting."""
        count = 0
        if data.get("ebs_settings"):
            count += 1
        if data.get("efs_settings"):
            count += 1
        if data.get("fsx_settings"):
            count += 1
        if count != 1:
            raise ValidationError(
                "You must provide one and only one configuration," " choosing among EBS, FSx, EFS in Shared Storage"
            )


# ---------------------- Networking ---------------------- #
class ProxySchema(BaseSchema):
    """Represent the schema of proxy."""

    http_proxy_address = fields.Str()

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return ProxyConfig(**data)


class BaseNetworkingSchema(BaseSchema):
    """Represent the schema of common networking parameters used by head and compute nodes."""

    additional_security_groups = fields.List(fields.Str(validate=_get_field_validator("security_group_id")))
    assign_public_ip = fields.Bool()
    security_groups = fields.List(fields.Str(validate=_get_field_validator("security_group_id")))
    proxy = fields.Nested(ProxySchema)


class HeadNodeNetworkingSchema(BaseNetworkingSchema):
    """Represent the schema of the Networking, child of the HeadNode."""

    subnet_id = fields.Str(required=True, validate=_get_field_validator("subnet_id"))
    elastic_ip = fields.Str()

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return HeadNodeNetworkingConfig(**data)


class PlacementGroupSchema(BaseSchema):
    """Represent the schema of placement group."""

    enabled = fields.Bool()
    id = fields.Str()

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return PlacementGroupConfig(**data)


class QueueNetworkingSchema(BaseNetworkingSchema):
    """Represent the schema of the Networking, child of Queue."""

    subnet_ids = fields.List(fields.Str(validate=_get_field_validator("subnet_id")), required=True)
    placement_group = fields.Nested(PlacementGroupSchema)

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return QueueNetworkingConfig(**data)


class SshSchema(BaseSchema):
    """Represent the schema of the SSH."""

    key_name = fields.Str(required=True)
    allowed_ips = fields.Str(validate=_get_field_validator("cidr"))

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return SshConfig(**data)


class DcvSchema(BaseSchema):
    """Represent the schema of DCV."""

    enabled = fields.Bool()
    port = fields.Int()
    allowed_ips = fields.Str(validate=_get_field_validator("cidr"))

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return DcvConfig(**data)


# ---------------------- Nodes ---------------------- #
class ImageSchema(BaseSchema):
    """Represent the schema of the Image."""

    os = fields.Str(required=True)
    custom_ami = fields.Str(validate=validate.Regexp(r"^ami-[0-9a-z]{8}$|^ami-[0-9a-z]{17}$"))

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return ImageConfig(**data)


class HeadNodeSchema(BaseSchema):
    """Represent the schema of the HeadNode."""

    instance_type = fields.Str(required=True)
    networking = fields.Nested(HeadNodeNetworkingSchema, required=True)
    ssh = fields.Nested(SshSchema, required=True)
    image = fields.Nested(ImageSchema)
    storage = fields.Nested(StorageSchema)
    dcv = fields.Nested(DcvSchema)

    @post_load()
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return HeadNodeConfig(**data)


class ComputeResourceSchema(BaseSchema):
    """Represent the schema of the ComputeResource."""

    instance_type = fields.Str(required=True)
    max_count = fields.Int()

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return ComputeResourceConfig(**data)


class QueueSchema(BaseSchema):
    """Represent the schema of the Queue."""

    name = fields.Str()
    networking = fields.Nested(QueueNetworkingSchema, required=True)
    compute_resources = fields.Nested(ComputeResourceSchema, many=True)
    storage = fields.Nested(StorageSchema)
    compute_type = fields.Str(validate=validate.OneOf(["ONDEMAND", "SPOT"]))
    image = fields.Nested(ImageSchema)

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return QueueConfig(**data)


class SchedulingSettingsSchema(BaseSchema):
    """Represent the schema of the Scheduling Settings."""

    scaledown_idletime = fields.Int(data_key="ScaleDownIdleTime")

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return SchedulingSettingsConfig(**data)


class SchedulingSchema(BaseSchema):
    """Represent the schema of the Scheduling."""

    scheduler = fields.Str(required=True, validate=validate.OneOf(["slurm", "awsbatch"]))
    settings = fields.Nested(SchedulingSettingsSchema)
    queues = fields.Nested(QueueSchema, many=True, required=True)

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return SchedulingConfig(**data)


class CustomActionSchema(BaseSchema):
    """Represent the schema of the custom action."""

    script = fields.Str(required=True, validate=validate.URL(schemes=["s3", "https", "file"]))
    args = fields.List(fields.Str())
    event = fields.Str(validate=validate.OneOf(["NODE_START", "NODE_CONFIGURED"]))
    run_as = fields.Str()

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return CustomActionConfig(**data)


# ---------------------- Monitoring ---------------------- #
class CloudWatchLogsSchema(BaseSchema):
    """Represent the schema of the SharedStorage with type = EFS."""

    enabled = fields.Bool()
    retention_in_days = fields.Int()
    log_group_id = fields.Str()
    kms_key_id = fields.Str()

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return CloudWatchLogsConfig(**data)


class CloudWatchDashboardsSchema(BaseSchema):
    """Represent the schema of the SharedStorage with type = EFS."""

    enabled = fields.Bool()

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return CloudWatchDashboardsConfig(**data)


class LogsSchema(BaseSchema):
    """Represent the schema of the SharedStorage with type = EFS."""

    cloud_watch = fields.Nested(CloudWatchLogsSchema)

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return LogsConfig(**data)


class DashboardsSchema(BaseSchema):
    """Represent the schema of the SharedStorage with type = EFS."""

    cloud_watch = fields.Nested(CloudWatchDashboardsSchema)

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return DashboardsConfig(**data)


class MonitoringSchema(BaseSchema):
    """Represent the schema of the SharedStorage with type = EFS."""

    detailed_monitoring = fields.Bool()
    logs = fields.Nested(LogsSchema)
    dashboards = fields.Nested(DashboardsSchema)

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return MonitoringConfig(**data)


# ---------------------- Others ---------------------- #
class TagSchema(BaseSchema):
    """Represent the schema of tag."""

    key = fields.Str()
    value = fields.Str()

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return TagConfig(**data)


class RolesSchema(BaseSchema):
    """Represent the schema of roles."""

    head_node = fields.Str()
    compute_node = fields.Str()
    custom_lambda_resources = fields.Str()

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return RolesConfig(**data)


class S3AccessSchema(BaseSchema):
    """Represent the schema of S3 access."""

    bucket_name = fields.Str(required=True)
    type = fields.Str()

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return S3AccessConfig(**data)


class AdditionalIamPolicySchema(BaseSchema):
    """Represent the schema of Additional IAM policy."""

    policy = fields.Str(required=True)
    scope = fields.Str()

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return AdditionalIamPolicyConfig(**data)


class IamSchema(BaseSchema):
    """Represent the schema of IAM."""

    roles = fields.Nested(RolesSchema)
    s3_access = fields.Nested(S3AccessSchema, many=True)
    additional_iam_policies = fields.Nested(AdditionalIamPolicySchema, data_key="AdditionalIAMPolicies", many=True)

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return IamConfig(**data)


# ---------------------- Root Schema ---------------------- #
class ClusterSchema(BaseSchema):
    """Represent the schema of the Cluster."""

    image = fields.Nested(ImageSchema, required=True)
    head_node = fields.Nested(HeadNodeSchema, required=True)
    scheduling = fields.Nested(SchedulingSchema, required=True)
    shared_storage = fields.Nested(SharedStorageSchema, many=True)

    monitoring = fields.Nested(MonitoringSchema)
    tags = fields.Nested(TagSchema, many=True)
    custom_actions = fields.Nested(CustomActionSchema, many=True)
    iam = fields.Nested(IamSchema, data_key="IAM")

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return ClusterConfig(**data)

    '''
    @pre_load
    def move_image(self, input_data, **kwargs):
        """Move image field into the head node."""
        # If image is not present in the Head node we can use the one from the Cluster
        input_data["HeadNode"]["Image"] = input_data["Image"]
        return input_data
    '''
