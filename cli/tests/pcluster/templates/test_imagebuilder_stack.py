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

import pcluster.utils as utils
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from tests.common.dummy_aws_api import DummyAWSApi

from ..models.imagebuilder_dummy_model import imagebuilder_factory


@pytest.mark.parametrize(
    "resource, response, expected_template",
    [
        (
            {
                "imagebuilder": {
                    "image": {"name": "Pcluster"},
                    "build": {
                        "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                        "instance_type": "c5.xlarge",
                    },
                    "dev_settings": {"update_os_and_reboot": True},
                }
            },
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
                        "Default": "3.0",
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
                    "ParallelClusterInfrastructureConfiguration": {
                        "Type": "AWS::ImageBuilder::InfrastructureConfiguration",
                        "Properties": {
                            "InstanceProfileName": {"Ref": "InstanceProfile"},
                            "Name": "ParallelClusterInfrastructureConfiguration-qd6lpbzo8gd2j4dr",
                            "InstanceTypes": ["c5.xlarge"],
                            "TerminateInstanceOnFailure": False,
                        },
                    },
                    "UpdateAndRebootComponent": {
                        "Type": "AWS::ImageBuilder::Component",
                        "Properties": {
                            "Name": "UpdateAndRebootComponent-qd6lpbzo8gd2j4dr",
                            "Platform": "Linux",
                            "Version": "3.0",
                            "Data": {"Fn::Sub": "content"},
                            "Description": "Update OS and Reboot",
                        },
                    },
                    "ParallelClusterComponent": {
                        "Type": "AWS::ImageBuilder::Component",
                        "Properties": {
                            "Name": "ParallelClusterComponent-qd6lpbzo8gd2j4dr",
                            "Platform": "Linux",
                            "Version": "3.0",
                            "Data": {"Fn::Sub": "content"},
                            "Description": "Bake ParallelCluster AMI",
                        },
                    },
                    "ParallelClusterImageRecipe": {
                        "Type": "AWS::ImageBuilder::ImageRecipe",
                        "Properties": {
                            "Components": [
                                {"ComponentArn": {"Ref": "UpdateAndRebootComponent"}},
                                {"ComponentArn": {"Ref": "ParallelClusterComponent"}},
                            ],
                            "Name": "ParallelClusterImageRecipe-qd6lpbzo8gd2j4dr",
                            "ParentImage": {
                                "Fn::Sub": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x"
                            },
                            "Version": "3.0",
                            "BlockDeviceMappings": [
                                {"DeviceName": "/dev/xvda", "Ebs": {"VolumeSize": 40, "VolumeType": "gp2"}}
                            ],
                        },
                    },
                    "ParallelClusterImage": {
                        "Type": "AWS::ImageBuilder::Image",
                        "Properties": {
                            "ImageRecipeArn": {"Ref": "ParallelClusterImageRecipe"},
                            "InfrastructureConfigurationArn": {"Ref": "ParallelClusterInfrastructureConfiguration"},
                            "DistributionConfigurationArn": {"Ref": "ParallelClusterDistributionConfiguration"},
                        },
                    },
                },
            },
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "Parallelcluster"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                    },
                }
            },
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
                    "ParallelClusterInfrastructureConfiguration": {
                        "Type": "AWS::ImageBuilder::InfrastructureConfiguration",
                        "Properties": {
                            "InstanceProfileName": {"Ref": "InstanceProfile"},
                            "Name": "ParallelClusterInfrastructureConfiguration-gw85hm3tw3qka4fd",
                            "InstanceTypes": ["g4dn.xlarge"],
                            "TerminateInstanceOnFailure": True,
                        },
                    },
                    "ParallelClusterComponent": {
                        "Type": "AWS::ImageBuilder::Component",
                        "Properties": {
                            "Name": "ParallelClusterComponent-gw85hm3tw3qka4fd",
                            "Platform": "Linux",
                            "Version": "0.0.1",
                            "ChangeDescription": "First version",
                            "Data": {"Fn::Sub": "install pcluster"},
                            "Description": "Bake ParallelCluster AMI",
                        },
                    },
                    "ParallelClusterImageRecipe": {
                        "Type": "AWS::ImageBuilder::ImageRecipe",
                        "Properties": {
                            "Components": [{"ComponentArn": {"Ref": "ParallelClusterComponent"}}],
                            "Name": "ParallelClusterImageRecipe-gw85hm3tw3qka4fd",
                            "ParentImage": {"Fn::Sub": "ami-0185634c5a8a37250"},
                            "Version": "3.0",
                            "BlockDeviceMappings": [
                                {"DeviceName": "/dev/xvda", "Ebs": {"VolumeSize": 65, "VolumeType": "gp2"}}
                            ],
                        },
                    },
                    "ParallelClusterImage": {
                        "Type": "AWS::ImageBuilder::Image",
                        "Properties": {
                            "ImageRecipeArn": {"Ref": "ParallelClusterImageRecipe"},
                            "InfrastructureConfigurationArn": {"Ref": "ParallelClusterInfrastructureConfiguration"},
                            "DistributionConfigurationArn": {"Ref": "ParallelClusterDistributionConfiguration"},
                        },
                    },
                },
            },
        ),
    ],
)
def test_imagebuilder(mocker, resource, response, expected_template):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    dummy_imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(dummy_imagebuild, "test")
    # TODO assert content of the template by matching expected template, re-enable it after refactoring
    _test_parameters(generated_template.get("Parameters"), expected_template.get("Parameters"))
    _test_resources(generated_template.get("Resources"), expected_template.get("Resources"))


