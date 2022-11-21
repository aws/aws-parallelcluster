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
import enum
import json

from marshmallow import Schema, ValidationError, fields, post_dump, post_load, pre_dump, validate, validates

from pcluster.config.cluster_config import BaseTag
from pcluster.config.common import AdditionalIamPolicy, Cookbook, DeploymentSettings, Imds, LambdaFunctionsVpcConfig
from pcluster.config.update_policy import UpdatePolicy
from pcluster.constants import PCLUSTER_PREFIX, SUPPORTED_ARCHITECTURES
from pcluster.utils import to_pascal_case

ALLOWED_VALUES = {
    "cidr": r"^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}"
    r"([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])"
    r"(\/([0-9]|[1-2][0-9]|3[0-2]))$",
    "file_path": r"^\/?[^\/.\\][^\/\\]*(\/[^\/.\\][^\/]*)*$",
    "security_group_id": r"^sg-[0-9a-z]{8}$|^sg-[0-9a-z]{17}$",
    "subnet_id": r"^subnet-[0-9a-z]{8}$|^subnet-[0-9a-z]{17}$",
    "architectures": SUPPORTED_ARCHITECTURES,
    "volume_type": ["standard", "io1", "io2", "gp2", "st1", "sc1", "gp3"],
}

SUPPORTED_IMDS_VERSIONS = ["v1.0", "v2.0"]


def validate_json_format(data):
    """Validate the input data in json format."""
    try:
        json.loads(data)
    except ValueError:
        return False
    return True


def validate_no_reserved_tag(tags):
    """Validate there is no tag with reserved prefix."""
    if tags:
        for tag in tags:
            if tag.key.startswith(PCLUSTER_PREFIX):
                raise ValidationError(message=f"The tag key prefix '{PCLUSTER_PREFIX}' is reserved and cannot be used.")


def get_field_validator(field_name):
    allowed_values = ALLOWED_VALUES[field_name]
    return validate.OneOf(allowed_values) if isinstance(allowed_values, list) else validate.Regexp(allowed_values)


class BaseSchema(Schema):
    """Represent a base schema, containing all the features required by all the Schema classes."""

    def on_bind_field(self, field_name, field_obj):
        """
        Bind PascalCase in the config with snake_case in Python.

        For example, subnet_id in the code is automatically bind with SubnetId in the config file.
        The bind can be overwritten by specifying data_key.
        For example, `EBS` in the config file is not PascalCase, we have to bind it with ebs manually.
        """
        if field_obj.data_key is None:
            field_obj.data_key = to_pascal_case(field_name)

    @staticmethod
    def fields_coexist(data, field_list, one_required=False, **kwargs):
        """
        Check if at least two fields in the field list co-exist in the schema.

        :param data: data to be checked
        :param field_list: list including the name of the fields to check
        :param one_required: True if one of the fields is required to exist
        :return: True if one and only one field is not None
        """
        if kwargs.get("partial"):
            # If the schema is to be loaded partially, do not check existence constrain.
            return False
        num_of_fields = len([data.get(field_name) for field_name in field_list if data.get(field_name)])
        return num_of_fields != 1 if one_required else num_of_fields > 1

    @pre_dump
    def prepare_objects(self, data, **kwargs):
        """Prepare objects to be ready for yaml conversion."""
        adapted_data = copy.deepcopy(data)
        if self.context.get("delete_defaults_when_dump"):
            for key, value in vars(adapted_data).copy().items():
                # Remove value implied by the code. i.e., only keep parameters that were specified in the yaml file
                if _is_implied(adapted_data, key, value):
                    delattr(adapted_data, key)
                if isinstance(value, list):
                    value[:] = [v for v in value if not _is_implied(adapted_data, key, v)]

        for key, value in vars(adapted_data).items():
            # Unwrap "param" attributes
            if adapted_data.get_param(key) is not None:
                setattr(adapted_data, key, value)

            # Convert back enums to string
            if isinstance(value, enum.Enum):
                setattr(adapted_data, key, value.value)
        return adapted_data

    @post_dump
    def remove_none_values(self, data, **kwargs):
        """Remove None values before creating the Yaml format."""
        if self.context.get("delete_defaults_when_dump"):
            return {key: value for key, value in data.items() if value not in (None, [], {})}
        return data


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

    key = fields.Str(
        # TODO Tags can be updated with policy QUEUE_UPDATE_STRATEGY
        required=True,
        validate=validate.Length(max=128),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )
    value = fields.Str(
        # TODO Tags can be updated with policy QUEUE_UPDATE_STRATEGY
        required=True,
        validate=validate.Length(max=256),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return BaseTag(**data)


class AdditionalIamPolicySchema(BaseSchema):
    """Represent the schema of Additional IAM policy."""

    policy = fields.Str(
        required=True, metadata={"update_policy": UpdatePolicy.SUPPORTED}, validate=validate.Regexp("^arn:.*:policy/")
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return AdditionalIamPolicy(**data)


class CookbookSchema(BaseSchema):
    """Represent the schema of cookbook."""

    chef_cookbook = fields.Str(
        metadata={
            "update_policy": UpdatePolicy(
                UpdatePolicy.UNSUPPORTED, fail_reason=UpdatePolicy.FAIL_REASONS["cookbook_update"]
            )
        }
    )
    extra_chef_attributes = fields.Str(
        metadata={
            "update_policy": UpdatePolicy(
                UpdatePolicy.UNSUPPORTED, fail_reason=UpdatePolicy.FAIL_REASONS["cookbook_update"]
            )
        }
    )

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


class LambdaFunctionsVpcConfigSchema(BaseSchema):
    """Represent the VPC configuration schema of PCluster Lambdas, used both by build image and cluster files."""

    security_group_ids = fields.List(
        fields.Str(validate=get_field_validator("security_group_id")),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
        validate=validate.Length(min=1, max=5),
        required=True,
    )
    subnet_ids = fields.List(
        fields.Str(validate=get_field_validator("subnet_id")),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
        validate=validate.Length(min=1, max=16),
        required=True,
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return LambdaFunctionsVpcConfig(**data)


class DeploymentSettingsSchema(BaseSchema):
    """Represent the common schema of DeploymentSettings for ImageBuilder and Cluster."""

    lambda_functions_vpc_config = fields.Nested(
        LambdaFunctionsVpcConfigSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED}
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return DeploymentSettings(**data)


class BaseDevSettingsSchema(BaseSchema):
    """Represent the common schema of Dev Setting for ImageBuilder and Cluster."""

    cookbook = fields.Nested(CookbookSchema, metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    node_package = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})
    aws_batch_cli_package = fields.Str(metadata={"update_policy": UpdatePolicy.UNSUPPORTED})


class ImdsSchema(BaseSchema):
    """
    Represent the Imds schema shared between cluster and build image files.

    It represents the Imds element that can be either at top level in the cluster config file,
    or in the Build section of the build image config file.
    """

    imds_support = fields.Str(
        data_key="ImdsSupport",
        validate=validate.OneOf(SUPPORTED_IMDS_VERSIONS),
        metadata={"update_policy": UpdatePolicy.UNSUPPORTED},
    )

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Imds(**data)
