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

from pcluster.validators.imagebuilder_validators import AMIVolumeSizeValidator
from tests.pcluster.validators.utils import assert_failure_messages


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
            "Root volume size 25 GB is less than the minimum required size 65 GB that equals base ami 50 GB plus "
            "size 15 GB to allow PCluster software stack installation.",
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
            15,
            "Root volume size 15 GB is less than the minimum required size 23 GB that equals base ami "
            "8 GB plus size 15 GB to allow PCluster software stack installation.",
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
    ],
)
def test_ami_volume_size_validator(mocker, image, volume_size, expected_message, ami_response):
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch("pcluster.validators.imagebuilder_validators.Ec2Client.__init__", return_value=None)
    mocker.patch(
        "pcluster.validators.imagebuilder_validators.Ec2Client.describe_image",
        return_value=ami_response,
    )
    actual_failures = AMIVolumeSizeValidator().execute(volume_size, image, pcluster_reserved_volume_size=15)
    assert_failure_messages(actual_failures, expected_message)
