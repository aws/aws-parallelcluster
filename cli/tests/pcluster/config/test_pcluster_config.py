# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from tests.common import MockedBoto3Request
from tests.pcluster.config.utils import get_mocked_pcluster_config


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.config.pcluster_config.boto3"


@pytest.mark.parametrize(
    "path, boto3_response, expected_message",
    [
        (
            "/aws/service/ami-amazon-linux-latest",
            {
                "Parameters": [
                    {
                        "Name": "/aws/service/ami-amazon-linux-latest/amzn-ami-hvm-x86_64-ebs",
                        "Value": "ami-0833bb56f241ee002",
                    },
                    {
                        "Name": "/aws/service/ami-amazon-linux-latest/amzn2-ami-minimal-hvm-x86_64-ebs",
                        "Value": "ami-00a2133c9940bf8c3",
                    },
                ]
            },
            None,
        ),
        ("/aws/service/ami-amazon-linux-latest", "Generic Error", "Unable to retrieve Amazon Linux AMI id"),
    ],
)
def test_get_latest_alinux_ami_id(mocker, boto3_stubber, path, boto3_response, expected_message):
    mocked_requests = [
        MockedBoto3Request(
            method="get_parameters_by_path",
            response=boto3_response,
            expected_params={"Path": path},
            generate_error=True if expected_message else False,
        )
    ]

    boto3_stubber("ssm", mocked_requests)
    pcluster_config = get_mocked_pcluster_config(mocker)

    if expected_message:
        with pytest.raises(SystemExit, match=expected_message):
            _ = pcluster_config._PclusterConfig__get_latest_alinux_ami_id()
    else:
        latest_linux_ami_id = pcluster_config._PclusterConfig__get_latest_alinux_ami_id()
        assert_that(latest_linux_ami_id).is_equal_to(boto3_response.get("Parameters")[0].get("Value"))
