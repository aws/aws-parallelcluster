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

import os

import pytest
import yaml
from assertpy import assert_that
from aws_cdk import core

from common.utils import load_yaml_dict
from pcluster.models.cluster import (
    HeadNode,
    HeadNodeNetworking,
    Image,
    QueueNetworking,
    SlurmCluster,
    SlurmComputeResource,
    SlurmQueue,
    SlurmScheduling,
    Ssh,
)
from pcluster.models.imagebuilder import Build, DevSettings
from pcluster.models.imagebuilder import Image as ImageBuilderImage
from pcluster.models.imagebuilder import ImageBuilder, Volume
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.templates.cluster_stack import HeadNodeConstruct


def dummy_head_node():
    """Generate dummy head node."""
    image = Image(os="fakeos")
    head_node_networking = HeadNodeNetworking(subnet_id="test")
    ssh = Ssh(key_name="test")
    return HeadNode(instance_type="fake", networking=head_node_networking, ssh=ssh, image=image)


def dummy_cluster():
    """Generate dummy cluster."""
    image = Image(os="fakeos")
    head_node = dummy_head_node()
    compute_resources = [SlurmComputeResource(instance_type="test")]
    queue_networking = QueueNetworking(subnet_ids=["test"])
    queues = [SlurmQueue(name="test", networking=queue_networking, compute_resources=compute_resources)]
    scheduling = SlurmScheduling(queues=queues)
    return SlurmCluster(image=image, head_node=head_node, scheduling=scheduling)


def dummy_imagebuilder(is_official_ami_build):
    """Generate dummy imagebuilder configuration."""
    image = ImageBuilderImage(name="Pcluster", root_volume=Volume())
    if is_official_ami_build:
        build = Build(
            instance_type="c5.xlarge",
            parent_image="arn:${AWS::Partition}:imagebuilder:${AWS::Region}:aws:image/amazon-linux-2-x86/x.x.x",
        )
        dev_settings = DevSettings(update_os_and_reboot=True)
    else:
        build = Build(instance_type="g4dn.xlarge", parent_image="ami-0185634c5a8a37250")
        dev_settings = DevSettings()
    return ImageBuilder(image=image, build=build, dev_settings=dev_settings)


def test_cluster_builder():
    generated_template = CDKTemplateBuilder().build(cluster=dummy_cluster())
    print(yaml.dump(generated_template))
    # TODO assert content of the template by matching expected template


def test_head_node_construct(tmpdir):
    # TODO verify if it's really useful

    class DummyStack(core.Stack):
        """Simple Stack to test a specific construct."""

        def __init__(self, scope: core.Construct, construct_id: str, head_node: HeadNode, **kwargs) -> None:
            super().__init__(scope, construct_id, **kwargs)

            HeadNodeConstruct(self, "HeadNode", head_node)

    output_file = "cluster"
    app = core.App(outdir=str(tmpdir))
    DummyStack(app, output_file, head_node=dummy_head_node())
    app.synth()
    generated_template = load_yaml_dict(os.path.join(tmpdir, f"{output_file}.template.json"))

    print(yaml.dump(generated_template))
    # TODO assert content of the template by matching expected template


