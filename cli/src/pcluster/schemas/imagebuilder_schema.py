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
from urllib.parse import urlparse

from marshmallow import ValidationError, fields, post_load, validate, validates, validates_schema

from common.utils import validate_json_format
from pcluster.models.imagebuilder import Build, ChefCookbook, Component, DevSettings, Image, ImageBuilder, Volume
from pcluster.schemas.common_schema import ALLOWED_VALUES, BaseSchema, TagSchema, get_field_validator

# ---------------------- Image Schema---------------------- #


class VolumeSchema(BaseSchema):
    """Represent the schema of the ImageBuilder Volume."""

    size = fields.Int()
    encrypted = fields.Bool()
    kms_key_id = fields.Str()

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Volume(**data)


class ImageSchema(BaseSchema):
    """Represent the schema of the ImageBuilder Image."""

    name = fields.Str(validate=validate.Regexp(r"^[-_A-Za-z-0-9][-_A-Za-z0-9 ]{1,126}[-_A-Za-z-0-9]$"), required=True)
    description = fields.Str()
    tags = fields.List(fields.Nested(TagSchema))
    root_volume = fields.Nested(VolumeSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Image(**data)

    @validates("tags")
    def validate_reserved_tag(self, value):
        """Validate reserved tag in tags."""
        if value:
            for tag in value:
                if tag.key == "PclusterVersion":
                    raise ValidationError(
                        message="The Key 'PclusterVersion' used in your 'tags' configuration parameter "
                        "is a reserved one, please change it."
                    )


# ---------------------- Build Schema---------------------- #


class ComponentSchema(BaseSchema):
    """Represent the schema of the ImageBuilder component."""

    type = fields.Str(validate=validate.OneOf(["arn", "yaml", "bash"]))
    value = fields.Str()

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Component(**data)

    @validates_schema()
    def validate_component_value(self, data, **kwargs):
        """Validate component value format."""
        type = data.get("type")
        value = data.get("value")
        if type == "arn" and not value.startswith("arn"):
            raise ValidationError(
                message="The Type in Component is arn, the value '{0}' is invalid. "
                "Choose a value with 'arn' prefix.".format(value),
                field_name="Value",
            )
        if type == "yaml" and (urlparse(value).scheme not in ["https", "s3", "file"] or not value.endswith("yaml")):
            print(urlparse(value))
            raise ValidationError(
                message="The Type in Component is yaml, the value '{0}' is invalid. "
                "Choose a value with 'https', 's3' or 'file' prefix and 'yaml' suffix url.".format(value),
                field_name="Value",
            )
        if type == "bash" and urlparse(value).scheme not in ["https", "s3", "file"]:
            raise ValidationError(
                message="The Type in Component is bash, the value '{0}' is invalid. "
                "Choose a value with 'https', 's3' or 'file' prefix url.".format(value),
                field_name="Value",
            )


class BuildSchema(BaseSchema):
    """Represent the schema of the ImageBuilder Build."""

    instance_role = fields.Str()
    instance_type = fields.Str(required=True)
    components = fields.List(fields.Nested(ComponentSchema))
    parent_image = fields.Str(required=True, validate=validate.Regexp("^ami|arn"))
    tags = fields.List(fields.Nested(TagSchema))
    security_group_ids = fields.List(fields.Str)
    subnet_id = fields.Str(validate=get_field_validator("subnet_id"))

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Build(**data)

    @validates("security_group_ids")
    def validate_security_group_ids(self, value):
        """Validate security group ids."""
        if value and not all(
            re.match(ALLOWED_VALUES["security_group_id"], security_group_id) for security_group_id in value
        ):
            raise ValidationError(message="The SecurityGroupIds contains invalid security group id.")


# ---------------------- Dev Settings Schema ---------------------- #


class ChefCookbookSchema(BaseSchema):
    """Represent the schema of the ImageBuilder chef cookbook."""

    url = fields.Str()
    json = fields.Str()

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ChefCookbook(**data)

    @validates("json")
    def validate_json(self, value):
        """Validate json."""
        if value and not validate_json_format(value):
            raise ValidationError(
                message="The Json in ChefCookbook '{0}' is invalid, check the json format.".format(value)
            )


class DevSettingsSchema(BaseSchema):
    """Represent the schema of the ImageBuilder Dev Setting."""

    update_os_and_reboot = fields.Bool()
    disable_pcluster_component = fields.Bool()
    chef_cookbook = fields.Nested(ChefCookbookSchema)
    node_url = fields.Str()
    aws_batch_cli_url = fields.Str(data_key="AWSBatchCliUrl")
    distribution_configuration_arn = fields.Str(validate=validate.Regexp("^arn"))
    terminate_instance_on_failure = fields.Bool()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return DevSettings(**data)


# ---------------------- ImageBuilder Schema ---------------------- #


class ImageBuilderSchema(BaseSchema):
    """Represent the schema of the ImageBuilder."""

    image = fields.Nested(ImageSchema, required=True)
    build = fields.Nested(BuildSchema, required=True)
    dev_settings = fields.Nested(DevSettingsSchema)

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ImageBuilder(**data)