def _test_parameters(generated_parameters, expected_parameters):
    for parameter in expected_parameters.keys():
        assert_that(parameter in generated_parameters).is_equal_to(True)


def _test_resources(generated_resouces, expected_resources):
    for resouce in expected_resources.keys():
        assert_that(resouce in generated_resouces).is_equal_to(True)


@pytest.mark.parametrize(
    "resource, response, expected_instance_role, expected_instance_profile, expected_instance_profile_in_configuration",
    [
        (
            {
                "imagebuilder": {
                    "image": {"name": "Pcluster"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                    },
                }
            },
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
                    "Policies": [
                        {
                            "PolicyDocument": {
                                "Version": "2012-10-17",
                                "Statement": [
                                    {
                                        "Effect": "Allow",
                                        "Action": ["ec2:CreateTags", "ec2:ModifyImageAttribute"],
                                        "Resource": [{"Fn::Sub": "arn:${AWS::Partition}:ec2:*::image/*"}],
                                    }
                                ],
                            },
                            "PolicyName": "InstanceRoleInlinePolicy",
                        }
                    ],
                },
                "Metadata": {"Comment": "Role to be used by instance during image build."},
            },
            {
                "Type": "AWS::IAM::InstanceProfile",
                "Properties": {"Roles": [{"Ref": "InstanceRole"}], "Path": "/executionServiceEC2Role/"},
            },
            {"Ref": "InstanceProfile"},
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "Pcluster"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "instance_role": "arn:aws:iam::xxxxxxxxxxxx:role/test-InstanceRole",
                    },
                }
            },
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
            None,
            {
                "Type": "AWS::IAM::InstanceProfile",
                "Properties": {
                    "Roles": [{"Ref": "arn:aws:iam::xxxxxxxxxxxx:role/test-InstanceRole"}],
                    "Path": "/executionServiceEC2Role/",
                },
            },
            {"Ref": "InstanceProfile"},
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "Pcluster"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "instance_role": "arn:aws:iam::xxxxxxxxxxxx:instance-profile/InstanceProfile",
                    },
                }
            },
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
            None,
            None,
            {"Ref": "arn:aws:iam::xxxxxxxxxxxx:instance-profile/InstanceProfile"},
        ),
    ],
)
def test_imagebuilder_instance_role(
    mocker,
    resource,
    response,
    expected_instance_role,
    expected_instance_profile,
    expected_instance_profile_in_configuration,
):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(imagebuild, "test")
    assert_that(generated_template.get("Resources").get("InstanceRole")).is_equal_to(expected_instance_role)
    assert_that(generated_template.get("Resources").get("InstanceProfile")).is_equal_to(expected_instance_profile)
    assert_that(
        generated_template.get("Resources")
        .get("ParallelClusterInfrastructureConfiguration")
        .get("Properties")
        .get("InstanceProfileName")
    ).is_equal_to(expected_instance_profile_in_configuration)


