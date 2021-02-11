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

from marshmallow import Schema, ValidationError, fields, post_dump, post_load, pre_dump, validate, validates

from common.utils import validate_json_format
from pcluster.constants import SUPPORTED_ARCHITECTURES
from pcluster.models.cluster import BaseTag
from pcluster.models.common import Cookbook

ALLOWED_VALUES = {
    "cidr": r"^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}"
    r"([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])"
    r"(\/([0-9]|[1-2][0-9]|3[0-2]))$",
    "file_path": r"^\/?[^\/.\\][^\/\\]*(\/[^\/.\\][^\/]*)*$",
    "security_group_id": r"^sg-[0-9a-z]{8}$|^sg-[0-9a-z]{17}$",
    "subnet_id": r"^subnet-[0-9a-z]{8}$|^subnet-[0-9a-z]{17}$",
    "architectures": SUPPORTED_ARCHITECTURES,
}


def get_field_validator(field_name):
    allowed_values = ALLOWED_VALUES[field_name]
    return validate.OneOf(allowed_values) if isinstance(allowed_values, list) else validate.Regexp(allowed_values)


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

    def only_one_field(self, data, field_list, **kwargs):
        """
        Check that the Schema contains only one of the given fields.

        :param data: the
        :param field_list: list including the name of the fields to check
        :return: True if one and only one field is not None
        """
        if kwargs.get("partial"):
            # If the schema is to be loaded partially, do not check existence constrain.
            return True
        return len([data.get(field_name) for field_name in field_list if data.get(field_name)]) == 1

    @pre_dump
    def remove_implied_values(self, data, **kwargs):
        """Remove value implied by the code. i.e., only keep parameters that were specified in the yaml file."""
        for key, value in vars(data).copy().items():
            if _is_implied(data, key, value):
                delattr(data, key)
            if isinstance(value, list):
                value[:] = [v for v in value if not _is_implied(data, key, v)]
        return data

    @pre_dump
    def unwrap_marked_class(self, data, **kwargs):
        """Remove value implied by the code. i.e., only keep parameters that were specified in the yaml file."""
        for key, value in vars(data).items():
            if data.get_param(key) is not None:
                setattr(data, key, value)
        return data

    @post_dump
    def remove_none_values(self, data, **kwargs):
        """Remove None values before creating the Yaml format."""
        return {key: value for key, value in data.items() if value is not None and value != []}


def _camelcase(snake_case_word):
    """Convert the given snake case word into a camel case one."""
    parts = iter(snake_case_word.split("_"))
    return "".join(word.title() for word in parts)


def _is_implied(resource, attr, value):
    """Check if the value of the given attribute for the resource is implied."""
    if hasattr(value, "implied"):
        implied = value.implied
    else:
        param = resource.get_param(attr)
        implied = param and param.implied

    return implied


# --------------- Common Schemas --------------- #


class TagSchema(BaseSchema):
    """Represent the schema of Tag section."""

    key = fields.Str()
    value = fields.Str()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return BaseTag(**data)


class CookbookSchema(BaseSchema):
    """Represent the schema of cookbook."""

    chef_cookbook = fields.Str()
    extra_chef_attributes = fields.Str()

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Cookbook(**data)

    @validates("extra_chef_attributes")
    def validate_extra_chef_attributes(self, value):
        """Validate json."""
        # TODO: double check the allowed pattern for extra chef attribute
        if value and not validate_json_format(value):
            raise ValidationError(message="'{0}' is invalid".format(value))


class BaseDevSettingsSchema(BaseSchema):
    """Represent the common schema of Dev Setting for ImageBuilder and Cluster."""

    cookbook = fields.Nested(CookbookSchema)
    node_package = fields.Str()
    aws_batch_cli_package = fields.Str()
