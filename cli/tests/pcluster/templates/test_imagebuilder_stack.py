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
from tests.common.dummy_aws_api import mock_aws_api

from ..models.cluster_dummy_model import mock_bucket
from ..models.imagebuilder_dummy_model import dummy_imagebuilder_bucket, imagebuilder_factory

# TODO missing tests for the following configuration parameters:
# UpdateOsAndReboot
# DisablePclusterComponent
# Cookbook
# NodePackage
# AWSBatchCliPackage


@pytest.mark.parametrize(
    "resource, response, expected_template",
    [
        (
            {
                "imagebuilder": {
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
            {
                "Parameters": {
                    "CfnParamChefDnaJson": {},
                    "CfnParamChefCookbook": {},
                    "CfnParamCincInstaller": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "UpdateOSComponent": {},
                    "ParallelClusterComponent": {},
                    "TagComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "BuildNotificationTopic": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                },
            },
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                        "instance_type": "c5.xlarge",
                        "iam": {"instance_role": "arn:aws:iam::111122223333:role/my_custom_role"},
                    },
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
            {
                "Parameters": {
                    "CfnParamChefDnaJson": {},
                    "CfnParamChefCookbook": {},
                    "CfnParamCincInstaller": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                },
                "Resources": {
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "ParallelClusterComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "TagComponent": {},
                    "BuildNotificationTopic": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                },
            },
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                        "instance_type": "c5.xlarge",
                        "iam": {
                            "instance_role": "arn:aws:iam::111122223333:instance-profile/my_custom_instance_profile"
                        },
                    },
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
            {
                "Parameters": {
                    "CfnParamChefDnaJson": {},
                    "CfnParamChefCookbook": {},
                    "CfnParamCincInstaller": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                },
                "Resources": {
                    "InfrastructureConfiguration": {},
                    "ParallelClusterComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "TagComponent": {},
                    "BuildNotificationTopic": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                },
            },
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                        "instance_type": "c5.xlarge",
                        "iam": {
                            "cleanup_lambda_role": "arn:aws:iam::111122223333:role/my_custom_lambda_execution_role"
                        },
                    },
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
            {
                "Parameters": {
                    "CfnParamChefDnaJson": {},
                    "CfnParamChefCookbook": {},
                    "CfnParamCincInstaller": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "ParallelClusterComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "TagComponent": {},
                    "BuildNotificationTopic": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                },
            },
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                    },
                    "dev_settings": {"disable_pcluster_component": True},
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
            {
                "Parameters": {
                    "CfnParamChefDnaJson": {},
                    "CfnParamChefCookbook": {},
                    "CfnParamCincInstaller": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "TagComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "BuildNotificationTopic": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                },
            },
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "components": [
                            {"type": "arn", "value": "arn:aws:imagebuilder:us-east-1:aws:component/managed_component/1"}
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
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            {
                "Parameters": {
                    "CfnParamChefDnaJson": {},
                    "CfnParamChefCookbook": {},
                    "CfnParamCincInstaller": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "TagComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "ParallelClusterComponent": {},
                    "BuildNotificationTopic": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                },
            },
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "components": [{"type": "script", "value": "s3://test/post_install.sh"}],
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
            {
                "Parameters": {
                    "CfnParamChefDnaJson": {},
                    "CfnParamChefCookbook": {},
                    "CfnParamCincInstaller": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "TagComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "ParallelClusterComponent": {},
                    "BuildNotificationTopic": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "ScriptComponent0": {},
                },
            },
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "components": [
                            {"type": "script", "value": "s3://test/post_install.sh"},
                            {
                                "type": "arn",
                                "value": "arn:aws:imagebuilder:us-east-1:aws:component/managed_component/1",
                            },
                            {"type": "script", "value": "s3://test/post_install_2.sh"},
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
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            {
                "Parameters": {
                    "CfnParamChefDnaJson": {},
                    "CfnParamChefCookbook": {},
                    "CfnParamCincInstaller": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "TagComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "ParallelClusterComponent": {},
                    "BuildNotificationTopic": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "ScriptComponent0": {},
                    "ScriptComponent1": {},
                },
            },
        ),
        (
            {
                "imagebuilder": {
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
            {
                "Parameters": {
                    "CfnParamChefDnaJson": {},
                    "CfnParamChefCookbook": {},
                    "CfnParamCincInstaller": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "ParallelClusterComponent": {},
                    "TagComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "BuildNotificationTopic": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                },
            },
        ),
    ],
)
def test_imagebuilder_parameters_and_resources(mocker, resource, response, expected_template):
    mock_aws_api(mocker)
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    dummy_imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(
        dummy_imagebuild, "Pcluster", dummy_imagebuilder_bucket()
    )
    # TODO assert content of the template by matching expected template, re-enable it after refactoring
    _test_parameters(generated_template.get("Parameters"), expected_template.get("Parameters"))
    _test_resources(generated_template.get("Resources"), expected_template.get("Resources"))


def _test_parameters(generated_parameters, expected_parameters):
    for parameter in generated_parameters.keys():
        assert_that(parameter in expected_parameters).is_equal_to(True)


def _test_resources(generated_resources, expected_resources):
    for resource in generated_resources.keys():
        assert_that(resource in expected_resources).is_equal_to(True)


@pytest.mark.parametrize(
    "resource, response, expected_instance_role, expected_instance_profile,"
    "expected_instance_profile_in_infrastructure_configuration",
    [
        (
            {
                "imagebuilder": {
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
            {
                "Type": "AWS::IAM::Role",
                "Properties": {
                    "AssumeRolePolicyDocument": {
                        "Statement": [
                            {
                                "Action": "sts:AssumeRole",
                                "Effect": "Allow",
                                "Principal": {"Service": {"Fn::Join": ["", ["ec2.", {"Ref": "AWS::URLSuffix"}]]}},
                            }
                        ],
                        "Version": "2012-10-17",
                    },
                    "ManagedPolicyArns": [
                        {"Fn::Sub": "arn:${AWS::Partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"},
                        {"Fn::Sub": "arn:${AWS::Partition}:iam::aws:policy/EC2InstanceProfileForImageBuilder"},
                    ],
                    "Path": "/ParallelClusterImage/",
                    "Policies": [
                        {
                            "PolicyDocument": {
                                "Version": "2012-10-17",
                                "Statement": [
                                    {
                                        "Effect": "Allow",
                                        "Action": ["ec2:CreateTags", "ec2:ModifyImageAttribute"],
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":ec2:",
                                                    {"Ref": "AWS::Region"},
                                                    "::image/*",
                                                ],
                                            ]
                                        },
                                    }
                                ],
                            },
                            "PolicyName": "InstanceRoleInlinePolicy",
                        }
                    ],
                    "Tags": [
                        {
                            "Key": "pcluster_build_image",
                            "Value": utils.get_installed_version(),
                        }
                    ],
                },
            },
            {
                "Type": "AWS::IAM::InstanceProfile",
                "Properties": {"Roles": [{"Ref": "InstanceRole"}], "Path": "/ParallelClusterImage/"},
            },
            {"Ref": "InstanceProfile"},
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "iam": {
                            "instance_role": "arn:aws:iam::xxxxxxxxxxxx:role/test-InstanceRole",
                        },
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
            {
                "Type": "AWS::IAM::InstanceProfile",
                "Properties": {
                    "Roles": ["arn:aws:iam::xxxxxxxxxxxx:role/test-InstanceRole"],
                    "Path": "/ParallelClusterImage/",
                },
            },
            {"Ref": "InstanceProfile"},
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "iam": {
                            "instance_role": "arn:aws:iam::xxxxxxxxxxxx:instance-profile/InstanceProfile",
                        },
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
            None,
            "arn:aws:iam::xxxxxxxxxxxx:instance-profile/InstanceProfile",
        ),
    ],
)
def test_imagebuilder_instance_role(
    mocker,
    resource,
    response,
    expected_instance_role,
    expected_instance_profile,
    expected_instance_profile_in_infrastructure_configuration,
):
    mock_aws_api(mocker)
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(imagebuild, "Pcluster", dummy_imagebuilder_bucket())
    assert_that(generated_template.get("Resources").get("InstanceRole")).is_equal_to(expected_instance_role)
    assert_that(generated_template.get("Resources").get("InstanceProfile")).is_equal_to(expected_instance_profile)
    assert_that(
        generated_template.get("Resources")
        .get("InfrastructureConfiguration")
        .get("Properties")
        .get("InstanceProfileName")
    ).is_equal_to(expected_instance_profile_in_infrastructure_configuration)


@pytest.mark.parametrize(
    "resource, response, expected_execution_role, expected_execution_role_in_lambda_function",
    [
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "components": [
                            {"type": "script", "value": "s3://test/post_install.sh"},
                            {"type": "script", "value": "s3://test/post_install2.sh"},
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
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            {
                "Type": "AWS::IAM::Role",
                "Properties": {
                    "AssumeRolePolicyDocument": {
                        "Statement": [
                            {
                                "Action": "sts:AssumeRole",
                                "Effect": "Allow",
                                "Principal": {"Service": {"Fn::Join": ["", ["lambda.", {"Ref": "AWS::URLSuffix"}]]}},
                            }
                        ],
                        "Version": "2012-10-17",
                    },
                    "ManagedPolicyArns": [
                        {"Fn::Sub": "arn:${AWS::Partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"},
                    ],
                    "Path": "/ParallelClusterImage/",
                    "Policies": [
                        {
                            "PolicyDocument": {
                                "Statement": [
                                    {
                                        "Action": "iam:DeleteRole",
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":iam::",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":role/ParallelClusterImage/My-Image-InstanceRole-*",
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": "iam:DeleteInstanceProfile",
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":iam::",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":instance-profile/ParallelClusterImage/My-Image-InstanceProfile-*",
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": "imagebuilder:DeleteInfrastructureConfiguration",
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":imagebuilder:",
                                                    {"Ref": "AWS::Region"},
                                                    ":",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":infrastructure-configuration/parallelclusterimage-",
                                                    {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": "imagebuilder:DeleteComponent",
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":imagebuilder:",
                                                    {"Ref": "AWS::Region"},
                                                    ":",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":component/parallelclusterimage-updateos-",
                                                    {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                                                    "/*",
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": "imagebuilder:DeleteComponent",
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":imagebuilder:",
                                                    {"Ref": "AWS::Region"},
                                                    ":",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":component/parallelclusterimage-",
                                                    {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                                                    "/*",
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": "imagebuilder:DeleteComponent",
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":imagebuilder:",
                                                    {"Ref": "AWS::Region"},
                                                    ":",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":component/parallelclusterimage-script-0-",
                                                    {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                                                    "/*",
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": "imagebuilder:DeleteComponent",
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":imagebuilder:",
                                                    {"Ref": "AWS::Region"},
                                                    ":",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":component/parallelclusterimage-script-1-",
                                                    {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                                                    "/*",
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": "imagebuilder:DeleteComponent",
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":imagebuilder:",
                                                    {"Ref": "AWS::Region"},
                                                    ":",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":component/parallelclusterimage-tag-",
                                                    {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                                                    "/*",
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": "imagebuilder:DeleteImageRecipe",
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":imagebuilder:",
                                                    {"Ref": "AWS::Region"},
                                                    ":",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":image-recipe/parallelclusterimage-",
                                                    {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                                                    "/*",
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": "imagebuilder:DeleteDistributionConfiguration",
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":imagebuilder:",
                                                    {"Ref": "AWS::Region"},
                                                    ":",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":distribution-configuration/parallelclusterimage-",
                                                    {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": "imagebuilder:DeleteImage",
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":imagebuilder:",
                                                    {"Ref": "AWS::Region"},
                                                    ":",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":image/parallelclusterimage-",
                                                    {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                                                    "/*",
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": "cloudformation:DeleteStack",
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":cloudformation:",
                                                    {"Ref": "AWS::Region"},
                                                    ":",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":stack/My-Image/",
                                                    {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": ["iam:DetachRolePolicy", "iam:DeleteRole", "iam:DeleteRolePolicy"],
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":iam::",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":role/ParallelClusterImage/"
                                                    "My-Image-DeleteStackFunctionExecutionRole-*",
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": ["lambda:DeleteFunction", "lambda:RemovePermission"],
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":lambda:",
                                                    {"Ref": "AWS::Region"},
                                                    ":",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":function:ParallelClusterImage-",
                                                    {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": "iam:RemoveRoleFromInstanceProfile",
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":iam::",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":instance-profile/ParallelClusterImage/My-Image-InstanceProfile-*",
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": ["iam:DetachRolePolicy", "iam:DeleteRolePolicy"],
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":iam::",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":role/ParallelClusterImage/My-Image-InstanceRole-*",
                                                ],
                                            ]
                                        },
                                    },
                                    {
                                        "Action": ["SNS:GetTopicAttributes", "SNS:DeleteTopic"],
                                        "Effect": "Allow",
                                        "Resource": {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    "arn:",
                                                    {"Ref": "AWS::Partition"},
                                                    ":sns:",
                                                    {"Ref": "AWS::Region"},
                                                    ":",
                                                    {"Ref": "AWS::AccountId"},
                                                    ":ParallelClusterImage-",
                                                    {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                                                ],
                                            ]
                                        },
                                    },
                                ],
                                "Version": "2012-10-17",
                            },
                            "PolicyName": "LambdaCleanupPolicy",
                        }
                    ],
                    "Tags": [
                        {
                            "Key": "pcluster_build_image",
                            "Value": utils.get_installed_version(),
                        }
                    ],
                },
            },
            {"Fn::GetAtt": ["DeleteStackFunctionExecutionRole", "Arn"]},
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "iam": {
                            "cleanup_lambda_role": "arn:aws:iam::346106133209:role/custom_lambda_cleanup_role",
                        },
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
            "arn:aws:iam::346106133209:role/custom_lambda_cleanup_role",
        ),
    ],
)
def test_imagebuilder_lambda_execution_role(
    mocker,
    resource,
    response,
    expected_execution_role,
    expected_execution_role_in_lambda_function,
):
    mock_aws_api(mocker)
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(imagebuild, "My-Image", dummy_imagebuilder_bucket())
    assert_that(generated_template.get("Resources").get("DeleteStackFunctionExecutionRole")).is_equal_to(
        expected_execution_role
    )
    assert_that(
        generated_template.get("Resources").get("DeleteStackFunction").get("Properties").get("Role")
    ).is_equal_to(expected_execution_role_in_lambda_function)


@pytest.mark.parametrize(
    "resource, response, expected_components",
    [
        (
            {
                "imagebuilder": {
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
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            [
                {"ComponentArn": {"Ref": "ParallelClusterComponent"}},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0"},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/amazon-cloudwatch-agent-linux/1.0.0"},
                {"ComponentArn": {"Ref": "TagComponent"}},
            ],
        ),
        (
            {
                "imagebuilder": {
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
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            [
                {"ComponentArn": {"Ref": "UpdateOSComponent"}},
                {"ComponentArn": {"Ref": "ParallelClusterComponent"}},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0"},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/amazon-cloudwatch-agent-linux/1.0.0"},
                {"ComponentArn": {"Ref": "TagComponent"}},
            ],
        ),
        (
            {
                "imagebuilder": {
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
                            "VolumeSize": 50,
                        },
                    }
                ],
            },
            [
                {"ComponentArn": {"Ref": "ParallelClusterComponent"}},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0"},
                {"ComponentArn": {"Ref": "ScriptComponent0"}},
                {"ComponentArn": {"Ref": "ScriptComponent1"}},
                {"ComponentArn": {"Ref": "TagComponent"}},
            ],
        ),
    ],
)
def test_imagebuilder_components(mocker, resource, response, expected_components):
    mock_aws_api(mocker)
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(imagebuild, "Pcluster", dummy_imagebuilder_bucket())
    assert_that(generated_template.get("Resources").get("ImageRecipe").get("Properties").get("Components")).is_equal_to(
        expected_components
    )


@pytest.mark.parametrize(
    "resource, response, expected_ami_distribution_configuration",
    [
        (
            {
                "imagebuilder": {
                    "image": {
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
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                        },
                    },
                    "Region": {"Ref": "AWS::Region"},
                },
            ],
        ),
        (
            {
                "imagebuilder": {
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
                        "AmiTags": {
                            "pcluster_version": utils.get_installed_version(),
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                        },
                    },
                    "Region": {"Ref": "AWS::Region"},
                },
            ],
        ),
        (
            {
                "imagebuilder": {
                    "image": {
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
                        "AmiTags": {
                            "pcluster_version": utils.get_installed_version(),
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                        },
                    },
                    "Region": {"Ref": "AWS::Region"},
                },
            ],
        ),
    ],
)
def test_imagebuilder_ami_tags(mocker, resource, response, expected_ami_distribution_configuration):
    mock_aws_api(mocker)
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(
        imagebuild, "Pcluster", dummy_imagebuilder_bucket()
    )
    assert_that(
        generated_template.get("Resources").get("DistributionConfiguration").get("Properties").get("Distributions")
    ).is_equal_to(expected_ami_distribution_configuration)


@pytest.mark.parametrize(
    "resource, response, expected_imagebuilder_resource_tags, expected_role_tags",
    [
        (
            {
                "imagebuilder": {
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
                            "VolumeSize": 50,
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
                {
                    "Key": "pcluster_build_image",
                    "Value": utils.get_installed_version(),
                },
            ],
        ),
        (
            {
                "imagebuilder": {
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
            [
                {
                    "Key": "pcluster_build_image",
                    "Value": utils.get_installed_version(),
                }
            ],
        ),
        (
            {
                "imagebuilder": {
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
            [
                {
                    "Key": "pcluster_build_image",
                    "Value": utils.get_installed_version(),
                }
            ],
        ),
    ],
)
def test_imagebuilder_build_tags(mocker, resource, response, expected_imagebuilder_resource_tags, expected_role_tags):
    mock_aws_api(mocker)
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(
        imagebuild, "Pcluster", dummy_imagebuilder_bucket()
    )
    for resource_name, resource in generated_template.get("Resources").items():
        if resource_name == "InstanceProfile" or resource_name == "DeleteStackFunctionPermission":
            # InstanceProfile and DeleteStackFunctionPermission have no tags
            continue
        elif (
            resource_name == "InstanceRole"
            or resource_name == "DeleteStackFunctionExecutionRole"
            or resource_name == "DeleteStackFunction"
            or resource_name == "BuildNotificationTopic"
        ):
            assert_that(resource.get("Properties").get("Tags")).is_equal_to(expected_role_tags)
        else:
            assert_that(resource.get("Properties").get("Tags")).is_equal_to(expected_imagebuilder_resource_tags)


@pytest.mark.parametrize(
    "resource, response, expected_imagebuilder_subnet_id",
    [
        (
            {
                "imagebuilder": {
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
    mock_aws_api(mocker)
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(
        imagebuild, "Pcluster", dummy_imagebuilder_bucket()
    )

    assert_that(
        generated_template.get("Resources").get("InfrastructureConfiguration").get("Properties").get("SubnetId")
    ).is_equal_to(expected_imagebuilder_subnet_id)


@pytest.mark.parametrize(
    "resource, response, expected_imagebuilder_instance_type",
    [
        (
            {
                "imagebuilder": {
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
            ["c5.xlarge"],
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "p2.8xlarge",
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
            ["p2.8xlarge"],
        ),
    ],
)
def test_imagebuilder_instance_type(mocker, resource, response, expected_imagebuilder_instance_type):
    mock_aws_api(mocker)
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(imagebuild, "Pcluster")

    assert_that(
        generated_template.get("Resources").get("InfrastructureConfiguration").get("Properties").get("InstanceTypes")
    ).is_equal_to(expected_imagebuilder_instance_type)


@pytest.mark.parametrize(
    "resource, response, expected_imagebuilder_parent_image",
    [
        (
            {
                "imagebuilder": {
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
            "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "p2.8xlarge",
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
            "ami-0185634c5a8a37250",
        ),
    ],
)
def test_imagebuilder_parent_image(mocker, resource, response, expected_imagebuilder_parent_image):
    mock_aws_api(mocker)
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(imagebuild, "Pcluster")

    assert_that(
        generated_template.get("Resources").get("ImageRecipe").get("Properties").get("ParentImage")
    ).is_equal_to(expected_imagebuilder_parent_image)


@pytest.mark.parametrize(
    "resource, response, expected_imagebuilder_security_group_ids",
    [
        (
            {
                "imagebuilder": {
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
    mock_aws_api(mocker)
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(
        imagebuild, "Pcluster", dummy_imagebuilder_bucket()
    )

    assert_that(
        generated_template.get("Resources").get("InfrastructureConfiguration").get("Properties").get("SecurityGroupIds")
    ).is_equal_to(expected_imagebuilder_security_group_ids)


@pytest.mark.parametrize(
    "resource, response, expected_distributions",
    [
        (
            {
                "imagebuilder": {
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
                        "AmiTags": {
                            "pcluster_version": "2.10.1",
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                        },
                    },
                    "Region": {"Ref": "AWS::Region"},
                },
            ],
        ),
        (
            {
                "imagebuilder": {
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
                            "pcluster_version": "2.10.1",
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                        },
                    },
                    "Region": {"Ref": "AWS::Region"},
                },
            ],
        ),
        (
            {
                "imagebuilder": {
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
                            "pcluster_version": "2.10.1",
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                        },
                    },
                    "Region": "eu-south-1",
                },
            ],
        ),
        (
            {
                "imagebuilder": {
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
                            "pcluster_version": "2.10.1",
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                        },
                        "LaunchPermissionConfiguration": "",
                    },
                    "Region": "eu-south-1",
                },
            ],
        ),
        (
            {
                "imagebuilder": {
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
                            "pcluster_version": "2.10.1",
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                        },
                        "LaunchPermissionConfiguration": {"UserIds": ["123456789012", "345678901234"]},
                    },
                    "Region": "eu-south-1",
                },
            ],
        ),
        (
            {
                "imagebuilder": {
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
                            "pcluster_version": "2.10.1",
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                        },
                        "LaunchPermissionConfiguration": {"UserIds": []},
                    },
                    "Region": "eu-south-1",
                },
            ],
        ),
        (
            {
                "imagebuilder": {
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
                            "pcluster_version": "2.10.1",
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                        },
                        "LaunchPermissionConfiguration": {"UserGroups": ["all"]},
                    },
                    "Region": "eu-south-1",
                },
                {
                    "AmiDistributionConfiguration": {
                        "Name": "Pcluster {{ imagebuilder:buildDate }}",
                        "AmiTags": {
                            "pcluster_version": "2.10.1",
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                        },
                        "LaunchPermissionConfiguration": {"UserGroups": ["all"]},
                    },
                    "Region": "us-west-1",
                },
            ],
        ),
    ],
)
def test_imagebuilder_distribution_configuraton(mocker, resource, response, expected_distributions):
    mock_aws_api(mocker)
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    mocker.patch(
        "pcluster.utils.get_installed_version",
        return_value="2.10.1",
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    dummy_imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(
        dummy_imagebuild, "Pcluster", dummy_imagebuilder_bucket()
    )

    assert_that(
        generated_template.get("Resources").get("DistributionConfiguration").get("Properties").get("Distributions")
    ).contains(*expected_distributions)


@pytest.mark.parametrize(
    "resource, response, expected_root_volume",
    [
        (
            {
                "imagebuilder": {
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
                            "VolumeSize": 8,
                        },
                    }
                ],
            },
            {"Encrypted": False, "VolumeSize": 23, "VolumeType": "gp2"},
        ),
        (
            {
                "imagebuilder": {
                    "image": {
                        "root_volume": {
                            "size": 60,
                        },
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
                            "VolumeSize": 25,
                        },
                    }
                ],
            },
            {"Encrypted": False, "VolumeSize": 60, "VolumeType": "gp2"},
        ),
        (
            {
                "imagebuilder": {
                    "image": {
                        "root_volume": {"size": 40, "encrypted": True},
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
                            "VolumeSize": 25,
                        },
                    }
                ],
            },
            {"Encrypted": True, "VolumeSize": 40, "VolumeType": "gp2"},
        ),
        (
            {
                "imagebuilder": {
                    "image": {
                        "root_volume": {
                            "encrypted": True,
                            "kms_key_id": "arn:aws:kms:us-east-1:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab",
                        },
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
            {
                "Encrypted": True,
                "VolumeSize": 65,
                "VolumeType": "gp2",
                "KmsKeyId": "arn:aws:kms:us-east-1:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab",
            },
        ),
    ],
)
def test_imagebuilder_root_volume(mocker, resource, response, expected_root_volume):
    mock_aws_api(mocker)
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    mocker.patch(
        "pcluster.utils.get_installed_version",
        return_value="2.10.1",
    )
    dummy_imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(dummy_imagebuild, "Pcluster")

    assert_that(
        generated_template.get("Resources")
        .get("ImageRecipe")
        .get("Properties")
        .get("BlockDeviceMappings")[0]
        .get("Ebs")
    ).is_equal_to(expected_root_volume)
