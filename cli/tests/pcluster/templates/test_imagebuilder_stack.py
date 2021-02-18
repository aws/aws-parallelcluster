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

import pytest
from assertpy import assert_that

from pcluster.templates.cdk_builder import CDKTemplateBuilder

from ..boto3.dummy_boto3 import DummyAWSApi
from ..models.imagebuilder_dummy_model import dummy_imagebuilder


@pytest.mark.parametrize(
    "is_official_ami_build, response, expected_template",
    [
        (
            True,
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
            },
            {
                "Metadata": {
                    "Config": "Build:\n  InstanceType: c5.xlarge\n  "
                    "ParentImage: arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x\n\
                    DevSettings:\n  UpdateOsAndReboot: true\nImage:\n  Name: Pcluster\n"
                },
                "Parameters": {
                    "CfnParamChefDnaJson": {
                        "Type": "String",
                        "Default": '{"cfncluster": {"cfn_region": '
                        '"{{ build.AWSRegion.outputs.stdout }}","nvidia": {"enabled": "false"}, '
                        '"is_official_ami_build": "true", "custom_node_package":"", "cfn_base_os": '
                        '"{{ build.OperatingSystemName.outputs.stdout }}"}}',
                        "Description": "ChefAttributes",
                    },
                    "CfnParamChefCookbook": {"Type": "String", "Default": "", "Description": "ChefCookbook"},
                    "CfnParamCincInstaller": {"Type": "String", "Default": "", "Description": "CincInstaller"},
                    "CfnParamCookbookVersion": {
                        "Type": "String",
                        "Default": "2.10.1",
                        "Description": "CookbookVersion",
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
                                "Fn::Sub": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x"
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
                },
            },
        ),
        (
            False,
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
            },
            {
                "Metadata": {
                    "Config": "Build:\n  InstanceType: g4dn.xlarge\n  ParentImage: ami-0185634c5a8a37250\n\
    DevSettings: {}\nImage:\n  Name: Pcluster\n"
                },
                "Parameters": {
                    "CfnParamChefDnaJson": {
                        "Type": "String",
                        "Default": '{"cfncluster": {"cfn_region": "{{ build.AWSRegion.outputs.stdout }}",'
                        '"nvidia": {"enabled": "false"}, "is_official_ami_build": "true", '
                        '"custom_node_package":"", "cfn_base_os": "{{ build.OperatingSystemName.outputs.stdout }}"}}',
                        "Description": "ChefAttributes",
                    },
                    "CfnParamChefCookbook": {"Type": "String", "Default": "", "Description": "ChefCookbook"},
                    "CfnParamCincInstaller": {"Type": "String", "Default": "", "Description": "CincInstaller"},
                    "CfnParamCookbookVersion": {
                        "Type": "String",
                        "Default": "2.10.1",
                        "Description": "CookbookVersion",
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
                },
            },
        ),
    ],
)
def test_imagebuilder(mocker, is_official_ami_build, response, expected_template):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    dummy_imagebuild = dummy_imagebuilder(is_official_ami_build)
    generated_template = CDKTemplateBuilder().build_ami(dummy_imagebuild)
    # TODO assert content of the template by matching expected template, re-enable it after refactoring
    _test_parameters(generated_template.get("Parameters"), expected_template.get("Parameters"))
    _test_resources(generated_template.get("Resources"), expected_template.get("Resources"))


def _test_parameters(generated_parameters, expected_parameters):
    for parameter in expected_parameters.keys():
        assert_that(parameter in generated_parameters).is_equal_to(True)


def _test_resources(generated_resouces, expected_resources):
    for resouce in expected_resources.keys():
        assert_that(resouce in generated_resouces).is_equal_to(True)
