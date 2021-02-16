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
from common.imagebuilder_utils import PCLUSTER_RESERVED_VOLUME_SIZE, ROOT_VOLUME_TYPE, InstanceRole
from common.utils import load_yaml
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
            "CfnParamDnaJson",
            type="String",
            default=ChefAttributes(dev_settings).dump_json(),
            description="ChefAttributes",
        )

        core.CfnParameter(
            self,
            "UpdateAndReboot",
            type="String",
            default=str.lower(str(dev_settings.update_os_and_reboot)),
            description="UpdateAndReboot",
        )

        # Setup ImageBuilder Resources
        resources_prefix = utils.generate_random_prefix()

        # InstanceRole and InstanceProfile
        instance_profile_name = None
        if build.instance_role:
            instance_role_type = self._get_instance_role_type()
            if instance_role_type == InstanceRole.ROLE:
                self._set_instance_profile(instance_role=build.instance_role)
            elif instance_role_type == InstanceRole.INSTANCE_PROFILE:
                instance_profile_name = build.instance_role
            else:
                self._set_instance_profile()
        else:
            self._set_default_instance_role()
            self._set_instance_profile()

        # InfrastructureConfiguration
        imagebuilder.CfnInfrastructureConfiguration(
            self,
            id="PClusterImageInfrastructureConfiguration",
            name="-".join(["PCluster-Image-Infrastructure-Configuration", resources_prefix]),
            instance_profile_name=core.Fn.ref(instance_profile_name or "InstanceProfile"),
            terminate_instance_on_failure=dev_settings.terminate_instance_on_failure,
            instance_types=[build.instance_type],
        )

        imagebuilder_cloudformation_dir = os.path.join(utils.get_cloudformation_directory(), "imagebuilder")
        # Components
        components = []
        if dev_settings and dev_settings.update_os_and_reboot:
            imagebuilder.CfnComponent(
                self,
                id="UpdateAndRebootComponent",
                name="-".join(["UpdateAndReboot", resources_prefix]),
                version="0.0.1",
                description="Update OS and Reboot",
                change_description="First version",
                platform="Linux",
                data=core.Fn.sub(load_yaml(imagebuilder_cloudformation_dir, "update_and_reboot.yaml")),
            )
            components.append(
                imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(
                    component_arn=core.Fn.ref("UpdateAndRebootComponent")
                )
            )

        imagebuilder.CfnComponent(
            self,
            id="PClusterComponent",
            name="-".join(["PCluster", resources_prefix]),
            version="0.0.1",
            description="Bake PCluster AMI",
            change_description="First version",
            platform="Linux",
            data=core.Fn.sub(load_yaml(imagebuilder_cloudformation_dir, "pcluster_install.yaml")),
        )

        components.append(
            imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(component_arn=core.Fn.ref("PClusterComponent"))
        )
        if build.components:
            self._set_custom_components(components)

        # ImageRecipe
        imagebuilder.CfnImageRecipe(
            self,
            id="PClusterImageRecipe",
            name="-".join(["PCluster", utils.get_installed_version().replace(".", "-"), resources_prefix]),
            version="0.0.1",
            parent_image=core.Fn.sub(build.parent_image),
            components=components,
            block_device_mappings=[
                imagebuilder.CfnImageRecipe.InstanceBlockDeviceMappingProperty(
                    device_name="/dev/xvda",
                    ebs=self._set_ebs_volume(),
                )
            ],
        )

        # Image
        imagebuilder.CfnImage(
            self,
            id="PClusterImage",
            image_recipe_arn=core.Fn.ref("PClusterImageRecipe"),
            infrastructure_configuration_arn=core.Fn.ref("PClusterImageInfrastructureConfiguration"),
        )

    def _get_instance_role_type(self):
        """Get instance role type based on instance_role in config."""
        instance_role = self.imagebuild.build.instance_role
        identifier = instance_role.split("/", 1)[0]
        if identifier.endswith("role"):
            return InstanceRole.ROLE
        if identifier.endswith("instance-profile"):
            return InstanceRole.INSTANCE_PROFILE
        return InstanceRole.DEFAULT

    def _set_default_instance_role(self):
        """Set default instance role in imagebuilder cfn template."""
        managed_policy_arns = [
            core.Fn.sub("arn:${AWS::Partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"),
            core.Fn.sub("arn:${AWS::Partition}:iam::aws:policy/EC2InstanceProfileForImageBuilder"),
        ]

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
        )

        instancerole.add_metadata("Comment", "Role to be used by instance during image build.")

    def _set_instance_profile(self, instance_role="InstanceRole"):
        """Set default instance profile in imagebuilder cfn template."""
        iam.CfnInstanceProfile(
            self, id="InstanceProfile", path="/executionServiceEC2Role/", roles=[core.Fn.ref(instance_role)]
        )

    def _set_custom_components(self, components):
        """Set custom component in imagebuilder cfn template."""
        build = self.imagebuild.build
        custom_components = build.components
        initial_component_len = len(custom_components)
        arn_components_len = 0
        for custom_component in custom_components:
            if custom_component.type.startswith("arn"):
                components.append(
                    imagebuilder.CfnImageRecipe.ComponentConfigurationProperty(component_arn=custom_component)
                )
                arn_components_len += 1
            elif custom_component.type.startswith("yaml"):
                imagebuilder.CfnComponent(
                    self,
                    id="CustomComponent" + str(len(components) - initial_component_len - arn_components_len),
                    name="-".join(
                        ["CustomComponent", str(len(components) - initial_component_len - arn_components_len)]
                    ),
                    version="0.0.1",
                    description="CustomComponent",
                    change_description="First version",
                    platform="Linux",
                    uri=custom_component,
                )
            else:
                imagebuilder.CfnComponent(
                    self,
                    id="CustomComponent" + str(len(components) - initial_component_len - arn_components_len),
                    name="-".join(
                        ["CustomComponent", str(len(components) - initial_component_len - arn_components_len)]
                    ),
                    version="0.0.1",
                    description="CustomComponent",
                    change_description="First version",
                    platform="Linux",
                    data=self._wrap_bash_to_component(),
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
