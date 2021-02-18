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
from urllib.error import URLError

import pytest

from common.boto3.common import AWSClientError
from pcluster.validators.common import FailureLevel
from tests.pcluster.boto3.dummy_boto3 import DummyAWSApi
from tests.pcluster.models.imagebuilder_dummy_model import imagebuilder_factory
from tests.pcluster.models.test_cluster_model import _assert_validation_result


@pytest.mark.parametrize(
    "resource, ami_response, ami_side_effect, expected_failure_messages, expected_failure_levels",
    [
        (
            {
                "imagebuilder": {
                    "image": {
                        "name": "Pcluster",
                        "description": "Pcluster 3.0 Image",
                        "root_volume": {"size": 25, "kms_key_id": "key_id"},
                        "tags": [
                            {"key": "name", "value": "pcluster"},
                            {"key": "date", "value": "2022.1.1"},
                        ],
                    },
                    "build": {"parent_image": "ami-0185634c5a8a37250", "instance_type": "c5.xlarge"},
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
            [
                "Kms Key Id key_id is specified, the encrypted state must be True.",
                "Root volume size 25 GB is less than the minimum required size 50 GB that equals parent ami"
                " volume size.",
            ],
            [FailureLevel.ERROR, FailureLevel.ERROR],
        )
    ],
)
def test_imagebuilder_ebs_volume_kms_key_id_validator_and_ami_volume_size_validator(
    mocker, resource, ami_response, ami_side_effect, expected_failure_messages, expected_failure_levels
):
    """Test EBSVolumeKmsKeyIdValidator and AMIVolumeSizeValidator."""
    fake_instance_response = ["c5.xlarge", "m6g.xlarge"]
    fake_supported_architecture = ["x86_64"]
    _test_imagebuilder(
        mocker,
        resource,
        ami_response,
        ami_side_effect,
        fake_instance_response,
        True,
        None,
        None,
        fake_supported_architecture,
        expected_failure_messages,
        expected_failure_levels,
    )


@pytest.mark.parametrize(
    "resource, url_response, url_side_effect, url_open_side_effect, expected_failure_messages, expected_failure_levels",
    [
        (
            {
                "dev_settings": {
                    "cookbook": {"chef_cookbook": "file:///test/aws-parallelcluster-cookbook-3.0.tgz"},
                    "node_package": "s3://test/aws-parallelcluster-node-3.0.tgz",
                    "aws_batch_cli_package": "ftp://test/aws-parallelcluster-batch-3.0.tgz",
                },
            },
            True,
            AWSClientError(function_name="head_object", message="error"),
            URLError("[Errno 2] No such file or directory: '/test/aws-parallelcluster-cookbook-3.0.tgz'"),
            [
                "The url 'file:///test/aws-parallelcluster-cookbook-3.0.tgz' causes URLError, the error reason is "
                "'[Errno 2] No such file or directory: '/test/aws-parallelcluster-cookbook-3.0.tgz''",
                "The S3 object does not exist or you do not have access to it.",
                "The value 'ftp://test/aws-parallelcluster-batch-3.0.tgz' is not a valid URL, choose URL with "
                "'https', 's3' or 'file' prefix.",
            ],
            [FailureLevel.WARNING, FailureLevel.ERROR, FailureLevel.ERROR],
        ),
    ],
)
def test_imagebuilder_url_validator(
    mocker,
    resource,
    url_response,
    url_side_effect,
    url_open_side_effect,
    expected_failure_messages,
    expected_failure_levels,
):
    """Test URLValidator."""
    _test_dev_settings(
        mocker,
        resource,
        url_response,
        url_side_effect,
        url_open_side_effect,
        expected_failure_messages,
        expected_failure_levels,
    )


def _test_imagebuilder(
    mocker,
    resource,
    ami_response,
    ami_side_effect,
    instance_response,
    url_response,
    url_side_effect,
    url_open_side_effect,
    supported_architecture,
    expected_failure_messages,
    expected_failure_levels,
):
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch("pcluster.utils.get_supported_architectures_for_instance_type", return_value=supported_architecture)
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=ami_response,
        side_effect=ami_side_effect,
    )
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_instance_type_offerings",
        return_value=instance_response,
    )
    mocker.patch("common.boto3.s3.S3Client.head_object", return_value=url_response, side_effect=url_side_effect)
    mocker.patch("pcluster.validators.s3_validators.urlopen", side_effect=url_open_side_effect)

    imagebuilder = imagebuilder_factory(resource).get("imagebuilder")
    validation_failures = imagebuilder.validate()
    for validation_failure, expected_failure_level, expected_failure_message in zip(
        validation_failures, expected_failure_levels, expected_failure_messages
    ):
        _assert_validation_result(validation_failure, expected_failure_level, expected_failure_message)


def _test_image(resource, expected_failure_messages, expected_failure_levels):
    image = imagebuilder_factory(resource).get("image")
    validation_failures = image.validate()
    for validation_failure, expected_failure_level, expected_failure_message in zip(
        validation_failures, expected_failure_levels, expected_failure_messages
    ):
        _assert_validation_result(validation_failure, expected_failure_level, expected_failure_message)


def _test_build(
    mocker,
    resource,
    ami_response,
    ami_side_effect,
    instance_response,
    supported_architecture,
    expected_failure_messages,
    expected_failure_levels,
):
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch("pcluster.utils.get_supported_architectures_for_instance_type", return_value=supported_architecture)
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_image",
        return_value=ami_response,
        side_effect=ami_side_effect,
    )
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_instance_type_offerings",
        return_value=instance_response,
    )

    build = imagebuilder_factory(resource).get("build")
    validation_failures = build.validate()
    for validation_failure, expected_failure_level, expected_failure_message in zip(
        validation_failures, expected_failure_levels, expected_failure_messages
    ):
        _assert_validation_result(validation_failure, expected_failure_level, expected_failure_message)


def _test_dev_settings(
    mocker,
    resource,
    url_response,
    url_side_effect,
    url_open_side_effect,
    expected_failure_messages,
    expected_failure_levels,
):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch("common.boto3.s3.S3Client.head_object", return_value=url_response, side_effect=url_side_effect)
    mocker.patch("pcluster.validators.s3_validators.urlopen", side_effect=url_open_side_effect)

    dev_settings = imagebuilder_factory(resource).get("dev_settings")
    validation_failures = dev_settings.validate()
    for validation_failure, expected_failure_level, expected_failure_message in zip(
        validation_failures, expected_failure_levels, expected_failure_messages
    ):
        _assert_validation_result(validation_failure, expected_failure_level, expected_failure_message)
