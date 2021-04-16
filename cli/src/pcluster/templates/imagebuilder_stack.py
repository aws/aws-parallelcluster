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
# This module contains all the classes required to convert a ImageBuilder into a CFN template by using CDK.
#
import copy
import os
from typing import List

from aws_cdk import aws_iam as iam
from aws_cdk import aws_imagebuilder as imagebuilder
from aws_cdk import aws_lambda as awslambda
from aws_cdk import aws_sns as sns
from aws_cdk.core import CfnParameter, CfnTag, Construct, Fn, Stack

import pcluster.utils as utils
from common import imagebuilder_utils
from common.aws.aws_api import AWSApi
from common.imagebuilder_utils import (
    AMI_NAME_REQUIRED_SUBSTRING,
    PCLUSTER_RESERVED_VOLUME_SIZE,
    ROOT_VOLUME_TYPE,
    InstanceRole,
)
from common.utils import get_url_scheme, load_yaml, parse_bucket_url
from pcluster.constants import PCLUSTER_S3_BUCKET_TAG, PCLUSTER_S3_IMAGE_DIR_TAG
from pcluster.models.common import BaseTag, S3Bucket, S3FileType
from pcluster.models.imagebuilder_config import ImageBuilderConfig, ImageBuilderExtraChefAttributes, Volume
from pcluster.templates.cdk_builder_utils import get_assume_role_policy_document

RESOURCE_NAME_PREFIX = "ParallelClusterImage"


