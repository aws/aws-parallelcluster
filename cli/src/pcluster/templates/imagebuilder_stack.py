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
# This module contains all the classes required to convert an ImageBuilder into a CFN template by using CDK.
#

# pylint: disable=too-many-lines

import copy
import json
import os
from typing import List

import yaml
from aws_cdk import aws_iam as iam
from aws_cdk import aws_imagebuilder as imagebuilder
from aws_cdk import aws_lambda as awslambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk.core import CfnParameter, CfnTag, Construct, Fn, Stack

from pcluster import imagebuilder_utils, utils
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import get_region
from pcluster.config.common import BaseTag
from pcluster.config.imagebuilder_config import ImageBuilderConfig, ImageBuilderExtraChefAttributes, Volume
from pcluster.constants import (
    IAM_ROLE_PATH,
    IMAGEBUILDER_RESOURCE_NAME_PREFIX,
    LAMBDA_VPC_ACCESS_MANAGED_POLICY,
    PCLUSTER_IMAGE_BUILD_LOG_TAG,
    PCLUSTER_IMAGE_CONFIG_TAG,
    PCLUSTER_IMAGE_ID_TAG,
    PCLUSTER_IMAGE_NAME_TAG,
    PCLUSTER_S3_BUCKET_TAG,
    PCLUSTER_S3_IMAGE_DIR_TAG,
    PCLUSTER_VERSION_TAG,
)
from pcluster.imagebuilder_utils import (
    AMI_NAME_REQUIRED_SUBSTRING,
    PCLUSTER_RESERVED_VOLUME_SIZE,
    ROOT_VOLUME_TYPE,
    wrap_script_to_component,
)
from pcluster.models.s3_bucket import S3Bucket, S3FileType, create_s3_presigned_url, parse_bucket_url
from pcluster.templates.cdk_builder_utils import apply_permissions_boundary, get_assume_role_policy_document
from pcluster.utils import get_http_tokens_setting


