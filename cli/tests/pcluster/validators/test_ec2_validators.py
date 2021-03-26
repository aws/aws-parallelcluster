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

from common.boto3.common import AWSClientError
from pcluster.utils import InstanceTypeInfo
from pcluster.validators.ec2_validators import (
    ComputeTypeValidator,
    InstanceTypeBaseAMICompatibleValidator,
    InstanceTypeValidator,
    KeyPairValidator,
)
from tests.common.dummy_aws_api import DummyAWSApi
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "instance_type, expected_message", [("t2.micro", None), ("c4.xlarge", None), ("c5.xlarge", "is not supported")]
)
def test_instance_type_validator(mocker, instance_type, expected_message):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_instance_type_offerings",
        return_value=["t2.micro", "c4.xlarge"],
    )

    actual_failures = InstanceTypeValidator().execute(instance_type)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "instance_type, parent_image, expected_message, ami_response, ami_side_effect, instance_response, "
    "instance_architectures",
    [
        (
            "c5.xlarge",
            "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
            None,
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
            ["m6g.xlarge", "c5.xlarge"],
            ["x86_64"],
        ),
        (
            "m6g.xlarge",
            "ami-0185634c5a8a37250",
            "AMI ami-0185634c5a8a37250's architecture \\(x86_64\\) is incompatible with the architecture supported by "
            "the instance type m6g.xlarge chosen \\(\\['arm64'\\]\\). "
            "Use either a different AMI or a different instance type.",
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
            ["m6g.xlarge", "c5.xlarge"],
            ["arm64"],
        ),
        (
            "m6g.xlarge",
            "ami-000000000000",
            "Invalid image 'ami-000000000000'",
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
            AWSClientError(function_name="describe_image", message="error"),
            ["m6g.xlarge", "c5.xlarge"],
            ["arm64"],
        ),
        (
            "p4d.24xlarge",
            "ami-0185634c5a8a37250",
            "The instance type 'p4d.24xlarge' is not supported.",
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
            ["m6g.xlarge", "c5.xlarge"],
            [],
        ),
    ],
)
def test_instance_type_base_ami_compatible_validator(
    mocker,
    instance_type,
    parent_image,
    expected_message,
    ami_response,
    ami_side_effect,
    instance_response,
    instance_architectures,
):
    mocker.patch("common.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
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
    mocker.patch("pcluster.utils.get_supported_architectures_for_instance_type", return_value=instance_architectures)
    actual_failures = InstanceTypeBaseAMICompatibleValidator().execute(instance_type=instance_type, image=parent_image)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "key_pair, side_effect, expected_message",
    [
        ("key-name", None, None),
        (None, None, "If you do not specify a key pair"),
        ("c5.xlarge", AWSClientError(function_name="describe_key_pair", message="does not exist"), "does not exist"),
    ],
)
def test_key_pair_validator(mocker, key_pair, side_effect, expected_message):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch("common.boto3.ec2.Ec2Client.describe_key_pair", return_value=key_pair, side_effect=side_effect)
    actual_failures = KeyPairValidator().execute(key_name=key_pair)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "compute_type, supported_usage_classes, expected_message",
    [
        ("ondemand", ["ondemand", "spot"], None),
        ("spot", ["ondemand", "spot"], None),
        ("ondemand", ["ondemand"], None),
        ("spot", ["spot"], None),
        ("spot", [], "Could not check support for usage class 'spot' with instance type 'instance-type'"),
        ("ondemand", [], "Could not check support for usage class 'ondemand' with instance type 'instance-type'"),
        ("spot", ["ondemand"], "Usage type 'spot' not supported with instance type 'instance-type'"),
        ("ondemand", ["spot"], "Usage type 'ondemand' not supported with instance type 'instance-type'"),
    ],
)
def test_compute_type_validator(mocker, compute_type, supported_usage_classes, expected_message):
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch(
        "common.boto3.ec2.Ec2Client.get_instance_type_info",
        return_value=InstanceTypeInfo(
            {"InstanceType": "instance-type", "SupportedUsageClasses": supported_usage_classes}
        ),
    )
    actual_failures = ComputeTypeValidator().execute(compute_type=compute_type, instance_type="instance-type")
    assert_failure_messages(actual_failures, expected_message)
