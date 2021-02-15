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

from marshmallow import ValidationError, fields, post_load, pre_dump, validate, validates, validates_schema

from pcluster.constants import FSX_HDD_THROUGHPUT, FSX_SSD_THROUGHPUT
from pcluster.models.cluster import (
    AdditionalIamPolicy,
    AdditionalPackages,
    CloudWatchDashboards,
    CloudWatchLogs,
    ClusterDevSettings,
    CommonSchedulingSettings,
    CustomAction,
    Dashboards,
    Dcv,
    Ebs,
    Efa,
    EphemeralVolume,
    HeadNode,
    HeadNodeNetworking,
    Iam,
    Image,
    IntelSelectSolutions,
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
    Ssh,
    Storage,
)
from pcluster.models.cluster_awsbatch import AwsbatchCluster, AwsbatchComputeResource, AwsbatchQueue, AwsbatchScheduling
from pcluster.models.cluster_slurm import (
    Dns,
    SlurmCluster,
    SlurmComputeResource,
    SlurmQueue,
    SlurmScheduling,
    SlurmSettings,
)
from pcluster.schemas.common_schema import BaseDevSettingsSchema, BaseSchema, TagSchema, get_field_validator
from pcluster.validators.cluster_validators import FSX_MESSAGES

# ---------------------- Storage ---------------------- #


class _BaseEbsSchema(BaseSchema):
    """Represent the schema shared by SharedEBS and RootVolume section."""

    volume_type = fields.Str(validate=validate.OneOf(["standard", "io1", "io2", "gp2", "st1", "sc1", "gp3"]))
    iops = fields.Int()
    size = fields.Int()
    kms_key_id = fields.Str()
    throughput = fields.Int()
    encrypted = fields.Bool()


class RootVolumeSchema(_BaseEbsSchema):
    """Represent the RootVolume schema."""

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Ebs(**data)

    @validates("size")
    def validate_size(self, value):
        """Validate the size of root volume is at least 25."""
        if value < 25:
            raise ValidationError(f"Root volume size {value} is invalid. It must be at least 25.")


class RaidSchema(BaseSchema):
    """Represent the schema of the parameters specific to Raid. It is a child of EBS schema."""

    raid_type = fields.Int(data_key="Type", validate=validate.OneOf([0, 1]))
    number_of_volumes = fields.Int(validate=validate.Range(min=2, max=5))

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Raid(**data)


class EbsSchema(_BaseEbsSchema):
    """Represent the schema of EBS."""

    snapshot_id = fields.Str(validate=validate.Regexp(r"^snap-[0-9a-z]{8}$|^snap-[0-9a-z]{17}$"))
    volume_id = fields.Str(validate=validate.Regexp(r"^vol-[0-9a-z]{8}$|^vol-[0-9a-z]{17}$"))
    raid = fields.Nested(RaidSchema)


class EphemeralVolumeSchema(BaseSchema):
    """Represent the schema of ephemeral volume.It is a child of storage schema."""

    encrypted = fields.Bool()
    mount_dir = fields.Str(validate=get_field_validator("file_path"))

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return EphemeralVolume(**data)