@pytest.mark.parametrize(
    "resource, response, expected_components",
    [
        (
            {
                "imagebuilder": {
                    "image": {"name": "Pcluster"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "components": [
                            {
                                "type": "arn",
                                "value": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0",
                            },
                            {
                                "type": "arn",
                                "value": "arn:aws:imagebuilder:us-east-1:"
                                "aws:component/amazon-cloudwatch-agent-linux/1.0.0",
                            },
                        ],
                    },
                }
            },
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
            [
                {"ComponentArn": {"Ref": "ParallelClusterComponent"}},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0"},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/amazon-cloudwatch-agent-linux/1.0.0"},
                {"ComponentArn": {"Ref": "ParallelClusterTagComponent"}},
            ],
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "Pcluster"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "components": [
                            {
                                "type": "arn",
                                "value": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0",
                            },
                            {
                                "type": "arn",
                                "value": "arn:aws:imagebuilder:us-east-1:"
                                "aws:component/amazon-cloudwatch-agent-linux/1.0.0",
                            },
                        ],
                    },
                    "dev_settings": {"update_os_and_reboot": True},
                }
            },
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
            [
                {"ComponentArn": {"Ref": "UpdateAndRebootComponent"}},
                {"ComponentArn": {"Ref": "ParallelClusterComponent"}},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0"},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/amazon-cloudwatch-agent-linux/1.0.0"},
                {"ComponentArn": {"Ref": "ParallelClusterTagComponent"}},
            ],
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "Pcluster"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "components": [
                            {
                                "type": "arn",
                                "value": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0",
                            },
                            {"type": "script", "value": "s3://test-slurm/templates/run.sh"},
                            {
                                "type": "script",
                                "value": "https://test-slurm.s3.us-east-2.amazonaws.com/post_install_script.sh",
                            },
                        ],
                    },
                }
            },
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
            [
                {"ComponentArn": {"Ref": "ParallelClusterComponent"}},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0"},
                {"ComponentArn": {"Ref": "ParallelClusterScriptComponent0"}},
                {"ComponentArn": {"Ref": "ParallelClusterScriptComponent1"}},
                {"ComponentArn": {"Ref": "ParallelClusterTagComponent"}},
            ],
        ),
    ],
)
def test_imagebuilder_components(mocker, resource, response, expected_components):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(imagebuild, "test")
    assert_that(
        generated_template.get("Resources").get("ParallelClusterImageRecipe").get("Properties").get("Components")
    ).is_equal_to(expected_components)


@pytest.mark.parametrize(
    "resource, response, expected_ami_distribution_configuration",
    [
        (
            {
                "imagebuilder": {
                    "image": {
                        "name": "my AMI 1",
                        "tags": [
                            {
                                "key": "keyTag1",
                                "value": "valueTag1",
                            },
                            {
                                "key": "keyTag2",
                                "value": "valueTag2",
                            },
                        ],
                    },
                    "build": {
                        "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                        "instance_type": "c5.xlarge",
                    },
                }
            },
            {
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            [
                {
                    "AmiDistributionConfiguration": {
                        "Name": "Pcluster {{ imagebuilder:buildDate }}",
                        "AmiTags": {
                            "keyTag1": "valueTag1",
                            "keyTag2": "valueTag2",
                            "pcluster_version": utils.get_installed_version(),
                        },
                    },
                    "Region": {"Fn::Sub": "${AWS::Region}"},
                },
            ],
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "my AMI 2"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                    },
                }
            },
            {
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            [
                {
                    "AmiDistributionConfiguration": {
                        "Name": "Pcluster {{ imagebuilder:buildDate }}",
                        "AmiTags": {"pcluster_version": utils.get_installed_version()},
                    },
                    "Region": {"Fn::Sub": "${AWS::Region}"},
                },
            ],
        ),
        (
            {
                "imagebuilder": {
                    "image": {
                        "name": "my AMI 1",
                        "tags": [],
                    },
                    "build": {
                        "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                        "instance_type": "c5.xlarge",
                    },
                }
            },
            {
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            [
                {
                    "AmiDistributionConfiguration": {
                        "Name": "Pcluster {{ imagebuilder:buildDate }}",
                        "AmiTags": {"pcluster_version": utils.get_installed_version()},
                    },
                    "Region": {"Fn::Sub": "${AWS::Region}"},
                },
            ],
        ),
    ],
)
def test_imagebuilder_ami_tags(mocker, resource, response, expected_ami_distribution_configuration):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(imagebuild, "Pcluster")
    assert_that(
        generated_template.get("Resources")
        .get("ParallelClusterDistributionConfiguration")
        .get("Properties")
        .get("Distributions")
    ).is_equal_to(expected_ami_distribution_configuration)