class ImageBuilderCdkStack(Stack):
    """Create the Stack for imagebuilder."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        image_config: ImageBuilderConfig,
        image_name: str,
        bucket: S3Bucket,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.config = image_config
        self.image_name = image_name
        self.bucket = bucket

        self.custom_instance_role = (
            self.config.build.iam.instance_role
            if self.config.build.iam and self.config.build.iam.instance_role
            else None
        )
        self.custom_cleanup_lambda_role = (
            self.config.build.iam.cleanup_lambda_role
            if self.config.build.iam and self.config.build.iam.cleanup_lambda_role
            else None
        )

        self._add_cfn_parameters()
        self._add_resources()

    # -- Utility methods --------------------------------------------------------------------------------------------- #

    def _get_root_device_name(self):
        ami_id = imagebuilder_utils.get_ami_id(self.config.build.parent_image)
        ami_info = AWSApi.instance().ec2.describe_image(ami_id)
        return ami_info.get("BlockDeviceMappings")[0].get("DeviceName")

    def _stack_unique_id(self):
        return Fn.select(2, Fn.split("/", self.stack_id))

    def _build_resource_name(self, name, to_lower=False):
        if to_lower:
            name = name.lower()
        return "-".join([name, self._stack_unique_id()])

    def _get_instance_role_type(self):
        """Get instance role type based on instance_role in config."""
        identifier = self.custom_instance_role.split("/", 1)[0]
        if identifier.endswith("role"):
            return InstanceRole.ROLE
        return InstanceRole.INSTANCE_PROFILE

    # -- Parameters -------------------------------------------------------------------------------------------------- #

    def _add_cfn_parameters(self):
        custom_chef_cookbook = (
            self.config.dev_settings.cookbook.chef_cookbook
            if self.config.dev_settings and self.config.dev_settings.cookbook
            else ""
        )

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
            default="true" if self.config.dev_settings and self.config.dev_settings.update_os_and_reboot else "false",
            description="UpdateOsAndReboot",
        )

    # -- Resources --------------------------------------------------------------------------------------------------- #

    def _add_resources(self):
        # Add default build tags information
        tags = copy.deepcopy(self.config.build.tags) or []
        tags.append(BaseTag(key="pcluster_build_image", value=utils.get_installed_version()))
        build_tags_map = {tag.key: tag.value for tag in tags}
        build_tags_list = [CfnTag(key=tag.key, value=tag.value) for tag in tags]

        # Add default ami tags information
        tags = copy.deepcopy(self.config.image.tags) if self.config.image and self.config.image.tags else []
        tags.append(BaseTag(key="pcluster_version", value=utils.get_installed_version()))
        tags.append(BaseTag(key=PCLUSTER_S3_BUCKET_TAG, value=self.bucket.name))
        tags.append(BaseTag(key=PCLUSTER_S3_IMAGE_DIR_TAG, value=self.bucket.artifact_directory))
        ami_tags = {tag.key: tag.value for tag in tags}

        lambda_cleanup_policy_statements = []

        # InstanceRole and InstanceProfile
        instance_profile_name = None
        if self.custom_instance_role:
            instance_role_type = self._get_instance_role_type()
            if instance_role_type == InstanceRole.ROLE:
                self._add_instance_profile(
                    instance_role=self.custom_instance_role,
                    cleanup_policy_statements=lambda_cleanup_policy_statements,
                )
            else:
                instance_profile_name = self.custom_instance_role
        else:
            self._add_default_instance_role(lambda_cleanup_policy_statements, build_tags_list)
            self._add_instance_profile(cleanup_policy_statements=lambda_cleanup_policy_statements)

        self._add_imagebuilder_resources(
            build_tags_map, ami_tags, instance_profile_name, lambda_cleanup_policy_statements
        )

        lambda_cleanup = self._add_lambda_cleanup(lambda_cleanup_policy_statements, build_tags_list)
        self._add_sns_topic(lambda_cleanup, build_tags_list)

    def _add_imagebuilder_resources(
        self, build_tags, ami_tags, instance_profile_name, lambda_cleanup_policy_statements
    ):
        self._add_imagebuilder_infrastructure_configuration(
            build_tags, instance_profile_name, lambda_cleanup_policy_statements
        )

        components = self._add_imagebuilder_components(build_tags, lambda_cleanup_policy_statements)

        self._add_imagebuilder_image_recipe(build_tags, components, lambda_cleanup_policy_statements)

        self._add_imagebuilder_distribution_configuration(ami_tags, build_tags, lambda_cleanup_policy_statements)

        self._add_imagebuilder_image(build_tags, lambda_cleanup_policy_statements)

    def _add_imagebuilder_image(self, build_tags, lambda_cleanup_policy_statements):
        # ImageBuilderImage
        imagebuilder.CfnImage(
            self,
            id=RESOURCE_NAME_PREFIX,
            tags=build_tags,
            image_recipe_arn=Fn.ref("ImageRecipe"),
            infrastructure_configuration_arn=Fn.ref("InfrastructureConfiguration"),
            distribution_configuration_arn=Fn.ref("DistributionConfiguration"),
        )
        if not self.custom_cleanup_lambda_role:
            self._add_resource_delete_policy(
                lambda_cleanup_policy_statements,
                ["imagebuilder:DeleteImage"],
                [
                    self.format_arn(
                        service="imagebuilder",
                        resource="image",
                        resource_name="{0}/*".format(self._build_resource_name(RESOURCE_NAME_PREFIX, to_lower=True)),
                    )
                ],
            )

    def _add_imagebuilder_distribution_configuration(self, ami_tags, build_tags, lambda_cleanup_policy_statements):
        # ImageBuilderDistributionConfiguration
        ami_distribution_configuration = {
            "Name": self.image_name + AMI_NAME_REQUIRED_SUBSTRING,
            "AmiTags": ami_tags,
            "LaunchPermissionConfiguration": self.config.dev_settings.distribution_configuration.launch_permission
            if self.config.dev_settings and self.config.dev_settings.distribution_configuration
            else None,
        }
        distributions = []
        if (
            self.config.dev_settings
            and self.config.dev_settings.distribution_configuration
            and self.config.dev_settings.distribution_configuration.regions
        ):
            regions = set(map(str.strip, self.config.dev_settings.distribution_configuration.regions.split(",")))
            for region in regions:
                distributions.append(
                    imagebuilder.CfnDistributionConfiguration.DistributionProperty(
                        ami_distribution_configuration=ami_distribution_configuration,
                        region=region,
                    )
                )
        else:
            distributions.append(
                imagebuilder.CfnDistributionConfiguration.DistributionProperty(
                    ami_distribution_configuration=ami_distribution_configuration,
                    region=self.region,
                )
            )
        imagebuilder.CfnDistributionConfiguration(
            self,
            id="DistributionConfiguration",
            name=self._build_resource_name(RESOURCE_NAME_PREFIX),
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
                        resource_name="{0}".format(self._build_resource_name(RESOURCE_NAME_PREFIX, to_lower=True)),
                    )
                ],
            )

    def _add_imagebuilder_image_recipe(self, build_tags, components, lambda_cleanup_policy_statements):
        # ImageBuilderImageRecipe
        imagebuilder.CfnImageRecipe(
            self,
            id="ImageRecipe",
            name=self._build_resource_name(RESOURCE_NAME_PREFIX),
            version=utils.get_installed_version(),
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
                        resource_name="{0}/*".format(self._build_resource_name(RESOURCE_NAME_PREFIX, to_lower=True)),
                    )
                ],
            )

    def _add_imagebuilder_components(self, build_tags, lambda_cleanup_policy_statements):
        imagebuilder_resources_dir = os.path.join(imagebuilder_utils.get_resources_directory(), "imagebuilder")

        # ImageBuilderComponents
        components = []
        if self.config.dev_settings and self.config.dev_settings.update_os_and_reboot:
            imagebuilder.CfnComponent(
                self,
                id="UpdateOSComponent",
                name=self._build_resource_name(RESOURCE_NAME_PREFIX + "-UpdateOS"),
                version=utils.get_installed_version(),
                tags=build_tags,
                description="Update OS and Reboot",
                platform="Linux",
                data=Fn.sub(load_yaml(imagebuilder_resources_dir, "update_and_reboot.yaml")),
            )
            components.append(
                imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(component_arn=Fn.ref("UpdateOSComponent"))
            )
            if not self.custom_cleanup_lambda_role:
                self._add_resource_delete_policy(
                    lambda_cleanup_policy_statements,
                    ["imagebuilder:DeleteComponent"],
                    [
                        self.format_arn(
                            service="imagebuilder",
                            resource="component",
                            resource_name="{0}/*".format(
                                self._build_resource_name(RESOURCE_NAME_PREFIX + "-UpdateOS", to_lower=True)
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
            imagebuilder.CfnComponent(
                self,
                id="ParallelClusterComponent",
                name=self._build_resource_name(RESOURCE_NAME_PREFIX),
                version=utils.get_installed_version(),
                tags=build_tags,
                description="Install ParallelCluster software stack",
                platform="Linux",
                data=Fn.sub(load_yaml(imagebuilder_resources_dir, "parallelcluster.yaml")),
            )
            components.append(
                imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(
                    component_arn=Fn.ref("ParallelClusterComponent")
                )
            )
            if not self.custom_cleanup_lambda_role:
                self._add_resource_delete_policy(
                    lambda_cleanup_policy_statements,
                    ["imagebuilder:DeleteComponent"],
                    [
                        self.format_arn(
                            service="imagebuilder",
                            resource="component",
                            resource_name="{0}/*".format(
                                self._build_resource_name(RESOURCE_NAME_PREFIX, to_lower=True)
                            ),
                        )
                    ],
                )

        if self.config.build.components:
            self._add_custom_components(components, lambda_cleanup_policy_statements)

        imagebuilder.CfnComponent(
            self,
            id="TagComponent",
            name=self._build_resource_name(RESOURCE_NAME_PREFIX + "-Tag"),
            version=utils.get_installed_version(),
            tags=build_tags,
            description="Tag ParallelCluster AMI",
            platform="Linux",
            data=load_yaml(imagebuilder_resources_dir, "parallelcluster_tag.yaml"),
        )
        components.append(
            imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(component_arn=Fn.ref("TagComponent"))
        )
        if not self.custom_cleanup_lambda_role:
            self._add_resource_delete_policy(
                lambda_cleanup_policy_statements,
                ["imagebuilder:DeleteComponent"],
                [
                    self.format_arn(
                        service="imagebuilder",
                        resource="component",
                        resource_name="{0}/*".format(
                            self._build_resource_name(RESOURCE_NAME_PREFIX + "-Tag", to_lower=True)
                        ),
                    )
                ],
            )

        return components

    def _add_imagebuilder_infrastructure_configuration(
        self, build_tags, instance_profile_name, lambda_cleanup_policy_statements
    ):
        # ImageBuilderInfrastructureConfiguration
        imagebuilder.CfnInfrastructureConfiguration(
            self,
            id="InfrastructureConfiguration",
            name=self._build_resource_name(RESOURCE_NAME_PREFIX),
            tags=build_tags,
            instance_profile_name=instance_profile_name or Fn.ref("InstanceProfile"),
            terminate_instance_on_failure=self.config.dev_settings.terminate_instance_on_failure
            if self.config.dev_settings and self.config.dev_settings.terminate_instance_on_failure is not None
            else True,
            instance_types=[self.config.build.instance_type],
            security_group_ids=self.config.build.security_group_ids,
            subnet_id=self.config.build.subnet_id,
            sns_topic_arn=Fn.ref("BuildNotificationTopic"),
        )
        if not self.custom_cleanup_lambda_role:
            self._add_resource_delete_policy(
                lambda_cleanup_policy_statements,
                ["imagebuilder:DeleteInfrastructureConfiguration"],
                [
                    self.format_arn(
                        service="imagebuilder",
                        resource="infrastructure-configuration",
                        resource_name="{0}".format(self._build_resource_name(RESOURCE_NAME_PREFIX, to_lower=True)),
                    )
                ],
            )

    def _add_lambda_cleanup(self, policy_statements, build_tags):
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
                        resource_name="{0}/{1}".format(self.image_name, self._stack_unique_id()),
                    )
                ],
            )

            self._add_resource_delete_policy(
                policy_statements,
                ["iam:DetachRolePolicy", "iam:DeleteRole", "iam:DeleteRolePolicy"],
                [
                    self.format_arn(
                        service="iam",
                        resource="role",
                        region="",
                        resource_name="{0}/{1}-{2}-*".format(
                            RESOURCE_NAME_PREFIX, self.image_name, "DeleteStackFunctionExecutionRole"
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
                        resource_name=self._build_resource_name(RESOURCE_NAME_PREFIX),
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
                        resource_name="{0}/{1}-{2}-*".format(RESOURCE_NAME_PREFIX, self.image_name, "InstanceProfile"),
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
                        resource_name="{0}/{1}-{2}-*".format(RESOURCE_NAME_PREFIX, self.image_name, "InstanceRole"),
                    )
                ],
            )

            self._add_resource_delete_policy(
                policy_statements,
                ["SNS:GetTopicAttributes", "SNS:DeleteTopic"],
                [
                    self.format_arn(
                        service="sns",
                        resource="{0}".format(self._build_resource_name(RESOURCE_NAME_PREFIX)),
                    )
                ],
            )

            policy_document = iam.PolicyDocument(statements=policy_statements)
            managed_lambda_policy = [
                Fn.sub("arn:${AWS::Partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"),
            ]

            # LambdaCleanupExecutionRole
            lambda_cleanup_execution_role = iam.CfnRole(
                scope=self,
                id="DeleteStackFunctionExecutionRole",
                managed_policy_arns=managed_lambda_policy,
                assume_role_policy_document=get_assume_role_policy_document("lambda.{0}".format(self.url_suffix)),
                path="/{0}/".format(RESOURCE_NAME_PREFIX),
                policies=[
                    iam.CfnRole.PolicyProperty(
                        policy_document=policy_document,
                        policy_name="LambdaCleanupPolicy",
                    ),
                ],
                tags=build_tags,
            )

            execution_role = lambda_cleanup_execution_role.attr_arn

        # LambdaCleanupEnv
        lambda_env = awslambda.CfnFunction.EnvironmentProperty(variables={"IMAGE_STACK_ARN": self.stack_id})

        # LambdaCleanupFunction
        lambda_cleanup = awslambda.CfnFunction(
            scope=self,
            id="DeleteStackFunction",
            function_name=self._build_resource_name(RESOURCE_NAME_PREFIX),
            code=awslambda.CfnFunction.CodeProperty(
                s3_bucket=self.config.custom_s3_bucket
                or S3Bucket.get_bucket_name(AWSApi.instance().sts.get_account_id(), utils.get_region()),
                s3_key=self.bucket.get_object_key(S3FileType.CUSTOM_RESOURCES.value, "artifacts.zip"),
            ),
            handler="delete_image_stack.handler",
            memory_size=128,
            role=execution_role,
            runtime="python3.8",
            timeout=900,
            environment=lambda_env,
            tags=build_tags,
        )
        awslambda.CfnPermission(
            self,
            id="DeleteStackFunctionPermission",
            action="lambda:InvokeFunction",
            principal="sns.{0}".format(self.url_suffix),
            function_name=lambda_cleanup.attr_arn,
            source_arn=Fn.ref("BuildNotificationTopic"),
        )

        return lambda_cleanup

    def _add_sns_topic(self, lambda_cleanup, build_tags):
        # SNSTopic
        subscription = sns.CfnTopic.SubscriptionProperty(endpoint=lambda_cleanup.attr_arn, protocol="lambda")
        sns.CfnTopic(
            self,
            id="BuildNotificationTopic",
            subscription=[subscription],
            topic_name=self._build_resource_name(RESOURCE_NAME_PREFIX),
            tags=build_tags,
        )

    def _add_default_instance_role(self, cleanup_policy_statements, build_tags):
        """Set default instance role in imagebuilder cfn template."""
        managed_policy_arns = [
            Fn.sub("arn:${AWS::Partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"),
            Fn.sub("arn:${AWS::Partition}:iam::aws:policy/EC2InstanceProfileForImageBuilder"),
        ]

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
                if custom_component.type == "script" and get_url_scheme(custom_component.value) == "s3":
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

        iam.CfnRole(
            self,
            id="InstanceRole",
            managed_policy_arns=managed_policy_arns,
            assume_role_policy_document=get_assume_role_policy_document("ec2.{0}".format(self.url_suffix)),
            path="/{0}/".format(RESOURCE_NAME_PREFIX),
            policies=[
                instancerole_policy,
            ],
            tags=build_tags,
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
                        resource_name="{0}/{1}-{2}-*".format(RESOURCE_NAME_PREFIX, self.image_name, "InstanceRole"),
                    )
                ],
            )

    def _add_instance_profile(self, cleanup_policy_statements, instance_role=None):
        """Set default instance profile in imagebuilder cfn template."""
        iam.CfnInstanceProfile(
            self,
            id="InstanceProfile",
            path="/{0}/".format(RESOURCE_NAME_PREFIX),
            roles=[instance_role or Fn.ref("InstanceRole")],
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
                        resource_name="{0}/{1}-{2}-*".format(RESOURCE_NAME_PREFIX, self.image_name, "InstanceProfile"),
                    )
                ],
            )

    def _add_custom_components(self, components, policy_statements):
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
                imagebuilder.CfnComponent(
                    self,
                    id=component_id,
                    name=self._build_resource_name(
                        RESOURCE_NAME_PREFIX + "-Script-{0}".format(str(custom_components_len))
                    ),
                    version=utils.get_installed_version(),
                    description="This component is custom component for script, script name is {0}, script url is "
                    "{1}".format(component_script_name, custom_component.value),
                    platform="Linux",
                    data=imagebuilder_utils.wrap_script_to_component(custom_component.value),
                )
                components.append(
                    imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(component_arn=Fn.ref(component_id))
                )
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
                                        RESOURCE_NAME_PREFIX + "-Script-{0}".format(str(custom_components_len)),
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
            default_root_volume_size = (
                ami_info.get("BlockDeviceMappings")[0].get("Ebs").get("VolumeSize") + PCLUSTER_RESERVED_VOLUME_SIZE
            )
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
