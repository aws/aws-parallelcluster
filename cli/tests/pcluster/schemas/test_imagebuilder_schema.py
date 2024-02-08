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
