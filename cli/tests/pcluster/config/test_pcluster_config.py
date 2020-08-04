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
import json

import pytest
from assertpy import assert_that

from tests.common import MockedBoto3Request
from tests.pcluster.config.utils import get_mocked_pcluster_config


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.cluster_model.boto3"


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
            _ = pcluster_config.cluster_model._get_latest_alinux_ami_id()
    else:
        latest_linux_ami_id = pcluster_config.cluster_model._get_latest_alinux_ami_id()
        assert_that(latest_linux_ami_id).is_equal_to(boto3_response.get("Parameters")[0].get("Value"))


@pytest.mark.parametrize(
    "cfn_params_dict, valid_bucket, expected_json, expected_message",
    [
        (
            # ResourceS3Bucket expected and not available
            {"Scheduler": "slurm"},
            False,
            None,
            "Unable to retrieve configuration: ResourceS3Bucket not available.",
        ),
        (
            # Invalid ResourcesS3Bucket
            {"Scheduler": "slurm", "ResourcesS3Bucket": "invalid_bucket"},
            False,
            None,
            "Unable to load configuration from bucket 'invalid_bucket'.\nInvalid file url",
        ),
        (
            # ResourceS3Bucket available
            {"Scheduler": "slurm", "ResourcesS3Bucket": "valid_bucket"},
            True,
            {"test_key": "test_value"},
            None,
        ),
        (
            # ResourceS3Bucket not expected
            {"Scheduler": "sge"},
            False,
            None,
            None,
        ),
    ],
)
def test_load_json_config(mocker, valid_bucket, cfn_params_dict, expected_json, expected_message):
    cfn_params = []
    for cfn_key, cfn_value in cfn_params_dict.items():
        cfn_params.append({"ParameterKey": cfn_key, "ParameterValue": cfn_value})
    pcluster_config = get_mocked_pcluster_config(mocker)

    patched_read_remote_file = mocker.patch("pcluster.config.pcluster_config.read_remote_file")
    if valid_bucket:
        patched_read_remote_file.return_value = json.dumps(expected_json)
    else:
        patched_read_remote_file.side_effect = Exception("Invalid file url")

    if expected_message:
        with pytest.raises(SystemExit, match=expected_message):
            pcluster_config._PclusterConfig__load_json_config(cfn_params)
    else:
        assert_that(pcluster_config._PclusterConfig__load_json_config(cfn_params)).is_equal_to(expected_json)