class StorageSchema(BaseSchema):
    """Represent the schema of storage attached to a node."""

    root_volume = fields.Nested(RootVolumeSchema)
    ephemeral_volume = fields.Nested(EphemeralVolumeSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Storage(**data)


class EfsSchema(BaseSchema):
    """Represent the EFS schema."""

    encrypted = fields.Bool()
    kms_key_id = fields.Str()
    performance_mode = fields.Str(validate=validate.OneOf(["generalPurpose", "maxIO"]))
    throughput_mode = fields.Str(validate=validate.OneOf(["provisioned", "bursting"]))
    provisioned_throughput = fields.Int(validate=validate.Range(min=1, max=1024))
    file_system_id = fields.Str(validate=validate.Regexp(r"^fs-[0-9a-z]{8}$|^fs-[0-9a-z]{17}$"))

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

    mount_dir = fields.Str(required=True, validate=get_field_validator("file_path"))
    ebs = fields.Nested(EbsSchema)
    efs = fields.Nested(EfsSchema)
    fsx = fields.Nested(FsxSchema, data_key="FsxLustre")

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate the right type of shared storage according to the child type (EBS vs EFS vs FSx)."""
        if data.get("efs"):
            return SharedEfs(data.get("mount_dir"), **data.get("efs"))
        if data.get("fsx"):
            return SharedFsx(data.get("mount_dir"), **data.get("fsx"))
        if data.get("ebs"):
            return SharedEbs(data.get("mount_dir"), **data.get("ebs"))
        return None

    @pre_dump
    def restore_child(self, data, **kwargs):
        """Restore back the child in the schema."""
        child = copy.copy(data)
        setattr(data, data.shared_storage_type.value, child)
        return data

    @validates_schema
    def only_one_storage(self, data, **kwargs):
        """Validate that there is one and only one setting."""
        if not self.only_one_field(data, ["ebs", "efs", "fsx"], **kwargs):
            raise ValidationError(
                "You must provide one and only one configuration, choosing among EBS, FSx, EFS in Shared Storage"
            )


# ---------------------- Networking ---------------------- #


class ProxySchema(BaseSchema):
    """Represent the schema of proxy."""

    http_proxy_address = fields.Str()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Proxy(**data)


class BaseNetworkingSchema(BaseSchema):
    """Represent the schema of common networking parameters used by head and compute nodes."""

    additional_security_groups = fields.List(fields.Str(validate=get_field_validator("security_group_id")))
    assign_public_ip = fields.Bool()
    security_groups = fields.List(fields.Str(validate=get_field_validator("security_group_id")))
    proxy = fields.Nested(ProxySchema)


class HeadNodeNetworkingSchema(BaseNetworkingSchema):
    """Represent the schema of the Networking, child of the HeadNode."""

    subnet_id = fields.Str(required=True, validate=get_field_validator("subnet_id"))
    elastic_ip = fields.Str()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return HeadNodeNetworking(**data)


class PlacementGroupSchema(BaseSchema):
    """Represent the schema of placement group."""

    enabled = fields.Bool()
    id = fields.Str()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return PlacementGroup(**data)


class QueueNetworkingSchema(BaseNetworkingSchema):
    """Represent the schema of the Networking, child of Queue."""

    subnet_ids = fields.List(fields.Str(validate=get_field_validator("subnet_id")), required=True)
    placement_group = fields.Nested(PlacementGroupSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return QueueNetworking(**data)


class SshSchema(BaseSchema):
    """Represent the schema of the SSH."""

    key_name = fields.Str(required=True)
    allowed_ips = fields.Str(validate=get_field_validator("cidr"))

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Ssh(**data)


class DcvSchema(BaseSchema):
    """Represent the schema of DCV."""

    enabled = fields.Bool()
    port = fields.Int()
    allowed_ips = fields.Str(validate=get_field_validator("cidr"))

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Dcv(**data)


class EfaSchema(BaseSchema):
    """Represent the schema of EFA."""

    enabled = fields.Bool()
    gdr_support = fields.Bool()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Efa(**data)


# ---------------------- Monitoring ---------------------- #


class CloudWatchLogsSchema(BaseSchema):
    """Represent the schema of the CloudWatchLogs section."""

    enabled = fields.Bool()
    retention_in_days = fields.Int(
        validate=validate.OneOf([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653])
    )
    log_group_id = fields.Str()
    kms_key_id = fields.Str()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CloudWatchLogs(**data)


class CloudWatchDashboardsSchema(BaseSchema):
    """Represent the schema of the CloudWatchDashboards section."""

    enabled = fields.Bool()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CloudWatchDashboards(**data)


class LogsSchema(BaseSchema):
    """Represent the schema of the Logs section."""

    cloud_watch = fields.Nested(CloudWatchLogsSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Logs(**data)


class DashboardsSchema(BaseSchema):
    """Represent the schema of the Dashboards section."""

    cloud_watch = fields.Nested(CloudWatchDashboardsSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Dashboards(**data)


class MonitoringSchema(BaseSchema):
    """Represent the schema of the Monitoring section."""

    detailed_monitoring = fields.Bool()
    logs = fields.Nested(LogsSchema)
    dashboards = fields.Nested(DashboardsSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Monitoring(**data)


# ---------------------- Others ---------------------- #


class RolesSchema(BaseSchema):
    """Represent the schema of roles."""

    instance_role = fields.Str()
    custom_lambda_resources = fields.Str()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Roles(**data)


class S3AccessSchema(BaseSchema):
    """Represent the schema of S3 access."""

    bucket_name = fields.Str(required=True)
    type = fields.Str(validate=validate.OneOf(["READ_ONLY", "READ_WRITE"]))

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return S3Access(**data)


class AdditionalIamPolicySchema(BaseSchema):
    """Represent the schema of Additional IAM policy."""

    policy = fields.Str(required=True)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AdditionalIamPolicy(**data)


class IamSchema(BaseSchema):
    """Represent the schema of IAM."""

    roles = fields.Nested(RolesSchema)
    s3_access = fields.Nested(S3AccessSchema, many=True)
    additional_iam_policies = fields.Nested(AdditionalIamPolicySchema, many=True)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Iam(**data)


class IntelSelectSolutionsSchema(BaseSchema):
    """Represent the schema of additional packages."""

    install_intel_software = fields.Bool()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return IntelSelectSolutions(**data)


class AdditionalPackagesSchema(BaseSchema):
    """Represent the schema of additional packages."""

    intel_select_solutions = fields.Nested(IntelSelectSolutionsSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AdditionalPackages(**data)


class ClusterDevSettingsSchema(BaseDevSettingsSchema):
    """Represent the schema of Dev Setting."""

    cluster_template = fields.Str()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ClusterDevSettings(**data)


# ---------------------- Node and Cluster Schema ---------------------- #


class ImageSchema(BaseSchema):
    """Represent the schema of the Image."""

    os = fields.Str(required=True, validate=validate.OneOf(["alinux2", "ubuntu1804", "centos7", "centos8"]))
    custom_ami = fields.Str(validate=validate.Regexp(r"^ami-[0-9a-z]{8}$|^ami-[0-9a-z]{17}$"))

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Image(**data)


class CustomActionSchema(BaseSchema):
    """Represent the schema of the custom action."""

    script = fields.Str(required=True)
    args = fields.List(fields.Str())
    event = fields.Str(validate=validate.OneOf(["NODE_START", "NODE_CONFIGURED"]))
    run_as = fields.Str()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CustomAction(**data)


class HeadNodeSchema(BaseSchema):
    """Represent the schema of the HeadNode."""

    instance_type = fields.Str(required=True)
    simultaneous_multithreading = fields.Bool()
    networking = fields.Nested(HeadNodeNetworkingSchema, required=True)
    image = fields.Nested(ImageSchema)
    ssh = fields.Nested(SshSchema, required=True)
    storage = fields.Nested(StorageSchema)
    dcv = fields.Nested(DcvSchema)
    efa = fields.Nested(EfaSchema)
    custom_actions = fields.Nested(CustomActionSchema, many=True)
    iam = fields.Nested(IamSchema)

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return HeadNode(**data)


class _ComputeResourceSchema(BaseSchema):
    """Represent the schema of the ComputeResource."""

    name = fields.Str(required=True)
    allocation_strategy = fields.Str()
    simultaneous_multithreading = fields.Bool()
    efa = fields.Nested(EfaSchema)


class SlurmComputeResourceSchema(_ComputeResourceSchema):
    """Represent the schema of the Slurm ComputeResource."""

    instance_type = fields.Str(required=True)
    max_count = fields.Int(validate=validate.Range(min=1))
    min_count = fields.Int(validate=validate.Range(min=0))
    spot_price = fields.Float(validate=validate.Range(min=0))

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SlurmComputeResource(**data)


class AwsbatchComputeResourceSchema(_ComputeResourceSchema):
    """Represent the schema of the Batch ComputeResource."""

    instance_type = fields.Str(required=True)  # TODO it is a comma separated list
    max_vcpus = fields.Int(data_key="MaxvCpus", validate=validate.Range(min=1))
    min_vcpus = fields.Int(data_key="MinvCpus", validate=validate.Range(min=0))
    desired_vcpus = fields.Int(data_key="DesiredvCpus", validate=validate.Range(min=0))
    spot_bid_percentage = fields.Float(validate=validate.Range(min=0, max=1, min_inclusive=False))

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AwsbatchComputeResource(**data)


class BaseQueueSchema(BaseSchema):
    """Represent the schema of the attributes in common between all the schedulers queues."""

    name = fields.Str()
    networking = fields.Nested(QueueNetworkingSchema, required=True)
    storage = fields.Nested(StorageSchema)
    compute_type = fields.Str(validate=validate.OneOf(["ONDEMAND", "SPOT"]))
    image = fields.Nested(ImageSchema)
    iam = fields.Nested(IamSchema)


class SlurmQueueSchema(BaseQueueSchema):
    """Represent the schema of a Slurm Queue."""

    compute_resources = fields.Nested(SlurmComputeResourceSchema, many=True)
    custom_actions = fields.Nested(CustomActionSchema, many=True)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SlurmQueue(**data)


class AwsbatchQueueSchema(BaseQueueSchema):
    """Represent the schema of a Batch Queue."""

    compute_resources = fields.Nested(AwsbatchComputeResourceSchema, many=True, validate=validate.Length(equal=1))

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AwsbatchQueue(**data)


class _BaseSchedulerSettingsSchema(BaseSchema):
    """Represent the schema of the common scheduler settings."""

    scaledown_idletime = fields.Int()


class AwsbatchSettingsSchema(_BaseSchedulerSettingsSchema):
    """Represent the schema of the Awsbatch Settings."""

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CommonSchedulingSettings(**data)


class DnsSchema(BaseSchema):
    """Represent the schema of Dns Settings."""

    disable_managed_dns = fields.Bool()
    domain = fields.Str()
    hosted_zone_id = fields.Str()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Dns(**data)


class SlurmSettingsSchema(_BaseSchedulerSettingsSchema):
    """Represent the schema of the Scheduling Settings."""

    dns = fields.Nested(DnsSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return SlurmSettings(**data)


class SlurmSchema(BaseSchema):
    """Represent the schema of the Slurm section."""

    settings = fields.Nested(SlurmSettingsSchema)
    queues = fields.Nested(SlurmQueueSchema, many=True, required=True)


class AwsbatchSchema(BaseSchema):
    """Represent the schema of the Awsbatch section."""

    settings = fields.Nested(AwsbatchSettingsSchema)
    queues = fields.Nested(AwsbatchQueueSchema, many=True, required=True, validate=validate.Length(equal=1))


class SchedulingSchema(BaseSchema):
    """Represent the schema of the Scheduling."""

    slurm = fields.Nested(SlurmSchema)
    awsbatch = fields.Nested(AwsbatchSchema)
    # custom = fields.Str(CustomSchema)

    @validates_schema
    def only_one_scheduling_type(self, data, **kwargs):
        """Validate that there is one and only one type of scheduling."""
        if not self.only_one_field(data, ["slurm", "awsbatch", "custom"], **kwargs):
            raise ValidationError("You must provide scheduler configuration")

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


class ClusterSchema(BaseSchema):
    """Represent the schema of the Cluster."""

    image = fields.Nested(ImageSchema, required=True)
    head_node = fields.Nested(HeadNodeSchema, required=True)
    scheduling = fields.Nested(SchedulingSchema, required=True)
    shared_storage = fields.Nested(SharedStorageSchema, many=True)

    monitoring = fields.Nested(MonitoringSchema)
    additional_packages = fields.Nested(AdditionalPackagesSchema)
    tags = fields.Nested(TagSchema, many=True)
    iam = fields.Nested(IamSchema)
    cluster_s3_bucket = fields.Str()
    additional_resources = fields.Str()
    dev_settings = fields.Nested(ClusterDevSettingsSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        if data.get("scheduling").scheduler == "slurm":
            return SlurmCluster(**data)
        if data.get("scheduling").scheduler == "awsbatch":
            return AwsbatchCluster(**data)
        return None