@pytest.mark.parametrize(
    "is_official_ami_build, response, expected_template",
    [
        (
            True,
            [
                {
                    "Architecture": "x86_64",
                    "BlockDeviceMappings": [
                        {
                            "DeviceName": "/dev/xvda",
                            "Ebs": {
                                "DeleteOnTermination": True,
                                "SnapshotId": "snap-0a20b6671bc5e3ead",
                                "VolumeSize": 25,
                                "VolumeType": "gp2",
                                "Encrypted": False,
                            },
                        }
                    ],
                }
            ],
            {
                "Parameters": {
                    "EnableNvidia": {"Type": "String", "Default": "false", "Description": "EnableNvidia"},
                    "EnableDCV": {"Type": "String", "Default": "false", "Description": "EnableDCV"},
                    "CustomNodePackage": {"Type": "String", "Default": "", "Description": "CustomNodePackage"},
                },
                "Resources": {
                    "InstanceRole": {
                        "Type": "AWS::IAM::Role",
                        "Properties": {
                            "AssumeRolePolicyDocument": {
                                "Statement": {
                                    "Action": "sts:AssumeRole",
                                    "Effect": "Allow",
                                    "Principal": {"Service": "ec2.amazonaws.com"},
                                },
                                "Version": "2012-10-17",
                            },
                            "ManagedPolicyArns": [
                                {"Fn::Sub": "arn:${AWS::Partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"},
                                {"Fn::Sub": "arn:${AWS::Partition}:iam::aws:policy/EC2InstanceProfileForImageBuilder"},
                            ],
                            "Path": "/executionServiceEC2Role/",
                        },
                        "Metadata": {"Comment": "Role to be used by instance during image build."},
                    },
                    "InstanceProfile": {
                        "Type": "AWS::IAM::InstanceProfile",
                        "Properties": {"Roles": [{"Ref": "InstanceRole"}], "Path": "/executionServiceEC2Role/"},
                    },
                    "PClusterImageInfrastructureConfiguration": {
                        "Type": "AWS::ImageBuilder::InfrastructureConfiguration",
                        "Properties": {
                            "InstanceProfileName": {"Ref": "InstanceProfile"},
                            "Name": "PCluster-Image-Infrastructure-Configuration-qd6lpbzo8gd2j4dr",
                            "InstanceTypes": ["c5.xlarge"],
                            "TerminateInstanceOnFailure": False,
                        },
                    },
                    "UpdateAndRebootComponent": {
                        "Type": "AWS::ImageBuilder::Component",
                        "Properties": {
                            "Name": "UpdateAndReboot-qd6lpbzo8gd2j4dr",
                            "Platform": "Linux",
                            "Version": "0.0.1",
                            "ChangeDescription": "First version",
                            "Data": {"Fn::Sub": "content"},
                            "Description": "Update OS and Reboot",
                        },
                    },
                    "PClusterComponent": {
                        "Type": "AWS::ImageBuilder::Component",
                        "Properties": {
                            "Name": "PCluster-qd6lpbzo8gd2j4dr",
                            "Platform": "Linux",
                            "Version": "0.0.1",
                            "ChangeDescription": "First version",
                            "Data": {"Fn::Sub": "content"},
                            "Description": "Bake PCluster AMI",
                        },
                    },
                    "PClusterImageRecipe": {
                        "Type": "AWS::ImageBuilder::ImageRecipe",
                        "Properties": {
                            "Components": [
                                {"ComponentArn": {"Ref": "UpdateAndRebootComponent"}},
                                {"ComponentArn": {"Ref": "PClusterComponent"}},
                            ],
                            "Name": "PCluster-2-10-1-qd6lpbzo8gd2j4dr",
                            "ParentImage": {
                                "Fn::Sub": "arn:${AWS::Partition}:imagebuilder:"
                                "${AWS::Region}:aws:image/amazon-linux-2-x86/x.x.x"
                            },
                            "Version": "0.0.1",
                            "BlockDeviceMappings": [
                                {"DeviceName": "/dev/xvda", "Ebs": {"VolumeSize": 40, "VolumeType": "gp2"}}
                            ],
                        },
                    },
                    "PClusterImage": {
                        "Type": "AWS::ImageBuilder::Image",
                        "Properties": {
                            "ImageRecipeArn": {"Ref": "PClusterImageRecipe"},
                            "InfrastructureConfigurationArn": {"Ref": "PClusterImageInfrastructureConfiguration"},
                        },
                    },
                    "PClusterParameter": {
                        "Type": "AWS::SSM::Parameter",
                        "Properties": {
                            "Type": "String",
                            "Value": {"Fn::GetAtt": ["PClusterImage", "ImageId"]},
                            "Description": "Image Id for PCluster",
                            "Name": "/Test/Images/PCluster-qd6lpbzo8gd2j4dr",
                        },
                    },
                },
            },
        ),
        (
            False,
            [
                {
                    "Architecture": "x86_64",
                    "BlockDeviceMappings": [
                        {
                            "DeviceName": "/dev/xvda",
                            "Ebs": {
                                "DeleteOnTermination": True,
                                "SnapshotId": "snap-0a20b6671bc5e3ead",
                                "VolumeSize": 50,
                                "VolumeType": "gp2",
                                "Encrypted": False,
                            },
                        }
                    ],
                }
            ],
            {
                "Parameters": {
                    "EnableNvidia": {"Type": "String", "Default": "false", "Description": "EnableNvidia"},
                    "EnableDCV": {"Type": "String", "Default": "false", "Description": "EnableDCV"},
                    "CustomNodePackage": {
                        "Type": "String",
                        "Default": "",
                        "Description": "CustomNodePackage",
                    },
                },
                "Resources": {
                    "InstanceRole": {
                        "Type": "AWS::IAM::Role",
                        "Properties": {
                            "AssumeRolePolicyDocument": {
                                "Statement": {
                                    "Action": "sts:AssumeRole",
                                    "Effect": "Allow",
                                    "Principal": {"Service": "ec2.amazonaws.com"},
                                },
                                "Version": "2012-10-17",
                            },
                            "ManagedPolicyArns": [
                                {"Fn::Sub": "arn:${AWS::Partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"},
                                {"Fn::Sub": "arn:${AWS::Partition}:iam::aws:policy/EC2InstanceProfileForImageBuilder"},
                            ],
                            "Path": "/executionServiceEC2Role/",
                        },
                        "Metadata": {"Comment": "Role to be used by instance during image build."},
                    },
                    "InstanceProfile": {
                        "Type": "AWS::IAM::InstanceProfile",
                        "Properties": {"Roles": [{"Ref": "InstanceRole"}], "Path": "/executionServiceEC2Role/"},
                    },
                    "PClusterImageInfrastructureConfiguration": {
                        "Type": "AWS::ImageBuilder::InfrastructureConfiguration",
                        "Properties": {
                            "InstanceProfileName": {"Ref": "InstanceProfile"},
                            "Name": "PCluster-Image-Infrastructure-Configuration-gw85hm3tw3qka4fd",
                            "InstanceTypes": ["g4dn.xlarge"],
                            "TerminateInstanceOnFailure": True,
                        },
                    },
                    "PClusterComponent": {
                        "Type": "AWS::ImageBuilder::Component",
                        "Properties": {
                            "Name": "PCluster-gw85hm3tw3qka4fd",
                            "Platform": "Linux",
                            "Version": "0.0.1",
                            "ChangeDescription": "First version",
                            "Data": {"Fn::Sub": "install pcluster"},
                            "Description": "Bake PCluster AMI",
                        },
                    },
                    "PClusterImageRecipe": {
                        "Type": "AWS::ImageBuilder::ImageRecipe",
                        "Properties": {
                            "Components": [{"ComponentArn": {"Ref": "PClusterComponent"}}],
                            "Name": "PCluster-2-10-1-gw85hm3tw3qka4fd",
                            "ParentImage": {"Fn::Sub": "ami-0185634c5a8a37250"},
                            "Version": "0.0.1",
                            "BlockDeviceMappings": [
                                {"DeviceName": "/dev/xvda", "Ebs": {"VolumeSize": 65, "VolumeType": "gp2"}}
                            ],
                        },
                    },
                    "PClusterImage": {
                        "Type": "AWS::ImageBuilder::Image",
                        "Properties": {
                            "ImageRecipeArn": {"Ref": "PClusterImageRecipe"},
                            "InfrastructureConfigurationArn": {"Ref": "PClusterImageInfrastructureConfiguration"},
                        },
                    },
                    "PClusterParameter": {
                        "Type": "AWS::SSM::Parameter",
                        "Properties": {
                            "Type": "String",
                            "Value": {"Fn::GetAtt": ["PClusterImage", "ImageId"]},
                            "Description": "Image Id for PCluster",
                            "Name": "/Test/Images/PCluster-gw85hm3tw3qka4fd",
                        },
                    },
                },
            },
        ),
    ],
)
def test_imagebuilder(mocker, is_official_ami_build, response, expected_template):
    mocker.patch("pcluster.utils.get_info_for_amis", return_value=response)
    # Tox can't find upper directory based on file_path in pcluster dir, mock it with file_path in test dir
    mocker.patch(
        "pcluster.utils.get_cloudformation_directory",
        return_value=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "cloudformation"),
    )
    dummy_imagebuild = dummy_imagebuilder(is_official_ami_build)
    generated_template = CDKTemplateBuilder().build_ami(dummy_imagebuild)
    # TODO assert content of the template by matching expected template
    _test_parameters(generated_template.get("Parameters"), expected_template.get("Parameters"))
    _test_resources(generated_template.get("Resources"), expected_template.get("Resources"))


def _test_parameters(generated_parameters, expected_parameters):
    for parameter in expected_parameters.keys():
        assert_that(parameter in generated_parameters).is_equal_to(True)


def _test_resources(generated_resouces, expected_resources):
    for resouce in expected_resources.keys():
        assert_that(resouce in generated_resouces).is_equal_to(True)
