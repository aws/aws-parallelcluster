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

from pcluster.utils import get_installed_version
from tests.common import MockedBoto3Request
from tests.pcluster.config.utils import get_mocked_pcluster_config, init_pcluster_config_from_configparser


@pytest.fixture(autouse=True)
def clear_cache():
    from pcluster.utils import Cache

    Cache.clear_all()


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.cluster_model.boto3"


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


@pytest.mark.parametrize(
    "custom_ami_id, os, architecture, expected_ami_suffix, expected_public_ami_id, expected_self_ami_id, "
    "expected_error_message, raise_boto3_error",
    [
        # Official ami
        (None, "alinux2", "x86_64", "amzn2-hvm-x86_64", "ami-official", None, None, False),
        (None, "centos7", "x86_64", "centos7-hvm-x86_64", "ami-official", None, None, False),
        (None, "ubuntu1804", "x86_64", "ubuntu-1804-lts-hvm-x86_64", "ami-official", None, None, False),
        (None, "alinux2", "arm_64", "amzn2-hvm-arm_64", "ami-official", None, None, False),
        (None, "centos7", "arm_64", "centos7-hvm-arm_64", "ami-official", None, None, False),
        (None, "ubuntu1804", "arm_64", "ubuntu-1804-lts-hvm-arm_64", "ami-official", None, None, False),
        # Custom ami
        ("ami-custom", "alinux2", "x86_64", None, "ami-custom", None, None, False),
        ("ami-custom", "alinux2", "arm_64", None, "ami-custom", None, None, False),
        # Self ami
        (None, "ubuntu1804", "arm_64", "ubuntu-1804-lts-hvm-arm_64", None, "ami-self", None, False),
        # No ami found
        (None, "alinux2", "x86_64", "amzn2-hvm-x86_64", None, None, "No official image id found", False),
        # Boto3 error
        (None, "alinux2", "x86_64", "amzn2-hvm-x86_64", None, None, "Unable to retrieve official image id", True),
    ],
)
def test_get_cluster_ami_id(
    mocker,
    boto3_stubber,
    custom_ami_id,
    os,
    architecture,
    expected_ami_suffix,
    expected_public_ami_id,
    expected_self_ami_id,
    expected_error_message,
    raise_boto3_error,
):
    if not custom_ami_id:
        # Expected request for public ami
        mocked_requests = [
            MockedBoto3Request(
                method="describe_images",
                response={
                    "Images": [
                        {
                            "Architecture": architecture,
                            "CreationDate": "2020-12-22T13:30:33.000Z",
                            "ImageId": expected_public_ami_id,
                        }
                    ]
                    if expected_public_ami_id
                    else []
                },
                expected_params={
                    "Filters": [
                        {
                            "Name": "name",
                            "Values": [
                                "aws-parallelcluster-{version}-{suffix}*".format(
                                    version=get_installed_version(), suffix=expected_ami_suffix
                                )
                            ],
                        },
                        {"Name": "is-public", "Values": ["true"]},
                    ],
                    "Owners": ["amazon"],
                },
                generate_error=raise_boto3_error,
            )
        ]

        if not expected_public_ami_id and not raise_boto3_error:
            # Expected request for self ami
            mocked_requests.append(
                MockedBoto3Request(
                    method="describe_images",
                    response={
                        "Images": [
                            {
                                "Architecture": architecture,
                                "CreationDate": "2020-12-22T13:30:33.000Z",
                                "ImageId": expected_self_ami_id,
                            }
                        ]
                        if expected_self_ami_id
                        else []
                    },
                    expected_params={
                        "Filters": [
                            {
                                "Name": "name",
                                "Values": [
                                    "aws-parallelcluster-{version}-{suffix}*".format(
                                        version=get_installed_version(), suffix=expected_ami_suffix
                                    )
                                ],
                            },
                        ],
                        "Owners": ["self"],
                    },
                    generate_error=raise_boto3_error,
                )
            )

        boto3_stubber("ec2", mocked_requests)

    pcluster_config = get_mocked_pcluster_config(mocker)
    pcluster_config.get_section("cluster").get_param("custom_ami").value = custom_ami_id
    pcluster_config.get_section("cluster").get_param("base_os").value = os
    pcluster_config.get_section("cluster").get_param("architecture").value = architecture

    if expected_error_message:
        with pytest.raises(SystemExit, match=expected_error_message):
            _ = pcluster_config.cluster_model._get_cluster_ami_id(pcluster_config)
    else:
        expected_ami_id = expected_public_ami_id if expected_public_ami_id else expected_self_ami_id
        cluster_ami_id = pcluster_config.cluster_model._get_cluster_ami_id(pcluster_config)
        assert_that(cluster_ami_id).is_equal_to(expected_ami_id)
