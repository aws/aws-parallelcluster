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
import configparser
import pytest
from assertpy import assert_that
from pytest import fail

from tests.common import MockedBoto3Request
from tests.pcluster.config.utils import get_mocked_pcluster_config, init_pcluster_config_from_configparser


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
    "cfn_params_dict, version, expected_json",
    [
        (
            # ResourceS3Bucket available
            {
                "Scheduler": "slurm",
                "ResourcesS3Bucket": "valid_bucket",
                "ArtifactS3RootDirectory": "valid_dir",
            },
            "2.9.0",
            {"test_key": "test_value"},
        ),
        (
            # SIT version
            {"Scheduler": "slurm"},
            "2.8.0",
            None,
        ),
        (
            # ResourceS3Bucket not expected
            {"Scheduler": "sge"},
            "2.9.0",
            None,
        ),
    ],
)
def test_load_json_config(mocker, cfn_params_dict, version, expected_json):
    cfn_params = []
    for cfn_key, cfn_value in cfn_params_dict.items():
        cfn_params.append({"ParameterKey": cfn_key, "ParameterValue": cfn_value})
    cfn_stack = {"Parameters": cfn_params, "Tags": [{"Key": "Version", "Value": version}]}
    pcluster_config = get_mocked_pcluster_config(mocker)

    patched_read_remote_file = mocker.patch.object(
        pcluster_config, "_PclusterConfig__retrieve_cluster_config", auto_spec=True
    )
    patched_read_remote_file.return_value = expected_json

    assert_that(pcluster_config._PclusterConfig__load_json_config(cfn_stack)).is_equal_to(expected_json)


@pytest.mark.parametrize(
    "config_parser_dict, expected_message",
    [
        (
            {
                "cluster default": {"queue_settings": "queue1,queue2"},
                "queue queue1": {"compute_resource_settings": "cr1,cr2"},
                "queue queue2": {"compute_resource_settings": "cr1"},
                "compute_resource cr1": {},
                "compute_resource cr2": {},
            },
            "ERROR: Multiple reference to section '\\[.*\\]'",
        ),
        (
            {
                "cluster default": {"queue_settings": "queue1,queue2"},
                "queue queue1": {"compute_resource_settings": "cr1"},
                "queue queue2": {"compute_resource_settings": "cr2"},
                "compute_resource cr1": {},
                "compute_resource cr2": {},
            },
            None,
        ),
    ],
)
def test_load_from_file_errors(capsys, config_parser_dict, expected_message):
    config_parser = configparser.ConfigParser()
    config_parser.read_dict(config_parser_dict)

    try:
        init_pcluster_config_from_configparser(config_parser, False, auto_refresh=False)
    except SystemExit as e:
        if expected_message:
            assert_that(e.args[0]).matches(expected_message)
        else:
            fail("Unexpected failure when loading file")
