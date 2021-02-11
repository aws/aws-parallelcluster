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

import os

from aws_cdk import aws_iam as iam
from aws_cdk import aws_imagebuilder as imagebuilder
from aws_cdk import aws_ssm as ssm
from aws_cdk import core

import pcluster.utils as utils
from common.utils import load_yaml
from pcluster.models.imagebuilder import ImageBuilder


class ImageBuilderStack(core.Stack):
    """Create the Stack for imagebuilder."""

    def __init__(self, scope: core.Construct, construct_id: str, imagebuild: ImageBuilder, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        image = imagebuild.image
        build = imagebuild.build
        dev_settings = imagebuild.dev_settings

        # TODO: use attributes from imagebuilder config instead of using these static variables.
        core.CfnParameter(self, "EnableNvidia", type="String", default="false", description="EnableNvidia")
        core.CfnParameter(self, "EnableDCV", type="String", default="false", description="EnableDCV")
        default_node_package = dev_settings.node_package if dev_settings and dev_settings.node_package else ""
        core.CfnParameter(
            self,
            "CustomNodePackage",
            type="String",
            default=default_node_package,
            description="CustomNodePackage",
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

        # InstanceRole
        managed_policy_arns = [
            core.Fn.sub("arn:${AWS::Partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"),
            core.Fn.sub("arn:${AWS::Partition}:iam::aws:policy/EC2InstanceProfileForImageBuilder"),
        ]
        if build.instance_role:
            managed_policy_arns.extend([build.instance_role])

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

        # InstanceProfile
        iam.CfnInstanceProfile(
            self, id="InstanceProfile", path="/executionServiceEC2Role/", roles=[core.Fn.ref("InstanceRole")]
        )

        # InfrastructureConfiguration
        imagebuilder.CfnInfrastructureConfiguration(
            self,
            id="PClusterImageInfrastructureConfiguration",
            name="-".join(["PCluster-Image-Infrastructure-Configuration", resources_prefix]),
            instance_profile_name=core.Fn.ref("InstanceProfile"),
            terminate_instance_on_failure=dev_settings.terminate_instance_on_failure,
            instance_types=[build.instance_type],
        )

        # Define ami build instance ebs
        ebs = imagebuilder.CfnImageRecipe.EbsInstanceBlockDeviceSpecificationProperty(
            volume_size=image.root_volume.size,
            volume_type="gp2",
            encrypted=image.root_volume.encrypted,
            kms_key_id=image.root_volume.kms_key_id,
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
                    ebs=ebs,
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

        # AWS Systems Manager
        ssm.CfnParameter(
            self,
            id="PClusterParameter",
            description="Image Id for PCluster",
            name="-".join(["/Test/Images/PCluster", resources_prefix]),
            type="String",
            value=core.Fn.get_att("PClusterImage", "ImageId").to_string(),
        )
