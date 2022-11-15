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

from marshmallow import ValidationError, fields, post_load, validate, validates, validates_schema

from pcluster.config.imagebuilder_config import (
    Build,
    Component,
    DistributionConfiguration,
    Iam,
    Image,
    ImageBuilderConfig,
    ImagebuilderDevSettings,
    UpdateOsPackages,
    Volume,
)
from pcluster.constants import PCLUSTER_IMAGE_NAME_REGEX
from pcluster.imagebuilder_utils import AMI_NAME_REQUIRED_SUBSTRING
from pcluster.schemas.common_schema import (
    ALLOWED_VALUES,
    AdditionalIamPolicySchema,
    BaseDevSettingsSchema,
    BaseSchema,
    DeploymentSettingsSchema,
    ImdsSchema,
    TagSchema,
    get_field_validator,
    validate_json_format,
    validate_no_reserved_tag,
)
from pcluster.utils import get_url_scheme

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

    name = fields.Str(
        validate=validate.Regexp(PCLUSTER_IMAGE_NAME_REGEX)
        and validate.Length(max=128 - len(AMI_NAME_REQUIRED_SUBSTRING)),
    )
    tags = fields.List(fields.Nested(TagSchema))
    root_volume = fields.Nested(VolumeSchema)

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Image(**data)

    @validates("tags")
    def validate_tags(self, tags):
        """Validate tags."""
        validate_no_reserved_tag(tags)


# ---------------------- Build Schema---------------------- #


class ComponentSchema(BaseSchema):
    """Represent the schema of the ImageBuilder component."""

    type = fields.Str(validate=validate.OneOf(["arn", "script"]))
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
        if type == "script" and get_url_scheme(value) not in ["https", "s3"]:
            raise ValidationError(
                message="The Type in Component is script, the value '{0}' is invalid. "
                "Choose a value with 'https' or 's3' prefix url.".format(value),
                field_name="Value",
            )


class DistributionConfigurationSchema(BaseSchema):
    """Represent the schema of the ImageBuilder distribution configuration."""

    regions = fields.Str(validate=validate.Regexp("^[a-z0-9-]+(,[a-z0-9-]+)*$"))
    launch_permission = fields.Str()

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return DistributionConfiguration(**data)

    @validates("launch_permission")
    def validate_launch_permission(self, value):
        """Validate json."""
        if value and not validate_json_format(value):
            raise ValidationError(message="'{0}' is invalid".format(value))


class IamSchema(BaseSchema):
    """Represent the schema of the ImageBuilder IAM."""

    instance_role = fields.Str(validate=validate.Regexp("^arn:.*:role/"))
    instance_profile = fields.Str(validate=validate.Regexp("^arn:.*:instance-profile/"))
    cleanup_lambda_role = fields.Str(validate=validate.Regexp("^arn:.*:role/"))
    additional_iam_policies = fields.Nested(AdditionalIamPolicySchema, many=True)
    permissions_boundary = fields.Str(validate=validate.Regexp("^arn:.*:policy/"))

    @validates_schema
    def no_coexist_role_policies(self, data, **kwargs):
        """Validate that instance_role, instance_profile or additional_iam_policies do not co-exist."""
        if self.fields_coexist(data, ["instance_role", "instance_profile", "additional_iam_policies"], **kwargs):
            raise ValidationError(
                "InstanceProfile, InstanceRole or AdditionalIamPolicies can not be configured together."
            )

    @post_load()
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return Iam(**data)


class UpdateOsPackagesSchema(BaseSchema):
    """Represents the schema of ImageBuilder UpdateOsPackages."""

    enabled = fields.Bool()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return UpdateOsPackages(**data)


class BuildSchema(BaseSchema):
    """Represent the schema of the ImageBuilder Build."""

    iam = fields.Nested(IamSchema)
    instance_type = fields.Str(required=True)
    components = fields.List(fields.Nested(ComponentSchema))
    parent_image = fields.Str(required=True, validate=validate.Regexp("^ami|arn"))
    tags = fields.List(fields.Nested(TagSchema))
    security_group_ids = fields.List(fields.Str)
    subnet_id = fields.Str(validate=get_field_validator("subnet_id"))
    update_os_packages = fields.Nested(UpdateOsPackagesSchema)
    imds = fields.Nested(ImdsSchema)

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


class ImagebuilderDevSettingsSchema(BaseDevSettingsSchema):
    """Represent the schema of the ImageBuilder Dev Setting."""

    disable_pcluster_component = fields.Bool()
    distribution_configuration = fields.Nested(DistributionConfigurationSchema)
    terminate_instance_on_failure = fields.Bool()
    disable_validate_and_test = fields.Bool()

    @post_load
    def make_resource(self, data, **kwargs):
        """Generate resource."""
        return ImagebuilderDevSettings(**data)


# ---------------------- ImageBuilder Schema ---------------------- #


class ImageBuilderSchema(BaseSchema):
    """Represent the schema of the ImageBuilder."""

    image = fields.Nested(ImageSchema)
    build = fields.Nested(BuildSchema, required=True)
    dev_settings = fields.Nested(ImagebuilderDevSettingsSchema)
    config_region = fields.Str(data_key="Region")
    custom_s3_bucket = fields.Str()
    deployment_settings = fields.Nested(DeploymentSettingsSchema)

    @post_load(pass_original=True)
    def make_resource(self, data, original_data, **kwargs):
        """Generate resource."""
        return ImageBuilderConfig(source_config=original_data, **data)
