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

import yaml
from aws_cdk import aws_iam as iam
from aws_cdk import aws_imagebuilder as imagebuilder
from aws_cdk import core

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
from pcluster.models.imagebuilder import ImageBuilder, Volume
from pcluster.models.imagebuilder_extra_attributes import ChefAttributes
from pcluster.schemas.imagebuilder_schema import ImageBuilderSchema


class ImageBuilderStack(core.Stack):
    """Create the Stack for imagebuilder."""

    def __init__(self, scope: core.Construct, construct_id: str, imagebuild: ImageBuilder, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.imagebuild = imagebuild
        build = imagebuild.build
        dev_settings = imagebuild.dev_settings

        config_file = ImageBuilderSchema().dump(copy.deepcopy(self.imagebuild))
        self.template_options.metadata = {"Config": yaml.dump(config_file)}

        # TODO: use attributes from imagebuilder config instead of using these static variables.
        custom_chef_cookbook = dev_settings.cookbook.chef_cookbook if dev_settings and dev_settings.cookbook else ""
        core.CfnParameter(
            self,
            "CfnParamCookbookVersion",
            type="String",
            default=utils.get_installed_version(),
            description="CookbookVersion",
        )
        core.CfnParameter(
            self, "CfnParamChefCookbook", type="String", default=custom_chef_cookbook, description="ChefCookbook"
        )
        core.CfnParameter(self, "CfnParamCincInstaller", type="String", default="", description="CincInstaller")
        core.CfnParameter(
            self,
            "CfnParamChefDnaJson",
            type="String",
            default=ChefAttributes(dev_settings).dump_json(),
            description="ChefAttributes",
        )
        core.CfnParameter(
            self,
            "CfnParamUpdateOsAndReboot",
            type="String",
            default="true" if dev_settings and dev_settings.update_os_and_reboot else "false",
            description="UpdateOsAndReboot",
        )

        # Setup ImageBuilder Resources
        resources_prefix = utils.generate_random_prefix()

        # InstanceRole and InstanceProfile
        instance_profile_name = None
        if build.instance_role:
            instance_role_type = self._get_instance_role_type()
            if instance_role_type == InstanceRole.ROLE:
                self._set_instance_profile(instance_role=build.instance_role)
            else:
                instance_profile_name = build.instance_role
        else:
            self._set_default_instance_role()
            self._set_instance_profile()

        build_tags = {tag.key: tag.value for tag in build.tags} if build.tags else None
        ami_tags = {tag.key: tag.value for tag in self.imagebuild.image.tags} if self.imagebuild.image.tags else None

        # InfrastructureConfiguration
        imagebuilder.CfnInfrastructureConfiguration(
            self,
            id="ParallelClusterInfrastructureConfiguration",
            name="-".join(["ParallelClusterInfrastructureConfiguration", resources_prefix]),
            tags=build_tags,
            instance_profile_name=core.Fn.ref(instance_profile_name or "InstanceProfile"),
            terminate_instance_on_failure=dev_settings.terminate_instance_on_failure
            if dev_settings and dev_settings.terminate_instance_on_failure is not None
            else True,
            instance_types=[build.instance_type],
            security_group_ids=build.security_group_ids,
            subnet_id=build.subnet_id,
        )

        imagebuilder_resources_dir = os.path.join(imagebuilder_utils.get_resources_directory(), "imagebuilder")
        # Components
        components = []
        if dev_settings and dev_settings.update_os_and_reboot:
            imagebuilder.CfnComponent(
                self,
                id="UpdateAndRebootComponent",
                name="-".join(["UpdateAndRebootComponent", resources_prefix]),
                version=utils.get_installed_version(),
                tags=build_tags,
                description="Update OS and Reboot",
                platform="Linux",
                data=core.Fn.sub(load_yaml(imagebuilder_resources_dir, "update_and_reboot.yaml")),
            )
            components.append(
                imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(
                    component_arn=core.Fn.ref("UpdateAndRebootComponent")
                )
            )

        imagebuilder.CfnComponent(
            self,
            id="ParallelClusterComponent",
            name="-".join(["ParallelClusterComponent", resources_prefix]),
            version=utils.get_installed_version(),
            tags=build_tags,
            description="Bake ParallelCluster AMI",
            platform="Linux",
            data=core.Fn.sub(load_yaml(imagebuilder_resources_dir, "parallelcluster.yaml")),
        )

        components.append(
            imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(
                component_arn=core.Fn.ref("ParallelClusterComponent")
            )
        )

        if build.components:
            self._set_custom_components(components, resources_prefix)

        imagebuilder.CfnComponent(
            self,
            id="ParallelClusterTagComponent",
            name="-".join(["ParallelClusterTagComponent", resources_prefix]),
            version=utils.get_installed_version(),
            tags=build_tags,
            description="Tag ParallelCluster AMI",
            platform="Linux",
            data=load_yaml(imagebuilder_resources_dir, "parallelcluster_tag.yaml"),
        )

        components.append(
            imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(
                component_arn=core.Fn.ref("ParallelClusterTagComponent")
            )
        )

        # ImageRecipe
        imagebuilder.CfnImageRecipe(
            self,
            id="ParallelClusterImageRecipe",
            name="-".join(["ParallelClusterImageRecipe", resources_prefix]),
            version=utils.get_installed_version(),
            tags=build_tags,
            parent_image=core.Fn.sub(build.parent_image),
            components=components,
            block_device_mappings=[
                imagebuilder.CfnImageRecipe.InstanceBlockDeviceMappingProperty(
                    device_name=self._get_root_device_name(),
                    ebs=self._set_ebs_volume(),
                )
            ],
        )

        ami_distribution_configuration = {
            "Name": self._set_ami_name(),
            "AmiTags": ami_tags,
            "LaunchPermissionConfiguration": dev_settings.distribution_configuration.launch_permission
            if dev_settings and dev_settings.distribution_configuration
            else None,
        }

        distributions = []
        if dev_settings and dev_settings.distribution_configuration and dev_settings.distribution_configuration.regions:
            regions = set(map(str.strip, dev_settings.distribution_configuration.regions.split(",")))
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
                    region=core.Fn.sub("${AWS::Region}"),
                )
            )

        imagebuilder.CfnDistributionConfiguration(
            self,
            id="ParallelClusterDistributionConfiguration",
            name="-".join(["ParallelClusterDistributionConfiguration", resources_prefix]),
            tags=build_tags,
            distributions=distributions,
        )

        # Image
        imagebuilder.CfnImage(
            self,
            id="ParallelClusterImage",
            tags=build_tags,
            image_recipe_arn=core.Fn.ref("ParallelClusterImageRecipe"),
            infrastructure_configuration_arn=core.Fn.ref("ParallelClusterInfrastructureConfiguration"),
            distribution_configuration_arn=core.Fn.ref("ParallelClusterDistributionConfiguration"),
        )

    def _set_ami_name(self):
        return self.imagebuild.image.name + AMI_NAME_REQUIRED_SUBSTRING

    def _get_instance_role_type(self):
        """Get instance role type based on instance_role in config."""
        instance_role = self.imagebuild.build.instance_role
        identifier = instance_role.split("/", 1)[0]
        if identifier.endswith("role"):
            return InstanceRole.ROLE
        return InstanceRole.INSTANCE_PROFILE

    def _set_default_instance_role(self):
        """Set default instance role in imagebuilder cfn template."""
        build = self.imagebuild.build
        managed_policy_arns = [
            core.Fn.sub("arn:${AWS::Partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"),
            core.Fn.sub("arn:${AWS::Partition}:iam::aws:policy/EC2InstanceProfileForImageBuilder"),
        ]

        instancerole_policy_document = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["ec2:CreateTags", "ec2:ModifyImageAttribute"],
                    "Resource": [
                        core.Fn.sub("arn:${AWS::Partition}:ec2:*::image/*"),
                    ],
                },
            ],
        }

        if build.components:
            for custom_component in build.components:
                # Check custom component is script, and the url is S3 url
                if custom_component.type == "script" and get_url_scheme(custom_component.value) == "s3":
                    bucket_info = parse_bucket_url(custom_component.value)
                    bucket_name = bucket_info.get("bucket_name")
                    object_key = bucket_info.get("object_key")
                    action_list = instancerole_policy_document["Statement"][0]["Action"]

                    if "s3:GetObject" not in action_list:
                        action_list.append("s3:GetObject")
                        instancerole_policy_document["Statement"][0]["Action"] = action_list
                    resources_list = instancerole_policy_document["Statement"][0]["Resource"]
                    resources_list.append(
                        core.Fn.sub("arn:${AWS::Partition}:s3:::" + "{0}/{1}".format(bucket_name, object_key))
                    )
                    instancerole_policy_document["Statement"][0]["Resource"] = resources_list

        instancerole_policy = iam.CfnRole.PolicyProperty(
            policy_name="InstanceRoleInlinePolicy",
            policy_document=instancerole_policy_document,
        )

        instancerole = iam.CfnRole(
            self,
            id="InstanceRole",
            managed_policy_arns=managed_policy_arns,
            assume_role_policy_document={
                "Statement": {
                    "Action": "sts:AssumeRole",
                    "Effect": "Allow",
                    "Principal": {"Service": "ec2.amazonaws.com"},
                },
                "Version": "2012-10-17",
            },
            path="/executionServiceEC2Role/",
            policies=[
                instancerole_policy,
            ],
            tags=[core.CfnTag(key=tag.key, value=tag.value) for tag in self.imagebuild.build.tags]
            if self.imagebuild.build.tags
            else None,
        )

        instancerole.add_metadata("Comment", "Role to be used by instance during image build.")

    def _set_instance_profile(self, instance_role="InstanceRole"):
        """Set default instance profile in imagebuilder cfn template."""
        iam.CfnInstanceProfile(
            self, id="InstanceProfile", path="/executionServiceEC2Role/", roles=[core.Fn.ref(instance_role)]
        )

    def _set_custom_components(self, components, resources_prefix):
        """Set custom component in imagebuilder cfn template."""
        build = self.imagebuild.build
        custom_components = build.components
        initial_components_len = len(components)
        arn_components_len = 0
        for custom_component in custom_components:
            custom_components_len = len(components) - initial_components_len - arn_components_len
            if custom_component.type == "arn":
                components.append(
                    imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(component_arn=custom_component.value)
                )
                arn_components_len += 1
            else:
                component_script_name = custom_component.value.split("/")[-1]
                id = "ParallelClusterScriptComponent" + str(custom_components_len)
                imagebuilder.CfnComponent(
                    self,
                    id=id,
                    name="-".join(["ParallelClusterComponentScript", str(custom_components_len), resources_prefix]),
                    version=utils.get_installed_version(),
                    description="This component is custom component for script, script name is {0}, script url is "
                    "{1}".format(component_script_name, custom_component.value),
                    platform="Linux",
                    data=imagebuilder_utils.wrap_script_to_component(custom_component.value),
                )
                components.append(
                    imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(component_arn=core.Fn.ref(id))
                )

    def _set_ebs_volume(self):
        """Set ebs root volume in imagebuilder cfn template."""
        image = self.imagebuild.image
        build = self.imagebuild.build

        if image.root_volume is None or image.root_volume.size is None:
            ami_id = imagebuilder_utils.get_ami_id(build.parent_image)
            ami_info = AWSApi.instance().ec2.describe_image(ami_id)
            default_root_volume_size = (
                ami_info.get("BlockDeviceMappings")[0].get("Ebs").get("VolumeSize") + PCLUSTER_RESERVED_VOLUME_SIZE
            )
            if image.root_volume is None:
                default_root_volume = Volume(size=default_root_volume_size)
            else:
                default_root_volume = copy.deepcopy(image.root_volume)
                default_root_volume.size = default_root_volume_size
            ebs = imagebuilder.CfnImageRecipe.EbsInstanceBlockDeviceSpecificationProperty(
                volume_size=default_root_volume.size,
                volume_type=ROOT_VOLUME_TYPE,
                encrypted=default_root_volume.encrypted,
                kms_key_id=default_root_volume.kms_key_id,
            )
        else:
            ebs = imagebuilder.CfnImageRecipe.EbsInstanceBlockDeviceSpecificationProperty(
                volume_size=image.root_volume.size,
                volume_type=ROOT_VOLUME_TYPE,
                encrypted=image.root_volume.encrypted,
                kms_key_id=image.root_volume.kms_key_id,
            )

        return ebs

    def _get_root_device_name(self):
        ami_id = imagebuilder_utils.get_ami_id(self.imagebuild.build.parent_image)
        ami_info = AWSApi.instance().ec2.describe_image(ami_id)
        return ami_info.get("BlockDeviceMappings")[0].get("DeviceName")
