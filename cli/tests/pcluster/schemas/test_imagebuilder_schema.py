import json

import pytest
import yaml
from assertpy import assert_that
from marshmallow import ValidationError

from pcluster.schemas.imagebuilder_schema import ImagebuilderDeploymentSettingsSchema, ImageBuilderSchema
from pcluster.utils import load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import mock_aws_api


@pytest.mark.parametrize(
    "config_file_name, describe_image_response, failure_message",
    [
        pytest.param(
            "imagebuilder_schema_required.yaml",
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
            None,
            id="Test with only required fields",
        ),
        pytest.param(
            "imagebuilder_schema_all.yaml",
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
            None,
            id="Testing with full config",
        ),
        pytest.param(
            "imagebuilder_schema_all.yaml",
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
            "Unknown field.",
            id="Testing unsupported config field i.e DisableSudoAccessForDefaultUser",
        ),
    ],
)
def test_imagebuilder_schema(
    mocker, test_datadir, config_file_name, describe_image_response, failure_message, pcluster_config_reader
):
    mock_aws_api(mocker)
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=describe_image_response,
    )
    disable_sudo_access_for_default_user = "False"
    if failure_message:
        disable_sudo_access_for_default_user = "True"

    rendered_config_file = pcluster_config_reader(
        config_file_name, disable_sudo_access_for_default_user=disable_sudo_access_for_default_user
    )
    # Load imagebuilder model from Yaml file
    input_yaml = load_yaml_dict(rendered_config_file)
    print(input_yaml)

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            ImageBuilderSchema().load(input_yaml)
    else:
        imagebuilder_config = ImageBuilderSchema().load(input_yaml)
        print(imagebuilder_config)

        # Re-create Yaml file from model and compare content
        image_builder_schema = ImageBuilderSchema()
        image_builder_schema.context = {"delete_defaults_when_dump": True}
        output_json = image_builder_schema.dump(imagebuilder_config)

        # Assert imagebuilder config file can be convert to imagebuilder config
        assert_that(json.dumps(input_yaml, sort_keys=True)).is_equal_to(json.dumps(output_json, sort_keys=True))

        # Print output yaml
        output_yaml = yaml.dump(output_json)
        print(output_yaml)


@pytest.mark.parametrize(
    "config_dict, failure_message",
    [
        pytest.param(
            {
                "LambdaFunctionsVpcConfig": {
                    "SubnetIds": ["subnet-8e482ce8"],
                    "SecurityGroupIds": ["sg-028d73ae220157d96"],
                },
            },
            None,
            id="No missing Fields",
        ),
        pytest.param(
            {"LambdaFunctionsVpcConfig": {"SubnetIds": ["subnet-8e482ce8"]}},
            "Missing data for required field",
            id="Missing SecurityGroupIds",
        ),
        pytest.param(
            {"LambdaFunctionsVpcConfig": {"SecurityGroupIds": ["sg-028d73ae220157d96"]}},
            "Missing data for required field",
            id="Missing SubnetIds",
        ),
        pytest.param(
            {"DisableSudoAccessForDefaultUser": "True"},
            "Unknown field.",
            id="Unsupported field DisableSudoAccessForDefaultUser is provided",
        ),
    ],
)
def test_imagebuilder_deployment_settings_schema(mocker, config_dict, failure_message):
    mock_aws_api(mocker)
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            ImagebuilderDeploymentSettingsSchema().load(config_dict)
    else:
        conf = ImagebuilderDeploymentSettingsSchema().load(config_dict)
        ImagebuilderDeploymentSettingsSchema().dump(conf)


@pytest.mark.parametrize(
    "config_dict, describe_image_response, failure_message",
    [
        pytest.param(
            {
                "Region": "us-east-1",
                "Image": {
                    "Name": "test-resource-prefix-ami",
                    "Tags": [
                        {"Key": "Name", "Value": "ParallelCluster-ResourcePrefix-AMI"},
                        {"Key": "Version", "Value": "3.15.0"}
                    ]
                },
                "Build": {
                    "Iam": {
                        "ResourcePrefix": "/test-path/test-prefix"
                    },
                    "InstanceType": "c5.large",
                    "ParentImage": "ami-12345678",
                    "SubnetId": "subnet-0d03dc52",
                    "Tags": [
                        {"Key": "Name", "Value": "ParallelCluster-ResourcePrefix-Build"},
                        {"Key": "Test", "Value": "ResourcePrefix"}
                    ],
                    "UpdateOsPackages": {
                        "Enabled": True
                    }
                },
                "CustomS3Bucket": "bucket-name"
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
            None,
            id="Test with ResourcePrefix path and name prefix",
        ),
        pytest.param(
            {
                "Region": "us-east-1",
                "Image": {
                    "Name": "test-resource-prefix-policies-ami",
                    "Tags": [
                        {"Key": "Name", "Value": "ParallelCluster-ResourcePrefix-Policies-AMI"}
                    ]
                },
                "Build": {
                    "Iam": {
                        "ResourcePrefix": "test-prefix-only",
                        "AdditionalIamPolicies": [
                            {"Policy": "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"}
                        ],
                        "PermissionsBoundary": "arn:aws:iam::111122223333:policy/test-boundary"
                    },
                    "InstanceType": "c5.xlarge",
                    "ParentImage": "ami-87654321",
                    "SubnetId": "subnet-0d03dc52",
                    "SecurityGroupIds": ["sg-0058826a55bae6679"],
                    "Tags": [
                        {"Key": "Name", "Value": "ParallelCluster-ResourcePrefix-Policies-Build"}
                    ],
                    "UpdateOsPackages": {
                        "Enabled": False
                    }
                },
                "CustomS3Bucket": "test-bucket-name"
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
            None,
            id="Test with ResourcePrefix name prefix only and additional IAM policies",
        ),
    ],
)
def test_imagebuilder_schema_with_resource_prefix(mocker, config_dict, describe_image_response, failure_message):
    """Test ImageBuilder schema with ResourcePrefix support."""
    mock_aws_api(mocker)
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=describe_image_response,
    )

    print(config_dict)

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            ImageBuilderSchema().load(config_dict)
    else:
        imagebuilder_config = ImageBuilderSchema().load(config_dict)
        print(imagebuilder_config)

        # Verify ResourcePrefix is properly loaded
        if imagebuilder_config.build.iam and imagebuilder_config.build.iam.resource_prefix:
            assert_that(imagebuilder_config.build.iam.resource_prefix).is_not_none()
            print(f"ResourcePrefix: {imagebuilder_config.build.iam.resource_prefix}")

        # Re-create Yaml file from model and compare content
        image_builder_schema = ImageBuilderSchema()
        image_builder_schema.context = {"delete_defaults_when_dump": True}
        output_json = image_builder_schema.dump(imagebuilder_config)

        # Assert imagebuilder config file can be convert to imagebuilder config
        assert_that(json.dumps(config_dict, sort_keys=True)).is_equal_to(json.dumps(output_json, sort_keys=True))

        # Print output yaml
        output_yaml = yaml.dump(output_json)
        print(output_yaml)