@pytest.mark.parametrize(
    "resource, response, expected_imagebuilder_resource_tags, expected_role_tags",
    [
        (
            {
                "imagebuilder": {
                    "image": {
                        "name": "my AMI 1",
                    },
                    "build": {
                        "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                        "instance_type": "c5.xlarge",
                        "tags": [
                            {
                                "key": "keyTag1",
                                "value": "valueTag1",
                            },
                            {
                                "key": "keyTag2",
                                "value": "valueTag2",
                            },
                        ],
                    },
                }
            },
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
            {"keyTag1": "valueTag1", "keyTag2": "valueTag2", "pcluster_build_image": utils.get_installed_version()},
            [
                {
                    "Key": "keyTag1",
                    "Value": "valueTag1",
                },
                {
                    "Key": "keyTag2",
                    "Value": "valueTag2",
                },
            ],
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "my AMI 2"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                    },
                }
            },
            {
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            {"pcluster_build_image": utils.get_installed_version()},
            None,
        ),
        (
            {
                "imagebuilder": {
                    "image": {
                        "name": "my AMI 1",
                    },
                    "build": {
                        "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                        "instance_type": "c5.xlarge",
                        "tags": [],
                    },
                }
            },
            {
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            {"pcluster_build_image": utils.get_installed_version()},
            None,
        ),
    ],
)
def test_imagebuilder_build_tags(mocker, resource, response, expected_imagebuilder_resource_tags, expected_role_tags):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(imagebuild, "Pcluster")
    for resource_name, resource in generated_template.get("Resources").items():
        if resource_name == "InstanceProfile":
            # InstanceProfile has no tags
            continue
        elif resource_name == "InstanceRole":
            assert_that(resource.get("Properties").get("Tags")).is_equal_to(expected_role_tags)
        else:
            assert_that(resource.get("Properties").get("Tags")).is_equal_to(expected_imagebuilder_resource_tags)


@pytest.mark.parametrize(
    "resource, response, expected_imagebuilder_subnet_id",
    [
        (
            {
                "imagebuilder": {
                    "image": {
                        "name": "my AMI 1",
                    },
                    "build": {
                        "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                        "instance_type": "c5.xlarge",
                    },
                }
            },
            {
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            None,
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "my AMI 2"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "subnet_id": "subnet-0292c5356eadc531f",
                    },
                }
            },
            {
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            "subnet-0292c5356eadc531f",
        ),
    ],
)
def test_imagebuilder_subnet_id(mocker, resource, response, expected_imagebuilder_subnet_id):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(imagebuild, "Pcluster")

    assert_that(
        generated_template.get("Resources")
        .get("ParallelClusterInfrastructureConfiguration")
        .get("Properties")
        .get("SubnetId")
    ).is_equal_to(expected_imagebuilder_subnet_id)


@pytest.mark.parametrize(
    "resource, response, expected_imagebuilder_security_group_ids",
    [
        (
            {
                "imagebuilder": {
                    "image": {
                        "name": "my AMI 1",
                    },
                    "build": {
                        "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                        "instance_type": "c5.xlarge",
                    },
                }
            },
            {
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            None,
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "my AMI 2"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "security_group_ids": ["sg-b0bbeacc", "sg-0fc70b22048995b07"],
                    },
                }
            },
            {
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            ["sg-b0bbeacc", "sg-0fc70b22048995b07"],
        ),
    ],
)
def test_imagebuilder_security_group_ids(mocker, resource, response, expected_imagebuilder_security_group_ids):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(imagebuild, "Pcluster")

    assert_that(
        generated_template.get("Resources")
        .get("ParallelClusterInfrastructureConfiguration")
        .get("Properties")
        .get("SecurityGroupIds")
    ).is_equal_to(expected_imagebuilder_security_group_ids)


