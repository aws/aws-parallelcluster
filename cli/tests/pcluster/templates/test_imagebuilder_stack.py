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
from pcluster.aws.aws_resources import ImageInfo
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.templates.imagebuilder_stack import parse_bucket_url
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.config.dummy_imagebuilder_config import imagebuilder_factory
from tests.pcluster.models.dummy_s3_bucket import dummy_imagebuilder_bucket, mock_bucket
from tests.pcluster.utils import assert_lambdas_have_expected_vpc_config_and_managed_policy

# TODO missing tests for the following configuration parameters:
# UpdateOsAndReboot
# DisablePclusterComponent
# DisableValidateAndTest
# Cookbook
# NodePackage
# AwsBatchCliPackage


@pytest.mark.parametrize(
    "resource, response, expected_template",
    [
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                        "instance_type": "c5.xlarge",
                        "update_os_packages": {"enabled": True},
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
                    "CfnParamCincVersion": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                    "CfnParamIsOfficialAmiBuild": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "UpdateOSComponent": {},
                    "ParallelClusterComponent": {},
                    "ParallelClusterTagComponent": {},
                    "ParallelClusterTestComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "BuildNotificationTopic": {},
                    "BuildNotificationSubscription": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "DeleteStackFunctionLog": {},
                },
            },
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                        "instance_type": "c5.xlarge",
                        "update_os_packages": {"enabled": True},
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
                    "CfnParamCincVersion": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                    "CfnParamIsOfficialAmiBuild": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "UpdateOSComponent": {},
                    "ParallelClusterTagComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "BuildNotificationTopic": {},
                    "BuildNotificationSubscription": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "DeleteStackFunctionLog": {},
                },
            },
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                        "instance_type": "c5.xlarge",
                        "update_os_packages": {"enabled": True},
                    },
                    "dev_settings": {
                        "disable_validate_and_test": True,
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
                    "CfnParamCincVersion": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                    "CfnParamIsOfficialAmiBuild": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "UpdateOSComponent": {},
                    "ParallelClusterComponent": {},
                    "ParallelClusterTagComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "BuildNotificationTopic": {},
                    "BuildNotificationSubscription": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "DeleteStackFunctionLog": {},
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
                    "CfnParamCincVersion": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                    "CfnParamIsOfficialAmiBuild": {},
                },
                "Resources": {
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "ParallelClusterComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "ParallelClusterTagComponent": {},
                    "ParallelClusterTestComponent": {},
                    "BuildNotificationTopic": {},
                    "BuildNotificationSubscription": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "DeleteStackFunctionLog": {},
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
                            "instance_profile": "arn:aws:iam::111122223333:instance-profile/my_custom_instance_profile"
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
                    "CfnParamCincVersion": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                    "CfnParamIsOfficialAmiBuild": {},
                },
                "Resources": {
                    "InfrastructureConfiguration": {},
                    "ParallelClusterComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "ParallelClusterTagComponent": {},
                    "ParallelClusterTestComponent": {},
                    "BuildNotificationTopic": {},
                    "BuildNotificationSubscription": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "DeleteStackFunctionLog": {},
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
                    "CfnParamCincVersion": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                    "CfnParamIsOfficialAmiBuild": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "ParallelClusterComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "ParallelClusterTagComponent": {},
                    "ParallelClusterTestComponent": {},
                    "BuildNotificationTopic": {},
                    "BuildNotificationSubscription": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "DeleteStackFunctionLog": {},
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
                    "CfnParamCincVersion": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                    "CfnParamIsOfficialAmiBuild": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "ParallelClusterTagComponent": {},
                    "ParallelClusterTestComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "BuildNotificationTopic": {},
                    "BuildNotificationSubscription": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "DeleteStackFunctionLog": {},
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
                    "CfnParamCincVersion": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                    "CfnParamIsOfficialAmiBuild": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "ParallelClusterTagComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "ParallelClusterComponent": {},
                    "ParallelClusterTestComponent": {},
                    "BuildNotificationTopic": {},
                    "BuildNotificationSubscription": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "DeleteStackFunctionLog": {},
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
                    "CfnParamCincVersion": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                    "CfnParamIsOfficialAmiBuild": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "ParallelClusterTagComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "ParallelClusterComponent": {},
                    "ParallelClusterTestComponent": {},
                    "BuildNotificationTopic": {},
                    "BuildNotificationSubscription": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "DeleteStackFunctionLog": {},
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
                    "CfnParamCincVersion": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                    "CfnParamIsOfficialAmiBuild": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "ParallelClusterTagComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "ParallelClusterComponent": {},
                    "ParallelClusterTestComponent": {},
                    "BuildNotificationTopic": {},
                    "BuildNotificationSubscription": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "DeleteStackFunctionLog": {},
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
                    "CfnParamCincVersion": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                    "CfnParamIsOfficialAmiBuild": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "ParallelClusterComponent": {},
                    "ParallelClusterTagComponent": {},
                    "ParallelClusterTestComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "BuildNotificationTopic": {},
                    "BuildNotificationSubscription": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "DeleteStackFunctionLog": {},
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
                    "dev_settings": {"cookbook": {"chef_cookbook": "s3://bucket_name/path/to/custom/cookbook"}},
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
                    "CfnParamChefCookbook": {"Default": "https://presigned.url"},
                    "CfnParamCincInstaller": {},
                    "CfnParamCincVersion": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                    "CfnParamIsOfficialAmiBuild": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "ParallelClusterComponent": {},
                    "ParallelClusterTagComponent": {},
                    "ParallelClusterTestComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "BuildNotificationTopic": {},
                    "BuildNotificationSubscription": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "DeleteStackFunctionLog": {},
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
                    "dev_settings": {"cookbook": {"chef_cookbook": "https://custom.cookbook.url"}},
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
                    "CfnParamChefCookbook": {"Default": "https://custom.cookbook.url"},
                    "CfnParamCincInstaller": {},
                    "CfnParamCincVersion": {},
                    "CfnParamCookbookVersion": {},
                    "CfnParamUpdateOsAndReboot": {},
                    "CfnParamIsOfficialAmiBuild": {},
                },
                "Resources": {
                    "InstanceRole": {},
                    "InstanceProfile": {},
                    "InfrastructureConfiguration": {},
                    "ParallelClusterComponent": {},
                    "ParallelClusterTagComponent": {},
                    "ParallelClusterTestComponent": {},
                    "ImageRecipe": {},
                    "ParallelClusterImage": {},
                    "BuildNotificationTopic": {},
                    "BuildNotificationSubscription": {},
                    "DistributionConfiguration": {},
                    "DeleteStackFunctionExecutionRole": {},
                    "DeleteStackFunction": {},
                    "DeleteStackFunctionPermission": {},
                    "DeleteStackFunctionLog": {},
                },
            },
        ),
    ],
)
def test_imagebuilder_parameters_and_resources(mocker, resource, response, expected_template):
    mock_aws_api(mocker)
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo(response),
    )
    mocker.patch("pcluster.aws.s3.S3Client.create_presigned_url", return_value="https://presigned.url")
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
                    "RoleName": {
                        "Fn::Join": [
                            "",
                            [
                                "ParallelClusterImage-",
                                {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                            ],
                        ]
                    },
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
                    "Path": "/parallelcluster/",
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
                        },
                    ],
                    "Tags": [
                        {
                            "Key": "parallelcluster:image_id",
                            "Value": "Pcluster",
                        },
                        {
                            "Key": "parallelcluster:image_name",
                            "Value": "Pcluster",
                        },
                    ],
                },
            },
            {
                "Type": "AWS::IAM::InstanceProfile",
                "Properties": {
                    "Roles": [{"Ref": "InstanceRole"}],
                    "Path": "/parallelcluster/",
                    "InstanceProfileName": {
                        "Fn::Join": [
                            "",
                            [
                                "ParallelClusterImage-",
                                {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                            ],
                        ]
                    },
                },
            },
            {"Ref": "InstanceProfile"},
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "iam": {
                            "additional_iam_policies": [{"policy": "arn:aws:iam::aws:policy/AmazonEC2ReadOnlyAccess"}]
                        },
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
                    "RoleName": {
                        "Fn::Join": [
                            "",
                            [
                                "ParallelClusterImage-",
                                {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                            ],
                        ]
                    },
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
                        "arn:aws:iam::aws:policy/AmazonEC2ReadOnlyAccess",
                    ],
                    "Path": "/parallelcluster/",
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
                            "Key": "parallelcluster:image_id",
                            "Value": "Pcluster",
                        },
                        {
                            "Key": "parallelcluster:image_name",
                            "Value": "Pcluster",
                        },
                    ],
                },
            },
            {
                "Type": "AWS::IAM::InstanceProfile",
                "Properties": {
                    "Roles": [{"Ref": "InstanceRole"}],
                    "Path": "/parallelcluster/",
                    "InstanceProfileName": {
                        "Fn::Join": [
                            "",
                            [
                                "ParallelClusterImage-",
                                {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                            ],
                        ]
                    },
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
                    "Roles": ["test-InstanceRole"],
                    "Path": "/parallelcluster/",
                    "InstanceProfileName": {
                        "Fn::Join": [
                            "",
                            [
                                "ParallelClusterImage-",
                                {"Fn::Select": [2, {"Fn::Split": ["/", {"Ref": "AWS::StackId"}]}]},
                            ],
                        ]
                    },
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
                            "instance_profile": "arn:aws:iam::xxxxxxxxxxxx:instance-profile/InstanceProfile",
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
            "InstanceProfile",
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
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo(response),
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(
        imagebuild, "Pcluster", dummy_imagebuilder_bucket()
    )
    assert_that(generated_template.get("Resources").get("InstanceRole")).is_equal_to(expected_instance_role)
    assert_that(generated_template.get("Resources").get("InstanceProfile")).is_equal_to(expected_instance_profile)
    assert_that(
        generated_template.get("Resources")
        .get("InfrastructureConfiguration")
        .get("Properties")
        .get("InstanceProfileName")
    ).is_equal_to(expected_instance_profile_in_infrastructure_configuration)


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
                {"ComponentArn": {"Ref": "ParallelClusterTagComponent"}},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0"},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/amazon-cloudwatch-agent-linux/1.0.0"},
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
                        "update_os_packages": {"enabled": True},
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
                {"ComponentArn": {"Ref": "UpdateOSComponent"}},
                {"ComponentArn": {"Ref": "ParallelClusterComponent"}},
                {"ComponentArn": {"Ref": "ParallelClusterTagComponent"}},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0"},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/amazon-cloudwatch-agent-linux/1.0.0"},
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
                {"ComponentArn": {"Ref": "ParallelClusterTagComponent"}},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0"},
                {"ComponentArn": {"Ref": "ScriptComponent0"}},
                {"ComponentArn": {"Ref": "ScriptComponent1"}},
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
                        "update_os_packages": {"enabled": True},
                    },
                    "dev_settings": {
                        "disable_pcluster_component": True,
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
                {"ComponentArn": {"Ref": "UpdateOSComponent"}},
                {"ComponentArn": {"Ref": "ParallelClusterTagComponent"}},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0"},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/amazon-cloudwatch-agent-linux/1.0.0"},
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
                    "dev_settings": {
                        "disable_validate_and_test": False,
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
                {"ComponentArn": {"Ref": "ParallelClusterTagComponent"}},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0"},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/amazon-cloudwatch-agent-linux/1.0.0"},
                {"ComponentArn": {"Ref": "ParallelClusterTestComponent"}},
            ],
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "installation": {"nvidia_software": {"enabled": True}, "lustre_client": {"enabled": True}},
                        "imds": {"imds_support": "v2.0"},
                        "subnet_id": "subnet-0292c5356eadc531f",
                        "iam": {
                            "instance_role": "arn:aws:iam::123456789012:role/pcluster",
                            "instance_profile": "arn:aws:iam::123456789012:instance-profile/pcluster",
                            "cleanup_lambda_role": "arn:aws:iam::123456789012:role/pcluster",
                            "additional_iam_policies": [{"policy": "arn:aws:iam::aws:policy/AmazonEC2ReadOnlyAccess"}],
                        },
                        "instance_type": "c5.xlarge",
                        "security_group_ids": ["sg-b0bbeacc", "sg-0fc70b22048995b07"],
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
                        "update_os_packages": {"enabled": True},
                    },
                    "dev_settings": {
                        "cookbook": {
                            "chef_cookbook": "https://tests/aws-parallelcluster-cookbook-3.0.tgz",
                            "extra_chef_attributes": '{"cluster": {"test_attribute": "test_attribute_values"}}',
                        },
                        "node_package": "https://tests/aws-parallelcluster-node-3.0.tgz",
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
                {"ComponentArn": {"Ref": "UpdateOSComponent"}},
                {"ComponentArn": {"Ref": "ParallelClusterComponent"}},
                {"ComponentArn": {"Ref": "ParallelClusterTagComponent"}},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/apache-tomcat-9-linux/1.0.0"},
                {"ComponentArn": "arn:aws:imagebuilder:us-east-1:aws:component/amazon-cloudwatch-agent-linux/1.0.0"},
            ],
        ),
    ],
)
def test_imagebuilder_components(mocker, resource, response, expected_components):
    mock_aws_api(mocker)
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo(response),
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(
        imagebuild, "Pcluster", dummy_imagebuilder_bucket()
    )
    assert_that(generated_template.get("Resources").get("ImageRecipe").get("Properties").get("Components")).is_equal_to(
        expected_components
    )

    # Check size Limits of ImageBuilder Components
    imagebuilder_resources = generated_template.get("Resources")
    for component_name, _ in imagebuilder_resources.items():
        if (
            imagebuilder_resources.get(component_name)
            and imagebuilder_resources.get(component_name).get("Type") == "AWS::ImageBuilder::Component"
        ):
            print(
                "Component {} has size {}".format(
                    component_name, len(str(imagebuilder_resources.get(component_name).get("Properties").get("Data")))
                )
            )
            assert_that(
                len(str(imagebuilder_resources.get(component_name).get("Properties").get("Data")))
            ).is_less_than(13600)
            # The limit of image builder is 16000.
            # This check is stricter to consider the parameters os stack might add in more length


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
                            "parallelcluster:image_name": "Pcluster",
                            "parallelcluster:image_id": "Pcluster",
                            "parallelcluster:version": utils.get_installed_version(),
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                            "parallelcluster:build_config": "s3://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete"
                            "/parallelcluster/imagebuilders/dummy-image-randomstring123/configs/image-config.yaml",
                            "parallelcluster:build_log": {
                                "Fn::Join": [
                                    "",
                                    [
                                        "arn:",
                                        {"Ref": "AWS::Partition"},
                                        ":logs:us-east-1:",
                                        {"Ref": "AWS::AccountId"},
                                        ":log-group:/aws/imagebuilder/ParallelClusterImage-Pcluster",
                                    ],
                                ]
                            },
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
                            "parallelcluster:version": utils.get_installed_version(),
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                            "parallelcluster:image_id": "Pcluster",
                            "parallelcluster:image_name": "Pcluster",
                            "parallelcluster:build_config": "s3://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete"
                            "/parallelcluster/imagebuilders/dummy-image-randomstring123/configs/image-config.yaml",
                            "parallelcluster:build_log": {
                                "Fn::Join": [
                                    "",
                                    [
                                        "arn:",
                                        {"Ref": "AWS::Partition"},
                                        ":logs:us-east-1:",
                                        {"Ref": "AWS::AccountId"},
                                        ":log-group:/aws/imagebuilder/ParallelClusterImage-Pcluster",
                                    ],
                                ]
                            },
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
                        "name": "pcluster_3.0.0",
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
                        "Name": "pcluster_3.0.0 {{ imagebuilder:buildDate }}",
                        "AmiTags": {
                            "parallelcluster:version": utils.get_installed_version(),
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                            "parallelcluster:image_id": "Pcluster",
                            "parallelcluster:image_name": "pcluster_3.0.0",
                            "parallelcluster:build_config": "s3://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete"
                            "/parallelcluster/imagebuilders/dummy-image-randomstring123/configs/image-config.yaml",
                            "parallelcluster:build_log": {
                                "Fn::Join": [
                                    "",
                                    [
                                        "arn:",
                                        {"Ref": "AWS::Partition"},
                                        ":logs:us-east-1:",
                                        {"Ref": "AWS::AccountId"},
                                        ":log-group:/aws/imagebuilder/ParallelClusterImage-Pcluster",
                                    ],
                                ]
                            },
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
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo(response),
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
                "keyTag1": "valueTag1",
                "keyTag2": "valueTag2",
                "parallelcluster:image_id": "Pcluster",
                "parallelcluster:image_name": "Pcluster",
            },
            [
                {
                    "Key": "keyTag1",
                    "Value": "valueTag1",
                },
                {
                    "Key": "keyTag2",
                    "Value": "valueTag2",
                },
                {"Key": "parallelcluster:image_id", "Value": "Pcluster"},
                {"Key": "parallelcluster:image_name", "Value": "Pcluster"},
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
            {"parallelcluster:image_id": "Pcluster", "parallelcluster:image_name": "Pcluster"},
            [
                {"Key": "parallelcluster:image_id", "Value": "Pcluster"},
                {"Key": "parallelcluster:image_name", "Value": "Pcluster"},
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
            {"parallelcluster:image_id": "Pcluster", "parallelcluster:image_name": "Pcluster"},
            [
                {"Key": "parallelcluster:image_id", "Value": "Pcluster"},
                {"Key": "parallelcluster:image_name", "Value": "Pcluster"},
            ],
        ),
    ],
)
def test_imagebuilder_build_tags(mocker, resource, response, expected_imagebuilder_resource_tags, expected_role_tags):
    mock_aws_api(mocker)
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo(response),
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(
        imagebuild, "Pcluster", dummy_imagebuilder_bucket()
    )
    for resource_name, resource in generated_template.get("Resources").items():
        if (
            resource_name == "InstanceProfile"
            or resource_name == "DeleteStackFunctionPermission"
            or resource_name == "DeleteStackFunctionLog"
            or resource_name == "BuildNotificationSubscription"
        ):
            # InstanceProfile, DeleteStackFunctionPermission,
            # DeleteStackFunctionLog and BuildNotificationSubscription have no tags
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

        if resource_name == "InfrastructureConfiguration":
            assert_that(resource.get("Properties").get("ResourceTags")).is_equal_to(expected_imagebuilder_resource_tags)


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
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo(response),
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
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo(response),
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(
        imagebuild, "Pcluster", dummy_imagebuilder_bucket()
    )

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
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo(response),
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(
        imagebuild, "Pcluster", dummy_imagebuilder_bucket()
    )

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
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo(response),
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
                        "update_os_packages": {"enabled": True},
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
            [
                {
                    "AmiDistributionConfiguration": {
                        "Name": "Pcluster {{ imagebuilder:buildDate }}",
                        "AmiTags": {
                            "parallelcluster:image_name": "Pcluster",
                            "parallelcluster:image_id": "Pcluster",
                            "parallelcluster:version": utils.get_installed_version(),
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                            "parallelcluster:build_config": "s3://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete"
                            "/parallelcluster/imagebuilders/dummy-image-randomstring123/configs/image-config.yaml",
                            "parallelcluster:build_log": {
                                "Fn::Join": [
                                    "",
                                    [
                                        "arn:",
                                        {"Ref": "AWS::Partition"},
                                        ":logs:us-east-1:",
                                        {"Ref": "AWS::AccountId"},
                                        ":log-group:/aws/imagebuilder/ParallelClusterImage-Pcluster",
                                    ],
                                ]
                            },
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
                            "parallelcluster:image_name": "Pcluster",
                            "parallelcluster:image_id": "Pcluster",
                            "parallelcluster:version": utils.get_installed_version(),
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                            "parallelcluster:build_config": "s3://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete"
                            "/parallelcluster/imagebuilders/dummy-image-randomstring123/configs/image-config.yaml",
                            "parallelcluster:build_log": {
                                "Fn::Join": [
                                    "",
                                    [
                                        "arn:",
                                        {"Ref": "AWS::Partition"},
                                        ":logs:us-east-1:",
                                        {"Ref": "AWS::AccountId"},
                                        ":log-group:/aws/imagebuilder/ParallelClusterImage-Pcluster",
                                    ],
                                ]
                            },
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
                            "parallelcluster:image_name": "Pcluster",
                            "parallelcluster:image_id": "Pcluster",
                            "parallelcluster:version": utils.get_installed_version(),
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                            "parallelcluster:build_config": "s3://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete"
                            "/parallelcluster/imagebuilders/dummy-image-randomstring123/configs/image-config.yaml",
                            "parallelcluster:build_log": {
                                "Fn::Join": [
                                    "",
                                    [
                                        "arn:",
                                        {"Ref": "AWS::Partition"},
                                        ":logs:us-east-1:",
                                        {"Ref": "AWS::AccountId"},
                                        ":log-group:/aws/imagebuilder/ParallelClusterImage-Pcluster",
                                    ],
                                ]
                            },
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
                            "parallelcluster:image_name": "Pcluster",
                            "parallelcluster:image_id": "Pcluster",
                            "parallelcluster:version": utils.get_installed_version(),
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                            "parallelcluster:build_config": "s3://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete"
                            "/parallelcluster/imagebuilders/dummy-image-randomstring123/configs/image-config.yaml",
                            "parallelcluster:build_log": {
                                "Fn::Join": [
                                    "",
                                    [
                                        "arn:",
                                        {"Ref": "AWS::Partition"},
                                        ":logs:us-east-1:",
                                        {"Ref": "AWS::AccountId"},
                                        ":log-group:/aws/imagebuilder/ParallelClusterImage-Pcluster",
                                    ],
                                ]
                            },
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
                    "dev_settings": {
                        "distribution_configuration": {
                            "regions": "eu-south-1",
                            "launch_permission": '{"UserIds": ["123456789012", "345678901234"]}',
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
                            "parallelcluster:image_name": "Pcluster",
                            "parallelcluster:image_id": "Pcluster",
                            "parallelcluster:version": utils.get_installed_version(),
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                            "parallelcluster:build_config": "s3://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete"
                            "/parallelcluster/imagebuilders/dummy-image-randomstring123/configs/image-config.yaml",
                            "parallelcluster:build_log": {
                                "Fn::Join": [
                                    "",
                                    [
                                        "arn:",
                                        {"Ref": "AWS::Partition"},
                                        ":logs:us-east-1:",
                                        {"Ref": "AWS::AccountId"},
                                        ":log-group:/aws/imagebuilder/ParallelClusterImage-Pcluster",
                                    ],
                                ]
                            },
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
                            "launch_permission": '{"UserIds": []}',
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
                            "parallelcluster:image_name": "Pcluster",
                            "parallelcluster:image_id": "Pcluster",
                            "parallelcluster:version": utils.get_installed_version(),
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                            "parallelcluster:build_config": "s3://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete"
                            "/parallelcluster/imagebuilders/dummy-image-randomstring123/configs/image-config.yaml",
                            "parallelcluster:build_log": {
                                "Fn::Join": [
                                    "",
                                    [
                                        "arn:",
                                        {"Ref": "AWS::Partition"},
                                        ":logs:us-east-1:",
                                        {"Ref": "AWS::AccountId"},
                                        ":log-group:/aws/imagebuilder/ParallelClusterImage-Pcluster",
                                    ],
                                ]
                            },
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
                            "launch_permission": '{"UserGroups": ["all"]}',
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
                            "parallelcluster:image_name": "Pcluster",
                            "parallelcluster:image_id": "Pcluster",
                            "parallelcluster:version": utils.get_installed_version(),
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                            "parallelcluster:build_config": "s3://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete"
                            "/parallelcluster/imagebuilders/dummy-image-randomstring123/configs/image-config.yaml",
                            "parallelcluster:build_log": {
                                "Fn::Join": [
                                    "",
                                    [
                                        "arn:",
                                        {"Ref": "AWS::Partition"},
                                        ":logs:us-east-1:",
                                        {"Ref": "AWS::AccountId"},
                                        ":log-group:/aws/imagebuilder/ParallelClusterImage-Pcluster",
                                    ],
                                ]
                            },
                        },
                        "LaunchPermissionConfiguration": {"UserGroups": ["all"]},
                    },
                    "Region": "eu-south-1",
                },
                {
                    "AmiDistributionConfiguration": {
                        "Name": "Pcluster {{ imagebuilder:buildDate }}",
                        "AmiTags": {
                            "parallelcluster:image_name": "Pcluster",
                            "parallelcluster:image_id": "Pcluster",
                            "parallelcluster:version": utils.get_installed_version(),
                            "parallelcluster:s3_bucket": "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
                            "parallelcluster:s3_image_dir": "parallelcluster/imagebuilders/dummy-image-randomstring123",
                            "parallelcluster:build_config": "s3://parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete"
                            "/parallelcluster/imagebuilders/dummy-image-randomstring123/configs/image-config.yaml",
                            "parallelcluster:build_log": {
                                "Fn::Join": [
                                    "",
                                    [
                                        "arn:",
                                        {"Ref": "AWS::Partition"},
                                        ":logs:us-east-1:",
                                        {"Ref": "AWS::AccountId"},
                                        ":log-group:/aws/imagebuilder/ParallelClusterImage-Pcluster",
                                    ],
                                ]
                            },
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
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo(response),
    )
    mocker.patch(
        "pcluster.utils.get_installed_version",
        return_value=utils.get_installed_version(),
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
            {"Encrypted": False, "VolumeSize": 45, "VolumeType": "gp3"},
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
            {"Encrypted": False, "VolumeSize": 60, "VolumeType": "gp3"},
        ),
        (
            {
                "imagebuilder": {
                    "image": {
                        "root_volume": {"size": 45, "encrypted": True},
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
            {"Encrypted": True, "VolumeSize": 45, "VolumeType": "gp3"},
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
                "VolumeSize": 87,
                "VolumeType": "gp3",
                "KmsKeyId": "arn:aws:kms:us-east-1:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab",
            },
        ),
    ],
)
def test_imagebuilder_root_volume(mocker, resource, response, expected_root_volume):
    mock_aws_api(mocker)
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo(response),
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
        generated_template.get("Resources")
        .get("ImageRecipe")
        .get("Properties")
        .get("BlockDeviceMappings")[0]
        .get("Ebs")
    ).is_equal_to(expected_root_volume)


@pytest.mark.parametrize(
    "resource, response, http_tokens",
    [
        (
            {
                "imagebuilder": {
                    "build": {
                        "imds": {"imds_support": "v2.0"},
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
            "required",
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "imds": {"imds_support": "v1.0"},
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
            "optional",
        ),
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
            "required",
        ),
    ],
)
def test_imagebuilder_imds_settings(mocker, resource, response, http_tokens):
    mock_aws_api(mocker)
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo(response),
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(
        imagebuild, "Pcluster", dummy_imagebuilder_bucket()
    )

    assert_that(
        generated_template.get("Resources")
        .get("InfrastructureConfiguration")
        .get("Properties")
        .get("InstanceMetadataOptions")
        .get("HttpTokens")
    ).is_equal_to(http_tokens)


@pytest.mark.parametrize(
    "resource",
    [
        {
            "imagebuilder": {
                "build": {
                    "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                    "instance_type": "c5.xlarge",
                },
                "deployment_settings": {
                    "lambda_functions_vpc_config": {
                        "subnet_ids": ["subnet-8e482ce8"],
                        "security_group_ids": ["sg-028d73ae220157d96"],
                    }
                },
            }
        },
        {
            "imagebuilder": {
                "build": {
                    "parent_image": "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
                    "instance_type": "c5.xlarge",
                },
            }
        },
    ],
)
def test_imagebuilder_lambda_functions_vpc_config(mocker, resource):
    mock_aws_api(mocker)
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo(
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
            }
        ),
    )
    # mock bucket initialization parameters
    mock_bucket(mocker)

    imagebuild = imagebuilder_factory(resource).get("imagebuilder")
    generated_template = CDKTemplateBuilder().build_imagebuilder_template(
        imagebuild, "Pcluster", dummy_imagebuilder_bucket()
    )

    assert_lambdas_have_expected_vpc_config_and_managed_policy(
        generated_template, _lambda_functions_vpc_config_with_camel_cased_keys(resource)
    )


def _lambda_functions_vpc_config_with_camel_cased_keys(resource):
    snake_case_config = resource.get("imagebuilder").get("deployment_settings", {}).get("lambda_functions_vpc_config")
    return (
        {key.title().replace("_", ""): value for key, value in snake_case_config.items()} if snake_case_config else None
    )


@pytest.mark.parametrize(
    "url, expect_output",
    [
        (
            "s3://test/post_install.sh",
            {"bucket_name": "test", "object_key": "post_install.sh", "object_name": "post_install.sh"},
        ),
        (
            "s3://test/templates/3.0/post_install.sh",
            {
                "bucket_name": "test",
                "object_key": "templates/3.0/post_install.sh",
                "object_name": "post_install.sh",
            },
        ),
    ],
)
def test_parse_bucket_url(url, expect_output):
    assert_that(parse_bucket_url(url)).is_equal_to(expect_output)