class ImageBuilderCdkStack(Stack):
    """Create the Stack for imagebuilder."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        image_config: ImageBuilderConfig,
        image_id: str,
        bucket: S3Bucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.config = image_config
        self.image_id = image_id
        self.bucket = bucket

        self.custom_instance_role = (
            self.config.build.iam.instance_role
            if self.config.build.iam and self.config.build.iam.instance_role
            else None
        )
        self.custom_instance_profile = (
            self.config.build.iam.instance_profile
            if self.config.build.iam and self.config.build.iam.instance_profile
            else None
        )
        self.custom_cleanup_lambda_role = (
            self.config.build.iam.cleanup_lambda_role
            if self.config.build.iam and self.config.build.iam.cleanup_lambda_role
            else None
        )

        self._add_cfn_parameters()
        self._add_resources()

        try:
            apply_permissions_boundary(image_config.build.iam.permissions_boundary, self)
        except AttributeError:
            pass

    # -- Utility methods --------------------------------------------------------------------------------------------- #

    def _get_root_device_name(self):
        ami_id = imagebuilder_utils.get_ami_id(self.config.build.parent_image)
        ami_info = AWSApi.instance().ec2.describe_image(ami_id)
        return ami_info.device_name

    def _stack_unique_id(self):
        return Fn.select(2, Fn.split("/", self.stack_id))

    def _build_resource_name(self, name, to_lower=False):
        if to_lower:
            name = name.lower()
        return "-".join([name, self._stack_unique_id()])

    def _build_image_recipe_name(self, to_lower=False):
        name = "{0}-{1}".format(IMAGEBUILDER_RESOURCE_NAME_PREFIX, self.image_id)[0:1024]
        if to_lower:
            name = name.lower()
        return name

    def _get_log_group_arn(self):
        log_group_arn = self.format_arn(
            service="logs",
            resource="log-group",
            region=get_region(),
            sep=":",
            resource_name=f"/aws/imagebuilder/{self._build_image_recipe_name()}",
        )
        return log_group_arn

    def _get_image_tags(self):
        """Get image tags."""
        image_tags = copy.deepcopy(self.config.image.tags) if self.config.image and self.config.image.tags else []
        tag_list = [
            {
                "key": PCLUSTER_IMAGE_NAME_TAG,
                "value": self.config.image.name if self.config.image and self.config.image.name else self.image_id,
            },
            {"key": PCLUSTER_VERSION_TAG, "value": utils.get_installed_version()},
            {"key": PCLUSTER_IMAGE_ID_TAG, "value": self.image_id},
            {"key": PCLUSTER_S3_BUCKET_TAG, "value": self.bucket.name},
            {"key": PCLUSTER_S3_IMAGE_DIR_TAG, "value": self.bucket.artifact_directory},
            {"key": PCLUSTER_IMAGE_BUILD_LOG_TAG, "value": self._get_log_group_arn()},
            {"key": PCLUSTER_IMAGE_CONFIG_TAG, "value": self.bucket.get_config_s3_url("image-config.yaml")},
        ]
        for tag in tag_list:
            image_tags.append(BaseTag(key=tag.get("key"), value=tag.get("value")))
        return {tag.key: tag.value for tag in image_tags}

    def _get_distribution_regions(self) -> set:
        if (
            self.config.dev_settings
            and self.config.dev_settings.distribution_configuration
            and self.config.dev_settings.distribution_configuration.regions
        ):
            return set(map(str.strip, self.config.dev_settings.distribution_configuration.regions.split(",")))
        return [self.region]

    # -- Parameters -------------------------------------------------------------------------------------------------- #

    def _add_cfn_parameters(self):
        if (
            self.config.dev_settings
            and self.config.dev_settings.cookbook
            and self.config.dev_settings.cookbook.chef_cookbook
        ):
            dev_settings_cookbook_value = self.config.dev_settings.cookbook.chef_cookbook
            custom_chef_cookbook = (
                create_s3_presigned_url(dev_settings_cookbook_value)
                if dev_settings_cookbook_value.startswith("s3://")
                else dev_settings_cookbook_value
            )
        else:
            custom_chef_cookbook = ""

        CfnParameter(
            self,
            "CfnParamCookbookVersion",
            type="String",
            default=utils.get_installed_version(),
            description="CookbookVersion",
        )
        CfnParameter(
            self, "CfnParamChefCookbook", type="String", default=custom_chef_cookbook, description="ChefCookbook"
        )
        CfnParameter(self, "CfnParamCincInstaller", type="String", default="", description="CincInstaller")
        CfnParameter(
            self,
            "CfnParamChefDnaJson",
            type="String",
            default=ImageBuilderExtraChefAttributes(self.config.dev_settings).dump_json(),
            description="ChefAttributes",
        )
        CfnParameter(
            self,
            "CfnParamUpdateOsAndReboot",
            type="String",
            default="true"
            if self.config.build
            and self.config.build.update_os_packages
            and self.config.build.update_os_packages.enabled
            else "false",
            description="UpdateOsAndReboot",
        )

    # -- Resources --------------------------------------------------------------------------------------------------- #

    def _add_resources(self):
        # Add default build tags information
        tags = copy.deepcopy(self.config.build.tags) or []
        tags.append(BaseTag(key=PCLUSTER_IMAGE_ID_TAG, value=self.image_id))
        tags.append(
            BaseTag(
                key=PCLUSTER_IMAGE_NAME_TAG,
                value=self.config.image.name if self.config.image and self.config.image.name else self.image_id,
            )
        )
        build_tags_map = {tag.key: tag.value for tag in tags}
        build_tags_list = [CfnTag(key=tag.key, value=tag.value) for tag in tags]

        # Get ami tags information
        ami_tags = self._get_image_tags()

        lambda_cleanup_policy_statements = []
        resource_dependency_list = []

        # InstanceRole and InstanceProfile
        instance_profile_name = None
        if self.custom_instance_role:
            resource_dependency_list.append(
                self._add_instance_profile(
                    instance_role=self.custom_instance_role,
                    cleanup_policy_statements=lambda_cleanup_policy_statements,
                )
            )
        elif self.custom_instance_profile:
            instance_profile_name = self.custom_instance_profile.split("/")[-1]
        else:
            resource_dependency_list.append(
                self._add_default_instance_role(lambda_cleanup_policy_statements, build_tags_list)
            )
            resource_dependency_list.append(
                self._add_instance_profile(cleanup_policy_statements=lambda_cleanup_policy_statements)
            )

        self._add_imagebuilder_resources(
            build_tags_map, ami_tags, instance_profile_name, lambda_cleanup_policy_statements, resource_dependency_list
        )

        lambda_cleanup, permission, lambda_cleanup_execution_role, lambda_log = self._add_lambda_cleanup(
            lambda_cleanup_policy_statements, build_tags_list
        )
        resource_dependency_list.extend([lambda_cleanup, permission, lambda_log])

        resource_dependency_list.extend(self._add_sns_topic_and_subscription(lambda_cleanup, build_tags_list))

        if lambda_cleanup_execution_role:
            for resource in resource_dependency_list:
                resource.add_depends_on(lambda_cleanup_execution_role)

    def _add_imagebuilder_resources(
        self, build_tags, ami_tags, instance_profile_name, lambda_cleanup_policy_statements, resource_dependency_list
    ):
        resource_dependency_list.append(
            self._add_imagebuilder_infrastructure_configuration(
                build_tags, instance_profile_name, lambda_cleanup_policy_statements
            )
        )

        components, components_resources = self._add_imagebuilder_components(
            build_tags, lambda_cleanup_policy_statements
        )

        resource_dependency_list.extend(components_resources)

        resource_dependency_list.append(
            self._add_imagebuilder_image_recipe(build_tags, components, lambda_cleanup_policy_statements)
        )

        resource_dependency_list.append(
            self._add_imagebuilder_distribution_configuration(ami_tags, build_tags, lambda_cleanup_policy_statements)
        )

        resource_dependency_list.append(self._add_imagebuilder_image(build_tags, lambda_cleanup_policy_statements))

    def _add_imagebuilder_image(self, build_tags, lambda_cleanup_policy_statements):
        # ImageBuilderImage
        image_resource = imagebuilder.CfnImage(
            self,
            IMAGEBUILDER_RESOURCE_NAME_PREFIX,
            tags=build_tags,
            image_recipe_arn=Fn.ref("ImageRecipe"),
            infrastructure_configuration_arn=Fn.ref("InfrastructureConfiguration"),
            distribution_configuration_arn=Fn.ref("DistributionConfiguration"),
            enhanced_image_metadata_enabled=False,
        )
        if not self.custom_cleanup_lambda_role:
            self._add_resource_delete_policy(
                lambda_cleanup_policy_statements,
                ["imagebuilder:DeleteImage", "imagebuilder:GetImage", "imagebuilder:CancelImageCreation"],
                [
                    self.format_arn(
                        service="imagebuilder",
                        resource="image",
                        resource_name="{0}/*".format(self._build_image_recipe_name(to_lower=True)),
                    )
                ],
            )

        return image_resource

    def _add_imagebuilder_distribution_configuration(self, ami_tags, build_tags, lambda_cleanup_policy_statements):
        # ImageBuilderDistributionConfiguration
        ami_distribution_configuration = {
            "Name": (self.config.image.name if self.config.image and self.config.image.name else self.image_id)
            + AMI_NAME_REQUIRED_SUBSTRING,
            "AmiTags": ami_tags,
            "LaunchPermissionConfiguration": json.loads(
                self.config.dev_settings.distribution_configuration.launch_permission
            )
            if self.config.dev_settings
            and self.config.dev_settings.distribution_configuration
            and self.config.dev_settings.distribution_configuration.launch_permission
            else None,
        }
        distributions = []
        for region in self._get_distribution_regions():
            distributions.append(
                imagebuilder.CfnDistributionConfiguration.DistributionProperty(
                    ami_distribution_configuration=ami_distribution_configuration,
                    region=region,
                )
            )
        distribution_configuration_resource = imagebuilder.CfnDistributionConfiguration(
            self,
            "DistributionConfiguration",
            name=self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX),
            tags=build_tags,
            distributions=distributions,
        )
        if not self.custom_cleanup_lambda_role:
            self._add_resource_delete_policy(
                lambda_cleanup_policy_statements,
                ["imagebuilder:DeleteDistributionConfiguration"],
                [
                    self.format_arn(
                        service="imagebuilder",
                        resource="distribution-configuration",
                        resource_name="{0}".format(
                            self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX, to_lower=True)
                        ),
                    )
                ],
            )

        return distribution_configuration_resource

    def _add_imagebuilder_image_recipe(self, build_tags, components, lambda_cleanup_policy_statements):
        # ImageBuilderImageRecipe
        image_recipe_resource = imagebuilder.CfnImageRecipe(
            self,
            "ImageRecipe",
            name=self._build_image_recipe_name(),
            version=utils.get_installed_version(base_version_only=True),
            tags=build_tags,
            parent_image=self.config.build.parent_image,
            components=components,
            block_device_mappings=[
                imagebuilder.CfnImageRecipe.InstanceBlockDeviceMappingProperty(
                    device_name=self._get_root_device_name(),
                    ebs=self._set_ebs_volume(),
                )
            ],
        )
        if not self.custom_cleanup_lambda_role:
            self._add_resource_delete_policy(
                lambda_cleanup_policy_statements,
                ["imagebuilder:DeleteImageRecipe"],
                [
                    self.format_arn(
                        service="imagebuilder",
                        resource="image-recipe",
                        resource_name="{0}/*".format(self._build_image_recipe_name(to_lower=True)),
                    )
                ],
            )

        return image_recipe_resource

    def _add_imagebuilder_components(self, build_tags, lambda_cleanup_policy_statements):
        imagebuilder_resources_dir = os.path.join(imagebuilder_utils.get_resources_directory(), "imagebuilder")

        # ImageBuilderComponents
        components = []
        components_resources = []
        if self.config.build and self.config.build.update_os_packages and self.config.build.update_os_packages.enabled:
            update_os_component_resource = imagebuilder.CfnComponent(
                self,
                "UpdateOSComponent",
                name=self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX + "-UpdateOS"),
                version=utils.get_installed_version(base_version_only=True),
                tags=build_tags,
                description="Update OS and Reboot",
                platform="Linux",
                data=Fn.sub(_load_yaml(imagebuilder_resources_dir, "update_and_reboot.yaml")),
            )
            components.append(
                imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(component_arn=Fn.ref("UpdateOSComponent"))
            )
            components_resources.append(update_os_component_resource)
            if not self.custom_cleanup_lambda_role:
                self._add_resource_delete_policy(
                    lambda_cleanup_policy_statements,
                    ["imagebuilder:DeleteComponent"],
                    [
                        self.format_arn(
                            service="imagebuilder",
                            resource="component",
                            resource_name="{0}/*".format(
                                self._build_resource_name(
                                    IMAGEBUILDER_RESOURCE_NAME_PREFIX + "-UpdateOS", to_lower=True
                                )
                            ),
                        )
                    ],
                )

        disable_pcluster_component = (
            self.config.dev_settings.disable_pcluster_component
            if self.config.dev_settings and self.config.dev_settings.disable_pcluster_component
            else False
        )
        if not disable_pcluster_component:
            parallelcluster_component_resource = imagebuilder.CfnComponent(
                self,
                "ParallelClusterComponent",
                name=self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX),
                version=utils.get_installed_version(base_version_only=True),
                tags=build_tags,
                description="Install ParallelCluster software stack",
                platform="Linux",
                data=Fn.sub(_load_yaml(imagebuilder_resources_dir, "parallelcluster.yaml")),
            )
            components.append(
                imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(
                    component_arn=Fn.ref("ParallelClusterComponent")
                )
            )
            components_resources.append(parallelcluster_component_resource)
            if not self.custom_cleanup_lambda_role:
                self._add_resource_delete_policy(
                    lambda_cleanup_policy_statements,
                    ["imagebuilder:DeleteComponent"],
                    [
                        self.format_arn(
                            service="imagebuilder",
                            resource="component",
                            resource_name="{0}/*".format(
                                self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX, to_lower=True)
                            ),
                        )
                    ],
                )

        tag_component_resource = imagebuilder.CfnComponent(
            self,
            "ParallelClusterTagComponent",
            name=self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX + "-Tag"),
            version=utils.get_installed_version(base_version_only=True),
            tags=build_tags,
            description="Tag ParallelCluster AMI",
            platform="Linux",
            data=_load_yaml(imagebuilder_resources_dir, "parallelcluster_tag.yaml"),
        )
        components.append(
            imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(
                component_arn=Fn.ref("ParallelClusterTagComponent")
            )
        )
        components_resources.append(tag_component_resource)
        if not self.custom_cleanup_lambda_role:
            self._add_resource_delete_policy(
                lambda_cleanup_policy_statements,
                ["imagebuilder:DeleteComponent"],
                [
                    self.format_arn(
                        service="imagebuilder",
                        resource="component",
                        resource_name="{0}/*".format(
                            self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX + "-Tag", to_lower=True)
                        ),
                    )
                ],
            )

        if self.config.build.components:
            self._add_custom_components(components, lambda_cleanup_policy_statements, components_resources)

        disable_validate_and_test_component = (
            self.config.dev_settings.disable_validate_and_test
            if self.config.dev_settings and isinstance(self.config.dev_settings.disable_validate_and_test, bool)
            else True
        )
        if not disable_pcluster_component and not disable_validate_and_test_component:
            validate_component_resource = imagebuilder.CfnComponent(
                self,
                id="ParallelClusterValidateComponent",
                name=self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX + "-Validate"),
                version=utils.get_installed_version(base_version_only=True),
                tags=build_tags,
                description="Validate ParallelCluster AMI",
                platform="Linux",
                data=_load_yaml(imagebuilder_resources_dir, "parallelcluster_validate.yaml"),
            )
            components.append(
                imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(
                    component_arn=Fn.ref("ParallelClusterValidateComponent")
                )
            )
            components_resources.append(validate_component_resource)
            if not self.custom_cleanup_lambda_role:
                self._add_resource_delete_policy(
                    lambda_cleanup_policy_statements,
                    ["imagebuilder:DeleteComponent"],
                    [
                        self.format_arn(
                            service="imagebuilder",
                            resource="component",
                            resource_name="{0}/*".format(
                                self._build_resource_name(
                                    IMAGEBUILDER_RESOURCE_NAME_PREFIX + "-Validate", to_lower=True
                                )
                            ),
                        )
                    ],
                )

            test_component_resource = imagebuilder.CfnComponent(
                self,
                id="ParallelClusterTestComponent",
                name=self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX + "-Test"),
                version=utils.get_installed_version(base_version_only=True),
                tags=build_tags,
                description="Test ParallelCluster AMI",
                platform="Linux",
                data=_load_yaml(imagebuilder_resources_dir, "parallelcluster_test.yaml"),
            )
            components.append(
                imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(
                    component_arn=Fn.ref("ParallelClusterTestComponent")
                )
            )
            components_resources.append(test_component_resource)
            if not self.custom_cleanup_lambda_role:
                self._add_resource_delete_policy(
                    lambda_cleanup_policy_statements,
                    ["imagebuilder:DeleteComponent"],
                    [
                        self.format_arn(
                            service="imagebuilder",
                            resource="component",
                            resource_name="{0}/*".format(
                                self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX + "-Test", to_lower=True)
                            ),
                        )
                    ],
                )

        return components, components_resources

    def _add_imagebuilder_infrastructure_configuration(
        self, build_tags, instance_profile_name, lambda_cleanup_policy_statements
    ):
        # ImageBuilderInfrastructureConfiguration
        infrastructure_configuration_resource = imagebuilder.CfnInfrastructureConfiguration(
            self,
            "InfrastructureConfiguration",
            name=self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX),
            tags=build_tags,
            resource_tags=build_tags,
            instance_profile_name=instance_profile_name or Fn.ref("InstanceProfile"),
            terminate_instance_on_failure=self.config.dev_settings.terminate_instance_on_failure
            if self.config.dev_settings and self.config.dev_settings.terminate_instance_on_failure is not None
            else True,
            instance_types=[self.config.build.instance_type],
            security_group_ids=self.config.build.security_group_ids,
            subnet_id=self.config.build.subnet_id,
            sns_topic_arn=Fn.ref("BuildNotificationTopic"),
            instance_metadata_options=imagebuilder.CfnInfrastructureConfiguration.InstanceMetadataOptionsProperty(
                http_tokens=get_http_tokens_setting(self.config.build.imds.imds_support)
            ),
        )
        if not self.custom_cleanup_lambda_role:
            self._add_resource_delete_policy(
                lambda_cleanup_policy_statements,
                ["imagebuilder:DeleteInfrastructureConfiguration"],
                [
                    self.format_arn(
                        service="imagebuilder",
                        resource="infrastructure-configuration",
                        resource_name="{0}".format(
                            self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX, to_lower=True)
                        ),
                    )
                ],
            )

        return infrastructure_configuration_resource

    def _add_lambda_cleanup(self, policy_statements, build_tags):
        lambda_cleanup_execution_role = None
        if self.custom_cleanup_lambda_role:
            execution_role = self.custom_cleanup_lambda_role
        else:
            # LambdaCleanupPolicies
            self._add_resource_delete_policy(
                policy_statements,
                ["cloudformation:DeleteStack"],
                [
                    self.format_arn(
                        service="cloudformation",
                        resource="stack",
                        resource_name="{0}/{1}".format(self.image_id, self._stack_unique_id()),
                    )
                ],
            )

            self._add_resource_delete_policy(
                policy_statements,
                ["ec2:CreateTags"],
                [
                    self.format_arn(
                        service="ec2",
                        account="",
                        resource="image",
                        region=region,
                        resource_name="*",
                    )
                    for region in self._get_distribution_regions()
                ],
            )

            self._add_resource_delete_policy(
                policy_statements,
                ["tag:TagResources"],
                ["*"],
            )

            self._add_resource_delete_policy(
                policy_statements,
                ["iam:DetachRolePolicy", "iam:DeleteRole", "iam:DeleteRolePolicy"],
                [
                    self.format_arn(
                        service="iam",
                        resource="role",
                        region="",
                        resource_name="{0}/{1}".format(
                            IAM_ROLE_PATH.strip("/"),
                            self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX + "Cleanup"),
                        ),
                    )
                ],
            )

            self._add_resource_delete_policy(
                policy_statements,
                ["lambda:DeleteFunction", "lambda:RemovePermission"],
                [
                    self.format_arn(
                        service="lambda",
                        resource="function",
                        sep=":",
                        resource_name=self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX),
                    )
                ],
            )

            self._add_resource_delete_policy(
                policy_statements,
                ["logs:DeleteLogGroup"],
                [
                    self.format_arn(
                        service="logs",
                        resource="log-group",
                        sep=":",
                        resource_name="/aws/lambda/{0}:*".format(
                            self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX)
                        ),
                    )
                ],
            )

            self._add_resource_delete_policy(
                policy_statements,
                ["iam:RemoveRoleFromInstanceProfile"],
                [
                    self.format_arn(
                        service="iam",
                        resource="instance-profile",
                        region="",
                        resource_name="{0}/{1}".format(
                            IAM_ROLE_PATH.strip("/"),
                            self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX),
                        ),
                    )
                ],
            )

            self._add_resource_delete_policy(
                policy_statements,
                ["iam:DetachRolePolicy", "iam:DeleteRolePolicy"],
                [
                    self.format_arn(
                        service="iam",
                        resource="role",
                        region="",
                        resource_name="{0}/{1}".format(
                            IAM_ROLE_PATH.strip("/"),
                            self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX),
                        ),
                    )
                ],
            )

            self._add_resource_delete_policy(
                policy_statements,
                ["SNS:GetTopicAttributes", "SNS:DeleteTopic", "SNS:Unsubscribe"],
                [
                    self.format_arn(
                        service="sns",
                        resource="{0}".format(self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX)),
                    )
                ],
            )

            policy_document = iam.PolicyDocument(statements=policy_statements)
            managed_lambda_policy = [
                Fn.sub("arn:${AWS::Partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"),
            ]

            if self.config.lambda_functions_vpc_config:
                managed_lambda_policy.append(Fn.sub(LAMBDA_VPC_ACCESS_MANAGED_POLICY))

            # LambdaCleanupExecutionRole
            lambda_cleanup_execution_role = iam.CfnRole(
                self,
                "DeleteStackFunctionExecutionRole",
                managed_policy_arns=managed_lambda_policy,
                assume_role_policy_document=get_assume_role_policy_document("lambda.amazonaws.com"),
                path=IAM_ROLE_PATH,
                policies=[
                    iam.CfnRole.PolicyProperty(
                        policy_document=policy_document,
                        policy_name="LambdaCleanupPolicy",
                    ),
                ],
                tags=build_tags,
                role_name=self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX + "Cleanup"),
            )

            execution_role = lambda_cleanup_execution_role.attr_arn

        # LambdaCleanupEnv
        lambda_env = awslambda.CfnFunction.EnvironmentProperty(variables={"IMAGE_STACK_ARN": self.stack_id})

        # LambdaCWLogGroup
        lambda_log = logs.CfnLogGroup(
            self,
            "DeleteStackFunctionLog",
            log_group_name="/aws/lambda/{0}".format(self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX)),
        )

        # LambdaCleanupFunction
        lambda_cleanup = awslambda.CfnFunction(
            self,
            "DeleteStackFunction",
            function_name=self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX),
            code=awslambda.CfnFunction.CodeProperty(
                s3_bucket=self.config.custom_s3_bucket
                or S3Bucket.get_bucket_name(AWSApi.instance().sts.get_account_id(), get_region()),
                s3_key=self.bucket.get_object_key(S3FileType.CUSTOM_RESOURCES, "artifacts.zip"),
            ),
            handler="delete_image_stack.handler",
            memory_size=128,
            role=execution_role,
            runtime="python3.9",
            timeout=900,
            environment=lambda_env,
            tags=build_tags,
            vpc_config=awslambda.CfnFunction.VpcConfigProperty(
                security_group_ids=self.config.lambda_functions_vpc_config.security_group_ids,
                subnet_ids=self.config.lambda_functions_vpc_config.subnet_ids,
            )
            if self.config.lambda_functions_vpc_config
            else None,
        )
        permission = awslambda.CfnPermission(
            self,
            "DeleteStackFunctionPermission",
            action="lambda:InvokeFunction",
            principal="sns.amazonaws.com",
            function_name=lambda_cleanup.attr_arn,
            source_arn=Fn.ref("BuildNotificationTopic"),
        )
        lambda_cleanup.add_depends_on(lambda_log)

        return lambda_cleanup, permission, lambda_cleanup_execution_role, lambda_log

    def _add_sns_topic_and_subscription(self, lambda_cleanup, build_tags):
        # SNSTopic
        sns_topic_resource = sns.CfnTopic(
            self,
            "BuildNotificationTopic",
            topic_name=self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX),
            tags=build_tags,
        )
        # SNSSubscription
        sns_subscription_resource = sns.CfnSubscription(
            self,
            "BuildNotificationSubscription",
            protocol="lambda",
            topic_arn=sns_topic_resource.ref,
            endpoint=lambda_cleanup.attr_arn,
        )

        return sns_subscription_resource, sns_topic_resource

    def _add_default_instance_role(self, cleanup_policy_statements, build_tags):
        """Set default instance role in imagebuilder cfn template."""
        managed_policy_arns = [
            Fn.sub("arn:${AWS::Partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"),
            Fn.sub("arn:${AWS::Partition}:iam::aws:policy/EC2InstanceProfileForImageBuilder"),
        ]
        if self.config.build.iam and self.config.build.iam.additional_iam_policies:
            for policy in self.config.build.iam.additional_iam_policy_arns:
                managed_policy_arns.append(policy)

        instancerole_policy_document = iam.PolicyDocument(
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    resources=[
                        self.format_arn(
                            service="ec2",
                            account="",
                            resource="image",
                            resource_name="*",
                        )
                    ],
                    actions=["ec2:CreateTags", "ec2:ModifyImageAttribute"],
                )
            ]
        )

        if self.config.build.components:
            for custom_component in self.config.build.components:
                # Check custom component is script, and the url is S3 url
                if custom_component.type == "script" and utils.get_url_scheme(custom_component.value) == "s3":
                    bucket_info = parse_bucket_url(custom_component.value)
                    bucket_name = bucket_info.get("bucket_name")
                    object_key = bucket_info.get("object_key")
                    instancerole_policy_document.add_statements(
                        iam.PolicyStatement(
                            actions=["s3:GetObject"],
                            effect=iam.Effect.ALLOW,
                            resources=[
                                self.format_arn(
                                    region="",
                                    service="s3",
                                    account="",
                                    resource=bucket_name,
                                    resource_name=object_key,
                                )
                            ],
                        ),
                    )

        instancerole_policy = iam.CfnRole.PolicyProperty(
            policy_name="InstanceRoleInlinePolicy",
            policy_document=instancerole_policy_document,
        )

        instance_role_resource = iam.CfnRole(
            self,
            "InstanceRole",
            path=IAM_ROLE_PATH,
            managed_policy_arns=managed_policy_arns,
            assume_role_policy_document=get_assume_role_policy_document("ec2.{0}".format(self.url_suffix)),
            policies=[
                instancerole_policy,
            ],
            tags=build_tags,
            role_name=self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX),
        )
        if not self.custom_cleanup_lambda_role:
            self._add_resource_delete_policy(
                cleanup_policy_statements,
                ["iam:DeleteRole"],
                [
                    self.format_arn(
                        service="iam",
                        region="",
                        resource="role",
                        resource_name="{0}/{1}".format(
                            IAM_ROLE_PATH.strip("/"),
                            self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX),
                        ),
                    )
                ],
            )

        return instance_role_resource

    def _add_instance_profile(self, cleanup_policy_statements, instance_role=None):
        """Set default instance profile in imagebuilder cfn template."""
        instance_profile_resource = iam.CfnInstanceProfile(
            self,
            "InstanceProfile",
            path=IAM_ROLE_PATH,
            roles=[instance_role.split("/")[-1] if instance_role else Fn.ref("InstanceRole")],
            instance_profile_name=self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX),
        )

        if not self.custom_cleanup_lambda_role:
            self._add_resource_delete_policy(
                cleanup_policy_statements,
                ["iam:DeleteInstanceProfile"],
                [
                    self.format_arn(
                        service="iam",
                        region="",
                        resource="instance-profile",
                        resource_name="{0}/{1}".format(
                            IAM_ROLE_PATH.strip("/"),
                            self._build_resource_name(IMAGEBUILDER_RESOURCE_NAME_PREFIX),
                        ),
                    )
                ],
            )

        return instance_profile_resource

    def _add_custom_components(self, components, policy_statements, components_resources):
        """Set custom component in imagebuilder cfn template."""
        initial_components_len = len(components)
        arn_components_len = 0
        for custom_component in self.config.build.components:
            custom_components_len = len(components) - initial_components_len - arn_components_len
            if custom_component.type == "arn":
                components.append(
                    imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(component_arn=custom_component.value)
                )
                arn_components_len += 1
            else:
                component_script_name = custom_component.value.split("/")[-1]
                component_id = "ScriptComponent" + str(custom_components_len)
                custom_component_resource = imagebuilder.CfnComponent(
                    self,
                    component_id,
                    name=self._build_resource_name(
                        IMAGEBUILDER_RESOURCE_NAME_PREFIX + "-Script-{0}".format(str(custom_components_len))
                    ),
                    version=utils.get_installed_version(base_version_only=True),
                    description="This component is custom component for script, script name is {0}, script url is "
                    "{1}".format(component_script_name, custom_component.value),
                    platform="Linux",
                    data=wrap_script_to_component(custom_component.value),
                )
                components.append(
                    imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(component_arn=Fn.ref(component_id))
                )
                components_resources.append(custom_component_resource)
                if not self.custom_cleanup_lambda_role:
                    self._add_resource_delete_policy(
                        policy_statements,
                        ["imagebuilder:DeleteComponent"],
                        [
                            self.format_arn(
                                service="imagebuilder",
                                resource="component",
                                resource_name="{0}/*".format(
                                    self._build_resource_name(
                                        IMAGEBUILDER_RESOURCE_NAME_PREFIX
                                        + "-Script-{0}".format(str(custom_components_len)),
                                        to_lower=True,
                                    )
                                ),
                            )
                        ],
                    )

    def _set_ebs_volume(self):
        """Set ebs root volume in imagebuilder cfn template."""
        if (
            self.config.image is None
            or self.config.image.root_volume is None
            or self.config.image.root_volume.size is None
        ):
            ami_id = imagebuilder_utils.get_ami_id(self.config.build.parent_image)
            ami_info = AWSApi.instance().ec2.describe_image(ami_id)
            default_root_volume_size = ami_info.volume_size + PCLUSTER_RESERVED_VOLUME_SIZE
            if self.config.image is None or self.config.image.root_volume is None:
                default_root_volume = Volume(size=default_root_volume_size)
            else:
                default_root_volume = copy.deepcopy(self.config.image.root_volume)
                default_root_volume.size = default_root_volume_size
            ebs = imagebuilder.CfnImageRecipe.EbsInstanceBlockDeviceSpecificationProperty(
                volume_size=default_root_volume.size,
                volume_type=ROOT_VOLUME_TYPE,
                encrypted=default_root_volume.encrypted,
                kms_key_id=default_root_volume.kms_key_id,
            )
        else:
            ebs = imagebuilder.CfnImageRecipe.EbsInstanceBlockDeviceSpecificationProperty(
                volume_size=self.config.image.root_volume.size,
                volume_type=ROOT_VOLUME_TYPE,
                encrypted=self.config.image.root_volume.encrypted,
                kms_key_id=self.config.image.root_volume.kms_key_id,
            )

        return ebs

    @staticmethod
    def _add_resource_delete_policy(policy_statements, actions: List[str], resources: List[str]):
        policy_statements.append(
            iam.PolicyStatement(
                actions=actions,
                effect=iam.Effect.ALLOW,
                resources=resources,
            )
        )


def _load_yaml(source_dir, file_name):
    """Get string data from yaml file."""
    return yaml.dump(utils.load_yaml_dict(os.path.join(source_dir, file_name)))
