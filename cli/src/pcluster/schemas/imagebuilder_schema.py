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
from marshmallow import fields, post_load

from pcluster.models.imagebuilder import Build, ChefCookbook, Component, DevSettings, Image, ImageBuilder, Volume
from pcluster.schemas.cluster_schema import BaseSchema, TagSchema

# ---------------------- Image Schema---------------------- #


class VolumeSchema(BaseSchema):
    """Represent the schema of the ImageBuilder Volume."""

    size = fields.Int(data_key="Size")
    encrypted = fields.Bool(data_key="Encrypted")
    kms_key_id = fields.Str()

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Volume(**data)


class ImageSchema(BaseSchema):
    """Represent the schema of the ImageBuilder Image."""

    name = fields.Str(data_key="Name", required=True)
    description = fields.Str(data_key="Description")
    tags = fields.List(fields.Nested(TagSchema), data_key="Tags")
    root_volume = fields.Nested(VolumeSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Image(**data)


# ---------------------- Build Schema---------------------- #


class ComponentSchema(BaseSchema):
    """Represent the schema of the ImageBuilder component."""

    type = fields.Str(data_key="Type")
    value = fields.Str(data_key="Value")

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Component(**data)


class BuildSchema(BaseSchema):
    """Represent the schema of the ImageBuilder Build."""

    instance_role = fields.Str()
    instance_type = fields.Str(required=True)
    components = fields.List(fields.Nested(ComponentSchema), data_key="Components")
    parent_image = fields.Str(required=True)
    tags = fields.List(fields.Nested(TagSchema), data_key="Tags")
    security_group_ids = fields.List(fields.Str)
    subnet_id = fields.Str()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Build(**data)


# ---------------------- Dev Settings Schema ---------------------- #


class ChefCookbookSchema(BaseSchema):
    """Represent the schema of the ImageBuilder chef cookbook."""

    url = fields.Str(data_key="Url")
    json = fields.Str(data_key="Json")

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ChefCookbook(**data)


class DevSettingsSchema(BaseSchema):
    """Represent the schema of the ImageBuilder Dev Setting."""

    update_os_and_reboot = fields.Bool()
    disable_pcluster_component = fields.Bool()
    chef_cookbook = fields.Nested(ChefCookbookSchema)
    node_url = fields.Str()
    aws_batch_cli_url = fields.Str(data_key="AWSBatchCliUrl")
    distribution_configuration_arn = fields.Str()
    terminate_instance_on_failure = fields.Bool()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return DevSettings(**data)


# ---------------------- ImageBuilder Schema ---------------------- #


class ImageBuilderSchema(BaseSchema):
    """Represent the schema of the ImageBuilder."""

    image = fields.Nested(ImageSchema, data_key="Image", required=True)
    build = fields.Nested(BuildSchema, data_key="Build", required=True)
    dev_settings = fields.Nested(DevSettingsSchema)

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ImageBuilder(**data)
