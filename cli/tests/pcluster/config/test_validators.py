# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import datetime
import re

import pytest
from assertpy import assert_that

import tests.pcluster.config.utils as utils
from tests.common import MockedBoto3Request
from tests.pcluster.config.defaults import DefaultDict


@pytest.mark.parametrize("instance_type, expected_message", [("t2.micro", None), ("c4.xlarge", None)])
def test_head_node_instance_type_validator(mocker, instance_type, expected_message):
    config_parser_dict = {"cluster default": {"master_instance_type": instance_type}}
    utils.assert_param_validator(mocker, config_parser_dict, expected_message)


def _kms_key_stubber(mocker, boto3_stubber, kms_key_id, expected_message, num_calls):
    describe_key_response = {
        "KeyMetadata": {
            "AWSAccountId": "1234567890",
            "Arn": "arn:aws:kms:us-east-1:1234567890:key/{0}".format(kms_key_id),
            "CreationDate": datetime.datetime(2019, 1, 10, 11, 25, 59, 128000),
            "Description": "",
            "Enabled": True,
            "KeyId": kms_key_id,
            "KeyManager": "CUSTOMER",
            "KeyState": "Enabled",
            "KeyUsage": "ENCRYPT_DECRYPT",
            "Origin": "AWS_KMS",
        }
    }
    mocked_requests = [
        MockedBoto3Request(
            method="describe_key",
            response=expected_message if expected_message else describe_key_response,
            expected_params={"KeyId": kms_key_id},
            generate_error=True if expected_message else False,
        )
    ] * num_calls
    boto3_stubber("kms", mocked_requests)


@pytest.mark.parametrize(
    "section_dict, bucket, expected_error, num_calls",
    [
        (
            {
                "storage_capacity": 1200,
                "per_unit_storage_throughput": "50",
                "deployment_type": "PERSISTENT_1",
                "automatic_backup_retention_days": 2,
            },
            None,
            None,
            0,
        ),
        (
            {
                "storage_capacity": 1200,
                "deployment_type": "PERSISTENT_1",
                "per_unit_storage_throughput": "50",
                "automatic_backup_retention_days": 2,
                "daily_automatic_backup_start_time": "03:00",
                "copy_tags_to_backups": True,
            },
            None,
            None,
            0,
        ),
    ],
)
def test_fsx_validator(mocker, section_dict, bucket, expected_error, num_calls):
    config_parser_dict = {"cluster default": {"fsx_settings": "default"}, "fsx default": section_dict}
    if expected_error:
        expected_error = re.escape(expected_error)
    utils.assert_param_validator(mocker, config_parser_dict, expected_error=expected_error)


@pytest.mark.parametrize(
    "section_dict, expected_error, expected_warning",
    [
        ({"storage_capacity": 7200}, None, None),
    ],
)
def test_fsx_storage_capacity_validator(mocker, capsys, section_dict, expected_error, expected_warning):
    config_parser_dict = {"cluster default": {"fsx_settings": "default"}, "fsx default": section_dict}
    utils.assert_param_validator(
        mocker, config_parser_dict, capsys=capsys, expected_error=expected_error, expected_warning=expected_warning
    )


def _head_bucket_stubber(mocker, boto3_stubber, bucket, num_calls):
    head_bucket_response = {
        "ResponseMetadata": {
            "AcceptRanges": "bytes",
            "ContentType": "text/html",
            "LastModified": "Thu, 16 Apr 2015 18:19:14 GMT",
            "ContentLength": 77,
            "VersionId": "null",
            "ETag": '"30a6ec7e1a9ad79c203d05a589c8b400"',
            "Metadata": {},
        }
    }
    mocked_requests = [
        MockedBoto3Request(method="head_bucket", response=head_bucket_response, expected_params=bucket)
    ] * num_calls
    boto3_stubber("s3", mocked_requests)
    mocker.patch("pcluster.config.validators.urllib.request.urlopen")


#########
#
# architecture validator tests
#
# Two things make it difficult to test validators that key on architecture in the same way that:
# 1) architecture is a derived parameter and cannot be configured directly via the config file
# 2) many validators key on the architecture, which makes it impossible to test some combinations of
#    parameters for validators that run later than others, because those run earlier will have
#    already raised exceptions.
#
# Thus, the following code mocks the pcluster_config object passed to the validator functions
# and calls those functions directly (as opposed to patching functions and instantiating a config
# as would be done when running `pcluster create/update`).
#
#########


def get_default_pcluster_sections_dict():
    """Return a dict similar in structure to that of a cluster config file."""
    default_pcluster_sections_dict = {}
    for section_default_dict in DefaultDict:
        if section_default_dict.name == "pcluster":  # Get rid of the extra layer in this case
            default_pcluster_sections_dict["cluster"] = section_default_dict.value.get("cluster")
        else:
            default_pcluster_sections_dict[section_default_dict.name] = section_default_dict.value
    return default_pcluster_sections_dict


def make_pcluster_config_mock(mocker, config_dict):
    """Mock the calls that made on a pcluster_config by validator functions."""
    cluster_config_dict = get_default_pcluster_sections_dict()
    for section_key in config_dict:
        cluster_config_dict = utils.merge_dicts(cluster_config_dict.get(section_key), config_dict.get(section_key))

    section_to_mocks = {}
    for section_key, section_dict in config_dict.items():
        section_mock = mocker.MagicMock()
        section_mock.get_param_value.side_effect = lambda param: section_dict.get(param)
        section_to_mocks[section_key] = section_mock

    pcluster_config_mock = mocker.MagicMock()
    pcluster_config_mock.get_section.side_effect = lambda section: section_to_mocks.get(section)
    return pcluster_config_mock


# TODO to be moved
def run_architecture_validator_test(
    mocker,
    config,
    constrained_param_section,
    constrained_param_name,
    param_name,
    param_val,
    validator,
    expected_messages,
):
    """Run a test for a validator that's concerned with the architecture param."""
    mocked_pcluster_config = make_pcluster_config_mock(mocker, config)
    errors, warnings = validator(param_name, param_val, mocked_pcluster_config)

    mocked_pcluster_config.get_section.assert_called_once_with(constrained_param_section)
    mocked_pcluster_config.get_section.side_effect(constrained_param_section).get_param_value.assert_called_with(
        constrained_param_name
    )
    assert_that(len(warnings)).is_equal_to(0)
    assert_that(len(errors)).is_equal_to(len(expected_messages))
    for error, expected_message in zip(errors, expected_messages):
        assert_that(error).matches(re.escape(expected_message))


#########
#
# ignored FSx params validator test
#
# Testing a validator that requires the fsx_fs_id parameter to be specified requires a lot of
# boto3 stubbing due to the complexity contained in the fsx_id_validator.
#
# Thus, the following code mocks the pcluster_config object passed to the validator functions
# and calls the validator directly.
#
#########
