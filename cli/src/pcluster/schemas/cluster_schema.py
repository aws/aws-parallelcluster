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

from marshmallow import Schema, ValidationError, fields, post_dump, post_load, pre_load

from pcluster.config.cluster_config import (
    ClusterConfig,
    ComputeResourceConfig,
    EbsConfig,
    EfsConfig,
    FsxConfig,
    HeadNodeConfig,
    HeadNodeNetworkingConfig,
    ImageConfig,
    QueueConfig,
    QueueNetworkingConfig,
    SchedulingConfig,
    SharedStorageType,
    SshConfig,
)


class BaseSchema(Schema):
    """Represent a base schema, containing all the features required by all the Schema classes."""

    @pre_load
    def evaluate_dynamic_defaults(self, raw_data, **kwargs):
        """Example of dynamic default evaluation."""
        # FIXME to be removed, it's a test
        for fieldname, field in self.fields.items():
            if fieldname not in raw_data and callable(field.metadata.get("dynamic_default")):
                raw_data[fieldname] = field.metadata.get("dynamic_default")(raw_data)
        return raw_data

    @post_dump
    def remove_none_values(self, data, **kwargs):
        """Remove None values before creating the Yaml format."""
        return {key: value for key, value in data.items() if value is not None}


class ImageSchema(BaseSchema):
    """Represent the schema of the Image."""

    os = fields.Str(data_key="Os", required=True)
    id = fields.Str(data_key="CustomAmi")

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return ImageConfig(**data)


class HeadNodeNetworkingSchema(BaseSchema):
    """Represent the schema of the Networking, child of the HeadNode."""

    subnet_id = fields.Str(data_key="SubnetId", required=True)
    elastic_ip = fields.Str(data_key="ElasticIp")
    assign_public_ip = fields.Bool(data_key="AssignPublicIp")
    security_groups = fields.List(fields.Str, data_key="SecurityGroups")
    additional_security_groups = fields.List(fields.Str, data_key="AdditionalSecurityGroups")

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return HeadNodeNetworkingConfig(**data)


class SshSchema(BaseSchema):
    """Represent the schema of the SSH."""

    key_name = fields.Str(data_key="KeyName", required=True)

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return SshConfig(**data)


class HeadNodeSchema(BaseSchema):
    """Represent the schema of the HeadNode."""

    instance_type = fields.Str(data_key="InstanceType", required=True)
    networking_config = fields.Nested(HeadNodeNetworkingSchema, data_key="Networking", required=True)
    ssh_config = fields.Nested(SshSchema, data_key="Ssh", required=True)
    image_config = fields.Nested(ImageSchema, data_key="Image")

    @post_load()
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return HeadNodeConfig(**data)


class QueueNetworkingSchema(BaseSchema):
    """Represent the schema of the Networking, child of Queue."""

    subnet_ids = fields.List(fields.Str, data_key="SubnetIds", required=True)

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return QueueNetworkingConfig(**data)


class ComputeResourceSchema(BaseSchema):
    """Represent the schema of the ComputeResource."""

    instance_type = fields.Str(data_key="InstanceType", required=True)
    max_count = fields.Int(data_key="MaxCount")

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return ComputeResourceConfig(**data)


class QueueSchema(BaseSchema):
    """Represent the schema of the Queue."""

    name = fields.Str(data_key="Name")
    networking_config = fields.Nested(QueueNetworkingSchema, data_key="Networking", required=True)
    compute_resources_config = fields.Nested(ComputeResourceSchema, data_key="ComputeResources", many=True)

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return QueueConfig(**data)


class SchedulingSchema(BaseSchema):
    """Represent the schema of the Scheduling."""

    scheduler = fields.Str(data_key="Scheduler")
    queues_config = fields.Nested(QueueSchema, data_key="Queues", many=True, required=True)

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return SchedulingConfig(**data)


class EbsSchema(BaseSchema):
    """Represent the schema of the SharedStorage with type = EBS."""

    mount_dir = fields.Str(data_key="MountDir")
    volume_type = fields.Str(data_key="VolumeType")
    iops = fields.Int(data_key="Iops")
    size = fields.Int(data_key="Size")
    encrypted = fields.Bool(data_key="Encrypted")
    kms_key_id = fields.Str(data_key="KmsKeyId")
    snapshot_id = fields.Str(data_key="SnapshotId")
    id = fields.Str(data_key="VolumeId")

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return EbsConfig(**data)


class EfsSchema(BaseSchema):
    """Represent the schema of the SharedStorage with type = EFS."""

    mount_dir = fields.Str(data_key="MountDir")
    type = fields.Str(data_key="StorageType")
    provisioned_throughput = fields.Str(data_key="ProvisionedThroughput")
    # TODO add missing fields

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return EfsConfig(**data)


class FsxSchema(BaseSchema):
    """Represent the schema of the SharedStorage with type = FSX."""

    mount_dir = fields.Str(data_key="MountDir")
    capacity = fields.Int(data_key="StorageCapacity")
    # TODO add missing fields

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return FsxConfig(**data)


class SharedStorageSchema(BaseSchema):
    """Represent the generic SharedStorage schema."""

    mount_dir = fields.Str(data_key="MountDir")
    type = fields.Str(data_key="StorageType")
    ebs_config = fields.Nested(EbsSchema, data_key="EBSSettings", required=False)
    efs_config = fields.Nested(EfsSchema, data_key="EFSSettings", required=False)
    fsx_config = fields.Nested(FsxSchema, data_key="FSXSettings", required=False)

    @pre_load
    def prepare_shared_storage(self, input_data, **kwargs):
        """Adapt SharedStorage items to be able to distinguish and validate different storage types."""

        if "MountDir" not in input_data:
            raise ValidationError("Missing MountDir")
        if "StorageType" not in input_data:
            raise ValidationError("Missing StorageType")
        if "Settings" not in input_data:
            raise ValidationError("Missing Settings")

        # Move mount dir into settings and rename settings section
        # to be able to validate different params according to the storage type. E.g. Settings --> EBSSettings
        storage_type = input_data["StorageType"]
        if SharedStorageType.is_valid(storage_type):
            mount_dir = input_data["MountDir"]
            input_data["Settings"].update({"MountDir": mount_dir})
            input_data[f"{storage_type}Settings"] = input_data.pop("Settings")

            del input_data["MountDir"]
            del input_data["StorageType"]
        else:
            # raise error
            raise ValidationError("Wrong storage type")

        return input_data

    @post_load
    def make_config(self, data, **kwargs):
        """Return the right SharedStorage type object, according to the given type."""
        if "ebs_config" in data:
            return data["ebs_config"]
        elif "efs_config" in data:
            return data["efs_config"]
        elif "fsx_config" in data:
            return data["fsx_config"]


class ClusterSchema(BaseSchema):
    """Represent the schema of the Cluster."""

    image_config = fields.Nested(ImageSchema, data_key="Image")
    head_node_config = fields.Nested(HeadNodeSchema, data_key="HeadNode")
    scheduling_config = fields.Nested(SchedulingSchema, data_key="Scheduling")
    shared_storage_list_config = fields.Nested(SharedStorageSchema, data_key="SharedStorage", many=True, required=False)

    @pre_load
    def move_image(self, input_data, **kwargs):
        """Move image field into the head node."""
        # If image is not present in the Head node we can use the one from the Cluster
        input_data["HeadNode"]["Image"] = input_data["Image"]
        return input_data

    @post_load
    def make_config(self, data, **kwargs):
        """Generate config object."""
        return ClusterConfig(**data)
