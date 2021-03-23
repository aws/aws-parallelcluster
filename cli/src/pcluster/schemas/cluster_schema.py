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

from pcluster.constants import EBS_VOLUME_SIZE_DEFAULT, FSX_HDD_THROUGHPUT, FSX_SSD_THROUGHPUT, SUPPORTED_OSES
from pcluster.models.cluster_config import (
    AdditionalIamPolicy,
    AdditionalPackages,
    AwsbatchClusterConfig,
    AwsbatchComputeResource,
    AwsbatchQueue,
    AwsbatchScheduling,
    BaseClusterConfig,
    CloudWatchDashboards,
    CloudWatchLogs,
    ClusterDevSettings,
    ClusterIam,
    CommonSchedulingSettings,
    ComputeType,
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

# ---------------------- Storage ---------------------- #


class _BaseEbsSchema(BaseSchema):
    """Represent the schema shared by SharedEBS and RootVolume section."""

    size = fields.Int()
    encrypted = fields.Bool()


class RootVolumeSchema(_BaseEbsSchema):
    """Represent the RootVolume schema."""

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

    raid_type = fields.Int(data_key="Type", validate=validate.OneOf([0, 1]))
    number_of_volumes = fields.Int(validate=validate.Range(min=2, max=5))

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Raid(**data)


class EbsSchema(_BaseEbsSchema):
    """Represent the schema of EBS."""

    iops = fields.Int()
    kms_key_id = fields.Str()
    throughput = fields.Int()
    snapshot_id = fields.Str(validate=validate.Regexp(r"^snap-[0-9a-z]{8}$|^snap-[0-9a-z]{17}$"))
    volume_id = fields.Str(validate=validate.Regexp(r"^vol-[0-9a-z]{8}$|^vol-[0-9a-z]{17}$"))
    volume_type = fields.Str(validate=get_field_validator("volume_type"))
    raid = fields.Nested(RaidSchema)


class EphemeralVolumeSchema(BaseSchema):
    """Represent the schema of ephemeral volume.It is a child of storage schema."""

    encrypted = fields.Bool()
    mount_dir = fields.Str(validate=get_field_validator("file_path"))

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return EphemeralVolume(**data)


class LocalStorageSchema(BaseSchema):
    """Represent the schema of local storage attached to a node."""

    root_volume = fields.Nested(RootVolumeSchema)
    ephemeral_volume = fields.Nested(EphemeralVolumeSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return LocalStorage(**data)


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
    fsx_storage_type = fields.Str(data_key="StorageType", validate=validate.OneOf(["HDD", "SSD"]))

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
    name = fields.Str(required=True)
    storage_type = fields.Str(required=True, validate=validate.OneOf(["Ebs", "FsxLustre", "Efs"]))
    ebs = fields.Nested(EbsSchema)
    efs = fields.Nested(EfsSchema)
    fsx = fields.Nested(FsxSchema)

    @pre_load
    def preprocess(self, data, **kwargs):
        """Before load the data into schema, change the settings to adapt different storage types."""
        try:
            if data.get("StorageType") == "Efs":
                data["Efs"] = data.pop("Settings")
            elif data.get("StorageType") == "Ebs":
                data["Ebs"] = data.pop("Settings")
            elif data.get("StorageType") == "FsxLustre":
                data["Fsx"] = data.pop("Settings")
            return data
        except IndexError as exception:
            raise ValidationError(f" Settings is required to be set for SharedStorage: {exception}")

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate the right type of shared storage according to the child type (EBS vs EFS vs FSx)."""
        if data.get("efs"):
            return SharedEfs(data.get("mount_dir"), data.get("name"), **data.get("efs"))
        if data.get("fsx"):
            return SharedFsx(data.get("mount_dir"), data.get("name"), **data.get("fsx"))
        if data.get("ebs"):
            return SharedEbs(data.get("mount_dir"), data.get("name"), **data.get("ebs"))
        return None

    @pre_dump
    def restore_child(self, data, **kwargs):
        """Restore back the child in the schema."""
        child = copy.copy(data)
        storage_type = "ebs" if data.shared_storage_type.value == "raid" else data.shared_storage_type.value
        setattr(data, storage_type, child)
        data.storage_type = "FsxLustre" if data.shared_storage_type.value == "fsx" else storage_type.capitalize()
        return data

    @post_dump
    def post_processed(self, data, **kwargs):
        """Restore the SharedStorage Schema back to its origin."""
        if data.get("Efs"):
            data["Settings"] = data.pop("Efs")
        elif data.get("Ebs"):
            data["Settings"] = data.pop("Ebs")
        elif data.get("Fsx"):
            data["Settings"] = data.pop("Fsx")
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

    @validates_schema
    def only_one_storage(self, data, **kwargs):
        """Validate that there is one and only one setting."""
        if self.fields_coexist(data=data, field_list=["ebs", "efs", "fsx"], one_required=True, **kwargs):
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

    @validates_schema
    def no_coexist_security_groups(self, data, **kwargs):
        """Validate that security_groups and additional_security_groups are not co-exist."""
        if self.fields_coexist(data, ["security_groups", "additional_security_groups"], **kwargs):
            raise ValidationError("SecurityGroups and AdditionalSecurityGroups can not be configured together.")


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

    subnet_ids = fields.List(
        fields.Str(validate=get_field_validator("subnet_id")), validate=validate.Length(equal=1), required=True
    )
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

    custom_lambda_resources = fields.Str()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Roles(**data)


class S3AccessSchema(BaseSchema):
    """Represent the schema of S3 access."""

    bucket_name = fields.Str(required=True)
    enable_write_access = fields.Bool()

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


class ClusterIamSchema(BaseSchema):
    """Represent the schema of IAM for Cluster."""

    roles = fields.Nested(RolesSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ClusterIam(**data)


class IamSchema(BaseSchema):
    """Represent the schema of IAM for HeadNode and Queue."""

    instance_role = fields.Str()
    s3_access = fields.Nested(S3AccessSchema, many=True)
    additional_iam_policies = fields.Nested(AdditionalIamPolicySchema, many=True)

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

    os = fields.Str(required=True, validate=validate.OneOf(SUPPORTED_OSES))
    custom_ami = fields.Str(validate=validate.Regexp(r"^ami-[0-9a-z]{8}$|^ami-[0-9a-z]{17}$"))

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Image(**data)


class CustomActionSchema(BaseSchema):
    """Represent the schema of the custom action."""

    script = fields.Str(required=True)
    args = fields.List(fields.Str())
    event = fields.Str(validate=validate.OneOf([event.value for event in CustomActionEvent]))

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return CustomAction(**data)


class HeadNodeSchema(BaseSchema):
    """Represent the schema of the HeadNode."""

    instance_type = fields.Str(required=True)
    disable_simultaneous_multithreading = fields.Bool()
    networking = fields.Nested(HeadNodeNetworkingSchema, required=True)
    ssh = fields.Nested(SshSchema, required=True)
    local_storage = fields.Nested(LocalStorageSchema)
    dcv = fields.Nested(DcvSchema)
    custom_actions = fields.Nested(
        CustomActionSchema, many=True
    )  # TODO validate to avoid more than one script for event type or add support for them.
    iam = fields.Nested(IamSchema)

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return HeadNode(**data)


class _ComputeResourceSchema(BaseSchema):
    """Represent the schema of the ComputeResource."""

    name = fields.Str(required=True)
    disable_simultaneous_multithreading = fields.Bool()
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

    instance_types = fields.Str()  # TODO it is a comma separated list
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
    local_storage = fields.Nested(LocalStorageSchema)
    compute_type = fields.Str(validate=validate.OneOf([event.value for event in ComputeType]))
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
        if self.fields_coexist(data=data, field_list=["slurm", "awsbatch", "custom"], one_required=True, **kwargs):
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
    iam = fields.Nested(ClusterIamSchema)
    cluster_s3_bucket = fields.Str()
    additional_resources = fields.Str()
    dev_settings = fields.Nested(ClusterDevSettingsSchema)

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
