import json

import pytest
import yaml
from assertpy import assert_that

from common.utils import load_yaml_dict
from pcluster.schemas.imagebuilder_schema import ImageBuilderSchema
from tests.pcluster.boto3.dummy_boto3 import DummyAWSApi


@pytest.mark.parametrize(
    "config_file_name, response",
    [
        (
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
        ),
        (
            "imagebuilder_schema_dev.yaml",
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
        ),
    ],
)
def test_imagebuilder_schema(mocker, test_datadir, config_file_name, response):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=response,
    )
    # Load imagebuilder model from Yaml file
    input_yaml = load_yaml_dict(test_datadir / config_file_name)
    print(input_yaml)
    imagebuilder_config = ImageBuilderSchema().load(input_yaml)
    print(imagebuilder_config)

    # Re-create Yaml file from model and compare content
    output_json = ImageBuilderSchema().dump(imagebuilder_config)

    # Assert imagebuilder config file can be convert to imagebuilder config
    assert_that(json.dumps(input_yaml, sort_keys=True)).is_equal_to(json.dumps(output_json, sort_keys=True))

    # Print output yaml
    output_yaml = yaml.dump(output_json)
    print(output_yaml)
