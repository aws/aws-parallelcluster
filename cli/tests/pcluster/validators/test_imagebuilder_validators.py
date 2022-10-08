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
from assertpy import soft_assertions

from pcluster.aws.aws_resources import ImageInfo
from pcluster.validators.common import FailureLevel
from pcluster.validators.imagebuilder_validators import (
    AMIVolumeSizeValidator,
    ComponentsValidator,
    RequireImdsV2Validator,
    SecurityGroupsAndSubnetValidator,
)
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.validators.utils import assert_failure_level, assert_failure_messages


@pytest.mark.parametrize(
    "image, volume_size, expected_message, ami_response",
    [
        (
            "ami-0185634c5a8a37250",
            65,
            None,
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
        ),
        (
            "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
            25,
            None,
            {
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "DeleteOnTermination": True,
                            "SnapshotId": "snap-0a20b6671bc5e3ead",
                            "VolumeSize": 8,
                            "VolumeType": "gp2",
                            "Encrypted": False,
                        },
                    }
                ],
            },
        ),
        (
            "ami-0185634c5a8a37250",
            25,
            "Root volume size 25 GB is less than the minimum required size 50 GB that equals parent ami volume size.",
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
        ),
    ],
)
def test_ami_volume_size_validator(mocker, image, volume_size, expected_message, ami_response):
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mock_aws_api(mocker)
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image",
        return_value=ImageInfo(ami_response),
    )
    actual_failures = AMIVolumeSizeValidator().execute(volume_size, image)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "components, expected_message",
    [
        (
            [],
            None,
        ),
        (range(0, 16), "Number of build components is 16. It's not possible to specify more than 15 build components."),
        (
            [1],
            None,
        ),
    ],
)
def test_components_validator(components, expected_message):
    actual_failures = ComponentsValidator().execute(components)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "security_group_ids, subnet_ids, expected_message",
    [
        (
            ["sg-0058826a55bae6679", "sg-01971157d4012122a"],
            "subnet-0d03dc52",
            None,
        ),
        (
            [],
            "subnet-0d03dc52",
            "Subnet id subnet-0d03dc52 is specified, security groups is required",
        ),
    ],
)
def test_security_groups_and_subnet_validator(security_group_ids, subnet_ids, expected_message):
    actual_failures = SecurityGroupsAndSubnetValidator().execute(security_group_ids, subnet_ids)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "require_imds_v2, expected_message, expected_failure_level",
    [
        (
            False,
            "The current build image configuration does not disable IMDSv1, "
            "which we plan to disable by default in future versions. If you do "
            "not explicitly need to use IMDSv1 enforce IMDSv2 usage by setting the "
            "RequireImdsV2 configuration parameter to true (see documentation at: "
            "https://docs.aws.amazon.com/parallelcluster/latest/ug/Build-v3.html)",
            FailureLevel.INFO,
        ),
        (True, None, None),
    ],
)
def test_require_imds_v2_validator(require_imds_v2, expected_message, expected_failure_level):
    actual_failures = RequireImdsV2Validator().execute(require_imds_v2)
    with soft_assertions():
        assert_failure_messages(actual_failures, expected_message)
        assert_failure_level(actual_failures, expected_failure_level)