@pytest.mark.parametrize(
    "resource, response, expected_distributions",
    [
        (
            {
                "imagebuilder": {
                    "image": {"name": "Pcluster"},
                    "build": {
                        "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                        "instance_type": "c5.xlarge",
                    },
                    "dev_settings": {"update_os_and_reboot": True},
                }
            },
            {
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "VolumeSize": 25,
                        },
                    }
                ],
            },
            [
                {
                    "AmiDistributionConfiguration": {
                        "Name": "Pcluster {{ imagebuilder:buildDate }}",
                        "AmiTags": {"pcluster_version": "2.10.1"},
                    },
                    "Region": {"Fn::Sub": "${AWS::Region}"},
                },
            ],
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "Pcluster"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                    },
                    "dev_settings": {"distribution_configuration": {"regions": ""}},
                }
            },
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
            [
                {
                    "AmiDistributionConfiguration": {
                        "Name": "Pcluster {{ imagebuilder:buildDate }}",
                        "AmiTags": {"pcluster_version": "2.10.1"},
                    },
                    "Region": {"Fn::Sub": "${AWS::Region}"},
                },
            ],
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "Pcluster"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                    },
                    "dev_settings": {"distribution_configuration": {"regions": " eu-south-1,   eu-south-1"}},
                }
            },
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
            [
                {
                    "AmiDistributionConfiguration": {
                        "Name": "Pcluster {{ imagebuilder:buildDate }}",
                        "AmiTags": {"pcluster_version": "2.10.1"},
                    },
                    "Region": "eu-south-1",
                },
            ],
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "Pcluster"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                    },
                    "dev_settings": {"distribution_configuration": {"regions": "eu-south-1", "launch_permission": ""}},
                }
            },
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
            [
                {
                    "AmiDistributionConfiguration": {
                        "Name": "Pcluster {{ imagebuilder:buildDate }}",
                        "AmiTags": {"pcluster_version": "2.10.1"},
                        "LaunchPermissionConfiguration": "",
                    },
                    "Region": "eu-south-1",
                },
            ],
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "Pcluster"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                    },
                    "dev_settings": {
                        "distribution_configuration": {
                            "regions": "eu-south-1",
                            "launch_permission": {"UserIds": ["123456789012", "345678901234"]},
                        }
                    },
                }
            },
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
            [
                {
                    "AmiDistributionConfiguration": {
                        "Name": "Pcluster {{ imagebuilder:buildDate }}",
                        "AmiTags": {"pcluster_version": "2.10.1"},
                        "LaunchPermissionConfiguration": {"UserIds": ["123456789012", "345678901234"]},
                    },
                    "Region": "eu-south-1",
                },
            ],
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "Pcluster"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                    },
                    "dev_settings": {
                        "distribution_configuration": {
                            "regions": "eu-south-1",
                            "launch_permission": {"UserIds": []},
                        }
                    },
                }
            },
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
            [
                {
                    "AmiDistributionConfiguration": {
                        "Name": "Pcluster {{ imagebuilder:buildDate }}",
                        "AmiTags": {"pcluster_version": "2.10.1"},
                        "LaunchPermissionConfiguration": {"UserIds": []},
                    },
                    "Region": "eu-south-1",
                },
            ],
        ),
        (
            {
                "imagebuilder": {
                    "image": {"name": "Pcluster"},
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                    },
                    "dev_settings": {
                        "distribution_configuration": {
                            "regions": "eu-south-1,us-west-1",
                            "launch_permission": {"UserGroups": ["all"]},
                        }
                    },
                }
            },
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
            [
                {
                    "AmiDistributionConfiguration": {
                        "Name": "Pcluster {{ imagebuilder:buildDate }}",
                        "AmiTags": {"pcluster_version": "2.10.1"},
                        "LaunchPermissionConfiguration": {"UserGroups": ["all"]},
                    },
                    "Region": "eu-south-1",
                },
                {
                    "AmiDistributionConfiguration": {
                        "Name": "Pcluster {{ imagebuilder:buildDate }}",
                        "AmiTags": {"pcluster_version": "2.10.1"},
                        "LaunchPermissionConfiguration": {"UserGroups": ["all"]},
                    },
                    "Region": "us-west-1",
                },
            ],
        ),
    ],
)
def test_imagebuilder_distribution_configuraton(mocker, resource, response, expected_distributions):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    dummy_imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(dummy_imagebuild, "Pcluster")

    assert_that(
        generated_template.get("Resources")
        .get("ParallelClusterDistributionConfiguration")
        .get("Properties")
        .get("Distributions")
    ).contains(*expected_distributions)
