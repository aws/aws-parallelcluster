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

from pcluster.models.common import Param
from pcluster.validators.ec2_validators import (
    BaseAMIValidator,
    InstanceTypeBaseAMICompatibleValidator,
    InstanceTypeValidator,
)
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "instance_type, expected_message", [("t2.micro", None), ("c4.xlarge", None), ("c5.xlarge", "is not supported")]
)
def test_instance_type_validator(mocker, instance_type, expected_message):

    mocker.patch("pcluster.validators.ec2_validators.Ec2Client.__init__", return_value=None)
    mocker.patch(
        "pcluster.validators.ec2_validators.Ec2Client.describe_instance_type_offerings",
        return_value=["t2.micro", "c4.xlarge"],
    )

    actual_failures = InstanceTypeValidator().execute(Param(instance_type))
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "image_id, expected_message, response",
    [("ami-0185634c5a8a37250", None, True), ("ami-000000000000", "is not supported", False)],
)
def test_base_ami_validator(mocker, image_id, expected_message, response):
    mocker.patch("pcluster.validators.ec2_validators.Ec2Client.__init__", return_value=None)
    mocker.patch("pcluster.validators.ec2_validators.Ec2Client.describe_ami_id_offering", return_value=response)
    actual_failures = BaseAMIValidator().execute(Param(image_id))
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "instance_type, parent_image, expected_message, ami_response, instance_architecture",
    [
        (
            "c5.xlarge",
            "arn:${AWS::Partition}:imagebuilder:${AWS::Region}:aws:image/amazon-linux-2-x86/x.x.x",
            None,
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
            "x86_64",
        ),
        (
            "m6g.xlarge",
            "ami-0185634c5a8a37250",
            "AMI ami-0185634c5a8a37250's architecture \\(x86_64\\) is incompatible with the architecture supported by "
            "the instance type m6g.xlarge chosen \\(arm64\\). Use either a different AMI or a different instance type.",
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
            "arm64",
        ),
    ],
)
def test_instance_type_base_ami_compatible_validator(
    mocker, instance_type, parent_image, expected_message, ami_response, instance_architecture
):
    mocker.patch("pcluster.utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch("pcluster.utils.get_info_for_amis", return_value=ami_response)
    mocker.patch("pcluster.utils.get_supported_architectures_for_instance_type", return_value=instance_architecture)
    actual_failures = InstanceTypeBaseAMICompatibleValidator().execute(
        instance_type=Param(instance_type), parent_image=Param(parent_image)
    )
    assert_failure_messages(actual_failures, expected_message)
